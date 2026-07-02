#!/usr/bin/env bash
#
# scheduled-backup.sh — cron/systemd-timer entry point for apiome-db backups.
#
# Runs one backup and then enforces the retention policy, logging both to stdout/stderr so the
# scheduler captures a record. Intended to be invoked on a schedule, e.g. hourly incremental-style
# logical backups plus a daily full pg_dump (see docs/runbooks/BACKUP_AND_DR.md).
#
# Usage:
#   scheduled-backup.sh full                 # whole-cluster pg_dump
#   scheduled-backup.sh tenant <slug>        # tenant-scoped logical backup
#   scheduled-backup.sh project <slug> <proj># project-scoped logical backup
#
# Configuration is read from the environment (see apiome-db/.env.example):
#   APIOME_DB_URL / POSTGRES_*          database connection
#   APIOME_BACKUP_DIR                    primary backup directory (required)
#   APIOME_BACKUP_OFFSITE_DIR            off-site mirror directory (recommended)
#   APIOME_BACKUP_KEY                    32-byte AES-256 key (hex/base64) — REQUIRED here
#   APIOME_BACKUP_KEEP_DAYS             retention age guard (default 30)
#   APIOME_BACKUP_KEEP_LAST             retention count guard (default 7)
#
# Encryption is mandatory in this wrapper: a scheduled job that writes plaintext off-site is a
# data-leak waiting to happen, so we pass --require-encryption and refuse to run without a key.
set -euo pipefail

SCOPE="${1:-full}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # apiome-db/ package root
CLI=(node "${HERE}/dist/cli.js")

if [[ -z "${APIOME_BACKUP_KEY:-}" ]]; then
  echo "scheduled-backup: APIOME_BACKUP_KEY is not set; refusing to write an unencrypted backup." >&2
  echo "  Generate one with:  openssl rand -hex 32" >&2
  exit 2
fi

KEEP_DAYS="${APIOME_BACKUP_KEEP_DAYS:-30}"
KEEP_LAST="${APIOME_BACKUP_KEEP_LAST:-7}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

case "${SCOPE}" in
  full)
    log "Creating full (pg_dump) backup…"
    "${CLI[@]}" backup create --full --require-encryption
    ;;
  tenant)
    TENANT="${2:?usage: scheduled-backup.sh tenant <slug>}"
    log "Creating tenant backup for '${TENANT}'…"
    "${CLI[@]}" backup create --tenant "${TENANT}" --require-encryption
    ;;
  project)
    TENANT="${2:?usage: scheduled-backup.sh project <tenant> <project>}"
    PROJECT="${3:?usage: scheduled-backup.sh project <tenant> <project>}"
    log "Creating project backup for '${TENANT}/${PROJECT}'…"
    "${CLI[@]}" backup create --tenant "${TENANT}" --project "${PROJECT}" --require-encryption
    ;;
  *)
    echo "scheduled-backup: unknown scope '${SCOPE}' (use: full | tenant <slug> | project <tenant> <project>)" >&2
    exit 2
    ;;
esac

log "Applying retention policy (keep-days=${KEEP_DAYS}, keep-last=${KEEP_LAST})…"
"${CLI[@]}" backup prune --keep-days "${KEEP_DAYS}" --keep-last "${KEEP_LAST}"

log "Done."
