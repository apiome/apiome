-- Opt-in SDK compatibility beacon — RDG-1.7 / SGD-3.1 (#4736).
--
-- A generated SDK can, when its user explicitly turns it on, report how its calls turned out so the
-- API owner learns which released contracts real SDK consumers find incompatible. The beacon says
-- exactly five things per call — which SDK and SDK version, which API version (and the published
-- revision the SDK was generated from), which operation, and an outcome category — and nothing else:
-- no request or response data, no status code, no latency, no host, no credential, no identifier of
-- the caller.
--
--   usage_sdk_beacon_daily      calls per (source, UTC day, revision, API version, SDK, SDK version,
--                               operation, outcome)
--   purge_usage_sdk_beacons()   prunes it past the tier's rollup retention
--
-- Why a table of its own rather than the usage index (V290): every usage_hourly row needs a real
-- status code and a latency histogram, and a beacon carries neither (a `network` outcome has no
-- status at all). The beacon still rides the usage machinery where it fits: it posts under a
-- `usage_source` of kind `sdk_beacon` (V290 already allows the kind) with a `usage:ingest` key, so the
-- source's `enabled` flag is the tenant's off switch, and rows age out with the tier's
-- `usage_rollup_retention_days` through the usage sweep.
--
-- Correlation: `spec_revision_id` is the published revision the SDK was generated from — the same
-- revision the SDK kit's manifest names — and `operation_id` is the manifest's operation id, so an
-- owner can line beacon counts up against the compatibility manifest.
--
-- Every text column is bounded and pattern-checked, so nothing but a version-like token can be
-- stored; the day is the server's receive day, never a client clock.
--
-- Rollback notes:
--   DROP FUNCTION IF EXISTS apiome.purge_usage_sdk_beacons(TIMESTAMPTZ, INTEGER);
--   DROP TABLE IF EXISTS apiome.usage_sdk_beacon_daily;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS usage_sdk_beacon_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES usage_source(id) ON DELETE CASCADE,
    day DATE NOT NULL,

    spec_revision_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    api_version VARCHAR(64) NOT NULL
        CONSTRAINT usage_sdk_beacon_api_version_ck CHECK (api_version ~ '^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$'),
    sdk_name VARCHAR(64) NOT NULL
        CONSTRAINT usage_sdk_beacon_sdk_name_ck CHECK (sdk_name ~ '^[a-z0-9][a-z0-9._/-]{0,63}$'),
    sdk_version VARCHAR(64) NOT NULL
        CONSTRAINT usage_sdk_beacon_sdk_version_ck CHECK (sdk_version ~ '^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$'),
    operation_id VARCHAR(255) NOT NULL
        CONSTRAINT usage_sdk_beacon_operation_id_ck CHECK (operation_id ~ '^[A-Za-z0-9_][A-Za-z0-9_.:/{} -]{0,254}$'),
    outcome VARCHAR(16) NOT NULL
        CONSTRAINT usage_sdk_beacon_outcome_ck CHECK (
            outcome IN ('ok', 'client_error', 'server_error', 'network', 'incompatible')
        ),

    calls BIGINT NOT NULL CONSTRAINT usage_sdk_beacon_calls_ck CHECK (calls >= 0),
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT usage_sdk_beacon_daily_pk PRIMARY KEY (
        tenant_id, project_id, source_id, day, spec_revision_id, api_version, sdk_name, sdk_version,
        operation_id, outcome
    )
);

-- The owner's read: a project's beacon counts over recent days.
CREATE INDEX IF NOT EXISTS idx_usage_sdk_beacon_project_day
    ON usage_sdk_beacon_daily (tenant_id, project_id, day DESC);
-- The retention prune.
CREATE INDEX IF NOT EXISTS idx_usage_sdk_beacon_day ON usage_sdk_beacon_daily (day);

COMMENT ON TABLE usage_sdk_beacon_daily IS
    'RDG-1.7 / SGD-3.1 (#4736): opt-in SDK compatibility beacon counts per source, UTC day, published '
    'revision, API version, SDK, SDK version, operation and outcome. No payload, status, latency, host, '
    'credential or caller identifier is ever stored.';
COMMENT ON COLUMN usage_sdk_beacon_daily.spec_revision_id IS
    'The published revision the SDK was generated from (the SDK kit manifest''s revision)';
COMMENT ON COLUMN usage_sdk_beacon_daily.operation_id IS 'The kit manifest''s operation id';
COMMENT ON COLUMN usage_sdk_beacon_daily.outcome IS
    'ok | client_error (4xx) | server_error (5xx) | network (no response) | incompatible (a 2xx the SDK could not decode)';
COMMENT ON COLUMN usage_sdk_beacon_daily.day IS 'The UTC day the server received the report — never a client clock';

-- Prune past the tier's rollup retention, at most p_batch rows per call (the rest go next time).
CREATE OR REPLACE FUNCTION purge_usage_sdk_beacons(
    p_now TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    p_batch INTEGER DEFAULT 10000
)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM apiome.usage_sdk_beacon_daily
    WHERE ctid IN (
        SELECT b.ctid
        FROM apiome.usage_retention(p_now) r
        JOIN apiome.usage_sdk_beacon_daily b
          ON b.tenant_id = r.tenant_id AND b.day < r.rollup_cutoff
        LIMIT GREATEST(p_batch, 1)
    );
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_usage_sdk_beacons(TIMESTAMPTZ, INTEGER) IS
    'Prune usage_sdk_beacon_daily past each tenant''s usage_rollup_retention_days (at most p_batch rows '
    'per call); returns the rows deleted. RDG-1.7 (#4736).';
