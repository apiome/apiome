-- Mock Server (#3615, RC1-2.2): hosted mock instances provisioned from a published version.
--
-- A mock instance freezes the OpenAPI spec generated from a published, immutable version (the same
-- spec the /v1/schema and /v1/swagger endpoints serve) into `spec` (JSONB) at provision time. The
-- data plane (/v1/mock/{id}/...) replays schema-valid responses from that frozen spec, so the mock
-- is stable for the life of the instance even though it never touches the live version again.
--
-- `config` (JSONB) holds the selectable, per-operation scenarios (status / latency / body overrides)
-- and the deterministic generation seed. Free-tier mocks auto-expire (`expires_at`) and are rate
-- limited per instance (`rate_limit_per_minute`), enforced by apiome-rest at request time.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_instances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    tenant_slug VARCHAR(255) NOT NULL,
    project_slug VARCHAR(255) NOT NULL,
    version_slug VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    spec JSONB NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    request_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE,
    CHECK (status IN ('active', 'expired')),
    CHECK (rate_limit_per_minute > 0)
);

CREATE INDEX IF NOT EXISTS idx_mock_instances_tenant_created_at
    ON mock_instances(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mock_instances_expires_at
    ON mock_instances(expires_at);

COMMENT ON TABLE mock_instances IS 'Hosted mock server instances provisioned from a published version (#3615, RC1-2.2)';
COMMENT ON COLUMN mock_instances.version_id IS 'The published apiome.versions row the mock was provisioned from; null if the version is later deleted';
COMMENT ON COLUMN mock_instances.spec IS 'Frozen OpenAPI 3.1 document generated from the version at provision time; the data plane replays responses from this';
COMMENT ON COLUMN mock_instances.config IS 'Mock configuration: scenarios (per-operation status/latency/body overrides), active scenario, and generation seed';
COMMENT ON COLUMN mock_instances.rate_limit_per_minute IS 'Per-instance fixed-window request budget enforced on the data plane (free-tier throttle)';
COMMENT ON COLUMN mock_instances.status IS 'active or expired; the data plane returns 410 Gone once past expires_at';
COMMENT ON COLUMN mock_instances.expires_at IS 'Free-tier auto-expiry; null means the instance never auto-expires';
COMMENT ON COLUMN mock_instances.request_count IS 'Best-effort lifetime count of data-plane requests served';
