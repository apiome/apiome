#!/usr/bin/env bash
# Run the public browse Next.js app with package-local .env loaded into the shell.
#
# Usage:
#   ./scripts/run.sh dev [extra next dev args...]
#   ./scripts/run.sh start [extra next start args...]
#
# Environment:
#   APIOME_LOAD_DOTENV=0   Skip loading .env files (tests)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

load_env_file() {
  local f="$1"
  if [[ -f "$f" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
  fi
}

if [[ "${APIOME_LOAD_DOTENV:-1}" != "0" ]]; then
  load_env_file "$ROOT/.env"
  load_env_file "$ROOT/.env.local"
fi

MODE="${1:-dev}"
shift || true

case "$MODE" in
  dev)
    exec yarn exec next dev -p "${PORT:-3001}" "$@"
    ;;
  start)
    exec yarn exec next start -p "${PORT:-3001}" "$@"
    ;;
  *)
    echo "Usage: $0 [dev|start] [extra next args...]" >&2
    exit 1
    ;;
esac
