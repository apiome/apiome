-- Usage export, retention and erasure controls — RDG-5.4 (#5789).
--
-- The usage index (V290) keeps counters about named consumers (V292). When a consumer is a
-- person's client those counters are personal data, so a workspace must be able to say what is
-- kept, for how long, and delete it on request. This migration adds the two database halves of
-- that; the REST surface (`app.usage_controls_routes`) is the other half.
--
--   usage_retention_setting     a workspace's own, shorter, usage retention
--   usage_retention()           now applies that setting under the tier caps
--   usage_buckets_add()         element-wise sum of two latency histograms
--   usage_hourly_open_day()     lets an erasure re-attribute counters on a final day
--   erase_usage_consumer()      deletes a consumer's bindings and re-attributes its counters
--
-- Rules:
--
--   1. **Retention can only go down.** `usage_retention_setting` holds a workspace's
--      `hourly_retention_days` / `rollup_retention_days`; NULL means "the tier's value". The REST
--      route refuses a value above the tier cap (`licenses.seats.usage_hourly_retention_days` /
--      `usage_rollup_retention_days`), and `usage_retention()` takes the smaller of the two anyway,
--      so a setting written before a downgrade can never keep rows longer than the new tier allows.
--      A tier that keeps rows forever (a negative cap) accepts any positive setting.
--
--   2. **Erasure keeps counts, not identity.** `erase_usage_consumer(tenant, consumer)` runs in one
--      statement (so one transaction): every `usage_hourly` and `usage_daily` row attributed to one
--      of the consumer's bindings — live or deleted — is merged into the matching anonymous row
--      (`consumer_binding_id IS NULL`), the CDG-3.5 unattributed-client rows that carry one of its
--      hashes are deleted, its bindings are deleted outright (hashes included), and its
--      `runtime_last_seen_at` is cleared. Totals per day, operation, status, source, environment and
--      version are unchanged.
--
--   3. **Only erasure may touch a final day.** A final day takes no new counts (V290 rule 5). The
--      erasure merges rows *within* a final day without changing its totals, so the trigger allows
--      it while the transaction-local setting `apiome.usage_erasure` is `on` — which only
--      `erase_usage_consumer` sets, and resets before it returns.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.erase_usage_consumer(UUID, UUID);
--   DROP FUNCTION IF EXISTS apiome.usage_buckets_add(BIGINT[], BIGINT[]);
--   -- restore usage_hourly_open_day() and usage_retention() from V290;
--   DROP TABLE IF EXISTS apiome.usage_retention_setting;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Rule 1: a workspace's own retention.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_retention_setting (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    -- NULL = the tier's value.
    hourly_retention_days INTEGER
        CONSTRAINT usage_retention_setting_hourly_ck CHECK (hourly_retention_days >= 1),
    rollup_retention_days INTEGER
        CONSTRAINT usage_retention_setting_rollup_ck CHECK (rollup_retention_days >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL
);

COMMENT ON TABLE usage_retention_setting IS
    'RDG-5.4 (#5789): a workspace''s own usage retention, at most its tier caps. NULL keeps the '
    'tier value. usage_retention() applies the smaller of the setting and the cap.';

CREATE OR REPLACE FUNCTION usage_retention(p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)
RETURNS TABLE (tenant_id UUID, hourly_cutoff TIMESTAMPTZ, rollup_cutoff DATE) AS $$
    WITH tiers AS (
        SELECT t.id AS tenant_id,
               CASE WHEN jsonb_typeof(l.seats -> 'usage_hourly_retention_days') = 'number'
                    THEN (l.seats ->> 'usage_hourly_retention_days')::numeric::integer
                    ELSE 7 END AS hourly_days,
               CASE WHEN jsonb_typeof(l.seats -> 'usage_rollup_retention_days') = 'number'
                    THEN (l.seats ->> 'usage_rollup_retention_days')::numeric::integer
                    ELSE 90 END AS rollup_days
        FROM apiome.tenants t
        LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
        LEFT JOIN apiome.licenses l ON l.id = tl.license_id
    ),
    effective AS (
        SELECT tiers.tenant_id,
               CASE WHEN s.hourly_retention_days IS NULL THEN tiers.hourly_days
                    WHEN tiers.hourly_days < 0 THEN s.hourly_retention_days
                    ELSE LEAST(tiers.hourly_days, s.hourly_retention_days) END AS hourly_days,
               CASE WHEN s.rollup_retention_days IS NULL THEN tiers.rollup_days
                    WHEN tiers.rollup_days < 0 THEN s.rollup_retention_days
                    ELSE LEAST(tiers.rollup_days, s.rollup_retention_days) END AS rollup_days
        FROM tiers
        LEFT JOIN apiome.usage_retention_setting s ON s.tenant_id = tiers.tenant_id
    )
    SELECT tenant_id,
           CASE WHEN hourly_days < 0 THEN NULL
                ELSE p_now - GREATEST(hourly_days, 1) * INTERVAL '1 day' END,
           CASE WHEN rollup_days < 0 THEN NULL
                ELSE (p_now AT TIME ZONE 'UTC')::date - GREATEST(rollup_days, 1) END
    FROM effective;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION usage_retention(TIMESTAMPTZ) IS
    'Per-tenant usage retention: the smaller of the licenses.seats tier cap and the workspace''s '
    'usage_retention_setting (RDG-5.4). hourly_cutoff (usage_hourly rows starting before it may go) '
    'and rollup_cutoff (daily rows and ledger days before it may go). NULL = keep forever. '
    'RDG-1.1 (#5759).';

-- ---------------------------------------------------------------------------------------------------
-- Rule 2 helper: add two latency histograms bucket by bucket.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION usage_buckets_add(p_a BIGINT[], p_b BIGINT[])
RETURNS BIGINT[] AS $$
    SELECT array_agg(COALESCE(a, 0) + COALESCE(b, 0) ORDER BY i)::BIGINT[]
    FROM unnest(p_a, p_b) WITH ORDINALITY AS t(a, b, i);
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION usage_buckets_add(BIGINT[], BIGINT[]) IS
    'RDG-5.4 (#5789): element-wise sum of two usage latency histograms of the same length.';

-- ---------------------------------------------------------------------------------------------------
-- Rule 3: only an erasure may rewrite rows of a final day.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION usage_hourly_open_day()
RETURNS TRIGGER AS $$
BEGIN
    IF COALESCE(current_setting('apiome.usage_erasure', true), '') = 'on' THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        SELECT 1 FROM apiome.usage_rollup_days
        WHERE day = (NEW.hour AT TIME ZONE 'UTC')::date AND finalized_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'usage day % is finalized and takes no new counts',
            (NEW.hour AT TIME ZONE 'UTC')::date
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------------
-- Rule 2: erase a consumer's identity from the usage index.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION erase_usage_consumer(p_tenant UUID, p_consumer UUID)
RETURNS JSONB AS $$
DECLARE
    v_bindings UUID[];
    v_hourly INTEGER := 0;
    v_daily INTEGER := 0;
    v_calls BIGINT := 0;
    v_clients INTEGER := 0;
    v_deleted INTEGER := 0;
BEGIN
    -- Lock the bindings so a concurrent create or delete on this consumer waits for the erasure.
    SELECT array_agg(id) INTO v_bindings
    FROM (
        SELECT id FROM apiome.usage_consumer_binding
        WHERE tenant_id = p_tenant AND consumer_id = p_consumer
        FOR UPDATE
    ) locked;

    IF v_bindings IS NOT NULL THEN
        PERFORM set_config('apiome.usage_erasure', 'on', true);

        SELECT count(*) INTO v_hourly FROM apiome.usage_hourly
        WHERE tenant_id = p_tenant AND consumer_binding_id = ANY (v_bindings);
        SELECT count(*), COALESCE(sum(calls), 0) INTO v_daily, v_calls FROM apiome.usage_daily
        WHERE tenant_id = p_tenant AND consumer_binding_id = ANY (v_bindings);

        WITH moved AS (
            DELETE FROM apiome.usage_hourly h
            WHERE h.tenant_id = p_tenant AND h.consumer_binding_id = ANY (v_bindings)
            RETURNING h.tenant_id, h.project_id, h.source_id, h.environment, h.hour,
                      h.version_record_id, h.operation_key, h.status_code, h.calls,
                      h.latency_buckets, h.latency_sum_ms, h.latency_max_ms, h.auth_present_calls,
                      h.auth_unknown_calls, h.versioned_calls, h.version_unknown_calls,
                      h.https_calls, h.request_bytes, h.response_bytes
        )
        INSERT INTO apiome.usage_hourly AS t (
            tenant_id, project_id, source_id, environment, hour, version_record_id, operation_key,
            status_code, consumer_binding_id, calls, latency_buckets, latency_sum_ms, latency_max_ms,
            auth_present_calls, auth_unknown_calls, versioned_calls, version_unknown_calls,
            https_calls, request_bytes, response_bytes, updated_at
        )
        SELECT m.tenant_id, m.project_id, m.source_id, m.environment, m.hour, m.version_record_id,
               m.operation_key, m.status_code, NULL, sum(m.calls),
               ARRAY[sum(m.latency_buckets[1]), sum(m.latency_buckets[2]), sum(m.latency_buckets[3]),
                     sum(m.latency_buckets[4]), sum(m.latency_buckets[5]), sum(m.latency_buckets[6]),
                     sum(m.latency_buckets[7]), sum(m.latency_buckets[8]), sum(m.latency_buckets[9]),
                     sum(m.latency_buckets[10]), sum(m.latency_buckets[11]),
                     sum(m.latency_buckets[12])]::BIGINT[],
               sum(m.latency_sum_ms), max(m.latency_max_ms), sum(m.auth_present_calls),
               sum(m.auth_unknown_calls), sum(m.versioned_calls), sum(m.version_unknown_calls),
               sum(m.https_calls), sum(m.request_bytes), sum(m.response_bytes), CURRENT_TIMESTAMP
        FROM moved m
        GROUP BY m.tenant_id, m.project_id, m.source_id, m.environment, m.hour, m.version_record_id,
                 m.operation_key, m.status_code
        ON CONFLICT ON CONSTRAINT usage_hourly_grain_uq DO UPDATE SET
            calls = t.calls + EXCLUDED.calls,
            latency_buckets = apiome.usage_buckets_add(t.latency_buckets, EXCLUDED.latency_buckets),
            latency_sum_ms = t.latency_sum_ms + EXCLUDED.latency_sum_ms,
            latency_max_ms = GREATEST(t.latency_max_ms, EXCLUDED.latency_max_ms),
            auth_present_calls = t.auth_present_calls + EXCLUDED.auth_present_calls,
            auth_unknown_calls = t.auth_unknown_calls + EXCLUDED.auth_unknown_calls,
            versioned_calls = t.versioned_calls + EXCLUDED.versioned_calls,
            version_unknown_calls = t.version_unknown_calls + EXCLUDED.version_unknown_calls,
            https_calls = t.https_calls + EXCLUDED.https_calls,
            request_bytes = t.request_bytes + EXCLUDED.request_bytes,
            response_bytes = t.response_bytes + EXCLUDED.response_bytes,
            updated_at = EXCLUDED.updated_at;

        WITH moved AS (
            DELETE FROM apiome.usage_daily d
            WHERE d.tenant_id = p_tenant AND d.consumer_binding_id = ANY (v_bindings)
            RETURNING d.tenant_id, d.project_id, d.source_id, d.environment, d.day,
                      d.version_record_id, d.operation_key, d.status_code, d.calls,
                      d.latency_buckets, d.latency_sum_ms, d.latency_max_ms, d.auth_present_calls,
                      d.auth_unknown_calls, d.versioned_calls, d.version_unknown_calls,
                      d.https_calls, d.request_bytes, d.response_bytes
        )
        INSERT INTO apiome.usage_daily AS t (
            tenant_id, project_id, source_id, environment, day, version_record_id, operation_key,
            status_code, consumer_binding_id, calls, latency_buckets, latency_sum_ms, latency_max_ms,
            auth_present_calls, auth_unknown_calls, versioned_calls, version_unknown_calls,
            https_calls, request_bytes, response_bytes, computed_at
        )
        SELECT m.tenant_id, m.project_id, m.source_id, m.environment, m.day, m.version_record_id,
               m.operation_key, m.status_code, NULL, sum(m.calls),
               ARRAY[sum(m.latency_buckets[1]), sum(m.latency_buckets[2]), sum(m.latency_buckets[3]),
                     sum(m.latency_buckets[4]), sum(m.latency_buckets[5]), sum(m.latency_buckets[6]),
                     sum(m.latency_buckets[7]), sum(m.latency_buckets[8]), sum(m.latency_buckets[9]),
                     sum(m.latency_buckets[10]), sum(m.latency_buckets[11]),
                     sum(m.latency_buckets[12])]::BIGINT[],
               sum(m.latency_sum_ms), max(m.latency_max_ms), sum(m.auth_present_calls),
               sum(m.auth_unknown_calls), sum(m.versioned_calls), sum(m.version_unknown_calls),
               sum(m.https_calls), sum(m.request_bytes), sum(m.response_bytes), CURRENT_TIMESTAMP
        FROM moved m
        GROUP BY m.tenant_id, m.project_id, m.source_id, m.environment, m.day, m.version_record_id,
                 m.operation_key, m.status_code
        ON CONFLICT ON CONSTRAINT usage_daily_grain_uq DO UPDATE SET
            calls = t.calls + EXCLUDED.calls,
            latency_buckets = apiome.usage_buckets_add(t.latency_buckets, EXCLUDED.latency_buckets),
            latency_sum_ms = t.latency_sum_ms + EXCLUDED.latency_sum_ms,
            latency_max_ms = GREATEST(t.latency_max_ms, EXCLUDED.latency_max_ms),
            auth_present_calls = t.auth_present_calls + EXCLUDED.auth_present_calls,
            auth_unknown_calls = t.auth_unknown_calls + EXCLUDED.auth_unknown_calls,
            versioned_calls = t.versioned_calls + EXCLUDED.versioned_calls,
            version_unknown_calls = t.version_unknown_calls + EXCLUDED.version_unknown_calls,
            https_calls = t.https_calls + EXCLUDED.https_calls,
            request_bytes = t.request_bytes + EXCLUDED.request_bytes,
            response_bytes = t.response_bytes + EXCLUDED.response_bytes,
            computed_at = EXCLUDED.computed_at;

        -- The suggestion rows that still carry one of the consumer's hashes, or the product token
        -- of one of its plain user-agent globs (`billing-service/*` -> `billing-service`).
        DELETE FROM apiome.usage_unattributed_client_daily u
        USING apiome.usage_consumer_binding b
        WHERE b.id = ANY (v_bindings)
          AND u.tenant_id = p_tenant AND u.project_id = b.project_id
          AND (
              (b.kind <> 'user_agent' AND u.client_kind = b.kind AND u.client_key = b.value_hmac::text)
              OR (b.kind = 'user_agent' AND u.client_kind = 'user_agent'
                  AND u.client_key = lower(split_part(b.name, '/', 1)))
          );
        GET DIAGNOSTICS v_clients = ROW_COUNT;

        DELETE FROM apiome.usage_consumer_binding WHERE id = ANY (v_bindings);
        GET DIAGNOSTICS v_deleted = ROW_COUNT;

        PERFORM set_config('apiome.usage_erasure', 'off', true);
    END IF;

    UPDATE apiome.consumer SET runtime_last_seen_at = NULL
    WHERE id = p_consumer AND tenant_id = p_tenant;

    RETURN jsonb_build_object(
        'bindings', v_deleted,
        'hourly_rows', v_hourly,
        'daily_rows', v_daily,
        'calls', v_calls,
        'unattributed_rows', v_clients
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION erase_usage_consumer(UUID, UUID) IS
    'RDG-5.4 (#5789): erase a consumer from the usage index in one transaction — merge every '
    'usage_hourly / usage_daily row attributed to its bindings into the anonymous row of the same '
    'grain (totals unchanged), delete the unattributed-client rows carrying its hashes, delete its '
    'bindings and clear runtime_last_seen_at. Returns the counts as JSON.';
