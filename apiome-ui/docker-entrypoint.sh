#!/bin/sh
set -e

# Standalone output lives in a package subdirectory when outputFileTracingRoot
# points at the monorepo root (apiome-ui/) or its parent in Docker (app/).
SERVER_JS="$(find /app -maxdepth 3 -name 'server.js' ! -path '*/node_modules/*' | head -1)"

if [ -z "$SERVER_JS" ]; then
  echo "Error: Cannot find server.js in standalone output under /app" >&2
  exit 1
fi

cd "$(dirname "$SERVER_JS")"
exec node server.js
