-- Scheduled provider verification & drift alerts — CTG-4.4 (#4501).
--
-- CTG-4.3 (V252) made a deployment checkable on demand. On demand only helps if somebody
-- remembers: drift that lands on a Friday deploy sits unnoticed until the next incident. This
-- migration adds the two tables that make the check *recurring* and its failures *loud*:
--
--   verification_schedule      — a tenant's standing instruction: verify this version against this
--                                deployment every N seconds, and tell us when it drifts.
--   verification_schedule_run  — the write-once history of what each tick found, so "when was this
--                                last verified, and has it been getting worse?" is a query rather
--                                than an archaeology exercise (CTG-4.5 reads it for freshness).
--
-- Six rules shape the schema, each an acceptance criterion the database keeps rather than one the
-- application is trusted to remember:
--
--   1. **A schedule cannot outlive the deployment it checks.** ``target_id`` is a hard reference
--      with ON DELETE CASCADE: deleting a verification target removes the schedules that point at
--      it, because a schedule aimed at nothing would tick forever and fail forever.
--
--   2. **A schedule is soft-deleted; its history is not.** Retiring a schedule sets ``deleted_at``,
--      which drops it out of due-selection and the unique handle index while leaving every run row
--      it produced intact — the freshness question ("when did this version last verify clean?")
--      outlives the instruction that answered it.
--
--   3. **Run history is write-once**, like the evidence and the reports it cites. The BEFORE UPDATE
--      guard is the same ``mcp_forbid_row_mutation`` V212 and V252 use. A history somebody can edit
--      is not a history.
--
--   4. **A run row can never cite another tenant's schedule.** The foreign key is composite —
--      ``(schedule_id, tenant_id)`` against the schedule's own unique key — so cross-tenant history
--      is structurally impossible rather than merely unlikely.
--
--   5. **The alert state machine lives on the row, not in a worker's memory.** ``alert_state`` and
--      ``alert_fingerprint`` are what make "a pass→fail transition triggers exactly one alert" true
--      across restarts and across replicas: the transition is recorded where every replica can see
--      it, so the second failing tick has something to be quiet about.
--
--   6. **Every tick advances the cadence anchor.** ``last_run_at`` moves whether the tick passed,
--      failed, or could not run at all, so a schedule whose version stopped compiling cannot stay
--      perpetually due and hammer the sweep — the same rule the repository-refresh and catalog-
--      digest sweeps follow.
--
-- **No new RBAC resource.** A schedule is *where and how often* verification points, which is the
-- decision V211's ``verification_targets`` resource already governs (Owner/Admin manage, Editor
-- view); its run history is verification evidence, governed by V212's ``verification_evidence``.
-- ``seed_builtin_roles`` is deliberately untouched here: adding a resource costs four synchronised
-- edits (the role grid, the REST ``Resource`` enum, the enforcement call sites, and the UI role
-- matrix), and a permission that would always be granted alongside an existing one earns none.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP FUNCTION IF EXISTS apiome.purge_verification_schedule_runs(INTEGER);
--   DROP TABLE IF EXISTS apiome.verification_schedule_run;
--   DROP TABLE IF EXISTS apiome.verification_schedule;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- verification_schedule — the standing instruction.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_schedule (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope. Carried on the row so a tenant-wide read needs no join, and repeated in the run
    -- table's composite foreign key below so it is also enforced rather than merely stored.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Handle. What CI and the UI address a schedule by, so a pipeline is not pinned to a UUID.
    slug VARCHAR(128) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- What is verified, and where. ``version_ref`` is the reference the CTG-4.3 service resolves
    -- (``project/petstore/1.0.0``); ``target_slug`` is the handle snapshot the run request carries,
    -- kept beside the id so a run request survives a rename without re-resolving.
    version_ref VARCHAR(500) NOT NULL,
    target_id UUID NOT NULL REFERENCES verification_target(id) ON DELETE CASCADE,
    target_slug VARCHAR(128) NOT NULL,

    -- When. An interval cadence, the same vocabulary every other periodic worker in the platform
    -- uses (repository refresh, MCP discovery, catalog digests). The floor is enforced here as well
    -- as in the application, because a one-second schedule against a live deployment is an outage.
    cadence_seconds INTEGER NOT NULL
        CONSTRAINT verification_schedule_cadence_check
            CHECK (cadence_seconds >= 300 AND cadence_seconds <= 2592000),

    -- Whether the schedule ticks at all, and whether recovery is worth a notification.
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    alert_on_recovery BOOLEAN NOT NULL DEFAULT TRUE,

    -- How the run is executed: the CTG-4.3 ``ProviderVerificationOptions`` (mutation opt-in and
    -- fixtures) and the ECA-1.1 compiler options. Stored as written; the application validates the
    -- shape (a fixture carrying a credential header is refused before it reaches this column).
    verification JSONB NOT NULL DEFAULT '{}'::jsonb,
    suite_options JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Scheduling + freshness state (rule 6). ``last_success_at`` is the freshness answer CTG-4.5
    -- reads: "how long since this deployment last verified clean?".
    last_run_at TIMESTAMPTZ,
    last_status VARCHAR(16)
        CONSTRAINT verification_schedule_last_status_check
            CHECK (last_status IS NULL OR last_status IN ('passed', 'failed', 'errored')),
    last_success_at TIMESTAMPTZ,
    last_report_id UUID REFERENCES provider_verification_report(id) ON DELETE SET NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    run_count INTEGER NOT NULL DEFAULT 0 CHECK (run_count >= 0),

    -- The alert state machine (rule 5). ``alert_state`` is 'ok' until a tick is unhealthy and
    -- 'alerting' until one is healthy again; ``alert_fingerprint`` is the digest of the violation
    -- set that was last alerted on, which is what lets a *changed* failure speak while an
    -- unchanged one stays quiet.
    alert_state VARCHAR(16) NOT NULL DEFAULT 'ok'
        CONSTRAINT verification_schedule_alert_state_check
            CHECK (alert_state IN ('ok', 'alerting')),
    alert_fingerprint VARCHAR(71),
    last_alert_at TIMESTAMPTZ,

    -- Provenance. ``created_by`` is ON DELETE SET NULL: a departing user must not take a tenant's
    -- drift monitoring with them.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Rule 2: retiring a schedule keeps its history.
    deleted_at TIMESTAMPTZ,

    -- Rule 4's other half: the run table's composite foreign key needs this to reference.
    CONSTRAINT verification_schedule_id_tenant_key UNIQUE (id, tenant_id)
);

