-- Provider verification reports — CTG-4.3 (#4489).
--
-- A published specification describes what was *promised*. Until something executes it against a
-- running deployment, nothing in the platform checks what is actually *served* — so a dropped
-- field, a narrowed type, or a newly-required parameter reaches production unnoticed and is
-- discovered by a consumer.
--
-- V212 already stores what a run *did*: one row per executed case, with its assertions. What it
-- cannot answer is the question a deploy gate actually asks — "how much of this contract did that
-- run check, and where did the deployment disagree?" Coverage has no denominator in the evidence
-- tables (a run records the cases it executed, never the operations it never reached), and the
-- per-operation drift picture would have to be recomputed from assertion rows on every read.
--
-- This migration adds the one table that answers it:
--
--   provider_verification_report — a conformance report: the verdict, the coverage numbers, the
--                                  per-operation drift, and the operations the run does *not*
--                                  vouch for, written once beside the evidence run it summarises.
--
-- Five rules shape the schema, each an acceptance criterion the database keeps rather than one the
-- application is trusted to remember:
--
--   1. **A report is write-once, like the evidence it summarises.** The BEFORE UPDATE trigger below
--      is the same guard V212 puts on all four evidence tables. A report that could be edited after
--      the fact would be a second, mutable truth about an immutable run — and the only reason to
--      edit one is to make a red deployment look green.
--
--   2. **A report can never summarise another tenant's run.** ``tenant_id`` sits on the row and the
--      foreign key to ``verification_run`` is composite — ``(run_id, tenant_id)`` against that
--      table's own ``(id, tenant_id)`` unique key — so a cross-tenant report is structurally
--      impossible rather than merely unlikely. Deleting the run takes its report with it: a report
--      whose evidence no longer exists cites nothing.
--
--   3. **Coverage and verdict are columns, not a JSON walk.** CTG-4.4 (scheduled verification) asks
--      "has this version drifted since the last run?" and CTG-4.5 (deploy gating) asks "what is the
--      newest report for this version, and did it pass?". Both are answered from indexed columns.
--      The full report — per-operation drift, JSON Pointers, uncovered operations — lives in
--      ``report`` JSONB, read only when somebody opens it.
--
--   4. **The denominator is honest.** ``operations_total`` counts every operation in the
--      specification, and ``operations_uncompiled`` counts the ones the suite compiler could not
--      turn into cases at all. Storing them separately is what stops a coverage number from being
--      inflated by a compiler that skipped half the document: ``exercised / total`` is the real
--      fraction, and the part nobody could check is visible beside it.
--
--   5. **A report names the target as it was.** The target columns are an identity *snapshot*, the
--      same rule V212 applies to evidence, so renaming a target or re-pointing its base URL cannot
--      rewrite what a past verification claimed to have checked. ``target_id`` is ON DELETE SET
--      NULL: losing the target definition makes a report historical, not false.
--
-- **No new RBAC resource.** A conformance report *is* verification evidence — it is written by the
-- same act, cites the same run, and is read by the same people — so it is governed by the existing
-- ``verification_evidence`` resource from V212. ``seed_builtin_roles`` is deliberately untouched
-- here: adding a resource costs four synchronised edits (the role grid, the REST ``Resource`` enum,
-- the enforcement call sites, and the UI role matrix), and a permission that would always be
-- granted alongside an existing one earns none of them.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP FUNCTION IF EXISTS apiome.purge_provider_verification_reports(INTEGER);
--   DROP TABLE IF EXISTS apiome.provider_verification_report;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- provider_verification_report — one conformance report per verification run.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provider_verification_report (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope. Carried on the row so a tenant-wide read needs no join, and repeated in the composite
    -- foreign key below so it is also enforced rather than merely stored.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The evidence this report summarises. A report is never written without one: the run holds the
    -- per-case records, this row holds the reading of them.
    run_id UUID NOT NULL,

    -- What was verified. ``version_ref`` is the reference the caller addressed
    -- (``project/petstore/1.0.0``) and is what CTG-4.5 will look a report up by; the artifact
    -- columns are the resolution of it, so a later rename does not orphan the report.
    version_ref VARCHAR(500) NOT NULL,
    artifact_kind VARCHAR(32),
    artifact_id UUID,
    artifact_slug VARCHAR(200),
    version_label VARCHAR(200),

    -- The suite that was executed. Two reports with the same digest checked the same requests.
    suite_digest VARCHAR(100) NOT NULL,

    -- Target identity snapshot (rule 5).
    target_id UUID REFERENCES verification_target(id) ON DELETE SET NULL,
    target_slug VARCHAR(200) NOT NULL,
    target_environment VARCHAR(32) NOT NULL,
    target_network_class VARCHAR(16) NOT NULL DEFAULT 'public',
    target_base_url TEXT NOT NULL,

    -- Verdict, derived from the case records rather than declared by the runner.
    outcome VARCHAR(16) NOT NULL
        CONSTRAINT provider_verification_report_outcome_check
            CHECK (outcome IN ('passed', 'failed', 'errored')),

    -- Coverage (rules 3 and 4). Every count is non-negative, and the exercised operations can never
    -- exceed the operations the specification declares — a coverage number above 100% would mean
    -- the report was measuring something other than the contract.
    operations_total INTEGER NOT NULL DEFAULT 0 CHECK (operations_total >= 0),
    operations_exercised INTEGER NOT NULL DEFAULT 0 CHECK (operations_exercised >= 0),
    operations_passed INTEGER NOT NULL DEFAULT 0 CHECK (operations_passed >= 0),
    operations_failed INTEGER NOT NULL DEFAULT 0 CHECK (operations_failed >= 0),
    operations_errored INTEGER NOT NULL DEFAULT 0 CHECK (operations_errored >= 0),
    operations_skipped INTEGER NOT NULL DEFAULT 0 CHECK (operations_skipped >= 0),
    operations_uncompiled INTEGER NOT NULL DEFAULT 0 CHECK (operations_uncompiled >= 0),
    coverage_percent NUMERIC(5,2) NOT NULL DEFAULT 0
        CHECK (coverage_percent >= 0 AND coverage_percent <= 100),
    CONSTRAINT provider_verification_report_coverage_bound_check
        CHECK (operations_exercised <= operations_total),

    -- Case counts, mirroring the evidence run's own tally so a list read needs neither join.
    cases_total INTEGER NOT NULL DEFAULT 0 CHECK (cases_total >= 0),
    cases_passed INTEGER NOT NULL DEFAULT 0 CHECK (cases_passed >= 0),
    cases_failed INTEGER NOT NULL DEFAULT 0 CHECK (cases_failed >= 0),
    cases_errored INTEGER NOT NULL DEFAULT 0 CHECK (cases_errored >= 0),
    cases_skipped INTEGER NOT NULL DEFAULT 0 CHECK (cases_skipped >= 0),

    -- How much drift was observed, so "did anything change" is answerable without opening the JSON.
    drift_count INTEGER NOT NULL DEFAULT 0 CHECK (drift_count >= 0),

    -- The mutation posture of the run. A report that exercised writes should be visibly different
    -- from one that did not, in a list, without reading it.
    mutating_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    fixture_count INTEGER NOT NULL DEFAULT 0 CHECK (fixture_count >= 0),

    -- The report itself: per-operation verdicts, drift located by JSON Pointer, and the operations
    -- the run does not vouch for. Never null — an empty report would be indistinguishable from a
    -- run nobody read.
    report JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Provenance. ``created_by`` is ON DELETE SET NULL: a departing user must not take the evidence
    -- of a deployment check with them.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label VARCHAR(320),
    actor_kind VARCHAR(16) NOT NULL DEFAULT 'user'
        CONSTRAINT provider_verification_report_actor_kind_check
            CHECK (actor_kind IN ('user', 'api_key', 'system')),

    -- Rule 2: the run and the report must belong to the same tenant.
    CONSTRAINT provider_verification_report_run_fk
        FOREIGN KEY (run_id, tenant_id)
        REFERENCES verification_run (id, tenant_id)
        ON DELETE CASCADE
);

-- One report per run. A run is executed once and read once; a second report for the same run would
-- be a second verdict on the same evidence.
CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_verification_report_run
    ON provider_verification_report (run_id);

-- "The tenant's newest reports" — the list read.
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_tenant
    ON provider_verification_report (tenant_id, created_at DESC);

-- "The newest report for this version" — what CTG-4.4 and CTG-4.5 ask.
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_version
    ON provider_verification_report (tenant_id, version_ref, created_at DESC);

-- "Everything that ran against this deployment."
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_target
    ON provider_verification_report (tenant_id, target_id, created_at DESC);

-- "What is currently drifting" — a partial index, because the failures are the small set.
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_failures
    ON provider_verification_report (tenant_id, created_at DESC)
    WHERE outcome <> 'passed';

-- ---------------------------------------------------------------------------------------------------
-- Immutability: a report is write-once (rule 1).
-- ---------------------------------------------------------------------------------------------------
-- The same guard V212 applies to every evidence table. DELETE stays available to the FK cascade and
-- to the retention sweep below, so bounded storage does not require mutable reports.
DROP TRIGGER IF EXISTS trigger_provider_verification_report_immutable ON provider_verification_report;
CREATE TRIGGER trigger_provider_verification_report_immutable
    BEFORE UPDATE ON provider_verification_report
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Retention: bounded by age, matching the evidence sweep.
-- ---------------------------------------------------------------------------------------------------
-- Reports are already removed when their run is purged (the composite FK cascades), so this exists
-- for the case where reports are kept on a shorter clock than the raw evidence.
CREATE OR REPLACE FUNCTION purge_provider_verification_reports(p_retention_days INTEGER DEFAULT 365)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM apiome.provider_verification_report
    WHERE created_at < CURRENT_TIMESTAMP - (p_retention_days || ' days')::INTERVAL;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE provider_verification_report IS
    'CTG-4.3: write-once conformance report for one verification run — verdict, coverage against '
    'every operation in the specification, per-operation drift located by JSON Pointer, and the '
    'operations the run does not vouch for. Governed by the verification_evidence RBAC resource.';

COMMENT ON COLUMN provider_verification_report.operations_total IS
    'Operations in the specification, compiled or not — the honest coverage denominator.';

COMMENT ON COLUMN provider_verification_report.operations_uncompiled IS
    'Operations the suite compiler could not turn into cases. Distinct from operations_skipped: '
    'one was not sendable, the other was not sent.';
