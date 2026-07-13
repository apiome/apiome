#!/usr/bin/env bash
#
# Start Apiome dev services. When private-suite/designer is present locally,
# also run yarn dev there in parallel; otherwise that optional project is skipped.
# Clears designer Turbopack cache first — stale SST files from interrupted runs
# panic on startup (common when turbo runs multiple Next.js apps together).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESIGNER_DIR="$ROOT/private-suite/designer"

cd "$ROOT"

if [[ ! -f "$DESIGNER_DIR/package.json" ]]; then
  exec turbo run dev
fi

rm -rf "$DESIGNER_DIR/.next/dev/cache/turbopack"

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
  cd "$DESIGNER_DIR"
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
