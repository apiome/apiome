#!/usr/bin/env bash
#
# Start the Apiome dev stack via turbo. When private-suite/designer is present,
# clear its Turbopack cache first — stale SST files from interrupted runs panic
# on startup (common when turbo runs multiple Next.js apps together).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESIGNER_DIR="$ROOT/private-suite/designer"

if [[ -f "$DESIGNER_DIR/package.json" ]]; then
  rm -rf "$DESIGNER_DIR/.next/dev/cache/turbopack"
fi

cd "$ROOT"
exec turbo run dev
