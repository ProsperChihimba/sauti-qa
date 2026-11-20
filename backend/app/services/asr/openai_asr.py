"""Any OpenAI-compatible /audio/transcriptions endpoint.

This sends audio OUT of the platform. It is only used when ASR_PROVIDER=openai is
set explicitly, and should only be enabled with the client's written approval.
A self-hosted OpenAI-compatible server (e.g. faster-whisper-server, vLLM audio)
on the internal network is also supported by setting ASR_OPENAI_BASE_URL.
"""

from __future__ import annotations

import math

import numpy as np

from app.config import get_settings
from app.services.asr.base import ASRContext, ASRProvider, ASRSegment, Region, Word
from app.services.audio import wav_bytes


class OpenAICompatASR(ASRProvider):
    name = "openai"

    def __init__(self, model_id: str = "whisper-1"):
        from openai import OpenAI

        s = get_settings()
        self.model_id = model_id
        self.client = OpenAI(base_url=s.asr_openai_base_url, api_key=s.asr_openai_api_key or "not-needed",
                             timeout=300)
        self.language = s.asr_language

    def transcribe(self, audio: np.ndarray, regions: list[Region], ctx: ASRContext, sr: int = 16000):
        out: list[ASRSegment] = []
        for region in regions:
            data = wav_bytes(self.clip(audio, region, sr), sr)
            resp = self.client.audio.transcriptions.create(
                model=self.model_id, file=("clip.wav", data, "audio/wav"), language=self.language,
                response_format="verbose_json", timestamp_granularities=["segment", "word"],
            )
            segs = getattr(resp, "segments", None) or []
            words = getattr(resp, "words", None) or []
            if not segs and getattr(resp, "text", "").strip():
                segs = [{"start": 0.0, "end": region[1] - region[0], "text": resp.text}]
            for sg in segs:
                g = sg if isinstance(sg, dict) else sg.model_dump()
                text = (g.get("text") or "").strip()
                if not text:
                    continue
                lp = g.get("avg_logprob")
                s0, e0 = float(g["start"]), float(g["end"])
                ws = []
                for w in words:
                    wd = w if isinstance(w, dict) else w.model_dump()
                    if s0 <= wd["start"] < e0:
                        ws.append(Word(wd["word"], round(region[0] + wd["start"], 3), round(region[0] + wd["end"], 3)))
                out.append(ASRSegment(round(region[0] + s0, 3), round(region[0] + e0, 3), text,
                                      round(math.exp(lp), 4) if lp is not None else None, ws))
        return out
