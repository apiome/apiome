-- MCP endpoint health / uptime monitoring (#3713, V2-MCP-27.3 / MCAT-13.3): one row per reachability
-- probe of a catalog endpoint.
--
-- Discovery (MCAT-3.2) re-handshakes and re-lists an endpoint's whole surface about once an hour, so
-- its job log is a coarse and expensive reachability signal. The health sweep runs a much lighter
-- probe — the MCP `initialize` handshake only, no `*/list` pagination — every few minutes and records
-- what it saw here, so catalog quality can include reachability and latency over time:
--
--   * mcp_endpoint_health_checks — one row per probe: when it ran, whether the endpoint answered
--                                  (`up`) or not (`down`), how long the handshake took, and for a
--                                  failure the stable discovery error code (`connect_error`, `timeout`,
--                                  `auth_required`, …). The URL is never copied here; the row points at
--                                  the endpoint, which owns it.
--
-- The latest row per endpoint is also how the sweep decides an endpoint is due again, so no column is
-- added to mcp_endpoints. Retention is enforced by the application (rows older than the retention
-- window are pruned as the sweep runs), keeping the table bounded per endpoint.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_endpoint_health_checks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The probed endpoint; its history goes with it when the endpoint row is removed.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- When the probe started.
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- `up` when the initialize handshake completed, `down` when it did not.
    status VARCHAR(8) NOT NULL,

    -- Wall-clock milliseconds the probe took (connect + initialize), for an `up` or a `down` probe.
    latency_ms INTEGER,

    -- The stable discovery error code for a `down` probe (app.mcp_client.errors.DiscoveryErrorCode);
    -- NULL for an `up` probe.
    error_code VARCHAR(64),

    CONSTRAINT mcp_endpoint_health_checks_status_check
        CHECK (status IN ('up', 'down')),
    CONSTRAINT mcp_endpoint_health_checks_latency_check
        CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

-- History reads, the "latest probe" due-selection and retention pruning all walk one endpoint's rows
-- newest-first.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_health_checks_endpoint_checked_at
    ON mcp_endpoint_health_checks(endpoint_id, checked_at DESC);

-- Retention pruning deletes by age across all endpoints.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_health_checks_checked_at
    ON mcp_endpoint_health_checks(checked_at);

COMMENT ON TABLE mcp_endpoint_health_checks IS
    'One row per lightweight reachability probe (MCP initialize handshake only) of a catalog endpoint (#3713): checked_at, up/down status, latency_ms and the discovery error code of a failure.';
COMMENT ON COLUMN mcp_endpoint_health_checks.status IS
    'up when the initialize handshake completed; down when it did not.';
COMMENT ON COLUMN mcp_endpoint_health_checks.latency_ms IS
    'Wall-clock milliseconds of the probe (connect + initialize).';
COMMENT ON COLUMN mcp_endpoint_health_checks.error_code IS
    'Stable discovery error code (connect_error, timeout, auth_required, ...) for a down probe; NULL when up.';
