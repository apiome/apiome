#!/usr/bin/env bash
#
# Pact Broker API conformance suite (PFX-1.8, #6921) against a fresh stack.
#
# Brings up Postgres + migrate + seed under their own compose project (so a dev stack on the same
# machine is untouched), starts apiome-rest from source with uv, runs conformance.py — the official
# pact-broker CLI, pact-js and pact-jvm against Apiome, with golden HAL transcripts — and tears the
# stack down. The REST image is not built: the Pact Broker routes need none of its bundled tools.
#
# Usage (from anywhere):
#   scripts/pact_conformance/run.sh                         # every client
#   scripts/pact_conformance/run.sh --clients cli,pact-js   # a subset (cli is always needed)
#   scripts/pact_conformance/run.sh --update-golden         # rewrite golden/ after an intended change
#   scripts/pact_conformance/run.sh --keep                  # leave the stack running afterwards
#
# Ports (override with env): POSTGRES_PUBLISH_PORT (5442), APIOME_REST_PORT (8041), PACT_PROVIDER_PORT (8790).
# Needs: docker (with compose), uv.
set -euo pipefail

KEEP=0
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP=1 ;;
    --update-golden) PASS+=("--update-golden") ;;
    --clients) PASS+=("--clients" "$2"); shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-apiome-pact-conformance}"
export POSTGRES_PUBLISH_PORT="${POSTGRES_PUBLISH_PORT:-5442}"
REST_PORT="${APIOME_REST_PORT:-8041}"
export PACT_PROVIDER_PORT="${PACT_PROVIDER_PORT:-8790}"
LOG_DIR="${PACT_CONFORMANCE_LOG_DIR:-$(mktemp -d)}"
REST_PID=""

cleanup() {
  if [ -n "$REST_PID" ]; then kill "$REST_PID" 2>/dev/null || true; fi
  if [ "$KEEP" -eq 0 ]; then
    echo "==> Tearing down ($COMPOSE_PROJECT_NAME)"
    docker compose down -v >/dev/null 2>&1 || true
  else
    echo "==> Leaving Postgres running. Tear down with: COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME docker compose down -v"
  fi
}
trap cleanup EXIT

echo "==> Fresh database (Postgres on :$POSTGRES_PUBLISH_PORT, migrate, seed)"
docker compose down -v >/dev/null 2>&1 || true
docker compose up --build --wait postgres migrate
docker compose run --rm seed

echo "==> apiome-rest from source on :$REST_PORT (log: $LOG_DIR/rest.log)"
(
  cd apiome-rest/src
  APIOME_LOAD_DOTENV=0 POSTGRES_HOST=localhost POSTGRES_PORT="$POSTGRES_PUBLISH_PORT" POSTGRES_DB=apiome \
    POSTGRES_USER=postgres POSTGRES_PASSWORD=apiome_local_dev PYTHONPATH=. \
    exec uv run --frozen --project .. uvicorn app.main:app --host 127.0.0.1 --port "$REST_PORT"
) >"$LOG_DIR/rest.log" 2>&1 &
REST_PID=$!
for _ in $(seq 1 120); do
  if curl -sf -o /dev/null "http://127.0.0.1:$REST_PORT/health"; then break; fi
  if ! kill -0 "$REST_PID" 2>/dev/null; then tail -40 "$LOG_DIR/rest.log"; exit 1; fi
  sleep 1
done
curl -sf -o /dev/null "http://127.0.0.1:$REST_PORT/health" || { tail -40 "$LOG_DIR/rest.log"; exit 1; }

echo "==> Conformance suite"
PY=(python3)
if command -v uv >/dev/null 2>&1; then PY=(uv run --no-project python); fi
"${PY[@]}" "$SCRIPT_DIR/conformance.py" --rest-url "http://127.0.0.1:$REST_PORT" "${PASS[@]}"
