"""Whisper via faster-whisper (CTranslate2). Fastest option on GPU.

ASR_MODEL may be a size name ("large-v3") or a path to a CTranslate2-converted
checkpoint, e.g. a fine-tuned Swahili model converted with
`ct2-transformers-converter --model openchs/asr-whisper-largev2-v6 --output_dir ... --quantization float16`.
"""

from __future__ import annotations

import math

import numpy as np

from app.config import get_settings
from app.services.asr.base import ASRContext, ASRProvider, ASRSegment, Region, Word


class FasterWhisperASR(ASRProvider):
    name = "faster_whisper"

    def __init__(self, model_id: str = "large-v3"):
        from faster_whisper import WhisperModel

        s = get_settings()
        self.model_id = model_id
        device = s.asr_device
        compute = s.asr_compute_type if device.startswith("cuda") else "int8"
        self.model = WhisperModel(model_id, device=device, compute_type=compute,
                                  download_root=str(s.hf_cache_dir) if s.hf_cache_dir else None)
        self.language = s.asr_language

    def transcribe(self, audio: np.ndarray, regions: list[Region], ctx: ASRContext, sr: int = 16000):
        out: list[ASRSegment] = []
        for region in regions:
            clip = self.clip(audio, region, sr)
            segs, _info = self.model.transcribe(clip, language=self.language, task="transcribe", beam_size=5,
                                                vad_filter=False, word_timestamps=True,
                                                condition_on_previous_text=False)
            for sg in segs:
                text = sg.text.strip()
                if not text:
                    continue
                words = [Word(w.word.strip(), round(region[0] + w.start, 3), round(region[0] + w.end, 3),
                              round(w.probability, 3)) for w in (sg.words or [])]
                out.append(ASRSegment(round(region[0] + sg.start, 3), round(region[0] + sg.end, 3), text,
                                      round(math.exp(sg.avg_logprob), 4), words))
        return out