-- One live schedule per handle in a tenant. Case-insensitive, because 'Staging' and 'staging' being
-- two different schedules against the same deployment is a trap, not a feature.
CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_schedule_slug
    ON verification_schedule (tenant_id, lower(slug))
    WHERE deleted_at IS NULL;

-- One live schedule per (version, deployment). Two schedules checking the same pair would double
-- the traffic at the deployment and double every alert.
CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_schedule_pair
    ON verification_schedule (tenant_id, version_ref, target_id)
    WHERE deleted_at IS NULL;

-- Due-selection: enabled, live, oldest anchor first. Never-run schedules sort first.
CREATE INDEX IF NOT EXISTS idx_verification_schedule_due
    ON verification_schedule (last_run_at NULLS FIRST)
    WHERE deleted_at IS NULL AND enabled;

-- "This tenant's schedules" — the list read.
CREATE INDEX IF NOT EXISTS idx_verification_schedule_tenant
    ON verification_schedule (tenant_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- "Is this version's deployment being watched, and how fresh is it?" — CTG-4.5's lookup.
CREATE INDEX IF NOT EXISTS idx_verification_schedule_version
    ON verification_schedule (tenant_id, version_ref, last_success_at DESC)
    WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------------------------------
-- verification_schedule_run — the write-once history (rules 3 and 4).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_schedule_run (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    schedule_id UUID NOT NULL,

    -- What the tick produced, when it produced anything. Both are ON DELETE SET NULL / unconstrained
    -- rather than cascading: retention purging the report must leave the fact that a run happened,
    -- or the freshness history develops holes exactly where the oldest evidence was.
    report_id UUID REFERENCES provider_verification_report(id) ON DELETE SET NULL,
    run_id UUID,

    -- The verdict. 'errored' covers both "the deployment never answered" and "the run could not be
    -- executed at all" — distinguished by ``error_code``, which is set only for the latter.
    status VARCHAR(16) NOT NULL
        CONSTRAINT verification_schedule_run_status_check
            CHECK (status IN ('passed', 'failed', 'errored')),
    error_code VARCHAR(64),
    error_message TEXT,

    -- Trend columns. Denormalized from the report so a 90-day chart never opens a report body.
    operations_total INTEGER NOT NULL DEFAULT 0 CHECK (operations_total >= 0),
    operations_exercised INTEGER NOT NULL DEFAULT 0 CHECK (operations_exercised >= 0),
    operations_failed INTEGER NOT NULL DEFAULT 0 CHECK (operations_failed >= 0),
    coverage_percent NUMERIC(5,2) NOT NULL DEFAULT 0
        CHECK (coverage_percent >= 0 AND coverage_percent <= 100),
    drift_count INTEGER NOT NULL DEFAULT 0 CHECK (drift_count >= 0),

    -- The violation set this tick observed, as a stable digest. Comparing two ticks' fingerprints is
    -- how "the same failure again" is told apart from "it got worse" without diffing two reports.
    drift_fingerprint VARCHAR(71),

    -- Whether this tick notified, and why. Written for every run so "why was I not paged?" is
    -- answerable from the history rather than from the worker's log.
    alerted BOOLEAN NOT NULL DEFAULT FALSE,
    alert_reason VARCHAR(32)
        CONSTRAINT verification_schedule_run_alert_reason_check
            CHECK (alert_reason IS NULL OR alert_reason IN
                   ('transition', 'new-violations', 'recovered')),
    alert_deliveries INTEGER NOT NULL DEFAULT 0 CHECK (alert_deliveries >= 0),

    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 4: the run and its schedule must belong to the same tenant, and history dies with the
    -- tenant, never with a rename.
    CONSTRAINT verification_schedule_run_schedule_fk
        FOREIGN KEY (schedule_id, tenant_id)
        REFERENCES verification_schedule (id, tenant_id)
        ON DELETE CASCADE
);

-- "This schedule's history, newest first" — the trend read and the freshness read.
CREATE INDEX IF NOT EXISTS idx_verification_schedule_run_schedule
    ON verification_schedule_run (schedule_id, created_at DESC);

-- "Everything this tenant's schedules found" — the cross-schedule drift view.
CREATE INDEX IF NOT EXISTS idx_verification_schedule_run_tenant
    ON verification_schedule_run (tenant_id, created_at DESC);

-- "When did this schedule last verify clean?" — a partial index, because the successes are what
-- freshness is measured from.
CREATE INDEX IF NOT EXISTS idx_verification_schedule_run_success
    ON verification_schedule_run (schedule_id, created_at DESC)
    WHERE status = 'passed';

-- ---------------------------------------------------------------------------------------------------
-- Immutability: a run row is write-once (rule 3).
-- ---------------------------------------------------------------------------------------------------
-- The same guard V212 applies to every evidence table and V252 applies to reports. DELETE stays
-- available to the FK cascade and to the retention function below, so bounded storage does not
-- require a mutable history.
DROP TRIGGER IF EXISTS trigger_verification_schedule_run_immutable ON verification_schedule_run;
CREATE TRIGGER trigger_verification_schedule_run_immutable
    BEFORE UPDATE ON verification_schedule_run
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Retention: bounded by age, matching the evidence and report sweeps.
-- ---------------------------------------------------------------------------------------------------
-- History is small (a handful of integers per tick) but unbounded in time, so it gets the same
-- age-based purge its siblings have. The default is deliberately longer than the report retention:
-- the trend line is cheap to keep and is the thing a freshness question actually needs.
CREATE OR REPLACE FUNCTION purge_verification_schedule_runs(p_retention_days INTEGER DEFAULT 365)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM apiome.verification_schedule_run
    WHERE created_at < CURRENT_TIMESTAMP - (p_retention_days || ' days')::INTERVAL;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE verification_schedule IS
    'CTG-4.4: a tenant''s standing instruction to verify one published version against one live '
    'deployment on a cadence, with the alert state machine that makes a pass→fail transition '
    'notify exactly once. Governed by the verification_targets RBAC resource.';

COMMENT ON COLUMN verification_schedule.alert_fingerprint IS
    'Digest of the violation set that was last alerted on. An unhealthy tick whose fingerprint '
    'matches stays silent (no alert storm); one whose fingerprint differs is new drift and speaks.';

COMMENT ON COLUMN verification_schedule.last_success_at IS
    'When this schedule last verified clean — the freshness input CTG-4.5 reads.';

COMMENT ON TABLE verification_schedule_run IS
    'CTG-4.4: write-once history of one scheduled verification tick — verdict, coverage, drift '
    'count, the violation-set fingerprint, and whether it notified. Governed by the '
    'verification_evidence RBAC resource.';
