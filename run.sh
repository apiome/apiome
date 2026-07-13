#!/usr/bin/env bash
#
# Start the Apiome dev stack (main monorepo + optional private-suite designer).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PRIVATE_SUITE_DIR="$ROOT/private-suite"

(cd apiome-db && ./run.sh migrate)

yarn install

if [[ -f "$PRIVATE_SUITE_DIR/package.json" ]]; then
  echo "run.sh: installing private-suite dependencies..." >&2
  (cd "$PRIVATE_SUITE_DIR" && yarn install) >&2
elif [[ ! -d "$PRIVATE_SUITE_DIR" ]]; then
  echo "" >&2
  echo "run.sh: ./private-suite is missing — the Suite Designer will not start." >&2
  echo "       Clone it with: git clone git@github.com:apiome/private-suite.git private-suite" >&2
  echo "" >&2
fi

exec yarn dev
