# Sauti QA

AI quality assurance for Swahili call centres. Every call is transcribed, redacted, scored against your QA scorecard and summarised in Swahili and English. Only the calls that need a human go to analysts, so analysts review instead of listening, and coverage goes from a small sample to 100% of calls.

```
recorder ──▶ upload / SFTP inbox / REST API
                 │
                 ▼
  prepare (cpu)    ffmpeg 16 kHz, stereo kept, mp3 playback copy, VAD
  transcribe (gpu) Whisper (Swahili fine-tunes) per stereo channel, or ASR + pyannote for mono
                   PII redacted in memory before anything is stored
  label (llm)      mono calls: LLM decides which speaker is the agent (heuristic fallback)
  score (llm)      LLM answers each criterion with verbatim Swahili evidence
                   output validated + repaired, score computed in code, review routing
                 │
                 ▼
  dashboard · review queue · review screen · Excel/CSV reports · speech dataset export
```

| Folder | What is inside |
|---|---|
| `backend/` | FastAPI app, SQLAlchemy models, Alembic migrations, Celery workers, scripts, tests |
| `web/` | Next.js (App Router, TypeScript, Tailwind, shadcn/ui-style components, Recharts) |
| `deploy/` | Docker Compose stack and Caddy config |
| `.env.example` | Every setting, documented |

## Contents

