#!/usr/bin/env bash
#
# End-to-end golden-path smoke test (#3608) against a clean `docker compose up`.
#
# Brings up the full spine (postgres + migrate + seed + rest + mcp), runs the golden-path
# harness (scripts/golden_path/smoke.py), and tears the stack down. Exits non-zero if any
# step of the golden path fails, so it works both by hand and as a CI gate.
#
# Usage (from anywhere):
#   scripts/golden_path/run.sh            # up --build, seed, run, then `down -v`
#   scripts/golden_path/run.sh --keep     # leave the stack running afterwards
#   scripts/golden_path/run.sh --no-build # skip the image build (reuse existing images)
#
# Override endpoints/credentials via the OBJECTIFIED_* env vars documented in smoke.py.
set -euo pipefail

KEEP=0
BUILD_FLAG="--build"
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    --no-build) BUILD_FLAG="" ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Resolve a command to run the objectified CLI. Prefer the package's uv environment so the
# export/download step exercises the real CLI; fall back to an `objectified` on PATH.
if command -v uv >/dev/null 2>&1 && [ -d "$REPO_ROOT/objectified-cli" ]; then
  CLI_RUN=(uv run --project "$REPO_ROOT/objectified-cli" objectified)
  PY_RUN=(uv run --project "$REPO_ROOT/objectified-cli" python)
else
  CLI_RUN=(objectified)
  PY_RUN=(python3)
fi

cleanup() {
  if [ "$KEEP" -eq 0 ]; then
    echo "==> Tearing down the stack (docker compose down -v)"
    docker compose down -v >/dev/null 2>&1 || true
  else
    echo "==> Leaving the stack running (--keep). Tear down with: docker compose down -v"
  fi
}
trap cleanup EXIT

echo "==> Bringing up the spine (docker compose up ${BUILD_FLAG} --wait)"
# shellcheck disable=SC2086
docker compose up ${BUILD_FLAG} --wait

echo "==> Loading dev seed data (idempotent)"
docker compose run --rm seed

echo "==> Running the golden-path smoke test"
export OBJECTIFIED_REST_URL="${OBJECTIFIED_REST_URL:-http://localhost:8000}"
export OBJECTIFIED_MCP_URL="${OBJECTIFIED_MCP_URL:-http://localhost:8765/mcp}"
export OBJECTIFIED_CLI_CMD="${OBJECTIFIED_CLI_CMD:-${CLI_RUN[*]}}"
"${PY_RUN[@]}" "$SCRIPT_DIR/smoke.py"
