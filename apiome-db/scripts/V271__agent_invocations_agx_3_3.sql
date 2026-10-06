-- Invocation audit & usage rollups — AGX-3.3 (#4539).
--
-- "Observable" is a third of the agent value proposition: a tenant must be able to answer *which
-- agent called which tool, when, how fast, with what outcome* — without the platform keeping
-- request/response bodies it has no business retaining. This migration adds:
--
--   agent_invocations          one metadata-only row per `tools/call` an agent key makes
--   agent_invocation_samples   opt-in, sampled, size-capped bodies for debugging (never by default)
--   agent_invocation_daily     per (tenant, day, key, toolset, tool, target) aggregates for charts
--   agent_invocation_rollup_days  which UTC days have been rolled up, and which are final
--   agent_toolsets.body_capture_rate / body_capture_until   the per-toolset sampling opt-in
--   licenses.seats keys        per-tier raw and rollup retention
--
-- and the functions the apiome-mcp usage sweep (`apiome_mcp.agent_usage_sweep`) calls on a
-- schedule: `rollup_agent_invocation_days`, `purge_agent_invocations`,
-- `purge_agent_invocation_samples` and `purge_agent_invocation_rollups`. The same sweep finally
-- schedules V268's `purge_upstream_credential_uses`.
--
-- Seven rules shape the schema:
--
--   1. **Metadata only.** An invocation row carries the key, toolset, tool, target, start time,
--      latency, outcome, upstream HTTP status, a machine reason code and the request/response sizes.
--      There is no body, header, argument value or free-text message column, so nothing an agent
--      sends or an upstream returns can end up here.
--
--   2. **Every outcome is a row.** `outcome` is `success`, `upstream_error`, `validation_failure`,
--      `quota_rejected` or `internal_error`; anything but `success` carries an `error_code` (and
--      `success` never does). Rows are written by the AGX-2.1 call path through
--      `apiome_mcp.agent_invocations.audit_invocation`, which writes exactly one row per call.
--
--   3. **History outlives keys.** `key_id` / `toolset_id` have no foreign key: revoking or deleting a
--      key or toolset must not rewrite who called what. Only deleting the tenant removes its rows.
--      Rows are write-once (the shared `mcp_forbid_row_mutation` trigger refuses UPDATE).
--
--   4. **Bodies are opt-in, sampled and bounded.** A toolset captures bodies only while
--      `body_capture_rate > 0` *and* `body_capture_until` is in the future; the window may be at
--      most 7 days ahead when it is set (trigger), each body is capped at 16 KiB (CHECK), and samples
--      are purged after 7 days whatever the tier. Headers are never captured.
--
--   5. **Rollups match raw counts.** `rollup_agent_invocation_days` recomputes each open UTC day
--      from the raw rows (idempotent upsert) and marks a day *final* once it closed more than a grace
--      period ago. A final day is never recomputed.
--
--   6. **Pruning never touches rollups.** `purge_agent_invocations` deletes raw rows only once they
--      are past the tenant's tier retention **and** their day is final, so every pruned row was
--      already counted. Rollups have their own, longer, per-tier retention.
--
--   7. **Retention follows the license tier.** `licenses.seats` gains
--      `agent_invocation_retention_days` (raw rows; minimum 1) and
--      `agent_usage_rollup_retention_days` (rollups). Free 7 / 90, Paid 30 / 395, Sponsor 90 / 730.
--      A negative value keeps rows forever; a tenant with no license, or a missing / non-numeric key,
--      gets the Free values.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.purge_agent_invocation_rollups(TIMESTAMPTZ, INTEGER);
--   DROP FUNCTION IF EXISTS apiome.purge_agent_invocation_samples(TIMESTAMPTZ, INTERVAL, INTEGER);
--   DROP FUNCTION IF EXISTS apiome.purge_agent_invocations(TIMESTAMPTZ, INTEGER);
--   DROP FUNCTION IF EXISTS apiome.rollup_agent_invocation_days(TIMESTAMPTZ, INTERVAL);
--   DROP FUNCTION IF EXISTS apiome.rollup_agent_invocations(DATE, TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.agent_usage_retention(TIMESTAMPTZ);
--   DROP TABLE IF EXISTS apiome.agent_invocation_rollup_days;
--   DROP TABLE IF EXISTS apiome.agent_invocation_daily;
--   DROP TABLE IF EXISTS apiome.agent_invocation_samples;
--   DROP TABLE IF EXISTS apiome.agent_invocations;
--   DROP TRIGGER IF EXISTS trigger_agent_toolsets_body_capture_window ON apiome.agent_toolsets;
--   DROP FUNCTION IF EXISTS apiome.agent_toolsets_body_capture_window();
--   ALTER TABLE apiome.agent_toolsets
--     DROP CONSTRAINT IF EXISTS agent_toolsets_body_capture_ck,
--     DROP COLUMN IF EXISTS body_capture_until,
--     DROP COLUMN IF EXISTS body_capture_rate;
--   UPDATE apiome.licenses
--     SET seats = seats - 'agent_invocation_retention_days' - 'agent_usage_rollup_retention_days';

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: the per-toolset body-capture opt-in.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE agent_toolsets
  ADD COLUMN IF NOT EXISTS body_capture_rate NUMERIC(5, 4) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS body_capture_until TIMESTAMPTZ;

ALTER TABLE agent_toolsets
  DROP CONSTRAINT IF EXISTS agent_toolsets_body_capture_ck;
ALTER TABLE agent_toolsets
  ADD CONSTRAINT agent_toolsets_body_capture_ck
  CHECK (
    body_capture_rate >= 0 AND body_capture_rate <= 1
    AND (body_capture_rate = 0 OR body_capture_until IS NOT NULL)
  );

-- A CHECK cannot read the clock, so the 7-day bound on the window is a trigger. It applies when the
-- window is written, so an existing window is never invalidated by time passing.
CREATE OR REPLACE FUNCTION agent_toolsets_body_capture_window()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.body_capture_rate > 0
       AND NEW.body_capture_until IS DISTINCT FROM
           (CASE WHEN TG_OP = 'UPDATE' THEN OLD.body_capture_until END)
       AND NEW.body_capture_until > CURRENT_TIMESTAMP + INTERVAL '7 days' THEN
        RAISE EXCEPTION 'agent_toolsets.body_capture_until may be at most 7 days ahead'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_agent_toolsets_body_capture_window ON agent_toolsets;
CREATE TRIGGER trigger_agent_toolsets_body_capture_window
    BEFORE INSERT OR UPDATE OF body_capture_rate, body_capture_until ON agent_toolsets
    FOR EACH ROW
    EXECUTE FUNCTION agent_toolsets_body_capture_window();

COMMENT ON COLUMN agent_toolsets.body_capture_rate IS
    'AGX-3.3 (#4539): fraction (0..1) of tools/call invocations whose bodies are captured into '
    'agent_invocation_samples for debugging. 0 (the default) captures nothing.';

COMMENT ON COLUMN agent_toolsets.body_capture_until IS
    'AGX-3.3 (#4539): body capture stops at this time. Required while body_capture_rate > 0; '
    'at most 7 days ahead when written.';

-- ---------------------------------------------------------------------------------------------------
-- Rules 1–3: the raw invocation log.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_invocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 3: no foreign keys — the history outlives the key and the toolset.
    key_id UUID NOT NULL,
    toolset_id UUID NOT NULL,
    tool_name VARCHAR(64) NOT NULL
        CONSTRAINT agent_invocations_tool_name_ck CHECK (tool_name ~ '^[A-Za-z0-9_-]{1,64}$'),
    target VARCHAR(8) NOT NULL
        CONSTRAINT agent_invocations_target_ck CHECK (target IN ('prod', 'mock')),

    -- When the call started, and the UTC day it is counted on.
    invoked_at TIMESTAMPTZ NOT NULL,
    invoked_day DATE GENERATED ALWAYS AS ((invoked_at AT TIME ZONE 'UTC')::date) STORED,
    latency_ms INTEGER NOT NULL
        CONSTRAINT agent_invocations_latency_ck CHECK (latency_ms >= 0),

    -- Rule 2: the outcome, with a machine reason code for every failure.
    outcome VARCHAR(24) NOT NULL
        CONSTRAINT agent_invocations_outcome_ck CHECK (
            outcome IN ('success', 'upstream_error', 'validation_failure', 'quota_rejected',
                        'internal_error')
        ),
    error_code VARCHAR(64)
        CONSTRAINT agent_invocations_error_code_ck CHECK (error_code ~ '^[a-z][a-z0-9_.]{0,63}$'),
    http_status SMALLINT
        CONSTRAINT agent_invocations_http_status_ck CHECK (http_status BETWEEN 100 AND 599),
    CONSTRAINT agent_invocations_error_code_outcome_ck CHECK (
        (outcome = 'success') = (error_code IS NULL)
    ),

    -- Sizes only (UTF-8 bytes of the arguments sent / the result returned).
    request_bytes BIGINT NOT NULL
        CONSTRAINT agent_invocations_request_bytes_ck CHECK (request_bytes >= 0),
    response_bytes BIGINT NOT NULL
        CONSTRAINT agent_invocations_response_bytes_ck CHECK (response_bytes >= 0),

    -- Rule 4: whether a body sample was captured for this call.
    sampled BOOLEAN NOT NULL DEFAULT false
);

-- A tenant's log, newest first (AGX-3.4 views, AGX-3.2 counters) and the per-tenant prune.
CREATE INDEX IF NOT EXISTS idx_agent_invocations_tenant_time
    ON agent_invocations (tenant_id, invoked_at DESC);

-- One key's recent calls (AGX-3.2 quotas, AGX-3.5 anomaly detection).
CREATE INDEX IF NOT EXISTS idx_agent_invocations_key_time
    ON agent_invocations (key_id, invoked_at DESC);

-- The rollup reads one UTC day at a time.
CREATE INDEX IF NOT EXISTS idx_agent_invocations_day
    ON agent_invocations (invoked_day);

COMMENT ON TABLE agent_invocations IS
    'AGX-3.3 (#4539): one metadata-only row per agent tools/call — which key called which tool, '
    'when, how fast, with what outcome and sizes. Never a body, header or argument value. Write-once.';

COMMENT ON COLUMN agent_invocations.key_id IS
    'The agent key (api_keys.id, kind=agent) that made the call. No FK: history outlives the key.';

COMMENT ON COLUMN agent_invocations.toolset_id IS
    'The agent toolset (agent_toolsets.id) the tool belongs to. No FK: history outlives the toolset.';

COMMENT ON COLUMN agent_invocations.invoked_at IS
    'When the call started. invoked_day is its UTC calendar day, the rollup grain.';

COMMENT ON COLUMN agent_invocations.outcome IS
    'success | upstream_error (upstream reached and failed, or unreachable) | validation_failure '
    '(arguments refused before the upstream) | quota_rejected (AGX-3.2 limit) | internal_error.';

COMMENT ON COLUMN agent_invocations.error_code IS
    'Machine reason code for a non-success outcome (e.g. upstream_timeout); NULL on success. '
    'Never free text.';

COMMENT ON COLUMN agent_invocations.http_status IS
    'The upstream HTTP status when the upstream answered; NULL when it was never reached.';

-- Rule 3: write-once. DELETE stays available to the tenant cascade and the purge below.
DROP TRIGGER IF EXISTS trigger_agent_invocations_immutable ON agent_invocations;
CREATE TRIGGER trigger_agent_invocations_immutable
    BEFORE UPDATE ON agent_invocations
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: sampled bodies. Bounded per body; pruned with their invocation, or after 7 days.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_invocation_samples (
    invocation_id UUID PRIMARY KEY REFERENCES agent_invocations(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    request_body TEXT
        CONSTRAINT agent_invocation_samples_request_ck CHECK (octet_length(request_body) <= 16384),
    response_body TEXT
        CONSTRAINT agent_invocation_samples_response_ck CHECK (octet_length(response_body) <= 16384),
    request_truncated BOOLEAN NOT NULL DEFAULT false,
    response_truncated BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_agent_invocation_samples_captured
    ON agent_invocation_samples (captured_at);

COMMENT ON TABLE agent_invocation_samples IS
    'AGX-3.3 (#4539): opt-in debugging capture of a sampled invocation''s bodies (no headers), '
    'each capped at 16 KiB. Only written while the toolset''s body_capture window is open; '
    'purged after 7 days regardless of tier.';

DROP TRIGGER IF EXISTS trigger_agent_invocation_samples_immutable ON agent_invocation_samples;
CREATE TRIGGER trigger_agent_invocation_samples_immutable
    BEFORE UPDATE ON agent_invocation_samples
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Rule 5: daily rollups.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_invocation_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    key_id UUID NOT NULL,
    toolset_id UUID NOT NULL,
    tool_name VARCHAR(64) NOT NULL,
    target VARCHAR(8) NOT NULL,

    calls BIGINT NOT NULL,
    success_calls BIGINT NOT NULL,
    upstream_errors BIGINT NOT NULL,
    validation_failures BIGINT NOT NULL,
    quota_rejections BIGINT NOT NULL,
    internal_errors BIGINT NOT NULL,
    errors BIGINT GENERATED ALWAYS AS (calls - success_calls) STORED,

    latency_p50_ms INTEGER NOT NULL,
    latency_p95_ms INTEGER NOT NULL,
    latency_p99_ms INTEGER NOT NULL,
    latency_max_ms INTEGER NOT NULL,
    latency_sum_ms BIGINT NOT NULL,

    request_bytes BIGINT NOT NULL,
    response_bytes BIGINT NOT NULL,

    computed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (tenant_id, day, key_id, toolset_id, tool_name, target),
    CONSTRAINT agent_invocation_daily_calls_ck CHECK (
        calls = success_calls + upstream_errors + validation_failures + quota_rejections
                + internal_errors
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_invocation_daily_day
    ON agent_invocation_daily (day);

COMMENT ON TABLE agent_invocation_daily IS
    'AGX-3.3 (#4539): per (tenant, UTC day, key, toolset, tool, target) aggregates of '
    'agent_invocations — calls by outcome, latency percentiles, bytes. Powers usage charts '
    '(AGX-3.4) without scanning raw rows; retained longer than raw rows.';

CREATE TABLE IF NOT EXISTS agent_invocation_rollup_days (
    day DATE PRIMARY KEY,
    rolled_up_at TIMESTAMPTZ NOT NULL,
    finalized_at TIMESTAMPTZ
);

COMMENT ON TABLE agent_invocation_rollup_days IS
    'AGX-3.3 (#4539): UTC days rolled up into agent_invocation_daily. A finalized day is never '
    'recomputed, and only a finalized day''s raw rows may be pruned.';

-- One UTC day: recompute every group from the raw rows. A no-op on a finalized day.
CREATE OR REPLACE FUNCTION rollup_agent_invocations(
    p_day DATE,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
RETURNS INTEGER AS $$
DECLARE
    v_groups INTEGER;
BEGIN
    IF EXISTS (
        SELECT 1 FROM apiome.agent_invocation_rollup_days
        WHERE day = p_day AND finalized_at IS NOT NULL
    ) THEN
        RETURN 0;
    END IF;

    INSERT INTO apiome.agent_invocation_daily AS d (
        tenant_id, day, key_id, toolset_id, tool_name, target,
        calls, success_calls, upstream_errors, validation_failures, quota_rejections,
        internal_errors, latency_p50_ms, latency_p95_ms, latency_p99_ms, latency_max_ms,
        latency_sum_ms, request_bytes, response_bytes, computed_at
    )
    SELECT i.tenant_id, p_day, i.key_id, i.toolset_id, i.tool_name, i.target,
           count(*),
           count(*) FILTER (WHERE i.outcome = 'success'),
           count(*) FILTER (WHERE i.outcome = 'upstream_error'),
           count(*) FILTER (WHERE i.outcome = 'validation_failure'),
           count(*) FILTER (WHERE i.outcome = 'quota_rejected'),
           count(*) FILTER (WHERE i.outcome = 'internal_error'),
           percentile_disc(0.50) WITHIN GROUP (ORDER BY i.latency_ms),
           percentile_disc(0.95) WITHIN GROUP (ORDER BY i.latency_ms),
           percentile_disc(0.99) WITHIN GROUP (ORDER BY i.latency_ms),
           max(i.latency_ms),
           sum(i.latency_ms),
           sum(i.request_bytes),
           sum(i.response_bytes),
           p_now
    FROM apiome.agent_invocations i
    WHERE i.invoked_day = p_day
    GROUP BY i.tenant_id, i.key_id, i.toolset_id, i.tool_name, i.target
    ON CONFLICT (tenant_id, day, key_id, toolset_id, tool_name, target) DO UPDATE SET
        calls = EXCLUDED.calls,
        success_calls = EXCLUDED.success_calls,
        upstream_errors = EXCLUDED.upstream_errors,
        validation_failures = EXCLUDED.validation_failures,
        quota_rejections = EXCLUDED.quota_rejections,
        internal_errors = EXCLUDED.internal_errors,
        latency_p50_ms = EXCLUDED.latency_p50_ms,
        latency_p95_ms = EXCLUDED.latency_p95_ms,
        latency_p99_ms = EXCLUDED.latency_p99_ms,
        latency_max_ms = EXCLUDED.latency_max_ms,
        latency_sum_ms = EXCLUDED.latency_sum_ms,
        request_bytes = EXCLUDED.request_bytes,
        response_bytes = EXCLUDED.response_bytes,
        computed_at = EXCLUDED.computed_at;
    GET DIAGNOSTICS v_groups = ROW_COUNT;

    INSERT INTO apiome.agent_invocation_rollup_days (day, rolled_up_at)
    VALUES (p_day, p_now)
    ON CONFLICT (day) DO UPDATE SET rolled_up_at = EXCLUDED.rolled_up_at;

    RETURN v_groups;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rollup_agent_invocations(DATE, TIMESTAMPTZ) IS
    'Recompute agent_invocation_daily for one UTC day from agent_invocations (idempotent upsert). '
    'No-op on a finalized day. Returns the number of groups written (AGX-3.3, #4539).';

-- Every open day, oldest first: from the day after the newest finalized one (or the oldest raw
-- row) through today. A day is finalized once it ended more than p_grace ago, which must exceed
-- the longest call so no late row lands on a final day.
CREATE OR REPLACE FUNCTION rollup_agent_invocation_days(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_grace INTERVAL DEFAULT INTERVAL '6 hours'
)
RETURNS INTEGER AS $$
DECLARE
    v_today DATE := (p_now AT TIME ZONE 'UTC')::date;
    v_from DATE;
    v_day DATE;
    v_days INTEGER := 0;
BEGIN
    SELECT max(day) + 1 INTO v_from
    FROM apiome.agent_invocation_rollup_days
    WHERE finalized_at IS NOT NULL;

    -- Also reach back to any raw day not yet finalized (e.g. the very first sweep).
    SELECT LEAST(v_from, min(i.invoked_day)) INTO v_from
    FROM apiome.agent_invocations i
    WHERE NOT EXISTS (
        SELECT 1 FROM apiome.agent_invocation_rollup_days r
        WHERE r.day = i.invoked_day AND r.finalized_at IS NOT NULL
    );

    IF v_from IS NULL THEN
        RETURN 0;
    END IF;

    v_day := v_from;
    WHILE v_day <= v_today LOOP
        PERFORM apiome.rollup_agent_invocations(v_day, p_now);
        -- The day ended at (v_day + 1) 00:00 UTC.
        IF ((v_day + 1)::timestamp AT TIME ZONE 'UTC') + p_grace <= p_now THEN
            UPDATE apiome.agent_invocation_rollup_days
            SET finalized_at = p_now
            WHERE day = v_day AND finalized_at IS NULL;
        END IF;
        v_days := v_days + 1;
        v_day := v_day + 1;
    END LOOP;
    RETURN v_days;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rollup_agent_invocation_days(TIMESTAMPTZ, INTERVAL) IS
    'Roll up every open UTC day through today and finalize days that ended more than p_grace ago. '
    'Returns the number of days processed (AGX-3.3, #4539).';

-- ---------------------------------------------------------------------------------------------------
-- Rules 6–7: per-tier retention.
-- ---------------------------------------------------------------------------------------------------

-- Each live tenant's retention windows from its license tier (Free values when unlicensed or unset).
-- NULL cutoff = keep forever (a negative seats value).
CREATE OR REPLACE FUNCTION agent_usage_retention(p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)
RETURNS TABLE (tenant_id UUID, raw_cutoff TIMESTAMPTZ, rollup_cutoff DATE) AS $$
    WITH tiers AS (
        SELECT t.id AS tenant_id,
               CASE WHEN jsonb_typeof(l.seats -> 'agent_invocation_retention_days') = 'number'
                    THEN (l.seats ->> 'agent_invocation_retention_days')::numeric::integer
                    ELSE 7 END AS raw_days,
               CASE WHEN jsonb_typeof(l.seats -> 'agent_usage_rollup_retention_days') = 'number'
                    THEN (l.seats ->> 'agent_usage_rollup_retention_days')::numeric::integer
                    ELSE 90 END AS rollup_days
        FROM apiome.tenants t
        LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
        LEFT JOIN apiome.licenses l ON l.id = tl.license_id
    )
    SELECT tenant_id,
           CASE WHEN raw_days < 0 THEN NULL
                ELSE p_now - GREATEST(raw_days, 1) * INTERVAL '1 day' END,
           CASE WHEN rollup_days < 0 THEN NULL
                ELSE (p_now AT TIME ZONE 'UTC')::date - GREATEST(rollup_days, 1) END
    FROM tiers;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION agent_usage_retention(TIMESTAMPTZ) IS
    'Per-tenant agent usage retention from licenses.seats: raw_cutoff (agent_invocations older '
    'than this may go) and rollup_cutoff (rollup days before this may go). NULL = keep forever. '
    'AGX-3.3 (#4539).';

-- Raw rows past the tenant's retention whose day is final (so they are already in the rollup).
CREATE OR REPLACE FUNCTION purge_agent_invocations(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
BEGIN
    DELETE FROM apiome.agent_invocations
    WHERE id IN (
        SELECT i.id
        FROM apiome.agent_usage_retention(p_now) r
        JOIN apiome.agent_invocations i
          ON i.tenant_id = r.tenant_id AND i.invoked_at < r.raw_cutoff
        JOIN apiome.agent_invocation_rollup_days d
          ON d.day = i.invoked_day AND d.finalized_at IS NOT NULL
        LIMIT GREATEST(p_batch, 1)
    );
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_agent_invocations(TIMESTAMPTZ, INTEGER) IS
    'Delete up to p_batch raw agent_invocations past their tenant''s tier retention whose UTC day '
    'is finalized. Never touches agent_invocation_daily. Returns the rows deleted (AGX-3.3, #4539).';

-- Samples are debugging aids: gone after p_max_age whatever the tier (they also cascade with
-- their invocation).
CREATE OR REPLACE FUNCTION purge_agent_invocation_samples(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_max_age INTERVAL DEFAULT INTERVAL '7 days',
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
BEGIN
    DELETE FROM apiome.agent_invocation_samples
    WHERE invocation_id IN (
        SELECT invocation_id FROM apiome.agent_invocation_samples
        WHERE captured_at < p_now - LEAST(p_max_age, INTERVAL '7 days')
        LIMIT GREATEST(p_batch, 1)
    );
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_agent_invocation_samples(TIMESTAMPTZ, INTERVAL, INTEGER) IS
    'Delete up to p_batch body samples older than p_max_age (never more than 7 days). Returns the '
    'rows deleted (AGX-3.3, #4539).';

CREATE OR REPLACE FUNCTION purge_agent_invocation_rollups(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
BEGIN
    DELETE FROM apiome.agent_invocation_daily
    WHERE (tenant_id, day, key_id, toolset_id, tool_name, target) IN (
        SELECT d.tenant_id, d.day, d.key_id, d.toolset_id, d.tool_name, d.target
        FROM apiome.agent_usage_retention(p_now) r
        JOIN apiome.agent_invocation_daily d
          ON d.tenant_id = r.tenant_id AND d.day < r.rollup_cutoff
        LIMIT GREATEST(p_batch, 1)
    );
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_agent_invocation_rollups(TIMESTAMPTZ, INTEGER) IS
    'Delete up to p_batch agent_invocation_daily rows older than their tenant''s tier rollup '
    'retention. Returns the rows deleted (AGX-3.3, #4539).';

-- ---------------------------------------------------------------------------------------------------
-- Rule 7: seed the tier retention (fill-if-absent, as V195: an operator's value is never clobbered).
-- ---------------------------------------------------------------------------------------------------
UPDATE licenses
SET    seats = jsonb_build_object(
                 'agent_invocation_retention_days',   7,
                 'agent_usage_rollup_retention_days', 90
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'free';

UPDATE licenses
SET    seats = jsonb_build_object(
                 'agent_invocation_retention_days',   30,
                 'agent_usage_rollup_retention_days', 395
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'paid';

UPDATE licenses
SET    seats = jsonb_build_object(
                 'agent_invocation_retention_days',   90,
                 'agent_usage_rollup_retention_days', 730
               ) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'sponsor';

COMMENT ON COLUMN licenses.seats IS
  'Capacity limits JSON. Canonical keys: max_tenants (int), max_users_per_tenant (int), '
  'max_projects (int), max_versions (int), max_ai_requests (int), mock_rps (int), '
  'mock_requests_per_month (int), agent_invocation_retention_days (int), agent_usage_rollup_retention_days (int). For the quota '
  'keys (projects/versions/ai) a negative value means unlimited and a missing key falls back to '
  'the Free-tier default (1 project / 3 versions / 0 AI requests). For the agent usage retention '
  'keys (AGX-3.3) a negative value keeps rows forever and a missing key falls back to Free '
  '(7 days raw / 90 days rollups).';
