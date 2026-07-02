#!/usr/bin/env bash
#
# Wrapper to run the Apiome Browse Docker image via start-apiome-docker.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export IMAGE="apiome-browse"
export ENV_FILE="/root/.env.browse"
export PORT="3003"

exec "$SCRIPT_DIR/start-apiome-docker.sh" "$@"
