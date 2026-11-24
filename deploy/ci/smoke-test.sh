#!/usr/bin/env bash
# Smoke test of the running Docker Compose stack (mock providers), through Caddy.
set -euo pipefail
cd "$(dirname "$0")/../.."
BASE=http://localhost
DC=${DC:-"docker compose -f deploy/docker-compose.yml --env-file .env"}
JAR=$(mktemp)
fail() { echo "SMOKE TEST FAILED: $*" >&2; exit 1; }
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

echo "== waiting for the API through Caddy"
for _ in $(seq 1 90); do curl -fsS "$BASE/api/health" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$BASE/api/ready" | tee /dev/stderr | grep -q '"database":"ok"' || fail "API not ready"

echo "== web UI"
for _ in $(seq 1 60); do [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/login")" = 200 ] && break; sleep 2; done
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/login")" = 200 ] || fail "login page not served"

echo "== login (bootstrap admin)"
curl -fsS -c "$JAR" -H 'content-type: application/json' \
  -d '{"email":"ci-admin@sauti.local","password":"ci-admin-password"}' "$BASE/api/auth/login" >/dev/null || fail "login"

echo "== seed 3 demo calls (processed by the queued workers)"
$DC exec -T api python scripts/seed.py --demo-calls 3

echo "== REST API ingestion with an API key"
KEY=$(curl -fsS -b "$JAR" -H 'content-type: application/json' -d '{"name":"ci"}' "$BASE/api/api-keys" | json 'd["key"]')
$DC exec -T api sh -c 'ffmpeg -y -loglevel error -f lavfi -i "sine=f=330:d=20" -ar 8000 /tmp/ci-call.wav'
$DC cp api:/tmp/ci-call.wav ./ci-call.wav
curl -fsS -H "X-API-Key: $KEY" -F file=@ci-call.wav \
  -F 'metadata={"external_id":"CI-API-1","agent_name":"CI Agent","queue":"CI","mock_variant":"poor"}' \
  "$BASE/api/v1/calls" >/dev/null || fail "API ingest"

echo "== waiting for the pipeline (prepare, transcribe, label, score)"
for _ in $(seq 1 90); do
  STATUS=$(curl -fsS -b "$JAR" "$BASE/api/calls?page_size=50" | json '" ".join(sorted(c["status"] for c in d["items"]))')
  echo "   $STATUS"
  echo "$STATUS" | grep -q failed && fail "a call failed processing"
  [ "$(echo "$STATUS" | tr ' ' '\n' | grep -c done)" -ge 4 ] && break
  sleep 3
done
[ "$(echo "$STATUS" | tr ' ' '\n' | grep -c done)" -ge 4 ] || fail "calls did not finish"

R=$(curl -fsS -H "X-API-Key: $KEY" "$BASE/api/v1/calls/CI-API-1")
echo "   CI-API-1: $R"
echo "$R" | grep -q '"auto_fail":true' || fail "poor call should auto-fail"

echo "== audio playback (range request)"
CID=$(curl -fsS -b "$JAR" "$BASE/api/calls?page_size=1" | json 'd["items"][0]["id"]')
[ "$(curl -s -b "$JAR" -H 'Range: bytes=0-99' -o /dev/null -w '%{http_code}' "$BASE/api/calls/$CID/audio")" = 206 ] || fail "audio range"

echo "== Excel export"
EID=$(curl -fsS -b "$JAR" -H 'content-type: application/json' -d '{"kind":"excel"}' "$BASE/api/exports" | json 'd["id"]')
for _ in $(seq 1 30); do
  ST=$(curl -fsS -b "$JAR" "$BASE/api/exports/$EID" | json 'd["status"]')
  [ "$ST" = succeeded ] && break
  [ "$ST" = failed ] && fail "export failed"
  sleep 2
done
curl -fsS -b "$JAR" -o report.xlsx "$BASE/api/exports/$EID/download"
head -c 2 report.xlsx | grep -q PK || fail "export is not an xlsx file"

echo "SMOKE TEST PASSED"
