-- MCP usage sweep: batched retention that keeps up, incremental rollups, audit retention
-- (DBP-1.23, #7206).
--
-- The apiome-mcp usage sweep (`apiome_mcp.agent_usage_sweep`, AGX-3.3 / V271) ran every step in one
-- transaction and deleted one batch per table per hourly tick: at most 240,000 raw invocation rows
-- a day, against a top-tier key that may make 1,000,000 calls a day. Each tick also found its start
-- day with an anti-join over every retained raw row and re-sorted all of the open day's rows. This
-- migration gives the sweep statements whose cost follows the work to do, not the table size:
--
--   * Indexes for the time-ordered purges: upstream_credential_uses (used_at), mcp_access_audit
--     (at) and mcp_capability_denials (at). Each purge reads its oldest rows from one index range,
--     which is empty when nothing is due.
--   * agent_invocations (invoked_day, invoked_at) replaces (invoked_day): the same day lookups, plus
--     "which groups had a call since T" for the incremental rollup.
--   * agent_invocation_open_days — the days a tick rolls up. The start day is the day after the
--     newest finalized day, reached back by a loose scan of the distinct raw days (one index
--     descent per retained day, never one per row) to any raw day that is not finalized.
--   * rollup_agent_invocations gains p_since: only groups with a call at or after p_since are
--     recomputed (each from all of its rows that day, so percentiles stay exact).
--     rollup_agent_invocation_day rolls up one day with p_since = the day's previous rollup minus
--     the grace period, and finalizes it when due. The grace period already must exceed the longest
--     call, so a row written after the previous rollup started at or after that instant: a group
--     with no such call has had no new rows, and its stored values are still complete.
--     rollup_agent_invocation_days keeps its signature and loops over the two in one transaction;
--     the sweep calls them one day per transaction instead.
--   * purge_agent_invocations and purge_agent_invocation_rollups find their tenants with a loose
--     scan of the tenants that have rows (not every tenant), and read each tenant's oldest rows
--     below its cutoff from (tenant_id, …) indexes. The rules are unchanged: raw rows go only past the
--     tier retention and only on finalized days.
--   * purge_upstream_credential_uses is batched and takes p_now; purge_mcp_access_audit and
--     purge_mcp_capability_denials are new (those tables had no retention).
--
-- The sweep now commits after every rollup day and every purge batch, and repeats each purge until
-- it deletes less than a batch or its time budget runs out (apiome-mcp settings).
--
-- Partitioning was evaluated and not adopted. agent_invocations is retained per tenant tier (7, 30
-- or 90 days, or forever), so dropping a day or month partition would only remove days past the
-- longest retention of any tenant, and the per-tenant deletes would still be needed; its primary key
-- would also have to include the partition key, which agent_invocation_samples' foreign key to
-- agent_invocations (id) does not allow. upstream_credential_uses has one global retention, but
-- writes at most one row per upstream call, and the batched delete through (used_at) removes far
-- more rows a minute than arrive in a day (see apiome-mcp/docs/AGENT_INVOCATIONS.md), without
-- partitions to create ahead of time.
--
-- Large databases: the index builds block writes to their tables while they run; to avoid that,
-- create them by hand with CREATE INDEX CONCURRENTLY (same names and definitions) before upgrading —
-- every CREATE INDEX below is IF NOT EXISTS. Drop idx_agent_invocations_day only after
-- idx_agent_invocations_day_time exists.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.purge_mcp_capability_denials(INTEGER, INTEGER, TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.purge_mcp_access_audit(INTEGER, INTEGER, TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.purge_upstream_credential_uses(INTEGER, INTEGER, TIMESTAMPTZ);
--   (and re-create V268's purge_upstream_credential_uses(INTEGER))
--   DROP FUNCTION IF EXISTS apiome.rollup_agent_invocation_day(DATE, TIMESTAMPTZ, INTERVAL);
--   DROP FUNCTION IF EXISTS apiome.agent_invocation_open_days(TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.rollup_agent_invocations(DATE, TIMESTAMPTZ, TIMESTAMPTZ);
--   (and re-create V271's rollup_agent_invocations(DATE, TIMESTAMPTZ), rollup_agent_invocation_days,
--   agent_usage_retention, purge_agent_invocations and purge_agent_invocation_rollups)
--   DROP FUNCTION IF EXISTS apiome.agent_invocation_raw_cutoff(JSONB, TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.agent_usage_rollup_cutoff(JSONB, TIMESTAMPTZ);
--   DROP FUNCTION IF EXISTS apiome.tenant_license_seats(UUID);
--   CREATE INDEX IF NOT EXISTS idx_agent_invocations_day ON apiome.agent_invocations (invoked_day);
--   DROP INDEX IF EXISTS apiome.idx_agent_invocations_day_time;
--   DROP INDEX IF EXISTS apiome.idx_upstream_credential_uses_used_at;
--   DROP INDEX IF EXISTS apiome.idx_mcp_access_audit_at;
--   DROP INDEX IF EXISTS apiome.idx_mcp_capability_denials_at;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Indexes.
-- ---------------------------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_upstream_credential_uses_used_at
    ON upstream_credential_uses (used_at);

CREATE INDEX IF NOT EXISTS idx_mcp_access_audit_at
    ON mcp_access_audit (at);

CREATE INDEX IF NOT EXISTS idx_mcp_capability_denials_at
    ON mcp_capability_denials (at);

CREATE INDEX IF NOT EXISTS idx_agent_invocations_day_time
    ON agent_invocations (invoked_day, invoked_at);

-- Covered by idx_agent_invocations_day_time (same leading column).
DROP INDEX IF EXISTS idx_agent_invocations_day;

-- ---------------------------------------------------------------------------------------------------
-- Per-tier retention, one tenant at a time.
-- ---------------------------------------------------------------------------------------------------

-- A tenant's licenses.seats (NULL when it has no license).
CREATE OR REPLACE FUNCTION tenant_license_seats(p_tenant_id UUID)
RETURNS JSONB AS $$
    SELECT l.seats
    FROM apiome.tenant_licenses tl
    JOIN apiome.licenses l ON l.id = tl.license_id
    WHERE tl.tenant_id = p_tenant_id;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION tenant_license_seats(UUID) IS
    'The licenses.seats JSON of a tenant''s license, or NULL when it has none (DBP-1.23, #7206).';

-- Raw agent_invocations older than this may go. NULL = keep forever (a negative value). Free (7 days)
-- when the key is missing or not a number; at least 1 day.
CREATE OR REPLACE FUNCTION agent_invocation_raw_cutoff(p_seats JSONB, p_now TIMESTAMPTZ)
RETURNS TIMESTAMPTZ AS $$
    SELECT CASE WHEN d < 0 THEN NULL ELSE p_now - GREATEST(d, 1) * INTERVAL '1 day' END
    FROM (
        SELECT CASE WHEN jsonb_typeof(p_seats -> 'agent_invocation_retention_days') = 'number'
                    THEN (p_seats ->> 'agent_invocation_retention_days')::numeric::integer
                    ELSE 7 END AS d
    ) s;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION agent_invocation_raw_cutoff(JSONB, TIMESTAMPTZ) IS
    'Raw agent_invocations retention cutoff from licenses.seats.agent_invocation_retention_days '
    '(Free 7 days when unset; at least 1; NULL = keep forever). DBP-1.23 (#7206).';

-- agent_invocation_daily days before this may go. NULL = keep forever. Free (90 days) when unset.
CREATE OR REPLACE FUNCTION agent_usage_rollup_cutoff(p_seats JSONB, p_now TIMESTAMPTZ)
RETURNS DATE AS $$
    SELECT CASE WHEN d < 0 THEN NULL ELSE (p_now AT TIME ZONE 'UTC')::date - GREATEST(d, 1) END
    FROM (
        SELECT CASE WHEN jsonb_typeof(p_seats -> 'agent_usage_rollup_retention_days') = 'number'
                    THEN (p_seats ->> 'agent_usage_rollup_retention_days')::numeric::integer
                    ELSE 90 END AS d
    ) s;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION agent_usage_rollup_cutoff(JSONB, TIMESTAMPTZ) IS
    'agent_invocation_daily retention cutoff from licenses.seats.agent_usage_rollup_retention_days '
    '(Free 90 days when unset; at least 1; NULL = keep forever). DBP-1.23 (#7206).';

-- Same result as V271; the two cutoffs now come from the helpers above.
CREATE OR REPLACE FUNCTION agent_usage_retention(p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)
RETURNS TABLE (tenant_id UUID, raw_cutoff TIMESTAMPTZ, rollup_cutoff DATE) AS $$
    SELECT t.id,
           apiome.agent_invocation_raw_cutoff(l.seats, p_now),
           apiome.agent_usage_rollup_cutoff(l.seats, p_now)
    FROM apiome.tenants t
    LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
    LEFT JOIN apiome.licenses l ON l.id = tl.license_id;
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------------------------------------
-- Rollups.
-- ---------------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS rollup_agent_invocations(DATE, TIMESTAMPTZ);

-- One UTC day. p_since NULL: recompute every group (as V271). Otherwise only the groups with a call
-- at or after p_since; each of those is recomputed from all of its rows that day. A no-op on a
-- finalized day. Returns the number of groups written.
CREATE OR REPLACE FUNCTION rollup_agent_invocations(
    p_day DATE,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_since TIMESTAMPTZ DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    v_groups INTEGER;
    v_start TIMESTAMPTZ := p_day::timestamp AT TIME ZONE 'UTC';
    v_end TIMESTAMPTZ := (p_day + 1)::timestamp AT TIME ZONE 'UTC';
BEGIN
    IF EXISTS (
        SELECT 1 FROM apiome.agent_invocation_rollup_days
        WHERE day = p_day AND finalized_at IS NOT NULL
    ) THEN
        RETURN 0;
    END IF;

    -- EXECUTE: planned for this day's sizes on every call (a cached generic plan would serve the
    -- full recompute and the few-groups case with the same join).
    EXECUTE $sql$
    WITH active AS MATERIALIZED (
        -- The groups to recompute. With p_since, from the (invoked_day, invoked_at) index range.
        SELECT DISTINCT a.tenant_id, a.key_id, a.toolset_id, a.tool_name, a.target
        FROM apiome.agent_invocations a
        WHERE a.invoked_day = $1
          AND a.invoked_at >= $3
    )
    INSERT INTO apiome.agent_invocation_daily AS d (
        tenant_id, day, key_id, toolset_id, tool_name, target,
        calls, success_calls, upstream_errors, validation_failures, quota_rejections,
        internal_errors, latency_p50_ms, latency_p95_ms, latency_p99_ms, latency_max_ms,
        latency_sum_ms, request_bytes, response_bytes, computed_at
    )
    SELECT i.tenant_id, $1, i.key_id, i.toolset_id, i.tool_name, i.target,
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
           $2
    FROM active g
    JOIN apiome.agent_invocations i
      ON i.key_id = g.key_id
     AND i.tenant_id = g.tenant_id
     AND i.toolset_id = g.toolset_id
     AND i.tool_name = g.tool_name
     AND i.target = g.target
     AND i.invoked_day = $1
     -- The same UTC day as a range on invoked_at, so (key_id, invoked_at) can serve a few keys.
     AND i.invoked_at >= $4
     AND i.invoked_at < $5
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
        computed_at = EXCLUDED.computed_at
    $sql$ USING p_day, p_now, COALESCE(p_since, v_start), v_start, v_end;
    GET DIAGNOSTICS v_groups = ROW_COUNT;

    INSERT INTO apiome.agent_invocation_rollup_days (day, rolled_up_at)
    VALUES (p_day, p_now)
    ON CONFLICT (day) DO UPDATE SET rolled_up_at = EXCLUDED.rolled_up_at;

    RETURN v_groups;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rollup_agent_invocations(DATE, TIMESTAMPTZ, TIMESTAMPTZ) IS
    'Recompute agent_invocation_daily for one UTC day from agent_invocations (idempotent upsert): '
    'every group, or with p_since only the groups with a call at or after p_since. No-op on a '
    'finalized day. Returns the number of groups written (AGX-3.3 #4539, DBP-1.23 #7206).';

-- The UTC days a sweep tick rolls up, oldest first: from the day after the newest finalized day (or,
-- reaching back, the oldest raw day that is not finalized) through today. Empty when there is
-- nothing to roll up.
CREATE OR REPLACE FUNCTION agent_invocation_open_days(p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)
RETURNS SETOF DATE AS $$
DECLARE
    v_today DATE := (p_now AT TIME ZONE 'UTC')::date;
    v_after_final DATE;
    v_from DATE;
BEGIN
    -- Newest finalized day: a backward walk of the primary key past the few open days.
    SELECT r.day + 1 INTO v_after_final
    FROM apiome.agent_invocation_rollup_days r
    WHERE r.finalized_at IS NOT NULL
    ORDER BY r.day DESC
    LIMIT 1;

    -- Loose scan of the distinct raw days before v_after_final (one index descent each), stopping at
    -- the first that is not finalized (e.g. the very first sweep, or a call that landed late).
    WITH RECURSIVE raw_days(day) AS (
        (SELECT a.invoked_day FROM apiome.agent_invocations a ORDER BY a.invoked_day LIMIT 1)
        UNION ALL
        SELECT (SELECT a.invoked_day FROM apiome.agent_invocations a
                WHERE a.invoked_day > rd.day ORDER BY a.invoked_day LIMIT 1)
        FROM raw_days rd
        WHERE rd.day IS NOT NULL
          AND (v_after_final IS NULL OR rd.day < v_after_final)
          AND EXISTS (
              SELECT 1 FROM apiome.agent_invocation_rollup_days r
              WHERE r.day = rd.day AND r.finalized_at IS NOT NULL
          )
    )
    SELECT LEAST(v_after_final, min(rd.day)) INTO v_from
    FROM raw_days rd
    WHERE rd.day IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM apiome.agent_invocation_rollup_days r
          WHERE r.day = rd.day AND r.finalized_at IS NOT NULL
      );

    IF v_from IS NULL THEN
        v_from := v_after_final;
    END IF;
    IF v_from IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY SELECT g::date FROM generate_series(v_from, v_today, INTERVAL '1 day') g;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION agent_invocation_open_days(TIMESTAMPTZ) IS
    'UTC days a usage sweep tick rolls up, oldest first: from the day after the newest finalized day '
    '(or the oldest raw day not finalized) through today. DBP-1.23 (#7206).';

-- One sweep step: roll up p_day incrementally and finalize it once it ended more than p_grace ago
-- (p_grace must exceed the longest call). Returns the number of groups written.
CREATE OR REPLACE FUNCTION rollup_agent_invocation_day(
    p_day DATE,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_grace INTERVAL DEFAULT INTERVAL '6 hours'
)
RETURNS INTEGER AS $$
DECLARE
    v_since TIMESTAMPTZ;
    v_final BOOLEAN;
    v_groups INTEGER;
BEGIN
    SELECT r.rolled_up_at - p_grace, r.finalized_at IS NOT NULL INTO v_since, v_final
    FROM apiome.agent_invocation_rollup_days r
    WHERE r.day = p_day;
    IF v_final THEN
        RETURN 0;
    END IF;

    -- v_since is NULL (full recompute) the first time the day is rolled up.
    v_groups := apiome.rollup_agent_invocations(p_day, p_now, v_since);

    -- The day ended at (p_day + 1) 00:00 UTC.
    IF ((p_day + 1)::timestamp AT TIME ZONE 'UTC') + p_grace <= p_now THEN
        UPDATE apiome.agent_invocation_rollup_days
        SET finalized_at = p_now
        WHERE day = p_day AND finalized_at IS NULL;
    END IF;
    RETURN v_groups;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rollup_agent_invocation_day(DATE, TIMESTAMPTZ, INTERVAL) IS
    'Roll up one UTC day, recomputing only the groups with a call since the day''s previous rollup '
    'minus p_grace, and finalize it once it ended more than p_grace ago. Returns the groups written '
    '(DBP-1.23, #7206).';

-- Same signature and result as V271, in one transaction; the apiome-mcp sweep calls
-- agent_invocation_open_days and rollup_agent_invocation_day one day per transaction instead.
CREATE OR REPLACE FUNCTION rollup_agent_invocation_days(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_grace INTERVAL DEFAULT INTERVAL '6 hours'
)
RETURNS INTEGER AS $$
DECLARE
    v_day DATE;
    v_days INTEGER := 0;
BEGIN
    FOR v_day IN SELECT d FROM apiome.agent_invocation_open_days(p_now) d LOOP
        PERFORM apiome.rollup_agent_invocation_day(v_day, p_now, p_grace);
        v_days := v_days + 1;
    END LOOP;
    RETURN v_days;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------------
-- Purges.
-- ---------------------------------------------------------------------------------------------------

-- Raw rows past the tenant's retention whose day is final (so they are already in the rollup),
-- oldest first per tenant.
CREATE OR REPLACE FUNCTION purge_agent_invocations(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_final_end TIMESTAMPTZ;
    v_purged INTEGER;
BEGIN
    -- Only finalized days may be pruned: nothing at or after the end of the newest one.
    SELECT (r.day + 1)::timestamp AT TIME ZONE 'UTC' INTO v_final_end
    FROM apiome.agent_invocation_rollup_days r
    WHERE r.finalized_at IS NOT NULL
    ORDER BY r.day DESC
    LIMIT 1;
    IF v_final_end IS NULL THEN
        RETURN 0;
    END IF;

    WITH RECURSIVE tenants_with_rows(tenant_id) AS (
        -- Loose scan of the tenants that have raw rows (idx_agent_invocations_tenant_time).
        (SELECT a.tenant_id FROM apiome.agent_invocations a ORDER BY a.tenant_id LIMIT 1)
        UNION ALL
        SELECT (SELECT a.tenant_id FROM apiome.agent_invocations a
                WHERE a.tenant_id > t.tenant_id ORDER BY a.tenant_id LIMIT 1)
        FROM tenants_with_rows t
        WHERE t.tenant_id IS NOT NULL
    ),
    cutoffs AS MATERIALIZED (
        -- NULL raw cutoff = keep forever (LEAST alone would ignore the NULL).
        SELECT r.tenant_id,
               CASE WHEN r.raw_cutoff IS NOT NULL THEN LEAST(r.raw_cutoff, v_final_end) END AS cutoff
        FROM (
            SELECT t.tenant_id,
                   apiome.agent_invocation_raw_cutoff(apiome.tenant_license_seats(t.tenant_id), p_now) AS raw_cutoff
            FROM tenants_with_rows t
            WHERE t.tenant_id IS NOT NULL
        ) r
    ),
    doomed AS (
        SELECT x.id
        FROM cutoffs c
        CROSS JOIN LATERAL (
            SELECT i.id
            FROM apiome.agent_invocations i
            WHERE i.tenant_id = c.tenant_id
              AND i.invoked_at < c.cutoff
              AND EXISTS (
                  SELECT 1 FROM apiome.agent_invocation_rollup_days d
                  WHERE d.day = i.invoked_day AND d.finalized_at IS NOT NULL
              )
            ORDER BY i.invoked_at
            LIMIT GREATEST(p_batch, 1)
        ) x
        WHERE c.cutoff IS NOT NULL
        LIMIT GREATEST(p_batch, 1)
    )
    -- = ANY(ARRAY(...)): primary-key probes, never a hash join over the whole table.
    DELETE FROM apiome.agent_invocations
    WHERE id = ANY (ARRAY(SELECT id FROM doomed));
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_agent_invocations(TIMESTAMPTZ, INTEGER) IS
    'Delete up to p_batch raw agent_invocations past their tenant''s tier retention whose UTC day '
    'is finalized, oldest first per tenant. Never touches agent_invocation_daily. Returns the rows '
    'deleted (AGX-3.3 #4539, DBP-1.23 #7206).';

CREATE OR REPLACE FUNCTION purge_agent_invocation_rollups(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
BEGIN
    WITH RECURSIVE tenants_with_rows(tenant_id) AS (
        -- Loose scan of the tenants that have rollups (the primary key leads with tenant_id).
        (SELECT d.tenant_id FROM apiome.agent_invocation_daily d ORDER BY d.tenant_id LIMIT 1)
        UNION ALL
        SELECT (SELECT d.tenant_id FROM apiome.agent_invocation_daily d
                WHERE d.tenant_id > t.tenant_id ORDER BY d.tenant_id LIMIT 1)
        FROM tenants_with_rows t
        WHERE t.tenant_id IS NOT NULL
    ),
    cutoffs AS MATERIALIZED (
        SELECT t.tenant_id,
               apiome.agent_usage_rollup_cutoff(apiome.tenant_license_seats(t.tenant_id), p_now) AS cutoff
        FROM tenants_with_rows t
        WHERE t.tenant_id IS NOT NULL
    ),
    doomed AS (
        SELECT x.row_id
        FROM cutoffs c
        CROSS JOIN LATERAL (
            SELECT d.ctid AS row_id
            FROM apiome.agent_invocation_daily d
            WHERE d.tenant_id = c.tenant_id AND d.day < c.cutoff
            ORDER BY d.day
            LIMIT GREATEST(p_batch, 1)
        ) x
        WHERE c.cutoff IS NOT NULL
        LIMIT GREATEST(p_batch, 1)
    )
    -- A TID scan of the chosen rows (ctid is stable within the statement; the sweep lock keeps the
    -- rollup from rewriting them concurrently).
    DELETE FROM apiome.agent_invocation_daily
    WHERE ctid = ANY (ARRAY(SELECT row_id FROM doomed));
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_agent_invocation_rollups(TIMESTAMPTZ, INTEGER) IS
    'Delete up to p_batch agent_invocation_daily rows older than their tenant''s tier rollup '
    'retention, oldest first per tenant. Returns the rows deleted (AGX-3.3 #4539, DBP-1.23 #7206).';

-- AGX-2.2 credential-use ledger: batched, oldest first, from idx_upstream_credential_uses_used_at.
DROP FUNCTION IF EXISTS purge_upstream_credential_uses(INTEGER);

CREATE OR REPLACE FUNCTION purge_upstream_credential_uses(
    p_retention_days INTEGER DEFAULT 90,
    p_batch INTEGER DEFAULT 10000,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
    v_cutoff TIMESTAMPTZ := p_now - (GREATEST(p_retention_days, 0) * INTERVAL '1 day');
BEGIN
    DELETE FROM apiome.upstream_credential_uses
    WHERE id = ANY (ARRAY(
        SELECT u.id FROM apiome.upstream_credential_uses u
        WHERE u.used_at < v_cutoff
        ORDER BY u.used_at
        LIMIT GREATEST(p_batch, 1)
    ));
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_upstream_credential_uses(INTEGER, INTEGER, TIMESTAMPTZ) IS
    'Hard-delete up to p_batch upstream credential use records older than p_retention_days, oldest '
    'first. Returns the rows deleted (AGX-2.2 #4534, DBP-1.23 #7206).';

-- MCP private-access audit (#3013): batched, oldest first, from idx_mcp_access_audit_at.
CREATE OR REPLACE FUNCTION purge_mcp_access_audit(
    p_retention_days INTEGER DEFAULT 365,
    p_batch INTEGER DEFAULT 10000,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
    v_cutoff TIMESTAMPTZ := p_now - (GREATEST(p_retention_days, 1) * INTERVAL '1 day');
BEGIN
    DELETE FROM apiome.mcp_access_audit
    WHERE id = ANY (ARRAY(
        SELECT a.id FROM apiome.mcp_access_audit a
        WHERE a.at < v_cutoff
        ORDER BY a.at
        LIMIT GREATEST(p_batch, 1)
    ));
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_mcp_access_audit(INTEGER, INTEGER, TIMESTAMPTZ) IS
    'Delete up to p_batch mcp_access_audit rows older than p_retention_days (at least 1), oldest '
    'first. Returns the rows deleted (DBP-1.23, #7206).';

-- MCP capability denials (#4773): batched, oldest first, from idx_mcp_capability_denials_at.
CREATE OR REPLACE FUNCTION purge_mcp_capability_denials(
    p_retention_days INTEGER DEFAULT 90,
    p_batch INTEGER DEFAULT 10000,
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
    v_cutoff TIMESTAMPTZ := p_now - (GREATEST(p_retention_days, 1) * INTERVAL '1 day');
BEGIN
    DELETE FROM apiome.mcp_capability_denials
    WHERE id = ANY (ARRAY(
        SELECT c.id FROM apiome.mcp_capability_denials c
        WHERE c.at < v_cutoff
        ORDER BY c.at
        LIMIT GREATEST(p_batch, 1)
    ));
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_mcp_capability_denials(INTEGER, INTEGER, TIMESTAMPTZ) IS
    'Delete up to p_batch mcp_capability_denials rows older than p_retention_days (at least 1), '
    'oldest first. Returns the rows deleted (DBP-1.23, #7206).';

COMMENT ON TABLE mcp_capability_denials IS
    'Append-only audit of authenticated MCP tools/call capability denials (MTG-2.4 / #4773). '
    'Never store tool arguments, Authorization headers, or secrets. Purged after '
    'APIOME_MCP_CAPABILITY_DENIAL_RETENTION_DAYS (default 90) by the apiome-mcp usage sweep '
    '(purge_mcp_capability_denials, DBP-1.23 #7206).';

COMMENT ON TABLE mcp_access_audit IS
    'Append-only audit of MCP tool reads that expose private published revisions (#3013). Purged '
    'after APIOME_MCP_ACCESS_AUDIT_RETENTION_DAYS (default 365) by the apiome-mcp usage sweep '
    '(purge_mcp_access_audit, DBP-1.23 #7206).';
