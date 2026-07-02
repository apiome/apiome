-- External MCP Catalog (#3675, V2-MCP-19.3 / MCAT-5.3): discovery failure handling, backoff & status.
--
-- MCAT-5.1/5.2 (V132, apiome-rest `mcp_discovery_sweep.py`) made the periodic re-discovery
-- sweep cadence-driven and bounded. This migration adds the per-endpoint failure-handling state the
-- sweep needs so a flaky/dead endpoint cannot wedge the sweep or spam failures every tick:
--
--   * `consecutive_failures`  — count of back-to-back failed discovery attempts. Incremented on each
--                               failure; reset to 0 on the next successful contact (a new version or an
--                               unchanged re-discovery). Drives the exponential backoff delay.
--   * `next_discovery_after`  — backoff anchor. After a failure the sweep must not re-select the
--                               endpoint until now() has passed this timestamp, even if its cadence has
--                               otherwise elapsed. Null means "no backoff in effect" (the cadence alone
--                               governs due-ness). On a rate-limited (HTTP 429) failure the server's
--                               Retry-After is honoured as a floor for this delay.
--   * `quarantined_at`        — when set, the endpoint has tripped the consecutive-failure threshold and
--                               is auto-disabled from the sweep (quarantined) until it recovers or an
--                               operator intervenes. Null means not quarantined. This is distinct from
--                               the operator `enabled` switch: a quarantine is automatic and self-clears
--                               on the next success, whereas `enabled = false` is a manual opt-out.
--   * `quarantine_reason`     — the discovery error code/summary that tripped the quarantine, retained
--                               for the status API and operator diagnosis.
--
-- The sweep's due-selection (apiome-rest `Database.list_due_mcp_endpoints`) is extended to skip
-- quarantined endpoints and any endpoint still inside its backoff window, so healthy endpoints are
-- unaffected while a failing one progressively backs off and eventually quarantines.
--
-- Rollback notes: purely additive (four nullable/defaulted columns, one partial index, one check
-- constraint, and comments). To roll back:
--   ALTER TABLE apiome.mcp_endpoints
--     DROP COLUMN IF EXISTS consecutive_failures,
--     DROP COLUMN IF EXISTS next_discovery_after,
--     DROP COLUMN IF EXISTS quarantined_at,
--     DROP COLUMN IF EXISTS quarantine_reason;
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_backoff_due;

SET search_path TO apiome, public;

ALTER TABLE mcp_endpoints
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_discovery_after TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS quarantined_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;

-- A failure counter is never negative.
ALTER TABLE mcp_endpoints
    DROP CONSTRAINT IF EXISTS mcp_endpoints_consecutive_failures_check;
ALTER TABLE mcp_endpoints
    ADD CONSTRAINT mcp_endpoints_consecutive_failures_check
        CHECK (consecutive_failures >= 0);

-- Sweep due-selection: the enabled-and-not-quarantined endpoints ordered by how stale they are.
-- Mirrors idx_mcp_endpoints_enabled_last_discovered (V126) but with the quarantine carve-out the
-- MCAT-5.3 due query adds, so a large quarantined backlog never bloats the scan.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_backoff_due
    ON mcp_endpoints(enabled, last_discovered_at)
    WHERE deleted_at IS NULL AND quarantined_at IS NULL;

COMMENT ON COLUMN mcp_endpoints.consecutive_failures IS
    'Count of back-to-back failed discovery attempts; reset to 0 on the next success. Drives exponential backoff and the quarantine threshold (MCAT-5.3).';
COMMENT ON COLUMN mcp_endpoints.next_discovery_after IS
    'Backoff anchor: the sweep skips this endpoint until now() passes this timestamp, even if its cadence elapsed. Null means no backoff in effect. Honours a 429 Retry-After as a floor (MCAT-5.3).';
COMMENT ON COLUMN mcp_endpoints.quarantined_at IS
    'When set, the endpoint tripped the consecutive-failure threshold and is auto-excluded from the sweep until it recovers (self-clears on the next success). Distinct from the manual enabled switch (MCAT-5.3).';
COMMENT ON COLUMN mcp_endpoints.quarantine_reason IS
    'The discovery error code/summary that tripped the quarantine, retained for the status API and diagnosis (MCAT-5.3).';
