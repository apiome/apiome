# Backup & Disaster-Recovery Runbook

**Status:** RC1 baseline (ticket RC1-1.3 / #3613) · **Owner:** Platform / on-call · **Scope:** `objectified-db`

Objectified is the **source of truth** for an organization's schemas, contracts, and data. This
runbook is the operational backup, restore, and point-in-time-recovery (PITR) procedure that makes
that claim credible: scheduled encrypted backups, a **tested** restore drill, and documented
RPO/RTO targets.

All tooling ships in the `objectified-db` CLI (`backup` command group) and the
[`scheduled-backup.sh`](../../objectified-db/scripts/backup/scheduled-backup.sh) wrapper. Nothing
here requires the REST API — backups are privileged, direct-to-database operations.

---

## 1. Recovery objectives (RPO / RTO)

| Objective | Definition | RC1 target | How it is met |
|-----------|------------|-----------|---------------|
| **RPO** (Recovery Point Objective) | Maximum acceptable data loss, measured as the age of the newest recoverable change | **≤ 1 hour** | Hourly logical backups of the event log (`odb.data_record`); the manifest's `recovery-point` (RPO marker) records the newest captured event |
| **RTO** (Recovery Time Objective) | Maximum acceptable time to restore service | **≤ 30 minutes** | Logical restore into a sandbox is seconds-to-minutes for typical tenants; full-cluster `pg_dump`/`pg_restore` dominates RTO for whole-platform loss |

Each backup's manifest stores its **RPO marker** (the timestamp of the newest event it captured).
The gap between consecutive backups bounds the achievable RPO; the monthly drill (§5) measures the
**actual** RPO/RTO and grades them `pass` / `warn` / `fail` against these targets.

---

## 2. What is backed up

Two complementary backup kinds, both encrypted at rest (AES-256-GCM) and mirrored off-site:

1. **Logical, scoped backup** (`backup create --tenant <slug> [--project <slug>]`)
   - Exports the event/snapshot model for one tenant or project: `class_schema`, `data_record`
     (the event log), and `data_snapshot` (materialized current state).
   - This is the substrate for **PITR** — events can be replayed to any second within the window.
   - Format: a JSON dataset, optionally `.enc` encrypted, plus a `*.manifest.json` sidecar.

2. **Full cluster backup** (`backup create --full`)
   - A whole-database `pg_dump` (custom format, `-Fc`), the DR safety net for total loss.
   - Restored with standard `pg_restore` (see §4.3).

Every backup writes an **artifact** + a plaintext **manifest** (scope, size, SHA-256, encryption
flag, RPO marker, row counts). The manifest carries no secrets, so operators can audit the backup
catalog without the encryption key.

---

## 3. Scheduling & retention

### 3.1 Keys & storage (one-time setup)

```bash
# Generate the 32-byte data key ONCE and store it in your secrets manager, NOT next to backups.
openssl rand -hex 32 > /secure/objectified-backup.key
export OBJECTIFIED_BACKUP_KEY="$(cat /secure/objectified-backup.key)"
export OBJECTIFIED_BACKUP_DIR=/var/backups/objectified           # primary
export OBJECTIFIED_BACKUP_OFFSITE_DIR=/mnt/offsite/objectified    # off-site mirror
```

> The encryption key is **the** recovery dependency. If it is lost, encrypted backups are
> unrecoverable. Store it in a managed secret store (and aligned with the BYOK/key-management
> workstream), separate from the backup artifacts.

### 3.2 Cron schedule (recommended baseline)

```cron
# Hourly tenant logical backup (low RPO for the data layer) + retention prune.
0 * * * *  OBJECTIFIED_BACKUP_KEEP_DAYS=7  /opt/objectified/objectified-db/scripts/backup/scheduled-backup.sh tenant acme-corp >> /var/log/objectified-backup.log 2>&1

# Daily full pg_dump at 02:00 (whole-cluster DR), retained 30 days.
0 2 * * *  OBJECTIFIED_BACKUP_KEEP_DAYS=30 /opt/objectified/objectified-db/scripts/backup/scheduled-backup.sh full        >> /var/log/objectified-backup.log 2>&1
```

`scheduled-backup.sh` **requires** `OBJECTIFIED_BACKUP_KEY` and always passes
`--require-encryption`, so a scheduled job can never silently write plaintext off-site.

### 3.3 Retention policy

Retention has two independent guards that compose conservatively — a backup is pruned only when it
is **both** older than `keep-days` **and** not among the `keep-last` most recent copies:

| Guard | Env / flag | Default |
|-------|------------|---------|
| Age | `OBJECTIFIED_BACKUP_KEEP_DAYS` / `--keep-days` | 30 |
| Count | `OBJECTIFIED_BACKUP_KEEP_LAST` / `--keep-last` | 7 |

This guarantees a quiet system never prunes its only good copies just because they aged out.

```bash
objectified-db backup prune --keep-days 30 --keep-last 7
```

---

## 4. Restore procedures

> **Golden rule:** always restore to a **sandbox** first and inspect before promoting over live
> data. The CLI only ever restores logical backups into an isolated sandbox schema — it never
> writes to `odb`.

### 4.1 Restore the latest state to a sandbox

1. **List** available backups and choose one:
   ```bash
   objectified-db backup list
   ```
2. **Restore** it into a sandbox schema:
   ```bash
   objectified-db backup restore <backup-id> --sandbox recovery_sandbox
   ```
3. **Inspect** the reconstructed records:
   ```sql
   SELECT record_id, data, last_sequence FROM recovery_sandbox.pitr_records;
   ```
4. **Promote** (manual, deliberate): once validated, copy the rows back into `odb` under change
   control. Promotion over live data is intentionally a manual, audited step in RC1.

### 4.2 Point-in-time recovery (PITR)

Replay the event log to a specific instant — e.g. to recover state from just before an accidental
mass delete at `2026-06-23T09:30:00Z`:

```bash
objectified-db backup restore <backup-id> \
  --sandbox pitr_0929 \
  --as-of 2026-06-23T09:29:59Z
```

The fold applies every event up to and including `--as-of`, in per-record sequence order:
`created` sets the document, `updated` merges a delta, `deleted` removes the record from the live
set, and `restored` brings it back. Records deleted at the chosen point are excluded and reported
as `deleted at point`.

### 4.3 Full-cluster restore (total loss)

The `--full` backups are standard `pg_dump` archives. To restore the whole database:

```bash
# 1. Decrypt the artifact (if encrypted). The artifact is AES-256-GCM with an objectified header;
#    use a fresh DB sandbox to validate before touching production.
# 2. Recreate an empty database and restore:
createdb objectified_restore
pg_restore --no-owner --no-privileges --dbname=objectified_restore <decrypted-archive>.dump
# 3. Run migrations to confirm the schema is at the expected version:
objectified-db migrate status --database-url postgresql://…/objectified_restore
```

> Decryption of `--full` artifacts: the CLI encrypts/decrypts logical datasets directly; for the
> `.dump.enc` archive, decrypt with the same key used to create it before handing the plaintext to
> `pg_restore`. (Automated `pg_restore` integration is tracked for Phase 5.)

---

## 5. Disaster-recovery drill (monthly)

A drill proves the backups are actually restorable and measures real RPO/RTO. It restores a backup
into a **throwaway** sandbox, verifies row counts, records the timings, and tears the sandbox down —
the backup artifact and live `odb` data are never modified.

```bash
objectified-db backup drill --rto-target-minutes 30 --rpo-target-minutes 60
```

Output grades the drill:

- **pass** — restored, verified, and within both targets.
- **warn** — restored and verified, but RPO or RTO exceeded its target (investigate cadence/sizing).
- **fail** — the restored state did not verify (exit code 1; page the owner).

Record each drill's result, measured RPO, and measured RTO in the DR log; these are exportable as
recovery evidence for audits (SOC 2 CC9.1 / availability).

### Example drill (reference)

A reference drill run against a sample tenant restored 2 records to a sandbox, verified the row
count, and measured RTO < 1s for the logical layer — confirming the restore path end-to-end.

---

## 6. Quick reference

| Action | Command |
|--------|---------|
| Create tenant backup (encrypted, off-site) | `objectified-db backup create --tenant <slug> --require-encryption` |
| Create full cluster backup | `objectified-db backup create --full --require-encryption` |
| List backups | `objectified-db backup list` |
| Restore latest to sandbox | `objectified-db backup restore <id> --sandbox <schema>` |
| PITR restore | `objectified-db backup restore <id> --sandbox <schema> --as-of <iso8601>` |
| Run a DR drill | `objectified-db backup drill --rto-target-minutes 30 --rpo-target-minutes 60` |
| Enforce retention | `objectified-db backup prune --keep-days 30 --keep-last 7` |
| Scheduled job | `scripts/backup/scheduled-backup.sh full \| tenant <slug> \| project <tenant> <proj>` |

See [`objectified-db/README.md`](../../objectified-db/README.md#backups--disaster-recovery) for the
full command reference and configuration.
