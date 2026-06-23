#!/usr/bin/env bash
#
# Run the objectified-db Flyway-style CLI, forwarding the command and args from "$@".
#
#   ./run.sh migrate        # apply pending migrations (default when no command is given)
#   ./run.sh seed           # load dev seed data
#   ./run.sh clean          # drop the odb schema + history (guarded)
#   ./run.sh migrate status # any subcommand / flags are passed straight through
#
# Connection is resolved from OBJECTIFIED_DB_URL / DATABASE_URL / POSTGRES_* (see README).
set -euo pipefail

# Run from the package directory so dist/cli.js resolves regardless of caller cwd.
cd "$(dirname "$0")"

exec node dist/cli.js "${@:-migrate}"
