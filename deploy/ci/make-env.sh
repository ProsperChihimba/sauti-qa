#!/usr/bin/env bash
# Print a .env for CI: mock speech and LLM providers, plain HTTP, random secrets.
set -euo pipefail
cd "$(dirname "$0")/../.."
rand() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
sed \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=$(rand)$(rand)|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand)|" \
  -e "s|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=$(rand)|" \
  -e "s|^BOOTSTRAP_ADMIN_EMAIL=.*|BOOTSTRAP_ADMIN_EMAIL=ci-admin@sauti.local|" \
  -e "s|^BOOTSTRAP_ADMIN_PASSWORD=.*|BOOTSTRAP_ADMIN_PASSWORD=ci-admin-password|" \
  -e "s|^SITE_ADDRESS=.*|SITE_ADDRESS=:80|" \
  -e "s|^COOKIE_SECURE=.*|COOKIE_SECURE=false|" \
  -e "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://localhost|" \
  -e 's|^CORS_ORIGINS=.*|CORS_ORIGINS=["http://localhost"]|' \
  -e "s|^ASR_PROVIDER=.*|ASR_PROVIDER=mock|" \
  -e "s|^LLM_PROVIDER=.*|LLM_PROVIDER=mock|" \
  -e "s|^VAD_BACKEND=.*|VAD_BACKEND=energy|" \
  -e "s|^DIARIZATION_BACKEND=.*|DIARIZATION_BACKEND=none|" \
  -e "s|^CPU_WORKER_QUEUES=.*|CPU_WORKER_QUEUES=cpu,llm,maintenance,gpu|" \
  .env.example
