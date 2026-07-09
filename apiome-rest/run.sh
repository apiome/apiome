#!/usr/bin/env bash
# Helper script to run the Apiome REST API server using uv

# Change to the script directory
cd "$(dirname "$0")"

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

