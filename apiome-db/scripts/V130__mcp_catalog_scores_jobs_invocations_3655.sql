-- External MCP Catalog (#3655, V2-MCP-15.5 / MCAT-1.5): scores, discovery jobs, and test invocations.
--
-- With the catalog (V126), capability items (V127), version snapshots (V128), and the credential
-- vault (V129) in place, this migration adds the last three persistence surfaces the catalog needs:
--
--   * mcp_version_scores    — a quality/lint score per discovery snapshot. Mirrors the shape of the
--                             per-revision `versions.quality_*` columns from V124 (a 0-100 `score`, an
--                             A-F `grade`, and a `report_fingerprint` for staleness detection), but as
--                             its own table keyed to `mcp_endpoint_versions`. One score per version
--                             (UNIQUE) — re-scoring a version upserts the row, so `scored_at` moves.
--   * mcp_discovery_jobs    — the async discovery-pipeline work log (MCAT-7.x). Each row is one job:
--                             its lifecycle `state` (queued -> running -> completed|failed), what
--                             `trigger`ed it (manual|sweep|registry), its start/finish times, and the
--                             `error`/`result` of the run. Mutable: the pipeline advances `state` and
--                             stamps `started_at`/`finished_at` as the job progresses.
--   * mcp_test_invocations  — the test-console call log (MCAT-9.x). Each row records one invocation of
--                             a capability item (a tool call, resource read, prompt get): the
--                             `arguments` sent, the `response` received, whether it was an error, and
--                             the round-trip `latency_ms`. An append-only audit of "what was tried".
--
-- FK cascades on endpoint delete (acceptance criterion). `mcp_discovery_jobs` and
-- `mcp_test_invocations` reference `mcp_endpoints(id) ON DELETE CASCADE` directly, so they are reaped
-- when their endpoint (or its tenant) is hard-deleted. `mcp_version_scores` keys to
-- `mcp_endpoint_versions(id) ON DELETE CASCADE`, which itself cascades from the endpoint (V128) — so
-- scores are reaped transitively on endpoint teardown too. `version_id` on `mcp_test_invocations` is
-- nullable and ON DELETE SET NULL: a single version snapshot can be pruned without losing the test
-- log (the endpoint_id cascade still reaps everything on full endpoint teardown). `invoked_by`
-- likewise SET NULLs so the audit survives a user being removed.
--
-- Indexes (acceptance criterion): `(endpoint_id, created_at)` for the discovery-job and test-invocation
-- logs (list an endpoint's most recent activity), and `(state)` for the discovery scheduler picking up
-- queued jobs.
--
-- Rollback notes: this migration is purely additive (three new tables, their indexes, and comments).
-- To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_test_invocations CASCADE;
--   DROP TABLE IF EXISTS apiome.mcp_discovery_jobs   CASCADE;
--   DROP TABLE IF EXISTS apiome.mcp_version_scores   CASCADE;
-- (Each DROP also removes that table's dependent indexes.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_version_scores — one quality/lint score per discovery snapshot (mirrors versions.quality_*).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_version_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The scored snapshot; one score per version (UNIQUE below). Reaped with its version, which in
    -- turn cascades from the endpoint (V128) — so scores drop on endpoint teardown.
    version_id UUID NOT NULL REFERENCES mcp_endpoint_versions(id) ON DELETE CASCADE,

    -- Deterministic 0-100 quality score for the snapshot's surface (mirrors versions.quality_score).
    score SMALLINT,

    -- A-F letter grade derived from the score (mirrors versions.quality_grade); free-form like V124.
    grade TEXT,

    -- The full scoring report the score was computed from, retained for drill-down/render.
    report JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Stable fingerprint of the report (mirrors versions.quality_report_fingerprint); lets callers
    -- detect when a snapshot's surface changed and the score has gone stale.
    report_fingerprint TEXT,

    -- When the score was (re)computed; moves each time the version is re-scored (upsert).
    scored_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Exactly one score row per version. The btree backing this constraint also serves the by-version
    -- lookup, so no separate index is created.
    CONSTRAINT mcp_version_scores_version_unique UNIQUE (version_id),

    -- The score, when present, is a 0-100 percentage (mirrors the schema-lint domain).
    CONSTRAINT mcp_version_scores_score_range_check
        CHECK (score IS NULL OR (score >= 0 AND score <= 100))
);

COMMENT ON TABLE mcp_version_scores IS 'Quality/lint score per MCP discovery snapshot, one per version; mirrors versions.quality_* (#3655, V2-MCP-15.5)';
COMMENT ON COLUMN mcp_version_scores.id IS 'Unique identifier for the score row';
COMMENT ON COLUMN mcp_version_scores.version_id IS 'Scored mcp_endpoint_versions snapshot (UNIQUE: one score per version); cascade-deleted with the version/endpoint';
COMMENT ON COLUMN mcp_version_scores.score IS 'Deterministic 0-100 quality score for the snapshot, or NULL if not yet scored (mirrors versions.quality_score)';
COMMENT ON COLUMN mcp_version_scores.grade IS 'A-F letter grade derived from the score, or NULL if not yet scored (mirrors versions.quality_grade)';
COMMENT ON COLUMN mcp_version_scores.report IS 'Full scoring report the score was computed from, retained for drill-down/render';
COMMENT ON COLUMN mcp_version_scores.report_fingerprint IS 'Stable fingerprint of the report; lets callers detect a stale score (mirrors versions.quality_report_fingerprint)';
COMMENT ON COLUMN mcp_version_scores.scored_at IS 'When the score was (re)computed; moves on each re-score';
COMMENT ON COLUMN mcp_version_scores.created_at IS 'Timestamp when the score row was first created';

-- ---------------------------------------------------------------------------------------------------
-- mcp_discovery_jobs — the async discovery-pipeline work log (queued -> running -> completed|failed).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_discovery_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The endpoint being discovered; jobs are reaped on endpoint/tenant teardown.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- Denormalized owning tenant (also cascade-deleted with the tenant) for tenant-scoped job queries
    -- without a join back through mcp_endpoints.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Lifecycle state, advanced by the discovery pipeline.
    state VARCHAR(32) NOT NULL DEFAULT 'queued',

    -- What enqueued this job: a manual UI request, a scheduled sweep, or a registry-driven refresh.
    trigger VARCHAR(32) NOT NULL,

    -- When the job transitioned to running / reached a terminal state; NULL until those happen.
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,

    -- Failure detail for a failed job (NULL on success / while in flight).
    error TEXT,

    -- Structured outcome of the run (e.g. version produced, items discovered, change summary).
    result JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- state must be one of the four lifecycle values.
    CONSTRAINT mcp_discovery_jobs_state_check
        CHECK (state IN ('queued', 'running', 'completed', 'failed')),

    -- trigger must be one of the three enqueue sources.
    CONSTRAINT mcp_discovery_jobs_trigger_check
        CHECK (trigger IN ('manual', 'sweep', 'registry'))
);

-- Discovery scheduler: find queued (or otherwise stated) jobs to pick up.
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_state
    ON mcp_discovery_jobs(state);

-- List an endpoint's discovery history, newest first.
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_endpoint_created
    ON mcp_discovery_jobs(endpoint_id, created_at DESC);

COMMENT ON TABLE mcp_discovery_jobs IS 'Async MCP discovery-pipeline work log; one row per job with its lifecycle state and outcome (#3655, V2-MCP-15.5)';
COMMENT ON COLUMN mcp_discovery_jobs.id IS 'Unique identifier for the discovery job';
COMMENT ON COLUMN mcp_discovery_jobs.endpoint_id IS 'Endpoint being discovered; cascade-deleted with the endpoint/tenant';
COMMENT ON COLUMN mcp_discovery_jobs.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN mcp_discovery_jobs.state IS 'Job lifecycle state: queued, running, completed, or failed';
COMMENT ON COLUMN mcp_discovery_jobs.trigger IS 'What enqueued the job: manual, sweep, or registry';
COMMENT ON COLUMN mcp_discovery_jobs.started_at IS 'When the job began running; NULL while queued';
COMMENT ON COLUMN mcp_discovery_jobs.finished_at IS 'When the job reached a terminal state; NULL until completed/failed';
COMMENT ON COLUMN mcp_discovery_jobs.error IS 'Failure detail for a failed job; NULL on success / while in flight';
COMMENT ON COLUMN mcp_discovery_jobs.result IS 'Structured outcome of the run (e.g. version produced, items discovered, change summary)';
COMMENT ON COLUMN mcp_discovery_jobs.created_at IS 'Timestamp when the job was enqueued';

-- ---------------------------------------------------------------------------------------------------
-- mcp_test_invocations — the test-console call log (one row per tool call / resource read / prompt get).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_test_invocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The endpoint the call was made against; invocations are reaped on endpoint/tenant teardown.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- The snapshot the call targeted (the surface the item came from). Nullable + SET NULL so pruning
    -- a single version does not destroy the test log; the endpoint_id cascade still reaps it on full
    -- endpoint teardown.
    version_id UUID REFERENCES mcp_endpoint_versions(id) ON DELETE SET NULL,

    -- Which kind of capability was invoked, and its programmatic name.
    item_type VARCHAR(32) NOT NULL,
    item_name VARCHAR(255) NOT NULL,

    -- The arguments sent with the call and the response received (NULL response if it never returned).
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    response JSONB,

    -- Whether the call returned an error (an MCP `isError` result or a transport failure).
    is_error BOOLEAN NOT NULL DEFAULT false,

    -- Round-trip latency of the call in milliseconds; NULL if it never completed.
    latency_ms INTEGER,

    -- The user who ran the test. SET NULL keeps the log if the user is later removed.
    invoked_by UUID REFERENCES users(id) ON DELETE SET NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- item_type must be one of the four MCP capability kinds (cf. V127).
    CONSTRAINT mcp_test_invocations_item_type_check
        CHECK (item_type IN ('tool', 'resource', 'resource_template', 'prompt')),

    -- Latency, when recorded, is non-negative.
    CONSTRAINT mcp_test_invocations_latency_check
        CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

-- List an endpoint's most recent test invocations, newest first.
CREATE INDEX IF NOT EXISTS idx_mcp_test_invocations_endpoint_created
    ON mcp_test_invocations(endpoint_id, created_at DESC);

COMMENT ON TABLE mcp_test_invocations IS 'Test-console call log: one row per tool call / resource read / prompt get against an MCP endpoint (#3655, V2-MCP-15.5)';
COMMENT ON COLUMN mcp_test_invocations.id IS 'Unique identifier for the test invocation';
COMMENT ON COLUMN mcp_test_invocations.endpoint_id IS 'Endpoint the call was made against; cascade-deleted with the endpoint/tenant';
COMMENT ON COLUMN mcp_test_invocations.version_id IS 'Snapshot the call targeted; SET NULL if that version is pruned (log survives)';
COMMENT ON COLUMN mcp_test_invocations.item_type IS 'Capability kind invoked: tool, resource, resource_template, or prompt';
COMMENT ON COLUMN mcp_test_invocations.item_name IS 'Programmatic name of the invoked item';
COMMENT ON COLUMN mcp_test_invocations.arguments IS 'Arguments sent with the call';
COMMENT ON COLUMN mcp_test_invocations.response IS 'Response received from the call; NULL if it never returned';
COMMENT ON COLUMN mcp_test_invocations.is_error IS 'Whether the call returned an error (MCP isError result or transport failure)';
COMMENT ON COLUMN mcp_test_invocations.latency_ms IS 'Round-trip latency of the call in milliseconds; NULL if it never completed';
COMMENT ON COLUMN mcp_test_invocations.invoked_by IS 'User who ran the test; SET NULL if the user is later removed';
COMMENT ON COLUMN mcp_test_invocations.created_at IS 'Timestamp when the invocation was recorded';