1. [Quick start (demo, no GPU)](#quick-start-demo-no-gpu)
2. [Production setup](#production-setup)
3. [Getting calls in](#getting-calls-in)
4. [Choosing models](#choosing-models)
5. [Going fully on-prem / offline](#going-fully-on-prem--offline)
6. [Data protection checklist (Tanzania PDPA)](#data-protection-checklist-tanzania-personal-data-protection-act)
7. [Scorecards, scoring and review routing](#scorecards-scoring-and-review-routing)
8. [Reports](#reports)
9. [Continuous improvement: fine-tuning Whisper](#continuous-improvement-fine-tuning-whisper)
10. [Operations](#operations)
11. [Development](#development)

## Quick start (demo, no GPU)

The mock speech and LLM providers return a realistic Swahili customer-care dialogue, so the whole platform runs on a laptop.

```bash
cp .env.example .env
```

Edit `.env`: set `SECRET_KEY`, `POSTGRES_PASSWORD`, `BOOTSTRAP_ADMIN_PASSWORD`, and for the demo:

```
SITE_ADDRESS=:80
COOKIE_SECURE=false
PUBLIC_BASE_URL=http://localhost
ASR_PROVIDER=mock
LLM_PROVIDER=mock
VAD_BACKEND=energy
DIARIZATION_BACKEND=none
CPU_WORKER_QUEUES=cpu,llm,maintenance,gpu
```

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

```bash
docker compose -f deploy/docker-compose.yml --env-file .env exec api python scripts/seed.py --demo-calls 40
```

Open http://localhost and sign in with `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`. The seed script creates the default Swahili telecom scorecard and 40 synthetic calls (good, poor and escalated) spread over two weeks.

## Production setup

1. **Server**: Linux with Docker and Docker Compose. For real transcription: an NVIDIA GPU (24 GB VRAM recommended for Whisper large; 16 GB works with `faster_whisper` int8/float16), the NVIDIA driver and the NVIDIA Container Toolkit.
2. **Configure**: `cp .env.example .env` and fill in every value marked REQUIRED. Set `SITE_ADDRESS` to the DNS name analysts will use.
   - Public DNS name: leave `TLS_DIRECTIVE` empty for automatic Let's Encrypt.
   - Internal-only name: `TLS_DIRECTIVE=tls internal`, then install Caddy's root certificate on analyst PCs, or mount your corporate certificate and use `tls /certs/cert.pem /certs/key.pem`.
3. **Start** (with the GPU worker):

```bash
docker compose -f deploy/docker-compose.yml --env-file .env --profile gpu up -d --build
```

4. **Download models once** (see [Going on-prem](#going-fully-on-prem--offline)), then set `HF_HUB_OFFLINE=1`.
5. **Sign in** with the bootstrap admin, change the password (or create named admins under Users and remove the bootstrap lines from `.env`), create analyst accounts, review the scorecard, and create an API key for the call recorder.

Services:

| Service | Role | Scale |
|---|---|---|
| `caddy` | HTTPS, single origin (`/api/*` → api, rest → web) | 1 |
| `web` | Next.js UI | 1+ |
| `api` | FastAPI; runs migrations on start | 1+ |
| `cpu-worker` | queues `cpu` (audio prep, exports), `llm` (speaker ID, scoring), `maintenance` | add replicas for throughput |
| `gpu-worker` | queue `gpu` (ASR + diarization), one model per process | one per GPU |
| `beat` | schedules stuck-job recovery (5 min) and audio retention purge (hourly) | exactly 1 |
| `inbox` | watches the SFTP inbox folder | exactly 1 |
| `postgres`, `redis` | data, queue | 1 |
| `minio` (profile `s3`) | optional bundled S3 store; by default audio is on the `storage` volume | optional |
| `sftp` (profile `sftp`) | optional SFTP endpoint for the recorder | optional |

Capacity guide: one modern GPU transcribes roughly 30 to 100 hours of call audio per hour with `faster_whisper` (less with transformers checkpoints). Measure on your hardware with the benchmark script.

## Getting calls in

All three paths are idempotent: re-sending an `external_id`, or a byte-identical file, never creates a second call.

**1. Browser upload** (Upload page): drag in many files at once. A `.json` file with the same name as an audio file is treated as its sidecar.

**2. Watched inbox folder (SFTP)**: the recorder drops files into the `inbox` volume (directly, through your SFTP server mounted on it, or through the built-in one: `--profile sftp`, port `SFTP_PORT`, user `SFTP_USER`, folder `upload/`). A file is picked up only after its size has been stable for `INBOX_STABLE_SECONDS`, and names ending in `.part`, `.tmp` or `.filepart` are ignored, so half-transferred files are never processed. Ingested files move to `processed/YYYY-MM-DD/`; rejected files move to `failed/` with a `.error.txt` beside them.

Optional sidecar `call123.json` next to `call123.wav`:

```json
{
  "external_id": "REC-2026-11-19-000123",
  "agent_name": "Neema Mushi",
  "queue": "M-Pesa",
  "call_time": "2026-11-19T10:15:00+03:00",
  "agent_channel": "left"
}
```

`call_time` without a timezone is read as East Africa Time. `agent_channel` overrides the stereo channel mapping for this call. Extra keys are stored as call metadata.

**3. REST API** with an API key (Users & API keys page):

```bash
curl -H "X-API-Key: $SAUTI_API_KEY" \
  -F file=@call123.wav \
  -F 'metadata={"external_id":"REC-123","agent_name":"Neema Mushi","queue":"Prepaid"}' \
  https://qa.example.co.tz/api/v1/calls
```

```bash
curl -H "X-API-Key: $SAUTI_API_KEY" https://qa.example.co.tz/api/v1/calls/REC-123
```

The second call returns processing status, score, pass/fail and review status. Interactive API docs: `/api/docs`.

**Stereo recordings** give exact speaker separation: each channel is transcribed separately and labelled agent or customer by the channel mapping (Settings → Agent channel; default left). **Mono recordings** are diarized with pyannote, then the LLM decides which speaker is the agent, falling back to keyword heuristics (greeting with the brand, "naitwa", "nikusaidie"...). Analysts can relabel a line or swap both speakers in the review screen.

## Choosing models

### Speech-to-text (`ASR_PROVIDER`)

| Provider | Model | When to use |
|---|---|---|
| `buzzasr` | `BuzzASR/swahili` | **Start here.** Whisper large-v3 fine-tuned for Swahili, openly downloadable. Best result in our phone-quality test (see `docs/real-test-2026-11.md`). Has no timestamp tokens, so each speech region becomes one transcript line |
| `openchs` | `openchs/asr-whisper-largev2-v6` | Whisper large-v2 adapted to Tanzanian helpline phone calls. **Gated**: request access on its Hugging Face page. Its card reports 44% WER on real helpline audio; benchmark it against BuzzASR on your own calls once you have access |
| `faster_whisper` | `large-v3` (or `ASR_MODEL=/path/to/ct2-model`) | Fastest on GPU, word timestamps. Fine-tuned checkpoints can be converted with `ct2-transformers-converter --model openchs/asr-whisper-largev2-v6 --output_dir /models/openchs-ct2 --quantization float16` |
| `hf_whisper` | `ASR_MODEL=<repo or folder>` | Your own fine-tuned model (see below) |
| `openai` | any OpenAI-compatible `/audio/transcriptions` | Cloud or a self-hosted compatible server. **Sends audio off the server: only with written client approval** when pointed at a cloud endpoint |
| `mock` | canned dialogue | Demos and tests |

**Benchmark on your own calls before choosing.** Take 50 to 100 representative calls (mix of queues, noisy and clean, code-switching), have analysts write reference transcripts, then:

```bash
docker compose -f deploy/docker-compose.yml --profile gpu run --rm -v $PWD/bench:/bench gpu-worker \
  python scripts/benchmark_asr.py --data /bench --models buzzasr,faster_whisper:large-v3 --out /bench/results.json
```

Real results on phone-quality Swahili are in `docs/real-test-2026-11.md`. It reports WER, CER and real-time factor per model after Swahili-aware normalisation (lowercase, punctuation, hesitation fillers, digits spoken as Swahili words so "10,000" equals "elfu kumi", redaction tags removed). Use `--channel left` to score only the agent side of stereo files. References can also come from a JSONL/CSV manifest (`--manifest`).

### LLM scoring (`LLM_PROVIDER`)

| Provider | Use |
|---|---|
| `anthropic` (default model `claude-sonnet-5-5`) | Prototyping and the accuracy baseline. Sends redacted transcripts to Anthropic. The scorecard prompt is prompt-cached; JSON output is schema-constrained; server-side fallback on declined requests is on by default (`ANTHROPIC_FALLBACKS=default`, set empty to disable) |
| `openai` | **On-prem production**: an open model served by vLLM or Ollama on your network (`LLM_OPENAI_BASE_URL=http://vllm:8000/v1`, `LLM_MODEL=<served name>`). JSON mode is negotiated automatically (`json_schema`, then `json_object`, then plain text) |
| `mock` | Tests and demos |

Recommended approach: score a few hundred calls with Claude, have analysts review a sample, then run the same calls through candidate open models (a strong multilingual instruction model, 30B+ parameters for good Swahili) and compare agreement with the analyst-corrected answers before switching. The prompt always tells the model to judge only the agent, not to penalise transcription errors, to lower confidence when unclear, and to quote verbatim in Swahili.

**Measure a model before trusting it.** `backend/evals/scoring/` holds 30 Swahili customer-care calls with analyst answers (fraud, wrong information, traps, rude agents, code-switching, noisy transcripts...). `python scripts/eval_scoring.py --provider anthropic` (or `--provider openai --model ... --base-url ...`) reports agreement per criterion, critical failures caught and missed, false auto-fails, flags and resolution accuracy. Run it for every candidate model; see `backend/evals/scoring/README.md`.

**The model never computes the score.** It returns yes / no / na per criterion with evidence and confidence; the code validates and repairs that output (missing criteria, invalid answers, N/A where not allowed, non-existent or wrong segment references, paraphrased quotes) and computes: score = points earned / applicable points; any critical criterion answered "no" is an auto-fail (score 0). Every repair is logged on the evaluation and forces human review.

## Going fully on-prem / offline

1. Choose `ASR_PROVIDER` from `buzzasr`, `openchs`, `faster_whisper` or `hf_whisper`; `LLM_PROVIDER=openai` pointed at an internal vLLM/Ollama server; audio on the local `storage` volume (default) or `STORAGE_BACKEND=s3` with the client's own S3-compatible store.
2. Download the weights once, with internet access, into the `models` volume:

```bash
docker compose -f deploy/docker-compose.yml --env-file .env --profile gpu run --rm gpu-worker \
  python scripts/download_models.py --asr buzzasr faster_whisper --pyannote --silero
```

   Only the model files at the root of each repository are downloaded (some repositories also hold full training checkpoints). The openchs model is gated: request access first. pyannote weights are gated too: accept the terms of `pyannote/speaker-diarization-3.1` (and `pyannote/segmentation-3.0`) on huggingface.co and set `HF_TOKEN` for this step only.
3. Set `HF_HUB_OFFLINE=1`, remove `HF_TOKEN`, restart. The UI uses system fonts and no external assets; Next.js telemetry is disabled in the image.
4. To move to an air-gapped server: build the images, then `docker save` them and copy the `models` volume.
5. Block outbound internet for the stack at the firewall and confirm `/api/ready` reports your local providers.

## Data protection checklist (Tanzania Personal Data Protection Act)

This is a technical checklist, not legal advice. Confirm obligations with the client's DPO and counsel.

**Built into the platform**

- [x] PII redacted **before storage**: Tanzanian phone numbers (+255 / 0 6xx / 7xx), NIDA numbers, card numbers (Luhn-checked), account numbers, PINs after a keyword, e-mails, and numbers dictated as words in Swahili or English ("sifuri saba sita..."). Raw ASR text is never written to disk. Analyst corrections are redacted too. Money amounts, dates and times are kept.
- [x] Optional muting of spoken PII in the playback audio (`MUTE_REDACTED_AUDIO=true`, needs word timestamps).
- [x] Audio retention with automatic deletion (Settings, default 90 days); redacted transcripts and scores remain for reporting.
- [x] No audio or transcript leaves the server unless a cloud provider is explicitly configured (`ASR_PROVIDER=openai` with a cloud URL, `LLM_PROVIDER=anthropic`).
- [x] Role-based access (admin, analyst); speech datasets can only be exported by admins and exclude any line whose audio contained personal data.
- [x] Audit log of sign-ins, overrides, transcript edits, re-scores, reviews, exports, downloads, settings, user and scorecard changes.
- [x] Sessions in httpOnly SameSite cookies; passwords hashed with Argon2; API keys stored as keyed hashes and revocable; HTTPS via Caddy with HSTS.

**Your responsibilities during deployment**

- [ ] Process on-prem in Tanzania (or as agreed with the client); use the on-prem providers above.
- [ ] If a cloud LLM is used even temporarily: written client approval, a data processing agreement, and a cross-border transfer assessment.
- [ ] Register / notify with the Personal Data Protection Commission as required and record this processing in the client's records of processing.
- [ ] Confirm the lawful basis and call-recording notice ("calls may be recorded for quality purposes") covers automated QA analysis.
- [ ] Encrypt disks (LUKS) holding the Postgres, audio storage and backup volumes; if the bundled MinIO is used, keep its console on localhost (the default).
- [ ] Set retention to the client's policy; agree what happens to transcripts and exports at contract end.
- [ ] Use named accounts only, enforce strong passwords, remove the bootstrap admin from `.env`, review the audit log periodically.
- [ ] Back up Postgres and the audio storage to encrypted storage; test restores.
- [ ] Spot-check redaction on real calls during pilot (redaction is rule-based; add patterns for new identifier formats in `backend/app/services/redaction/__init__.py`).
- [ ] Handle data-subject requests: calls can be found by `external_id` or search and deleted by an admin (audio and data removed).

## Scorecards, scoring and review routing

Scorecards are JSON (editable in the UI form or as raw JSON). Each criterion has `id`, `section`, `label`, `description`, Swahili `examples` (met), optional `negative_examples` (failed), `weight`, `critical`, `allow_na` and optional `na_guidance`. Every save creates a new version; evaluations keep a link to the version they were scored with. The default "Telecom Customer Care (Swahili)" scorecard is in `backend/seed/scorecard_telecom_sw.json`.

A call goes to the review queue when any of these hold (thresholds in Settings):

- critical failure (auto-fail),
- a flag: fraud (e.g. the agent asked for a PIN), wrong information, escalation risk,
- score below the threshold (default 80%),
- any criterion with AI confidence below the threshold (default 0.6), including repaired AI output.

The queue is ordered by urgency (auto-fail, then flagged, then lowest score). "Start reviewing" claims the next call; several analysts can work at once without collisions.

On the review screen analysts can play the audio with a speaker timeline, click a timestamp or an evidence quote to jump there, correct lines inline (double-click), relabel speakers, override any answer (the score is recalculated instantly, the AI's answer is kept for comparison), add notes and coaching points, re-score from the corrected transcript (human overrides are kept), and "Mark reviewed & next".

## Reports

Reports & exports page:

- **Excel QA report**: Summary (KPIs, call reasons, resolution, sentiment), Agents, Criteria, and Details (one row per call: score, result, failed items, critical failures, Swahili and English summaries, flags, reviewer, reviewer notes, overridden items, and one Y/N/N/A column per criterion).
- **CSV**: one row per call with every answer, for BI tools.

The workbook layout is defined in `backend/seed/report_layout.yaml`: sheet names, column order, headers, widths and number formats. To match the client's exact template, copy the file, edit it, and set `REPORT_LAYOUT_PATH`; set `template:` to the client's `.xlsx` to fill their workbook in place starting at `start_row`.

## Continuous improvement: fine-tuning Whisper

Every transcript correction is training data. Reports & exports → **Speech dataset** (admins) exports the analyst-corrected lines as a Hugging Face audiofolder zip (`train/`, `test/`, `metadata.jsonl`, 16 kHz WAV clips cut from the speaker's own channel for stereo calls). Lines whose audio contained personal data are always excluded. The split is by call, so no call is in both train and test.

```bash
pip install -e ".[gpu,train]"
python scripts/finetune_whisper.py --data ./asr-dataset --out /models/sauti-whisper \
  --base BuzzASR/swahili --lora --epochs 3
```

The script reports WER/CER before and after (same normaliser as the benchmark), and with `--lora` writes a merged model to `<out>/merged`. Benchmark it against the current model, then switch with `ASR_PROVIDER=hf_whisper` and `ASR_MODEL=/models/sauti-whisper/merged`. A few hundred minutes of corrected audio typically gives a noticeable gain on in-domain vocabulary (product names, bundle names, M-Pesa terms); keep a fixed benchmark set to measure each round.

## Operations

- **Processing jobs** page (admin): queued, running and failed stages per call, with error details and Retry. Workers ack late, so a crashed worker's job is redelivered; the `beat` service re-queues jobs with a stale heartbeat every 5 minutes (`JOB_STUCK_MINUTES`) and gives up after `JOB_MAX_ATTEMPTS`.
- **Reprocess** a call from any stage: `POST /api/calls/{id}/reprocess?from=transcribe` (admin), e.g. after changing the ASR model.
- **Health**: `/api/health` (liveness), `/api/ready` (database, Redis, configured providers).
- **Backups**: `pg_dump` the database and back up the `storage` volume (or the S3 bucket when `STORAGE_BACKEND=s3`). Audio is the large part; transcripts and scores are in Postgres.
- **Audio storage**: the default is the `storage` Docker volume. To use S3-compatible storage set `STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`; or start the bundled MinIO with `--profile s3` (MinIO no longer publishes images on Docker Hub; `MINIO_IMAGE` defaults to the official quay.io image).
- **Create or reset an admin**: `docker compose ... exec api python scripts/create_admin.py --email you@example.co.tz`.
- **Upgrades**: rebuild images; the API applies database migrations (Alembic) on start.

## Checking a build (CI or any machine with Docker)

`deploy/ci/run-all.sh` runs everything CI runs, needing only Docker:

```bash
deploy/ci/run-all.sh
```

It runs backend lint and tests (Postgres and Redis in containers), web lint and type-check, builds the images, starts the full stack with mock providers on port 80, and runs `deploy/ci/smoke-test.sh` through Caddy: login, calls ingested by upload and by the REST API, processed by the queued workers, auto-fail detection, audio playback and an Excel export. Use `--tests` or `--stack` to run one half. The same steps run on GitHub Actions (`.github/workflows/ci.yml`) for every pull request.

## Development

Backend (Python 3.12, Postgres and Redis running locally):

```bash
cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[dev]"
createdb sauti && createdb sauti_test
.venv/bin/alembic upgrade head
.venv/bin/pytest
```

```bash
VAD_BACKEND=energy DIARIZATION_BACKEND=mock CELERY_EAGER=true .venv/bin/uvicorn app.main:app --reload
```

`CELERY_EAGER=true` runs the pipeline inline, so no worker is needed. Seed demo data with `.venv/bin/python scripts/seed.py --admin-password ... --demo-calls 30 --inline`.

Frontend:

```bash
cd web && npm install && npm run dev
```

The dev server proxies `/api/*` to `http://localhost:8000` (`API_INTERNAL_URL`).

Tests run against a real Postgres (`TEST_DATABASE_URL`, default `sauti_test`) with mock ASR and mock LLM, and cover: the full flow (upload, transcribe, score, override, re-score, review, Excel, CSV and dataset export), redaction (Swahili spoken numbers, phone/NIDA/card/PIN, amounts kept), score maths, LLM output validation and repair, provider request construction, stereo and mono pipelines, review queue claiming, scorecard versioning, dashboard aggregates, ingestion (upload, API, inbox), auth and roles, jobs, retention and audio range streaming.
