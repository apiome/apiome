#!/usr/bin/env bash
# Helper script to run the Objectified REST API server using uv

# Change to the script directory
cd "$(dirname "$0")"

# Checks if the virtual environment is activated
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    uv sync
fi

# Run the app using uv
uv run -m app

