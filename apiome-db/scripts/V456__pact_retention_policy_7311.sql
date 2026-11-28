-- Contracts clean-up rules, nightly run and restore window — PFX-8.14 (#7311).
--
-- PFX-1.11 (V437) made deleting a pacticipant or a version a restorable stamp, and gave apiome-rest a
-- selector-based retention run that a caller had to start by hand. The Contracts **Settings → Clean-up**
-- tab (and `apiome pact retention show|set|preview`) stores the rules instead, so the workspace says
-- once what it keeps and apiome-rest applies it every night:
--
--   pact_retention_policy — one row per tenant: the keep rules, whether the nightly clean-up runs,
--                           how many days a deleted item stays restorable, and what the last
--                           nightly run did.
--
-- Rules kept by the database:
--
--   1. **Deployed and released versions are always kept.** There is no column to turn that off;
--      apiome-rest adds the rule to every run it makes from this row.
--   2. **Bounded numbers.** A count of 1 … 1000 versions, an age of 1 … 3650 days, a restore window
--      of 1 … 365 days, at most 50 tags of the shape `pacticipant_version_tag.name` allows.
--   3. **A run that never ran says so.** `last_run_*` are all NULL until the first nightly run.
--   4. **Nothing crosses a tenant.** The row is keyed by `tenant_id` and goes with the tenant.
--
-- The **Recently deleted** list reads a tenant's deleted pacticipants, and the versions deleted on
-- their own (not with their pacticipant), newest first. Two partial indexes keep both reads to the
-- deleted rows of one tenant (apiome-db plan-check: pact.retention_deleted_*).
--
-- Online: one new table and two partial index builds over the deleted rows only.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_pacticipant_tenant_deleted;
--   DROP INDEX IF EXISTS apiome.idx_pacticipant_version_deleted_by_pacticipant;
--   DROP TABLE IF EXISTS apiome.pact_retention_policy;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_retention_policy
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_retention_policy (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    -- The newest N versions of each pacticipant's main branch.
    keep_main_branch_latest INTEGER
        CONSTRAINT pact_retention_policy_main_latest_check
            CHECK (keep_main_branch_latest IS NULL OR keep_main_branch_latest BETWEEN 1 AND 1000),
    -- The newest N versions of every other branch, while recorded in the last D days (no limit when
    -- the days are NULL).
    keep_other_branch_latest INTEGER
        CONSTRAINT pact_retention_policy_other_latest_check
            CHECK (keep_other_branch_latest IS NULL OR keep_other_branch_latest BETWEEN 1 AND 1000),
    keep_other_branch_days INTEGER
        CONSTRAINT pact_retention_policy_other_days_check
            CHECK (keep_other_branch_days IS NULL
                   OR (keep_other_branch_latest IS NOT NULL AND keep_other_branch_days BETWEEN 1 AND 3650)),
    -- Every version carrying one of these tags.
    keep_tags TEXT[] NOT NULL DEFAULT '{}'
        CONSTRAINT pact_retention_policy_tags_check
            CHECK (cardinality(keep_tags) <= 50 AND array_position(keep_tags, NULL) IS NULL),

    nightly_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    restore_window_days INTEGER NOT NULL DEFAULT 30
        CONSTRAINT pact_retention_policy_restore_window_check
            CHECK (restore_window_days BETWEEN 1 AND 365),

    -- What the last nightly run did (rule 3).
    last_run_at TIMESTAMP WITH TIME ZONE,
    last_run_deleted INTEGER
        CONSTRAINT pact_retention_policy_last_deleted_check
            CHECK (last_run_deleted IS NULL OR last_run_deleted >= 0),
    last_run_remaining INTEGER
        CONSTRAINT pact_retention_policy_last_remaining_check
            CHECK (last_run_remaining IS NULL OR last_run_remaining >= 0),
    last_run_error TEXT
        CONSTRAINT pact_retention_policy_last_error_check
            CHECK (last_run_error IS NULL OR length(last_run_error) <= 500),

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by_label TEXT,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pact_retention_policy_updated_by
    ON pact_retention_policy (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE pact_retention_policy IS
    'A workspace''s Contracts clean-up rules, nightly switch and restore window (PFX-8.14, #7311)';
COMMENT ON COLUMN pact_retention_policy.keep_main_branch_latest IS
    'Keep the newest N versions of each pacticipant''s main branch; NULL: no such rule';
COMMENT ON COLUMN pact_retention_policy.keep_other_branch_latest IS
    'Keep the newest N versions of every other branch; NULL: no such rule';
COMMENT ON COLUMN pact_retention_policy.keep_other_branch_days IS
    'Only while those versions were recorded in the last D days; NULL: however old';
COMMENT ON COLUMN pact_retention_policy.keep_tags IS
    'Keep every version carrying one of these tags';
COMMENT ON COLUMN pact_retention_policy.nightly_enabled IS
    'Whether apiome-rest applies the rules every night; off: nothing is removed by clean-up';
COMMENT ON COLUMN pact_retention_policy.restore_window_days IS
    'Days a deleted pacticipant or version can be restored before it is purged';
COMMENT ON COLUMN pact_retention_policy.last_run_at IS
    'When the last nightly run finished; NULL before the first';

-- ---------------------------------------------------------------------------------------------------
-- 2. Recently deleted
-- ---------------------------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_pacticipant_tenant_deleted
    ON pacticipant (tenant_id, deleted_at DESC)
    WHERE deleted_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pacticipant_version_deleted_by_pacticipant
    ON pacticipant_version (pacticipant_id, deleted_at DESC)
    WHERE deleted_at IS NOT NULL AND delete_cause <> 'pacticipant';
