#!/usr/bin/env bash
#
# Start Apiome dev services. When private-suite is present locally, also start the
# suite designer in parallel; otherwise that optional project is skipped.
# Clears designer Turbopack cache first — stale SST files from interrupted runs
# panic on startup (common when turbo runs multiple Next.js apps together).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_SUITE_DIR="$ROOT/private-suite"
TURBO="$ROOT/node_modules/.bin/turbo"

read_env_value() {
  local file="$1"
  local key="$2"
  local default="${3:-}"
  local line value

  [[ -f "$file" ]] || {
    printf '%s' "$default"
    return 0
  }

  line="$(grep -E "^${key}=" "$file" | tail -n1 || true)"
  if [[ -z "$line" ]]; then
    printf '%s' "$default"
    return 0
  fi

  value="${line#*=}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value:-$default}"
}

resolve_designer_dir() {
  local candidate
  for candidate in \
    "$PRIVATE_SUITE_DIR/designer" \
    "$PRIVATE_SUITE_DIR/suite/designer"; do
    if [[ -f "$candidate/package.json" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

log() {
  printf '%s\n' "$*" >&2
}

cd "$ROOT"

if [[ ! -x "$TURBO" ]]; then
  log "dev.sh: turbo not found — run 'yarn install' at the repo root first."
  exit 1
fi

DESIGNER_DIR=""
if DESIGNER_DIR="$(resolve_designer_dir)"; then
  :
else
  log ""
  log "==> Starting Apiome dev stack (suite designer not found)"
  log "    Control Panel : http://localhost:3000"
  log "    Browse        : http://localhost:3001"
  log "    REST API      : http://localhost:8000"
  log ""
  log "    To enable the Suite Designer, clone private-suite into ./private-suite:"
  log "      git clone git@github.com:apiome/private-suite.git private-suite"
  log ""
  exec "$TURBO" run dev
fi

if [[ -f "$PRIVATE_SUITE_DIR/package.json" && ! -d "$PRIVATE_SUITE_DIR/node_modules" ]]; then
  log "dev.sh: installing private-suite dependencies..."
  (cd "$PRIVATE_SUITE_DIR" && yarn install) >&2
fi

rm -rf "$DESIGNER_DIR/.next/dev/cache/turbopack"

DESIGNER_PORT="$(read_env_value "$DESIGNER_DIR/.env" PORT 3004)"

log ""
log "==> Starting Apiome dev stack"
log "    Control Panel : http://localhost:3000"
log "    Browse        : http://localhost:3001"
log "    REST API      : http://localhost:8000"
log "    Suite Designer: http://localhost:${DESIGNER_PORT}"
log ""

pids=()

cleanup() {
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT INT TERM

"$TURBO" run dev &
pids+=($!)

(
  cd "$PRIVATE_SUITE_DIR"
  log "[suite/designer] starting on http://localhost:${DESIGNER_PORT} ..."
  yarn dev 2>&1 | while IFS= read -r line; do
    printf '[suite/designer] %s\n' "$line"
  done
) &
pids+=($!)

status=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    status=1
  fi
done

exit "$status"
