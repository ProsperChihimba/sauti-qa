# Real test, November 2026

First run of the platform with real speech models and real Swahili speech, on a
CPU-only machine (4 cores, 16 GB RAM, no GPU).

## Test data

No real call recordings were available, so the test used real human Swahili speech
from the public **FLEURS** dataset (Kenyan Swahili, `sw_ke` test split, read
sentences), degraded to telephone quality:

- loudness to -20 LUFS, band-limited to 300-3400 Hz, resampled to 8 kHz,
  G.711 mu-law codec round trip, pink line noise about 30 dB below the speech.

25 clips (6.3 minutes) were used for the benchmark. One FLEURS source clip turned
out to be almost silent (one second above -45 dB in 10.7 s); results are given with
and without it.

A stereo "call" (81 s) was also built from six FLEURS utterances alternating
between the left (agent) and right (customer) channels, then run through the full
platform via the API.

Caveat: read sentences are cleaner and more formal than call-centre conversation
(no overlap, no code-switching, no product names). Expect higher error rates on
real calls; repeat this benchmark on 50 to 100 real calls with analyst-written
references before choosing a production model.

## ASR benchmark (`scripts/benchmark_asr.py`, Swahili-normalised WER/CER)

| Model | WER | CER | WER without silent clip | Speed (CPU, real-time factor) |
|---|---|---|---|---|
| `buzzasr` (BuzzASR/swahili, Whisper large-v3 fine-tune) | **17.9%** | **8.8%** | **16.2%** | 3.3 (3.3x slower than real time) |
| `faster_whisper:large-v3` (int8) | 37.4% | 12.7% | 36.1% | 0.9 |

BuzzASR halves the word error rate of plain Whisper large-v3 on this data. Note that
BuzzASR was trained on FLEURS (train split) and Common Voice, so this test set is
in-domain for it; the gap on real calls may be smaller.

`openchs/asr-whisper-largev2-v6` could not be tested: it is gated on Hugging Face
("access is restricted and you are not in the authorized list"). Its model card
reports 44% WER on real helpline phone calls.

On a GPU (fp16) both models run far faster than real time. On this 4-core CPU,
BuzzASR needs about 3.3 hours of processing per hour of audio, so a CPU-only
install only suits very low volumes or a pilot.

## Full pipeline on the stereo call

Upload via the API → prepare (ffmpeg, Silero VAD) → BuzzASR per channel →
redaction → (mock) scoring → routing → Excel export. Took 4.5 minutes on CPU for
81 s of audio.

- Speaker labels: all 9 transcript lines on the correct side (stereo channels).
- Transcript quality: most lines near word-for-word, e.g.
  reference "Tamaduni na makabila ya kale yalianza kuwafuga kwa ufikiaji rahisi wa
  maziwa, nywele, nyama, na ngozi." → "tamaduni na makabila ya kale alianza kuwafuga
  kwa ufikiaji rahisi wa maziwa nywele nyama na ngozi"; "2007" came out as spoken,
  "elfu mbili na saba". One weak line ("Vile vile, wanaume wanahitajika kuvaa
  suruali..." → "katika kuvazu ruwale ilihitajika magoti", confidence 0.39) is the
  kind the review screen flags as low-confidence.
- Playback MP3, review data and the Excel report were produced.
- Scoring used the mock scorer (no LLM key was configured), so the score is not
  meaningful; LLM scoring still needs a live test.
- Crash recovery: the first attempt was killed for lack of memory mid-transcription;
  the stuck-job recovery re-queued it and the call completed.

## Problems found and fixed

| Problem | Fix |
|---|---|
| `backend/app/models/` was excluded by `.gitignore` (`models/`), so the repository could not run | `.gitignore` entry anchored to `/models/`; files restored |
| BuzzASR has no timestamp tokens (replaced tokenizer), the provider crashed | Detect timestamp support; without it, each VAD region is one transcript line and regions are capped at 12 s |
| Very quiet recordings: VAD found no speech, call came out empty | Gain normalisation before VAD/ASR (capped at +45 dB); playback loudness-normalised |
| Whisper invents short phrases on noise/silence ("Hii ni chanzo", "Stamba na stamba au tupu") | Segments with very low confidence are dropped (configurable), times kept on the call |
| Batch decoding on CPU: batch 8 ran out of 16 GB, with no speed gain | CPU decodes one region at a time; batching stays for GPU |
| `download_models.py` would fetch openchs three times (~18 GB: model plus two training checkpoints) | Download only root model files |

## Still to test

- LLM scoring with Claude (needs `ANTHROPIC_API_KEY`) or an on-prem model.
- pyannote diarization on mono calls (needs the Hugging Face account to accept the
  pyannote model terms).
- openchs (needs access approval).
- Backend Docker image build (Docker Hub rate-limited the test machine) and the GPU image.
- Real call-centre recordings.
