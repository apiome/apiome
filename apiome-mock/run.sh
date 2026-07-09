#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Without APIOME_MOCK_DATABASE_URL (env or local .env) the server refuses to start;
# reuse the shared dev database from apiome-rest/.env so checkouts that predate
# setup.sh writing apiome-mock/.env still come up under `yarn dev`.
if [[ -z "${APIOME_MOCK_DATABASE_URL:-}" && ! -f .env && -f ../apiome-rest/.env ]]; then
  db_url="$(grep -E '^DATABASE_URL=' ../apiome-rest/.env | tail -n1 | cut -d= -f2-)"
  db_url="${db_url%\"}"
  db_url="${db_url#\"}"
  if [[ -n "$db_url" ]]; then
    export APIOME_MOCK_DATABASE_URL="$db_url"
  fi
fi

exec uv run apiome-mock serve "$@"
