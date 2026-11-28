-- Migration runs: a broker migration as a job the product can watch — PFX-8.16 (#7313).
--
-- `apiome pact migrate` (PFX-6.7) reads a Pact Broker or PactFlow workspace on the caller's machine
-- and keeps its progress in a state file. The Migration wizard runs the same engine on the server,
-- so its progress has to live here:
--
--   pact_migration_run — one row per run a workspace started: the source it reads, what was chosen
--     (kinds, history depth, conflict policy), where it is (status, phase, counts per kind), what it
--     found (findings, failures, the newest log lines) and who started it. The **Past migrations**
--     drawer lists these rows.
--   pact_migration_run_done — the source keys a run imported, so a resumed run (or a later run from
--     the same source) skips them: the state file's `done` list.
--
-- Rules kept by the database:
--
--   1. **The source's credentials are never stored.** There is no column for a token or a password;
--      `auth_kind` only says which kind was used, so a resume knows what to ask for again.
--   2. **One run at a time per workspace.** A partial unique index allows a single `running` row per
--      tenant, whichever apiome-rest worker started it.
--   3. **Nothing crosses a tenant.** Every run carries its tenant and goes with it; a run's done keys
--      go with the run.
--
-- Online: two new tables and their indexes; nothing existing is touched.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.pact_migration_run_done;
--   DROP TABLE IF EXISTS apiome.pact_migration_run;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_migration_run
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_migration_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    source TEXT NOT NULL,
    auth_kind VARCHAR(8) NOT NULL DEFAULT 'token',
    mode VARCHAR(8) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'running',
    phase VARCHAR(16) NOT NULL DEFAULT 'reading',

    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    failures JSONB NOT NULL DEFAULT '[]'::jsonb,
    failures_dropped INTEGER NOT NULL DEFAULT 0,
    log JSONB NOT NULL DEFAULT '[]'::jsonb,
    log_seq INTEGER NOT NULL DEFAULT 0,
    error TEXT,

    stop_requested BOOLEAN NOT NULL DEFAULT FALSE,

    started_by UUID REFERENCES users(id) ON DELETE SET NULL,
    started_by_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT pact_migration_run_source_length_check CHECK (char_length(source) BETWEEN 1 AND 2048),
    CONSTRAINT pact_migration_run_auth_kind_check CHECK (auth_kind IN ('token', 'basic', 'none')),
    CONSTRAINT pact_migration_run_mode_check CHECK (mode IN ('dry-run', 'copy')),
    CONSTRAINT pact_migration_run_status_check CHECK (status IN ('running', 'completed', 'stopped', 'failed')),
    CONSTRAINT pact_migration_run_finished_check CHECK ((status = 'running') = (finished_at IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pact_migration_run_one_running
    ON pact_migration_run (tenant_id) WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_pact_migration_run_tenant_created
    ON pact_migration_run (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pact_migration_run_started_by
    ON pact_migration_run (started_by) WHERE started_by IS NOT NULL;

COMMENT ON TABLE pact_migration_run IS
    'A broker migration run by the Migration wizard (PFX-8.16, #7313): its choices, progress and report';
COMMENT ON COLUMN pact_migration_run.source IS 'The source broker''s base URL (never with credentials)';
COMMENT ON COLUMN pact_migration_run.auth_kind IS
    'How the source was signed in to (token, basic, none); the credential itself is never stored';
COMMENT ON COLUMN pact_migration_run.mode IS 'dry-run: read and check, write nothing; copy: import';
COMMENT ON COLUMN pact_migration_run.status IS
    'running; completed (read counts for failures); stopped (asked to, or its worker went away); failed (could not go on)';
COMMENT ON COLUMN pact_migration_run.phase IS 'reading, the record kind being copied, or done';
COMMENT ON COLUMN pact_migration_run.options IS 'What was chosen: kinds, history depth, conflict policy, limits';
COMMENT ON COLUMN pact_migration_run.counts IS 'Per record kind: total, copied, unchanged, skipped, failed (or exists / would_create)';
COMMENT ON COLUMN pact_migration_run.facts IS 'What the run learned for the wizard: product, hosts, versions clean-up would skip';
COMMENT ON COLUMN pact_migration_run.findings IS 'Everything the source holds that cannot be carried over as it is';
COMMENT ON COLUMN pact_migration_run.failures IS 'Refused records with their reason (the newest are kept; failures_dropped counts the rest)';
COMMENT ON COLUMN pact_migration_run.log IS 'The newest log lines, each with its sequence number';
COMMENT ON COLUMN pact_migration_run.log_seq IS 'How many log lines the run has written in all';
COMMENT ON COLUMN pact_migration_run.stop_requested IS 'Someone asked the run to stop; it does before its next batch';
COMMENT ON COLUMN pact_migration_run.heartbeat_at IS
    'Last time its worker wrote progress; a running row with an old heartbeat lost its worker and can be resumed';

-- ---------------------------------------------------------------------------------------------------
-- 2. pact_migration_run_done
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_migration_run_done (
    run_id UUID NOT NULL REFERENCES pact_migration_run(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    PRIMARY KEY (run_id, source_key),
    CONSTRAINT pact_migration_run_done_key_length_check CHECK (char_length(source_key) BETWEEN 1 AND 1024)
);

COMMENT ON TABLE pact_migration_run_done IS
    'Source keys a migration run imported, so a resumed or repeated run skips them (PFX-8.16, #7313)';
