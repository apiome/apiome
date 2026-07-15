-- Consent-gated, sandboxed MCP dynamic probes — audit trail and target allowlist. CLX-3.3 (#4857).
--
-- The three prior MCP scan engines are static: they read what a server advertised, how it behaved
-- during ordinary discovery, or what it is built from. CLX-3.3 adds the first engine that *sends the
-- server something and watches what it does*, so that a defect can be classified not merely as
-- SUSPECTED (a static signal) but as OBSERVED (a probe witnessed the behaviour) or EXPLOITED-IN-TEST
-- (a probe demonstrated it against a live server in isolation).
--
-- Sending a live server anything is dangerous in two directions, and this migration is the durable
-- half of the guardrails the acceptance criteria demand:
--
--   mcp_probe_targets   — the ALLOWLIST. You may only fire active probes at a target someone
--                         explicitly enrolled, having declared they own/are authorized to test it and
--                         named the dedicated (non-production) credential the probe authenticates as.
--   mcp_probe_runs      — the AUDIT TRAIL. Every active run records its target, scope (profile),
--                         test identity, hard limits, consent, isolation, and outcome — so the
--                         evidence always answers "who authorized firing what at whom, under what
--                         limits, as which identity, and what happened".
--
-- The audit table is ALSO the concurrency/rate ledger (AC5): a tenant's in-flight run count is the
-- number of its rows in 'running' state, and its trailing-hour count is the rows started in the last
-- hour. The application's per-tenant governor reads exactly those two counts before authorizing a new
-- run, so there is one source of truth for how much probing a tenant has in flight — the database,
-- not an in-memory counter that a restart would lose.
--
-- ---------------------------------------------------------------------------------------------------
-- Passive is absent by design
-- ---------------------------------------------------------------------------------------------------
-- The default probe profile (passive) sends nothing — it re-reads the transcript discovery already
-- captured — so it needs neither consent nor an audit row and creates none here. Only profiles that
-- put traffic on the wire (safe-active, payload-fuzzing) are gated, allowlisted, and audited. That is
-- why an endpoint nobody enrolled still has a fully useful passive posture: freezing active probing
-- (the kill switch) never blinds the read-only lane.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.mcp_probe_runs;
--   DROP TABLE IF EXISTS apiome.mcp_probe_targets;
--
-- Idempotent: CREATE ... IF NOT EXISTS throughout.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_probe_targets — the explicit allowlist an active probe may fire at.
-- ---------------------------------------------------------------------------------------------------
-- Enrolling a target is the operator asserting, on the record, "I own or am authorized to probe this,
-- and here is the dedicated credential a probe should authenticate as." A run against a target with no
-- live row here is refused before a single byte is sent — probing a system you did not enrol is an
-- attack, and this table is the record that you said you may.
CREATE TABLE IF NOT EXISTS mcp_probe_targets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Denormalized from the endpoint so tenant-scoped listing never needs a join; cascades with tenant.
    tenant_id UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,

    -- The endpoint enrolled for active probing. An allowlist entry is a fact about the ENDPOINT, not
    -- any one version snapshot.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints (id) ON DELETE CASCADE,

    -- 'http'  — a remote server contacted over the network (probed with restricted egress).
    -- 'stdio' — a server run as a local subprocess (untrusted code; MUST be sandboxed to be probed).
    transport TEXT NOT NULL,

    -- The resolved target the operator enrolled: a URL for http, a command reference for stdio.
    -- Recorded so an audit says what was contacted, not merely which endpoint id.
    locator TEXT NOT NULL,

    -- The operator's assertion that they own, or are authorized to test, this target. Enrollment is
    -- refused without it; it is stored so the assertion is auditable after the fact.
    ownership_declared BOOLEAN NOT NULL DEFAULT FALSE,

    -- The id of the DEDICATED test credential a probe authenticates as. Never a production credential
    -- — a probe must not act as a real user. NULL only for an unauthenticated target.
    test_credential_id UUID REFERENCES mcp_endpoint_credentials (id) ON DELETE SET NULL,

    -- Who enrolled it. RESTRICT, not CASCADE: deleting a user must not silently erase the provenance of
    -- an allowlist entry other evidence depends on.
    enrolled_by UUID REFERENCES users (id) ON DELETE RESTRICT,

    -- Soft retirement. A retired target stops authorizing new runs but stays readable, so historical
    -- audit rows that cite it remain interpretable.
    retired_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_probe_targets_transport_check
        CHECK (transport IN ('http', 'stdio')),

    CONSTRAINT mcp_probe_targets_locator_not_blank_check
        CHECK (length(trim(locator)) > 0),

    -- Enrollment requires a declared ownership. The schema refuses to store an allowlist entry that
    -- did not carry the authorization assertion — the alternative (a target enrolled without anyone
    -- vouching for it) is the precise failure this table exists to prevent.
    CONSTRAINT mcp_probe_targets_ownership_required_check
        CHECK (ownership_declared = TRUE)
);

-- One live allowlist entry per (endpoint, transport). Retired rows are excluded so a target can be
-- re-enrolled after retirement without colliding with its own history.
CREATE UNIQUE INDEX IF NOT EXISTS mcp_probe_targets_live_unique
    ON mcp_probe_targets (endpoint_id, transport)
    WHERE retired_at IS NULL;

CREATE INDEX IF NOT EXISTS mcp_probe_targets_tenant_idx
    ON mcp_probe_targets (tenant_id)
    WHERE retired_at IS NULL;

