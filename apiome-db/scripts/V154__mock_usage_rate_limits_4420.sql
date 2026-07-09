-- Mock runtime usage rollups and license-tier mock quotas (#4420, SIM-1.5).
--
-- Daily per-tenant/project/version counters feed the Control Panel usage sparkline (SIM-2.2)
-- and monthly quota enforcement on the apiome-mock data plane. License ``seats`` JSON gains
-- ``mock_rps`` and ``mock_requests_per_month`` keys (free tier defaults: 5 rps / 10k req/mo).

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_usage (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_slug VARCHAR(255) NOT NULL,
    version_label VARCHAR(255) NOT NULL,
    usage_date DATE NOT NULL,
    request_count BIGINT NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    PRIMARY KEY (tenant_id, project_slug, version_label, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_mock_usage_tenant_date
    ON mock_usage(tenant_id, usage_date DESC);

COMMENT ON TABLE mock_usage IS
  'Daily mock request rollups per tenant/project/version (#4420, SIM-1.5); source for usage stats and monthly quotas';
COMMENT ON COLUMN mock_usage.usage_date IS 'UTC calendar day the requests were served';
COMMENT ON COLUMN mock_usage.request_count IS 'Count of mock data-plane requests recorded for this coordinate on usage_date';

-- Seed mock quota keys into license plans (merge so existing seat keys are preserved).
UPDATE apiome.licenses
SET seats = seats || '{"mock_rps": 5, "mock_requests_per_month": 10000}'::jsonb
WHERE name = 'Free';

UPDATE apiome.licenses
SET seats = seats || '{"mock_rps": 60, "mock_requests_per_month": 100000}'::jsonb
WHERE name = 'Paid';

UPDATE apiome.licenses
SET seats = seats || '{"mock_rps": 200, "mock_requests_per_month": 1000000}'::jsonb
WHERE name = 'Sponsor';

COMMENT ON COLUMN apiome.licenses.seats IS
  'Capacity limits JSON. Known keys: max_tenants, max_users_per_tenant, mock_rps, mock_requests_per_month.';

CREATE OR REPLACE FUNCTION apiome.record_mock_usage(
  p_tenant_id UUID,
  p_project_slug TEXT,
  p_version_label TEXT
)
RETURNS void
LANGUAGE sql
AS $$
  INSERT INTO apiome.mock_usage (tenant_id, project_slug, version_label, usage_date, request_count)
  VALUES (p_tenant_id, p_project_slug, p_version_label, (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date, 1)
  ON CONFLICT (tenant_id, project_slug, version_label, usage_date)
  DO UPDATE SET request_count = apiome.mock_usage.request_count + 1;
$$;

COMMENT ON FUNCTION apiome.record_mock_usage(UUID, TEXT, TEXT) IS
  'Atomically increment the daily mock usage rollup for one tenant/project/version (#4420).';
