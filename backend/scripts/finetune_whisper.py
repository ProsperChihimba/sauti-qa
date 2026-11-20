#!/usr/bin/env python
"""Fine-tune Whisper on the dataset exported from Sauti QA (Reports -> Speech dataset).

The export is a Hugging Face "audiofolder" (train/ and test/ with metadata.jsonl).
Defaults start from the Tanzanian helpline model, which already knows telephony
Swahili; LoRA keeps GPU memory low and the result small.

Install:   pip install -e ".[gpu,train]"
Run:
  python scripts/finetune_whisper.py --data ./asr-dataset --out ./models/sauti-whisper \
      --base openchs/asr-whisper-largev2-v6 --lora --epochs 3

Then serve it with ASR_PROVIDER=hf_whisper and ASR_MODEL=./models/sauti-whisper (a
merged copy is written to <out>/merged when --lora is used), and compare it with
scripts/benchmark_asr.py before switching production over.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.textnorm import normalize_sw  # noqa: E402


@dataclass
class Collator:
    processor: Any
    decoder_start_token_id: int

    def __call__(self, features):
        import torch  # noqa: F401

        inputs = [{"input_features": f["input_features"]} for f in features]
        batch = self.processor.feature_extractor.pad(inputs, return_tensors="pt")
        labels = [{"input_ids": f["labels"]} for f in features]
        lab = self.processor.tokenizer.pad(labels, return_tensors="pt")
        ids = lab["input_ids"].masked_fill(lab.attention_mask.ne(1), -100)
        if (ids[:, 0] == self.decoder_start_token_id).all():
            ids = ids[:, 1:]
        batch["labels"] = ids
        return batch


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="unzipped dataset export directory")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="openchs/asr-whisper-largev2-v6")
    ap.add_argument("--language", default="swahili")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=None, help="default 1e-5 full / 1e-3 LoRA")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--lora", action="store_true", help="train LoRA adapters instead of all weights")
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--eval-steps", type=int, default=200)
    ap.add_argument("--max-label-tokens", type=int, default=225)
    args = ap.parse_args()

    import evaluate
    import torch
    from datasets import Audio, load_dataset
    from transformers import (
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        WhisperForConditionalGeneration,
        WhisperProcessor,
    )

    ds = load_dataset("audiofolder", data_dir=args.data)
    if "test" not in ds:
        split = ds["train"].train_test_split(test_size=0.1, seed=42)
        ds = {"train": split["train"], "test": split["test"]}
    print({k: len(v) for k, v in ds.items()})

    processor = WhisperProcessor.from_pretrained(args.base, language=args.language, task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(args.base)
    model.generation_config.language = args.language
    model.generation_config.task = "transcribe"
    model.generation_config.forced_decoder_ids = None
    model.config.use_cache = False

    def prep(batch):
        audio = batch["audio"]
        batch["input_features"] = processor.feature_extractor(audio["array"], sampling_rate=16000).input_features[0]
        batch["labels"] = processor.tokenizer(batch["transcription"]).input_ids[: args.max_label_tokens]
        return batch

    for k in ds:
        ds[k] = ds[k].cast_column("audio", Audio(sampling_rate=16000))
        ds[k] = ds[k].map(prep, remove_columns=ds[k].column_names)

    if args.lora:
        from peft import LoraConfig, get_peft_model

        model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=args.lora_r * 2, lora_dropout=0.05,
                                                 target_modules=["q_proj", "k_proj", "v_proj", "out_proj", "fc1", "fc2"]))
        model.print_trainable_parameters()

    wer_metric = evaluate.load("wer")
    cer_metric = evaluate.load("cer")

    def metrics(pred):
        ids = pred.predictions
        label_ids = pred.label_ids
        label_ids[label_ids == -100] = processor.tokenizer.pad_token_id
        hyp = [normalize_sw(t) for t in processor.batch_decode(ids, skip_special_tokens=True)]
        ref = [normalize_sw(t) for t in processor.batch_decode(label_ids, skip_special_tokens=True)]
        return {"wer": wer_metric.compute(predictions=hyp, references=ref),
                "cer": cer_metric.compute(predictions=hyp, references=ref)}

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr or (1e-3 if args.lora else 1e-5),
        warmup_ratio=0.1,
        num_train_epochs=args.epochs,
        fp16=torch.cuda.is_available(),
        gradient_checkpointing=not args.lora,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_steps=args.eval_steps,
        save_total_limit=2,
        logging_steps=25,
        predict_with_generate=True,
        generation_max_length=args.max_label_tokens,
        load_best_model_at_end=True,
        metric_for_best_model="wer",
        greater_is_better=False,
        remove_unused_columns=False,
        label_names=["labels"],
        report_to=[],
    )
    trainer = Seq2SeqTrainer(
        model=model, args=training_args, train_dataset=ds["train"], eval_dataset=ds["test"],
        data_collator=Collator(processor, model.config.decoder_start_token_id if not args.lora
                               else model.base_model.model.config.decoder_start_token_id),
        compute_metrics=metrics, processing_class=processor.feature_extractor,
    )
    baseline = trainer.evaluate()
    print("baseline:", {k: v for k, v in baseline.items() if k in ("eval_wer", "eval_cer")})
    trainer.train()
    final = trainer.evaluate()
    print("fine-tuned:", {k: v for k, v in final.items() if k in ("eval_wer", "eval_cer")})

    trainer.save_model(args.out)
    processor.save_pretrained(args.out)
    if args.lora:
        merged = model.merge_and_unload()
        merged.save_pretrained(Path(args.out) / "merged")
        processor.save_pretrained(Path(args.out) / "merged")
        print(f"Merged model: {Path(args.out) / 'merged'}  (use as ASR_MODEL with ASR_PROVIDER=hf_whisper)")


if __name__ == "__main__":
    main()
