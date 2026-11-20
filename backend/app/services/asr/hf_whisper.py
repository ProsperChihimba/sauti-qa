"""Whisper checkpoints from Hugging Face via transformers.

Used for fine-tuned Swahili models that are published as transformers weights:
  - openchs/asr-whisper-largev2-v6   (Tanzanian helpline phone calls)
  - BuzzASR/swahili                  (Whisper large-v3 fine-tuned for Swahili)
  - your own fine-tuned checkpoint (point ASR_MODEL at a local directory)
"""

from __future__ import annotations

import logging
import math

import numpy as np

from app.config import get_settings
from app.services.asr.base import ASRContext, ASRProvider, ASRSegment, Region

log = logging.getLogger(__name__)


class HFWhisperASR(ASRProvider):
    name = "hf_whisper"

    def __init__(self, model_id: str):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        s = get_settings()
        self.model_id = model_id
        self.device = s.asr_device if (s.asr_device != "cuda" or torch.cuda.is_available()) else "cpu"
        self.dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        cache = str(s.hf_cache_dir) if s.hf_cache_dir else None
        self.processor = WhisperProcessor.from_pretrained(model_id, cache_dir=cache)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_id, torch_dtype=self.dtype, cache_dir=cache)
        self.model.to(self.device).eval()
        self.language = s.asr_language
        self.batch_size = s.asr_batch_size
        log.info("loaded %s on %s", model_id, self.device)

    def _generate(self, feats):
        import torch

        kwargs = dict(return_timestamps=True, return_dict_in_generate=True, output_scores=True, max_new_tokens=440)
        with torch.inference_mode():
            try:
                return self.model.generate(feats, language=self.language, task="transcribe", **kwargs)
            except (ValueError, KeyError):
                # Some fine-tuned checkpoints ship without language tokens in generation_config.
                return self.model.generate(feats, **kwargs)

    def transcribe(self, audio: np.ndarray, regions: list[Region], ctx: ASRContext, sr: int = 16000):
        segments: list[ASRSegment] = []
        tok = self.processor.tokenizer
        for b in range(0, len(regions), self.batch_size):
            batch = regions[b: b + self.batch_size]
            clips = [self.clip(audio, r, sr) for r in batch]
            feats = self.processor(clips, sampling_rate=sr, return_tensors="pt").input_features
            feats = feats.to(self.device, dtype=self.dtype)
            out = self._generate(feats)
            scores = self.model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
            for i, (region, seq) in enumerate(zip(batch, out.sequences, strict=True)):
                lp = scores[i].float().cpu().numpy()
                lp = lp[np.isfinite(lp) & (lp < 0)]
                conf = float(math.exp(lp.mean())) if lp.size else None
                decoded = tok.decode(seq, skip_special_tokens=True, output_offsets=True)
                offsets = decoded.get("offsets") or []
                if not offsets and decoded.get("text", "").strip():
                    offsets = [{"text": decoded["text"], "timestamp": (0.0, region[1] - region[0])}]
                for o in offsets:
                    text = o["text"].strip()
                    if not text:
                        continue
                    s0, e0 = o["timestamp"]
                    e0 = e0 if e0 is not None else region[1] - region[0]
                    segments.append(ASRSegment(round(region[0] + s0, 3), round(min(region[1], region[0] + e0), 3),
                                               text, round(conf, 4) if conf is not None else None))
        return segments
