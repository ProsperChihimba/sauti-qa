#!/usr/bin/env python
"""Benchmark speech-to-text models on your own Swahili call recordings.

Input (one of):
  --data DIR         audio files with a same-named .txt reference next to each
                     (call1.wav + call1.txt), or a manifest
  --manifest FILE    JSONL lines {"audio": "path.wav", "text": "reference"} or
                     CSV with columns audio,text (paths relative to the manifest)

Models (comma-separated, provider[:model]):
  mock, openchs, buzzasr, faster_whisper[:large-v3|path], hf_whisper:<repo-or-path>,
  openai[:whisper-1]   (the last one sends audio to the configured endpoint!)

Reports WER and CER after Swahili-aware normalisation (lowercase, punctuation,
fillers, numbers as Swahili words, redaction tags removed), and speed as the
real-time factor (processing seconds / audio seconds; lower is faster).

Example:
  python scripts/benchmark_asr.py --data ./bench --models openchs,buzzasr,faster_whisper:large-v3 \
      --out results.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jiwer  # noqa: E402

from app.services.asr import ASRContext, build_provider  # noqa: E402
from app.services.audio import load_pcm  # noqa: E402
from app.services.audio.vad import detect_speech  # noqa: E402
from app.services.textnorm import normalize_sw  # noqa: E402

AUDIO_EXT = {".wav", ".mp3", ".ogg", ".opus", ".flac", ".m4a", ".amr", ".gsm", ".webm"}


def load_items(args) -> list[tuple[Path, str]]:
    items = []
    if args.manifest:
        m = Path(args.manifest)
        base = m.parent
        if m.suffix == ".jsonl":
            for line in m.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    items.append((base / d["audio"], d["text"]))
        else:
            with m.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    items.append((base / row["audio"], row["text"]))
    else:
        for p in sorted(Path(args.data).iterdir()):
            if p.suffix.lower() in AUDIO_EXT and p.with_suffix(".txt").exists():
                items.append((p, p.with_suffix(".txt").read_text(encoding="utf-8").strip()))
    if args.limit:
        items = items[: args.limit]
    if not items:
        sys.exit("No audio/reference pairs found.")
    return items


def run_model(spec: str, items, channel: int | None, use_vad: bool):
    name, _, model = spec.partition(":")
    t0 = time.perf_counter()
    provider = build_provider(name, model or None)
    load_s = time.perf_counter() - t0
    refs, hyps, per_file = [], [], []
    audio_s = proc_s = 0.0
    for path, ref in items:
        audio = load_pcm(path, channel=channel)
        dur = len(audio) / 16000
        t = time.perf_counter()
        regions = detect_speech(audio, max_len=provider.max_region_seconds) if use_vad else [(0.0, dur)]
        if not use_vad:
            # Whisper windows are 30 s: chunk long files.
            regions = [(a, min(dur, a + 28.0)) for a in [i * 28.0 for i in range(int(dur // 28) + 1)] if a < dur]
        segs = provider.transcribe(audio, regions, ASRContext(call_id=path.stem, duration=dur))
        elapsed = time.perf_counter() - t
        hyp = " ".join(s.text for s in segs)
        r, h = normalize_sw(ref), normalize_sw(hyp)
        refs.append(r)
        hyps.append(h)
        audio_s += dur
        proc_s += elapsed
        per_file.append({"file": path.name, "wer": jiwer.wer(r, h) if r else None, "cer": jiwer.cer(r, h) if r else None,
                         "rtf": elapsed / dur if dur else None, "hypothesis": hyp})
    return {
        "model": spec,
        "model_id": getattr(provider, "model_id", spec),
        "files": len(items),
        "audio_minutes": round(audio_s / 60, 2),
        "wer": round(jiwer.wer(refs, hyps), 4),
        "cer": round(jiwer.cer(refs, hyps), 4),
        "rtf": round(proc_s / audio_s, 4) if audio_s else None,
        "load_seconds": round(load_s, 1),
        "per_file": per_file,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data")
    src.add_argument("--manifest")
    ap.add_argument("--models", required=True)
    ap.add_argument("--channel", choices=["mix", "left", "right"], default="mix",
                    help="for stereo recordings: score one channel only (e.g. the agent)")
    ap.add_argument("--no-vad", action="store_true", help="transcribe whole files in 28 s windows")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", help="write full results (incl. per-file hypotheses) to this JSON file")
    args = ap.parse_args()

    items = load_items(args)
    channel = {"mix": None, "left": 0, "right": 1}[args.channel]
    results = []
    for spec in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"> {spec} on {len(items)} files ...", flush=True)
        try:
            results.append(run_model(spec, items, channel, not args.no_vad))
        except Exception as exc:  # noqa: BLE001 - report and continue with the next model
            print(f"  failed: {type(exc).__name__}: {exc}")
            results.append({"model": spec, "error": str(exc)})

    print()
    print(f"{'model':<34} {'WER':>7} {'CER':>7} {'RTF':>7} {'audio min':>10}")
    for r in sorted(results, key=lambda r: r.get("wer", float("inf"))):
        if "error" in r:
            print(f"{r['model']:<34} error: {r['error'][:60]}")
        else:
            print(f"{r['model']:<34} {r['wer']:>7.1%} {r['cer']:>7.1%} {r['rtf']:>7.3f} {r['audio_minutes']:>10}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull results: {args.out}")


if __name__ == "__main__":
    main()
