-- Export history & audit ledger — MFX-46.1 (#4379).
--
-- "Who exported what, where, with how much loss?" is a tenant-wide question, and the live job store
-- cannot answer it: `apiome.async_job` rows are reaped after a short retention window (7 days for a
-- completed export by default), they do not record who started the job, and the full fidelity and
-- verify reports go with them (`async_job_history` keeps only a slim summary).
--
-- `export_run_ledger` keeps one row per export job, written when the job reaches a terminal state:
-- the source and revision, the target, the actor, the outcome, the headline numbers the history
-- screen filters and sorts on (preserved %, validation / lint verdicts, delivery decision), and the
-- stored reports its read-only detail renders. Delivery outcomes are not copied: the git, webhook and
-- object-storage delivery runs already record them per `job_id` (V354–V356) and are joined at read
-- time. Rows are pruned by the async-job retention sweep after `async_job_history_retention_days`
-- (90 by default), the same window as the slim job history.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_run_ledger (
    job_id VARCHAR(64) PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- The source: the artifact (project / catalog item) id, its name when known, and the revision.
    artifact_id VARCHAR(255) NOT NULL,
    artifact_name VARCHAR(512),
    version_record_id VARCHAR(64),
    version_label VARCHAR(255),
    -- The requested target(s), as submitted (comma-joined for a multi-target job).
    target VARCHAR(512) NOT NULL,
    -- Who started the job; the label outlives the account.
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label VARCHAR(320) NOT NULL DEFAULT 'Unknown',
    state VARCHAR(16) NOT NULL
        CONSTRAINT export_run_ledger_state_check
            CHECK (state IN ('completed', 'failed', 'canceled')),
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    -- Headline numbers (null when the job never got that far).
    preserved_percent INTEGER
        CONSTRAINT export_run_ledger_preserved_check
            CHECK (preserved_percent IS NULL OR (preserved_percent BETWEEN 0 AND 100)),
    fidelity_tier VARCHAR(32),
    validation_verdict VARCHAR(32),
    lint_verdict VARCHAR(16)
        CONSTRAINT export_run_ledger_lint_check
            CHECK (lint_verdict IS NULL OR lint_verdict IN ('pass', 'warn', 'block')),
    delivery_decision VARCHAR(32),
    error_code VARCHAR(64),
    error_message TEXT,
    -- What the job was submitted with, for "Re-run in Studio".
    options JSONB,
    -- The stored reports the detail renders read-only.
    fidelity JSONB,
    validation JSONB,
    delivery_gate JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE export_run_ledger IS
    'One row per finished export job (MFX-46.1, #4379): who exported what, where, with how much loss. '
    'Written at the terminal state; pruned after async_job_history_retention_days.';
COMMENT ON COLUMN export_run_ledger.actor_label IS
    'Display label of the user (or API key) that started the job, kept after the account is gone.';
COMMENT ON COLUMN export_run_ledger.lint_verdict IS
    'Worst lint finding of the delivery gate: pass (none), warn, or block.';
COMMENT ON COLUMN export_run_ledger.options IS
    'The per-target options the job was submitted with (a "Re-run in Studio" pre-fills them).';

-- The history screen lists newest first, scoped to a tenant, filtered by source / target / actor.
CREATE INDEX IF NOT EXISTS export_run_ledger_tenant_finished_idx
    ON export_run_ledger (tenant_id, finished_at DESC, job_id DESC);
CREATE INDEX IF NOT EXISTS export_run_ledger_tenant_artifact_idx
    ON export_run_ledger (tenant_id, artifact_id);
CREATE INDEX IF NOT EXISTS export_run_ledger_tenant_actor_idx
    ON export_run_ledger (tenant_id, actor_id);
-- The retention sweep prunes by age.
CREATE INDEX IF NOT EXISTS export_run_ledger_finished_idx
    ON export_run_ledger (finished_at);

-- Rollback notes
-- The ledger is append-only history read by the export history screen; nothing else references it.
--   DROP TABLE IF EXISTS export_run_ledger;
-- Dropping it loses the export history; the live jobs and the delivery runs are unaffected.
