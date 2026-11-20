"""Pipeline stages. Each stage is idempotent: it rebuilds its output from scratch,
so retries and re-processing are always safe.

prepare     (cpu) probe, normalise to 16 kHz, mp3 playback copy, VAD
transcribe  (gpu) ASR per channel (stereo) or ASR + diarization (mono); PII is
                  redacted in memory before any text is written
label       (llm) mono calls: decide which diarized speaker is the agent
score       (llm) LLM evaluation, validation/repair, score maths, review routing
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Call, Segment
from app.models.enums import Speaker
from app.services import audio as audio_mod
from app.services.app_settings import get_runtime_settings
from app.services.asr import ASRContext, ASRSegment, filter_hallucinations, get_asr
from app.services.audio.vad import detect_speech
from app.services.redaction import redact, redact_words
from app.services.speakers import assign_speakers, get_diarizer, heuristic_agent
from app.services.storage import get_storage
from app.workers.jobs import PermanentError

log = logging.getLogger(__name__)


def _tmpdir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="sauti-")


def _fetch(key: str, tmp: str, name: str) -> Path:
    return get_storage().get_to_path(key, Path(tmp) / name)


# ---------------------------------------------------------------- prepare
def prepare(db: Session, call: Call, heartbeat) -> None:
    if not call.audio_original_key:
        raise PermanentError("Audio is no longer available")
    storage = get_storage()
    with _tmpdir() as tmp:
        src = _fetch(call.audio_original_key, tmp, "original" + Path(call.audio_original_key).suffix)
        try:
            info = audio_mod.probe(src)
        except audio_mod.AudioError as exc:
            raise PermanentError(f"Not a readable audio file: {exc}") from exc
        if info.channels < 1:
            raise PermanentError("Audio has no channels")
        wav = audio_mod.normalise(src, Path(tmp) / "processed.wav")
        mp3 = audio_mod.playback_mp3(wav, Path(tmp) / "playback.mp3")
        mono = audio_mod.load_pcm(wav, normalize=True)
        heartbeat()
        duration = len(mono) / get_settings().target_sample_rate
        if duration < 0.5:
            raise PermanentError("Recording is shorter than half a second")
        regions = detect_speech(mono)

        call.audio_processed_key = f"calls/{call.id}/processed.wav"
        call.audio_playback_key = f"calls/{call.id}/playback.mp3"
        storage.put_file(call.audio_processed_key, wav, "audio/wav")
        storage.put_file(call.audio_playback_key, mp3, "audio/mpeg")
    call.duration_s = round(duration, 2)
    call.channels = min(info.channels, 2)
    call.speech_regions = [[a, b] for a, b in regions]
    call.speech_s = round(sum(b - a for a, b in regions), 2)


# ---------------------------------------------------------------- transcribe
def _agent_channel(db: Session, call: Call) -> int:
    side = (call.meta or {}).get("agent_channel") or get_runtime_settings(db).stereo_agent_channel
    return 0 if side == "left" else 1


def _transcribe_audio(db: Session, call: Call, wav: Path, heartbeat) -> tuple[list[ASRSegment], str]:
    asr = get_asr()
    sr = get_settings().target_sample_rate
    ctx = ASRContext(call_id=str(call.id), meta=call.meta or {}, duration=call.duration_s or 0.0)
    if (call.channels or 1) >= 2:
        agent_ch = _agent_channel(db, call)
        segs: list[ASRSegment] = []
        for ch in (0, 1):
            role = Speaker.agent if ch == agent_ch else Speaker.customer
            audio = audio_mod.load_pcm(wav, channel=ch, normalize=True)
            regions = detect_speech(audio, max_len=asr.max_region_seconds)
            ctx.role = str(role)
            for s in asr.transcribe(audio, regions, ctx, sr):
                s.speaker_raw = f"channel_{'left' if ch == 0 else 'right'}:{role}"
                segs.append(s)
            heartbeat()
        return sorted(segs, key=lambda s: (s.start, s.end)), "stereo"

    audio = audio_mod.load_pcm(wav, normalize=True)
    regions = detect_speech(audio, max_len=asr.max_region_seconds)
    segs = asr.transcribe(audio, regions, ctx, sr)
    heartbeat()
    diarizer = get_diarizer()
    if diarizer is not None and segs:
        turns = diarizer.diarize(audio, sr, ctx)
        assign_speakers(segs, turns)
        heartbeat()
        return segs, "diarized"
    return segs, "none"


def transcribe(db: Session, call: Call, heartbeat) -> None:
    if not call.audio_processed_key:
        raise PermanentError("Audio has not been prepared")
    s = get_settings()
    asr = get_asr()
    mute_spans: list[tuple[float, float]] = []
    with _tmpdir() as tmp:
        wav = _fetch(call.audio_processed_key, tmp, "processed.wav")
        segs, method = _transcribe_audio(db, call, wav, heartbeat)
        segs, dropped = filter_hallucinations(segs)
        # Keep only where and how sure, never the dropped text (it may contain PII).
        call.meta = {**(call.meta or {}), "asr_dropped": [
            {"start": d.start, "end": d.end, "confidence": d.confidence} for d in dropped]}

        db.execute(delete(Segment).where(Segment.call_id == call.id))
        idx = 0
        for sg in segs:
            text = " ".join(sg.text.split())
            if not text:
                continue
            # Redact in memory: the raw ASR text is never written anywhere.
            r = redact(text)
            words = [{"text": w.text, "start": w.start, "end": w.end, "confidence": w.confidence} for w in sg.words]
            words, mute = redact_words(words, text, r)
            mute_spans += mute
            speaker = Speaker.unknown
            if method == "stereo" and sg.speaker_raw:
                speaker = Speaker(sg.speaker_raw.split(":")[1])
            db.add(Segment(call_id=call.id, idx=idx, start_s=sg.start, end_s=sg.end, speaker=speaker,
                           speaker_raw=sg.speaker_raw.split(":")[0] if sg.speaker_raw else None,
                           text=r.text, asr_text=r.text, confidence=sg.confidence, words=words or None,
                           has_redaction=r.redacted, redactions=r.as_json()))
            idx += 1
        if idx == 0:
            log.warning("call %s: ASR returned no speech", call.id)

        if s.mute_redacted_audio and mute_spans and call.audio_playback_key:
            mp3 = audio_mod.playback_mp3(wav, Path(tmp) / "playback.mp3", mute_spans)
            get_storage().put_file(call.audio_playback_key, mp3, "audio/mpeg")

    call.asr_provider, call.asr_model = asr.name, asr.model_id
    call.speaker_method = "stereo" if method == "stereo" else ("pending" if method == "diarized" else "none")
    db.flush()
    db.expire(call, ["segments"])


# ---------------------------------------------------------------- label
def label(db: Session, call: Call, heartbeat) -> None:
    """Mono calls: map diarization labels to agent / customer."""
    if call.speaker_method == "stereo":
        return
    segments = list(call.segments)
    labels = {sg.speaker_raw for sg in segments if sg.speaker_raw}
    if not labels:
        call.speaker_method = "none"
        return
    seg_dicts = [{"speaker_raw": sg.speaker_raw, "text": sg.text} for sg in segments]
    agent_label, method = None, "heuristic"
    s = get_settings()
    if s.llm_speaker_identification and len(labels) > 1:
        from app.services.scoring.llm import LLMError, get_llm

        try:
            res = get_llm().identify_agent(seg_dicts)
            cand = str(res.get("agent_speaker") or "").strip()
            if cand in labels and float(res.get("confidence") or 0) >= 0.5:
                agent_label, method = cand, "llm"
        except (LLMError, ValueError, TypeError) as exc:
            log.warning("call %s: LLM speaker identification failed, using heuristics: %s", call.id, exc)
    if agent_label is None:
        agent_label, _ = heuristic_agent(seg_dicts)
        method = "heuristic"
    for sg in segments:
        if sg.edited_by_id is not None and sg.speaker != Speaker.unknown:
            continue  # keep human relabels
        sg.speaker = Speaker.agent if sg.speaker_raw == agent_label else Speaker.customer
    call.speaker_method = method


# ---------------------------------------------------------------- score
def score(db: Session, call: Call, heartbeat) -> None:
    from app.services.scoring import score_call

    if not call.segments:
        call.review_status = "pending"
        call.review_reasons = ["no_speech"]
        return
    requested_by = (call.meta or {}).get("rescore_requested_by")
    score_call(db, call, user_id=requested_by)
    if requested_by is not None:
        call.meta = {k: v for k, v in (call.meta or {}).items() if k != "rescore_requested_by"}