COMMENT ON TABLE mcp_probe_targets IS
    'CLX-3.3 (#4857): the explicit allowlist an active MCP probe may fire at. A run against a target '
    'with no live row here is refused. Records the operator ownership assertion and the dedicated '
    '(non-production) test credential a probe authenticates as. Passive (read-only) probing needs no '
    'entry here and creates none.';

COMMENT ON COLUMN mcp_probe_targets.test_credential_id IS
    'The dedicated probe credential a run authenticates as — never a production credential. NULL only '
    'for an unauthenticated target.';

-- ---------------------------------------------------------------------------------------------------
-- mcp_probe_runs — the audit trail and the concurrency/rate ledger.
-- ---------------------------------------------------------------------------------------------------
-- One row per active probe run, written the moment the run is authorized (status 'running') and
-- updated once to its terminal state ('completed' / 'refused' / 'failed'). A refused run is recorded
-- too — an attempt that the kill switch, the allowlist, consent, or isolation turned away is itself
-- audit-worthy, so the refusal and its reason are persisted rather than dropped.
CREATE TABLE IF NOT EXISTS mcp_probe_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints (id) ON DELETE CASCADE,

    -- The snapshot the run assessed, when it was pinned to one. NULL for a run against the endpoint's
    -- current live server without a specific version snapshot.
    version_id UUID REFERENCES mcp_endpoint_versions (id) ON DELETE SET NULL,

    -- The profile that ran: 'safe-active' or 'payload-fuzzing'. Passive never lands here (it sends
    -- nothing), so the check deliberately excludes it — a 'passive' row would be a contradiction.
    profile TEXT NOT NULL,

    -- AC2: target, scope, test identity, limits, and consent recorded in the evidence itself.
    target_locator TEXT NOT NULL,
    transport TEXT NOT NULL,
    -- The full consent record verbatim: allowlisted, ownership_declared, test_identity,
    -- dedicated_credentials, acknowledged_by, acknowledged_at, explicit_approval.
    consent JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- The hard limits the run carried: max_requests, rate_per_minute, wall_clock_seconds,
    -- max_response_bytes.
    limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- The isolation spec for a stdio run (least-privilege sandbox). NULL for an http run.
    isolation JSONB,

    -- Lifecycle. 'running' is the in-flight state the concurrency ledger counts.
    status TEXT NOT NULL DEFAULT 'running',

    -- Why a run was refused, when status is 'refused' (kill switch, not allowlisted, consent invalid,
    -- isolation not least-privilege, rate/concurrency limit). NULL otherwise.
    refusal_reason TEXT,

    -- Outcome tallies, filled on completion.
    requests_sent INTEGER NOT NULL DEFAULT 0,
    observed_count INTEGER NOT NULL DEFAULT 0,
    exploited_count INTEGER NOT NULL DEFAULT 0,

    -- The full probe report (findings, classification/severity counts, evidence). NULL until terminal.
    report JSONB,
    report_fingerprint TEXT,

    started_by UUID REFERENCES users (id) ON DELETE SET NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT mcp_probe_runs_profile_check
        CHECK (profile IN ('safe-active', 'payload-fuzzing')),

    CONSTRAINT mcp_probe_runs_transport_check
        CHECK (transport IN ('http', 'stdio')),

    CONSTRAINT mcp_probe_runs_status_check
        CHECK (status IN ('running', 'completed', 'refused', 'failed')),

    CONSTRAINT mcp_probe_runs_counts_nonneg_check
        CHECK (requests_sent >= 0 AND observed_count >= 0 AND exploited_count >= 0),

    -- A refused run must say why; a running row may not pretend it already has an outcome. These keep
    -- the ledger honest: an in-flight run has no report, and a refusal is never silent.
    CONSTRAINT mcp_probe_runs_refusal_has_reason_check
        CHECK (status <> 'refused' OR refusal_reason IS NOT NULL),
    CONSTRAINT mcp_probe_runs_running_has_no_outcome_check
        CHECK (status <> 'running' OR (report IS NULL AND completed_at IS NULL))
);

-- The concurrency ledger: how many of a tenant's runs are in flight right now. Partial so the index
-- is small and the count the governor reads is a cheap index-only scan.
CREATE INDEX IF NOT EXISTS mcp_probe_runs_active_idx
    ON mcp_probe_runs (tenant_id)
    WHERE status = 'running';

-- The rate ledger: how many runs a tenant started in the trailing window.
CREATE INDEX IF NOT EXISTS mcp_probe_runs_tenant_started_idx
    ON mcp_probe_runs (tenant_id, started_at DESC);

CREATE INDEX IF NOT EXISTS mcp_probe_runs_endpoint_idx
    ON mcp_probe_runs (endpoint_id, started_at DESC);

COMMENT ON TABLE mcp_probe_runs IS
    'CLX-3.3 (#4857): audit trail and concurrency/rate ledger for active MCP probe runs. One row per '
    'run (safe-active or payload-fuzzing; passive is never recorded), recording target, scope, test '
    'identity, limits, consent, isolation, and outcome. A tenant''s in-flight count is its rows in '
    'status=running; its trailing-hour count is rows by started_at — the per-tenant governor reads '
    'exactly those, so the DB is the single source of truth for probing in flight. Refused runs are '
    'recorded with their reason, never dropped.';

COMMENT ON COLUMN mcp_probe_runs.status IS
    'running (in-flight; the concurrency ledger counts these) | completed | refused (turned away by a '
    'guardrail; refusal_reason is set) | failed (an error during the run).';
