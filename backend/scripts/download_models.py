#!/usr/bin/env python
"""Download model weights once, so the platform can then run fully offline.

Run inside the GPU worker container (it writes to the shared /models volume):
  docker compose -f deploy/docker-compose.yml --profile gpu run --rm gpu-worker \
      python scripts/download_models.py --asr openchs buzzasr faster_whisper --pyannote --silero

Then set HF_HUB_OFFLINE=1 in .env and restart. pyannote weights are gated: accept
the model terms on huggingface.co once and set HF_TOKEN for this download only.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.asr import PRESETS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", nargs="*", default=["openchs"],
                    help="openchs, buzzasr, faster_whisper[:size], or any Hugging Face repo id")
    ap.add_argument("--pyannote", action="store_true")
    ap.add_argument("--silero", action="store_true")
    args = ap.parse_args()
    cache = os.environ.get("HF_HOME")
    from huggingface_hub import snapshot_download

    for name in args.asr:
        if name.startswith("faster_whisper"):
            from faster_whisper import download_model

            size = name.partition(":")[2] or "large-v3"
            print("faster-whisper", size, "->", download_model(size, cache_dir=cache))
            continue
        repo = PRESETS.get(name, name)
        # Only the files transformers loads: some repos (e.g. openchs) also ship full
        # training checkpoints in sub-folders, which would triple the download.
        path = snapshot_download(repo, cache_dir=cache,
                                 allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "*.tiktoken"],
                                 ignore_patterns=["*/*"])
        print(repo, "->", path)
    if args.pyannote:
        from pyannote.audio import Pipeline

        model = os.environ.get("PYANNOTE_MODEL", "pyannote/speaker-diarization-3.1")
        Pipeline.from_pretrained(model, use_auth_token=os.environ.get("HF_TOKEN"), cache_dir=cache)
        print(model, "-> cached")
    if args.silero:
        from silero_vad import load_silero_vad

        load_silero_vad()  # bundled with the pip package; this just checks it loads
        print("silero-vad -> ok (bundled)")


if __name__ == "__main__":
    main()
