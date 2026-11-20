"""ASR provider registry. Choose with ASR_PROVIDER (and optionally ASR_MODEL)."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.asr.base import ASRContext, ASRProvider, ASRSegment, Word

PRESETS = {
    "openchs": "openchs/asr-whisper-largev2-v6",
    "buzzasr": "BuzzASR/swahili",
}
# Decoding options per preset, from each model card. BuzzASR bakes the language into
# its generation config and recommends repetition guards.
PRESET_OPTIONS: dict[str, dict] = {
    "buzzasr": {"language": None, "generate_kwargs": {"no_repeat_ngram_size": 3, "repetition_penalty": 1.2}},
}


def build_provider(name: str, model: str | None = None) -> ASRProvider:
    if name == "mock":
        from app.services.asr.mock import MockASR

        return MockASR()
    if name in PRESETS or name == "hf_whisper":
        from app.services.asr.hf_whisper import HFWhisperASR

        model_id = model or PRESETS.get(name)
        if not model_id:
            raise ValueError("ASR_MODEL must be set for ASR_PROVIDER=hf_whisper")
        p = HFWhisperASR(model_id, **PRESET_OPTIONS.get(name, {}))
        p.name = name
        return p
    if name == "faster_whisper":
        from app.services.asr.faster_whisper_asr import FasterWhisperASR

        return FasterWhisperASR(model or "large-v3")
    if name == "openai":
        from app.services.asr.openai_asr import OpenAICompatASR

        return OpenAICompatASR(model or "whisper-1")
    raise ValueError(f"Unknown ASR provider '{name}'")


def filter_hallucinations(segments: list[ASRSegment]) -> tuple[list[ASRSegment], list[ASRSegment]]:
    """Split segments into (kept, dropped) by confidence. Segments without a
    confidence score (e.g. some OpenAI-compatible servers) are always kept."""
    s = get_settings()
    kept, dropped = [], []
    for seg in segments:
        c = seg.confidence
        short = (seg.end - seg.start) < s.asr_short_seconds
        if c is not None and (c < s.asr_min_confidence or (short and c < s.asr_short_min_confidence)):
            dropped.append(seg)
        else:
            kept.append(seg)
    return kept, dropped


@lru_cache
def get_asr() -> ASRProvider:
    """One model instance per worker process (loading Whisper takes a while)."""
    s = get_settings()
    return build_provider(s.asr_provider, s.asr_model)


__all__ = ["ASRContext", "ASRProvider", "ASRSegment", "Word", "build_provider", "filter_hallucinations", "get_asr",
           "PRESETS"]
