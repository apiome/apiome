#!/usr/bin/env bash
# Push one or more local image tags with bounded retries.
# Registry errors like "blob upload unknown to registry" are often transient
# (upload session expired, network blip, or registry race under parallel uploads).
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <tag> [tag...]" >&2
  exit 2
fi

tags=("$@")
max_attempts=3

for attempt in $(seq 1 "$max_attempts"); do
  failed=0
  for tag in "${tags[@]}"; do
    echo "Pushing ${tag} (attempt ${attempt}/${max_attempts})..."
    if ! docker push "$tag"; then
      failed=1
      break
    fi
  done

  if [ "$failed" -eq 0 ]; then
    echo "All tags pushed successfully."
    exit 0
  fi

  if [ "$attempt" -lt "$max_attempts" ]; then
    wait=$((attempt * 45))
    echo "Push failed; waiting ${wait}s before retry..."
    sleep "$wait"
  fi
done

echo "Push failed after ${max_attempts} attempts." >&2
exit 1
