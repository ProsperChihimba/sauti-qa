"""Voice activity detection: find speech so silence and hold music are not transcribed.

Silero VAD is used when installed (GPU image); an energy-based fallback keeps the
platform working on CPU-only installs and in tests.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from app.config import get_settings

log = logging.getLogger(__name__)
Region = tuple[float, float]


def merge_regions(regions: list[Region], *, gap: float = 0.5, pad: float = 0.2, duration: float | None = None,
                  max_len: float = 28.0) -> list[Region]:
    """Pad, merge close regions, and split very long ones (Whisper works on <=30 s windows)."""
    if not regions:
        return []
    padded = sorted((max(0.0, a - pad), b + pad if duration is None else min(duration, b + pad)) for a, b in regions)
    merged: list[list[float]] = [list(padded[0])]
    for a, b in padded[1:]:
        if a - merged[-1][1] <= gap and b - merged[-1][0] <= max_len:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out: list[Region] = []
    for a, b in merged:
        while b - a > max_len:
            out.append((round(a, 3), round(a + max_len, 3)))
            a += max_len
        if b - a > 0.05:
            out.append((round(a, 3), round(b, 3)))
    return out


def energy_vad(audio: np.ndarray, sr: int = 16000, frame_ms: int = 30, threshold_db: float = -40.0,
               min_speech: float = 0.25) -> list[Region]:
    if audio.size == 0:
        return []
    frame = int(sr * frame_ms / 1000)
    n = len(audio) // frame
    if n == 0:
        return []
    frames = audio[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    # Adaptive: at least threshold_db, and 15 dB above the noise floor of the call.
    floor = np.percentile(db, 10)
    active = db > max(threshold_db, floor + 15)
    regions: list[Region] = []
    start = None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            regions.append((start * frame / sr, i * frame / sr))
            start = None
    if start is not None:
        regions.append((start * frame / sr, n * frame / sr))
    return [r for r in regions if r[1] - r[0] >= min_speech]


@lru_cache
def _silero():
    from silero_vad import get_speech_timestamps, load_silero_vad

    return load_silero_vad(), get_speech_timestamps


def silero_vad(audio: np.ndarray, sr: int = 16000) -> list[Region]:
    import torch

    model, get_ts = _silero()
    ts = get_ts(torch.from_numpy(audio), model, sampling_rate=sr, return_seconds=True,
                min_speech_duration_ms=250, min_silence_duration_ms=300)
    return [(float(t["start"]), float(t["end"])) for t in ts]


def detect_speech(audio: np.ndarray, sr: int = 16000) -> list[Region]:
    backend = get_settings().vad_backend
    duration = len(audio) / sr
    if backend == "none":
        return [(0.0, duration)] if duration > 0 else []
    raw: list[Region]
    if backend == "silero":
        try:
            raw = silero_vad(audio, sr)
        except ImportError:
            log.warning("silero-vad not installed; using energy VAD")
            raw = energy_vad(audio, sr)
    else:
        raw = energy_vad(audio, sr)
    return merge_regions(raw, duration=duration)
