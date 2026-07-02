#!/usr/bin/env bash
# Run the apiome CLI from this package with a local venv and optional .env.
#
# Usage:
#   ./run.sh [global flags] <command> ...   Run one command (same as apiome)
#   ./run.sh                                 Interactive prompt (TTY) or read
#                                            one command per line from stdin
#
# Environment:
#   APIOME_LOAD_DOTENV=0     Skip loading .env (tests)
#   APIOME_CLI_COMMAND       Override path to the apiome executable

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
fi

if [[ ! -x "$ROOT/.venv/bin/apiome" ]]; then
  uv sync
fi

CLI="${APIOME_CLI_COMMAND:-$ROOT/.venv/bin/apiome}"

if [[ $# -gt 0 ]]; then
  exec "$CLI" "$@"
fi

exec uv run python -m apiome_cli.run_interactive
