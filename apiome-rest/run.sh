#!/usr/bin/env bash
# Helper script to run the Apiome REST API server using uv

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

# Checks if the virtual environment is activated
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    uv sync
fi

# Ensure buf is available for local gRPC/Protobuf catalog import (.tools/bin is also resolved
# by app.toolchain_runner without PATH, but exporting PATH helps subprocess diagnostics).
./scripts/install_dev_toolchain.sh
export PATH="$(pwd)/.tools/bin:${PATH}"

# Run the app using uv
uv run -m app

