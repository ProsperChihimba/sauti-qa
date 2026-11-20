from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

Region = tuple[float, float]


@dataclass
class Word:
    text: str
    start: float
    end: float
    confidence: float | None = None


@dataclass
class ASRSegment:
    start: float
    end: float
    text: str
    confidence: float | None = None
    words: list[Word] = field(default_factory=list)
    speaker_raw: str | None = None


@dataclass
class ASRContext:
    """Per-call information a provider may use (only the mock uses most of it)."""

    call_id: str = ""
    role: str | None = None  # "agent"/"customer" when transcribing one stereo channel
    meta: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0


class ASRProvider(ABC):
    name: str = "base"
    model_id: str = ""
    # Longest speech region sent in one piece (Whisper's window is 30 s; models
    # without timestamps use shorter regions so each becomes a short transcript line).
    max_region_seconds: float = 28.0

    @abstractmethod
    def transcribe(self, audio: np.ndarray, regions: list[Region], ctx: ASRContext, sr: int = 16000
                   ) -> list[ASRSegment]:
        """Transcribe the speech regions of a 16 kHz mono float32 signal.
        Returned timestamps are absolute (seconds from the start of the call)."""

    @staticmethod
    def clip(audio: np.ndarray, region: Region, sr: int = 16000) -> np.ndarray:
        a, b = region
        return audio[int(a * sr): int(b * sr)]
