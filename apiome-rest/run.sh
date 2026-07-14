#!/usr/bin/env bash
# Helper script to run the Apiome REST API server using uv

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Load KEY=VALUE pairs without `source`, so JSON/base64 values with `{`, `}`,
# `/`, spaces, etc. are not interpreted by bash (brace expansion, word split).
load_env_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    if [[ ${#val} -ge 2 ]]; then
      if [[ "${val:0:1}" == '"' && "${val: -1}" == '"' ]]; then
        val="${val:1:${#val}-2}"
      elif [[ "${val:0:1}" == "'" && "${val: -1}" == "'" ]]; then
        val="${val:1:${#val}-2}"
      fi
    fi
    printf -v "$key" '%s' "$val"
    export "$key"
  done <"$f"
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

