-- Quotas & rate limits per agent key — AGX-3.2 (#4538).
--
-- An agent with no limits can retry in a tight loop and flood an upstream (and the tenant's bill)
-- within seconds. Every agent key therefore gets two limits, both set by the tenant's license tier:
--
--   agent_key_rps          sustained tools/call rate per key (token bucket, burst = one second)
--   agent_key_daily_calls  tools/call cap per key per UTC day
--
-- The apiome-mcp agent surface enforces them (`apiome_mcp.agent_quotas.AgentQuotaMiddleware`). The
-- apiome-rest key management API reports them, with today's usage, at
-- `GET /v1/tenants/{t}/agent-keys/{id}/usage`. This migration adds what both services read:
--
--   licenses.seats keys        per-tier `agent_key_rps` / `agent_key_daily_calls`
--   agent_key_quota(tenant)    the tenant's two caps, resolved from its license tier
--   agent_key_call_count(key, day)   calls a key made on a UTC day
--
-- Four rules shape it:
--
--   1. **Caps follow the license tier.** Free 2 rps / 1,000 calls a day, Paid 20 / 100,000,
--      Sponsor 100 / 1,000,000. The tier is read through `tenant_licenses` (V182), as the AGX-3.3
--      retention does, so changing a tenant's license changes its caps. A tenant with no license,
--      or a missing / non-numeric key, gets the Free values.
--   2. **Zero or negative means unlimited**, as for the mock data plane's `mock_rps` /
--      `mock_requests_per_month` (V154). `agent_key_quota` returns NULL for an unlimited cap.
--   3. **One count of calls made.** `agent_key_call_count` counts the key's AGX-3.3
--      `agent_invocations` rows on the day, leaving out `quota_rejected` refusals: a refused call
--      was never made. The same rows feed `agent_invocation_daily`, so the count always equals that
--      day's rollup `calls - quota_rejections` for the key, summed over its tools and targets.
--   4. **Seeds are fill-if-absent**, so a value an operator set by hand is kept.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.agent_key_call_count(UUID, DATE);
--   DROP FUNCTION IF EXISTS apiome.agent_key_quota(UUID);
--   UPDATE apiome.licenses SET seats = seats - 'agent_key_rps' - 'agent_key_daily_calls';

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Rules 1 and 4: per-tier caps, seeded fill-if-absent.
-- ---------------------------------------------------------------------------------------------------
UPDATE licenses
SET    seats = jsonb_build_object('agent_key_rps', 2, 'agent_key_daily_calls', 1000) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'free';

UPDATE licenses
SET    seats = jsonb_build_object('agent_key_rps', 20, 'agent_key_daily_calls', 100000) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'paid';

UPDATE licenses
SET    seats = jsonb_build_object('agent_key_rps', 100, 'agent_key_daily_calls', 1000000) || seats,
       updated_at = CURRENT_TIMESTAMP
WHERE  license_type = 'sponsor';

COMMENT ON COLUMN licenses.seats IS
  'Capacity limits JSON. Canonical keys: max_tenants (int), max_users_per_tenant (int), '
  'max_projects (int), max_versions (int), max_ai_requests (int), mock_rps (int), '
  'mock_requests_per_month (int), agent_invocation_retention_days (int), '
  'agent_usage_rollup_retention_days (int), agent_key_rps (number), agent_key_daily_calls (int). '
  'For the quota keys (projects/versions/ai) a negative value means unlimited and a missing key '
  'falls back to the Free-tier default (1 project / 3 versions / 0 AI requests). For the agent '
  'usage retention keys (AGX-3.3) a negative value keeps rows forever and a missing key falls back '
  'to Free (7 days raw / 90 days rollups). For the agent key limits (AGX-3.2) zero or a negative '
  'value means unlimited and a missing key falls back to Free (2 rps / 1000 calls per UTC day).';

-- ---------------------------------------------------------------------------------------------------
-- Rules 1 and 2: a tenant's caps.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION agent_key_quota(p_tenant_id UUID)
RETURNS TABLE (license_type VARCHAR, rps NUMERIC, daily_calls BIGINT) AS $$
    WITH tier AS (
        SELECT l.license_type,
               CASE WHEN jsonb_typeof(l.seats -> 'agent_key_rps') = 'number'
                    THEN (l.seats ->> 'agent_key_rps')::numeric
                    ELSE 2 END AS rps,
               CASE WHEN jsonb_typeof(l.seats -> 'agent_key_daily_calls') = 'number'
                    THEN trunc((l.seats ->> 'agent_key_daily_calls')::numeric)
                    ELSE 1000 END AS daily_calls
        FROM (SELECT p_tenant_id AS tenant_id) t
        LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.tenant_id
        LEFT JOIN apiome.licenses l ON l.id = tl.license_id
        LIMIT 1
    )
    SELECT license_type,
           CASE WHEN rps > 0 THEN rps END,
           CASE WHEN daily_calls > 0 THEN daily_calls::bigint END
    FROM tier;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION agent_key_quota(UUID) IS
    'The agent key caps of a tenant from its license tier (licenses.seats agent_key_rps / '
    'agent_key_daily_calls): always one row. license_type is NULL when the tenant has no license. '
    'rps / daily_calls are NULL when unlimited (a zero or negative seats value); a missing or '
    'non-numeric key gets the Free values (2 / 1000). AGX-3.2 (#4538).';

-- ---------------------------------------------------------------------------------------------------
-- Rule 3: calls a key made on one UTC day — the counter both services read.
-- ---------------------------------------------------------------------------------------------------
-- Ranges on invoked_at (not invoked_day) so idx_agent_invocations_key_time serves it.
CREATE OR REPLACE FUNCTION agent_key_call_count(p_key_id UUID, p_day DATE)
RETURNS BIGINT AS $$
    SELECT count(*)
    FROM apiome.agent_invocations i
    WHERE i.key_id = p_key_id
      AND i.invoked_at >= (p_day::timestamp AT TIME ZONE 'UTC')
      AND i.invoked_at < ((p_day + 1)::timestamp AT TIME ZONE 'UTC')
      AND i.outcome <> 'quota_rejected';
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION agent_key_call_count(UUID, DATE) IS
    'Agent tools/calls a key made on a UTC day: its agent_invocations rows that day, except '
    'quota_rejected refusals. Equals the day''s agent_invocation_daily calls - quota_rejections for '
    'the key (summed over tools and targets). AGX-3.2 (#4538).';
