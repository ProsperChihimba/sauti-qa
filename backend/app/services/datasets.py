"""Speech fine-tuning dataset from analyst-corrected transcript lines.

Output: a zip in Hugging Face "audiofolder" layout, loadable with
    datasets.load_dataset("audiofolder", data_dir="<unzipped dir>")

    train/metadata.jsonl, train/<clip>.wav
    test/metadata.jsonl,  test/<clip>.wav
    README.md

Rules:
  - only lines an analyst corrected (text differs from the ASR output), unless
    include_unedited_reviewed is set (lines of reviewed calls count as verified);
  - lines whose audio contained personal data (has_redaction) are always excluded,
    as are lines whose corrected text still contains a redaction tag;
  - stereo calls are cut from the speaker's own channel (clean audio);
  - clips shorter than 0.4 s or longer than 30 s are skipped (Whisper window);
  - the train/test split is by call, so one call never appears in both.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Call, Segment
from app.models.enums import ReviewStatus
from app.services import audio as audio_mod
from app.services.call_query import CallFilters, base_query
from app.services.storage import get_storage

MIN_CLIP, MAX_CLIP = 0.4, 30.0
REDACTION_TAG = ("[PHONE]", "[NIDA]", "[CARD]", "[ACCOUNT]", "[NUMBER]", "[PIN]", "[EMAIL]")


def _split(call_id: str, test_fraction: float) -> str:
    h = int(hashlib.sha256(call_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < test_fraction else "train"


def _channel(call: Call, seg: Segment) -> int | None:
    if (call.channels or 1) < 2 or not seg.speaker_raw:
        return None
    return 0 if seg.speaker_raw == "channel_left" else 1 if seg.speaker_raw == "channel_right" else None


def build_dataset(db: Session, f: CallFilters, *, include_unedited_reviewed: bool = False,
                  test_fraction: float = 0.1, pad: float = 0.15) -> tuple[bytes, dict[str, Any]]:
    stmt, _ = base_query(f)
    calls = [c for c, _ in db.execute(stmt.where(Call.audio_processed_key.is_not(None))).all()]
    stats = {"calls": 0, "clips": 0, "seconds": 0.0, "skipped_redacted": 0, "skipped_length": 0, "train": 0, "test": 0}
    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="sauti-ds-") as tmp:
        root = Path(tmp) / "dataset"
        meta: dict[str, list[dict]] = {"train": [], "test": []}
        for call in calls:
            segs = db.scalars(select(Segment).where(Segment.call_id == call.id).order_by(Segment.idx)).all()
            reviewed = call.review_status == ReviewStatus.reviewed
            chosen = []
            for s in segs:
                corrected = s.text.strip() != s.asr_text.strip()
                if not (corrected or (include_unedited_reviewed and reviewed)):
                    continue
                if s.has_redaction or any(t in s.text for t in REDACTION_TAG):
                    stats["skipped_redacted"] += 1
                    continue
                if not (MIN_CLIP <= s.end_s - s.start_s <= MAX_CLIP):
                    stats["skipped_length"] += 1
                    continue
                chosen.append(s)
            if not chosen:
                continue
            wav = storage.get_to_path(call.audio_processed_key, Path(tmp) / f"{call.id}.wav")
            cache: dict[int | None, Any] = {}
            split = _split(str(call.id), test_fraction)
            stats["calls"] += 1
            for s in chosen:
                ch = _channel(call, s)
                if ch not in cache:
                    cache[ch] = audio_mod.load_pcm(wav, channel=ch)
                pcm = cache[ch]
                a = max(0, int((s.start_s - pad) * 16000))
                b = min(len(pcm), int((s.end_s + pad) * 16000))
                name = f"{call.id.hex[:12]}_{s.idx:04d}.wav"
                audio_mod.write_wav(root / split / name, pcm[a:b])
                meta[split].append({
                    "file_name": name, "transcription": s.text.strip(), "asr_transcription": s.asr_text.strip(),
                    "call_id": str(call.id), "segment_idx": s.idx, "speaker": s.speaker,
                    "duration": round((b - a) / 16000, 3), "queue": call.queue, "corrected": s.text != s.asr_text,
                })
                stats["clips"] += 1
                stats[split] += 1
                stats["seconds"] += (b - a) / 16000
            wav.unlink(missing_ok=True)
        for split, rows in meta.items():
            if rows:
                (root / split).mkdir(parents=True, exist_ok=True)
                with (root / split / "metadata.jsonl").open("w", encoding="utf-8") as fh:
                    for r in rows:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        stats["seconds"] = round(stats["seconds"], 1)
        root.mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_text(
            "# Sauti QA speech dataset\n\nAnalyst-corrected Swahili call-centre utterances (16 kHz mono WAV).\n"
            "Lines that contained personal data are excluded.\n\n"
            "```python\nfrom datasets import load_dataset\nds = load_dataset('audiofolder', data_dir='.')\n```\n\n"
            f"Stats: {json.dumps(stats)}\n\nFine-tune with `scripts/finetune_whisper.py --data <this dir>`.\n",
            encoding="utf-8")
        buf_path = Path(tmp) / "dataset.zip"
        with zipfile.ZipFile(buf_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(root))
        return buf_path.read_bytes(), stats
