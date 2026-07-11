#!/usr/bin/env bash
# Bootstrap Docker Buildx on self-hosted runners without reinstalling the
# cli-plugins binary. docker/setup-buildx-action copies a fresh buildx binary
# on every job; when several workflows run in parallel the target file is
# already mapped (ETXTBSY: text file is busy).
#
# The docker driver only supports one builder instance, so reuse the active
# builder instead of creating a per-job one.
set -euo pipefail

docker buildx version
docker buildx inspect --bootstrap
