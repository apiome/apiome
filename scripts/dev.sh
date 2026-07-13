#!/usr/bin/env bash
#
# Start Apiome dev services. When private-suite/ is present in the workspace,
# also runs yarn dev there; otherwise that optional project is skipped.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_SUITE_DIR="$ROOT/private-suite"

cd "$ROOT"

has_private_suite() {
  [[ -d "$PRIVATE_SUITE_DIR" && -f "$PRIVATE_SUITE_DIR/package.json" ]]
}

if ! has_private_suite; then
  exec turbo run dev
fi

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

turbo run dev &
pids+=($!)

(
  cd "$PRIVATE_SUITE_DIR"
  yarn dev
) &
pids+=($!)

status=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    status=1
  fi
done

exit "$status"
