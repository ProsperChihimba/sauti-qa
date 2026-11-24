#!/usr/bin/env bash
# Run every check that CI runs, on any machine with Docker (no Python/Node needed):
#   1. backend lint + tests (Postgres + Redis containers, mock ASR/LLM)
#   2. web lint + type-check (the image build in step 3 also runs `next build`)
#   3. build the api and web images, start the full stack with mock providers,
#      run the smoke test through Caddy, then tear everything down.
#
# Usage:  deploy/ci/run-all.sh            all steps
#         deploy/ci/run-all.sh --stack    only step 3
#         deploy/ci/run-all.sh --tests    only steps 1-2
# The stack test uses port 80 and a throwaway .env.ci; your own .env is not touched.
set -euo pipefail
cd "$(dirname "$0")/../.."
MODE=${1:-all}
T="docker compose -f deploy/ci/tests.yml"
S="docker compose -p sauti-qa-ci -f deploy/docker-compose.yml --env-file .env.ci"
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

if [ "$MODE" != "--stack" ]; then
  step "1/3 backend lint and tests"
  $T run --rm backend-tests
  step "2/3 web lint and type-check"
  $T run --rm web-checks
  $T down -v --remove-orphans >/dev/null 2>&1 || true
fi

if [ "$MODE" != "--tests" ]; then
  step "3/3 images, full stack and smoke test"
  bash deploy/ci/make-env.sh > .env.ci
  cleanup() {
    $S down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f .env.ci ci-call.wav report.xlsx
  }
  trap cleanup EXIT
  # The stack reads ../.env; point it at the throwaway file for this run.
  ENV_BACKUP=""
  if [ -f .env ]; then ENV_BACKUP=$(mktemp); cp .env "$ENV_BACKUP"; fi
  cp .env.ci .env
  restore() { if [ -n "$ENV_BACKUP" ]; then mv "$ENV_BACKUP" .env; else rm -f .env; fi; cleanup; }
  trap restore EXIT
  ${SKIP_BUILD:+:} $S build api web
  if ! $S up -d || ! DC="$S" bash deploy/ci/smoke-test.sh; then
    $S logs --tail 150
    exit 1
  fi
fi

step "ALL CHECKS PASSED"
