"""Speaker separation and labelling.

Stereo calls: each channel is one party, so labels are exact (channel mapping is
configurable per call or globally). Mono calls: pyannote diarization gives
anonymous speakers (SPEAKER_00, SPEAKER_01...), then the LLM decides which one is
the agent; if that fails, keyword heuristics decide.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from functools import lru_cache

import numpy as np

from app.config import get_settings
from app.services.asr.base import ASRContext, ASRSegment

log = logging.getLogger(__name__)
Turn = tuple[float, float, str]


# ---------- diarization ----------
class Diarizer:
    name = "base"

    def diarize(self, audio: np.ndarray, sr: int, ctx: ASRContext) -> list[Turn]:
        raise NotImplementedError


class MockDiarizer(Diarizer):
    """Uses the mock dialogue timeline (tests and GPU-less demos)."""

    name = "mock"

    def diarize(self, audio, sr, ctx):
        from app.services.asr.mock import timeline

        roles: dict[str, str] = {}
        out = []
        for start, end, role, _ in timeline(ctx):
            label = roles.setdefault(role, f"SPEAKER_{len(roles):02d}")
            out.append((start, end, label))
        return out


class PyannoteDiarizer(Diarizer):
    name = "pyannote"

    def __init__(self):
        import torch
        from pyannote.audio import Pipeline

        s = get_settings()
        kwargs = {"use_auth_token": s.hf_token} if s.hf_token else {}
        if s.hf_cache_dir:
            kwargs["cache_dir"] = str(s.hf_cache_dir)
        self.pipeline = Pipeline.from_pretrained(s.pyannote_model, **kwargs)
        if torch.cuda.is_available() and s.asr_device.startswith("cuda"):
            self.pipeline.to(torch.device("cuda"))

    def diarize(self, audio, sr, ctx):
        import torch

        waveform = torch.from_numpy(audio).unsqueeze(0)
        # Call-centre calls: almost always agent + customer (sometimes a supervisor).
        result = self.pipeline({"waveform": waveform, "sample_rate": sr}, min_speakers=1, max_speakers=3)
        annotation = getattr(result, "speaker_diarization", result)  # pyannote 4 returns a wrapper
        return [(float(t.start), float(t.end), str(lbl)) for t, _, lbl in annotation.itertracks(yield_label=True)]


@lru_cache
def get_diarizer() -> Diarizer | None:
    backend = get_settings().diarization_backend
    if backend == "none":
        return None
    if backend == "mock":
        return MockDiarizer()
    try:
        return PyannoteDiarizer()
    except ImportError:
        log.warning("pyannote.audio not installed; mono calls will not be diarized")
        return None


def assign_speakers(segments: list[ASRSegment], turns: list[Turn]) -> None:
    """Give each ASR segment the diarization label it overlaps most."""
    for seg in segments:
        overlap: dict[str, float] = defaultdict(float)
        for a, b, label in turns:
            o = min(seg.end, b) - max(seg.start, a)
            if o > 0:
                overlap[label] += o
        if overlap:
            seg.speaker_raw = max(overlap, key=overlap.get)
        elif turns:
            mid = (seg.start + seg.end) / 2
            seg.speaker_raw = min(turns, key=lambda t: min(abs(t[0] - mid), abs(t[1] - mid)))[2]


# ---------- agent identification ----------
AGENT_CUES = [
    r"karibu", r"vodacom", r"naitwa", r"nikusaidie", r"nikusaidie", r"naweza kukusaidia", r"kukusaidia",
    r"asante kwa kupiga", r"pole kwa", r"pole sana", r"naomba (majina|namba|jina)", r"kwa usalama",
    r"thibitish", r"tafadhali subiri", r"nakuunganisha", r"kuna kingine", r"how may i help", r"welcome",
    r"customer care", r"huduma kwa wateja", r"siku njema",
]
CUSTOMER_CUES = [
    r"nina tatizo", r"nimekosea", r"nimelipia", r"nililipia", r"nataka", r"naomba msaada", r"bando langu",
    r"salio langu", r"simu yangu", r"namba yangu", r"nimetuma", r"supervisor wako", r"huduma mbaya",
]


def heuristic_agent(segments: list[dict]) -> tuple[str | None, float]:
    """segments: dicts with speaker_raw and text. Returns (agent_label, confidence)."""
    labels = [s["speaker_raw"] for s in segments if s.get("speaker_raw")]
    if not labels:
        return None, 0.0
    score: Counter = Counter()
    for s in segments:
        lbl = s.get("speaker_raw")
        if not lbl:
            continue
        t = s["text"].lower()
        score[lbl] += sum(1 for p in AGENT_CUES if re.search(p, t))
        score[lbl] -= sum(1 for p in CUSTOMER_CUES if re.search(p, t))
    # The agent usually opens a call-centre call.
    score[labels[0]] += 1
    ranked = score.most_common()
    if len(ranked) == 1:
        return ranked[0][0], 0.5
    margin = ranked[0][1] - ranked[1][1]
    return ranked[0][0], round(min(0.95, 0.5 + 0.1 * margin), 2)
