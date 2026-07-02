#!/usr/bin/env bash
#
# Wrapper to run the Apiome Web Docker image via start-apiome-docker.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export IMAGE="apiome-web"
export ENV_FILE="/root/.env.web"
export PORT="3002"

exec "$SCRIPT_DIR/start-apiome-docker.sh" "$@"
