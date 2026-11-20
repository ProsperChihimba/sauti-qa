"""ffmpeg-based audio handling. Everything is converted to 16 kHz PCM for the models."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import get_settings


class AudioError(Exception):
    pass


@dataclass
class ProbeResult:
    duration_s: float
    channels: int
    sample_rate: int
    codec: str | None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise AudioError(p.stderr.decode(errors="replace")[-800:] or f"{cmd[0]} failed")
    return p


def probe(path: Path) -> ProbeResult:
    s = get_settings()
    p = _run([s.ffprobe_bin, "-v", "error", "-select_streams", "a:0", "-show_entries",
              "stream=channels,sample_rate,codec_name,duration:format=duration", "-of", "json", str(path)])
    data = json.loads(p.stdout or b"{}")
    streams = data.get("streams") or []
    if not streams:
        raise AudioError("No audio stream found")
    st = streams[0]
    dur = st.get("duration") or (data.get("format") or {}).get("duration")
    try:
        duration = float(dur)
    except (TypeError, ValueError):
        duration = 0.0
    return ProbeResult(duration, int(st.get("channels") or 0), int(st.get("sample_rate") or 0), st.get("codec_name"))


def normalise(src: Path, dest: Path, *, keep_stereo: bool = True) -> Path:
    """16 kHz 16-bit WAV. Stereo is kept (for channel-based speaker separation);
    more than two channels are reduced to the first two."""
    s = get_settings()
    info = probe(src)
    channels = 2 if keep_stereo and info.channels >= 2 else 1
    cmd = [s.ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-vn"]
    if info.channels > 2 and channels == 2:
        cmd += ["-af", "pan=stereo|c0=c0|c1=c1"]
    cmd += ["-ac", str(channels), "-ar", str(s.target_sample_rate), "-c:a", "pcm_s16le", str(dest)]
    _run(cmd)
    return dest


def playback_mp3(src: Path, dest: Path, mute_spans: list[tuple[float, float]] | None = None) -> Path:
    """Mono MP3 for the browser. Optional muting of spoken PII spans."""
    s = get_settings()
    cmd = [s.ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "22050"]
    if mute_spans:
        expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in mute_spans)
        cmd += ["-af", f"volume=enable='{expr}':volume=0"]
    cmd += ["-c:a", "libmp3lame", "-b:a", "48k", str(dest)]
    _run(cmd)
    return dest


def load_pcm(path: Path, *, channel: int | None = None, sr: int | None = None) -> np.ndarray:
    """Decode to float32 mono at `sr` (default 16 kHz). channel=None mixes down;
    channel=0/1 selects left/right."""
    s = get_settings()
    sr = sr or s.target_sample_rate
    cmd = [s.ffmpeg_bin, "-loglevel", "error", "-i", str(path)]
    if channel is not None:
        cmd += ["-af", f"pan=mono|c0=c{channel}"]
    else:
        cmd += ["-ac", "1"]
    cmd += ["-ar", str(sr), "-f", "f32le", "-"]
    p = _run(cmd)
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def write_wav(path: Path, audio: np.ndarray, sr: int = 16000) -> Path:
    """Write float32 mono audio to 16-bit WAV (used for dataset clips and API uploads)."""
    import wave

    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def wav_bytes(audio: np.ndarray, sr: int = 16000) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
