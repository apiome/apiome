-- External MCP Catalog (#3673, V2-MCP-19.1 / MCAT-5.1): periodic re-discovery sweep cadence semantics.
--
-- V126 (MCAT-1.1) created `mcp_endpoints.discovery_cadence_seconds` and documented a null value as
-- "no automatic discovery". MCAT-5.1 introduces the periodic re-discovery sweep
-- (apiome-rest `mcp_discovery_sweep.py`), and with it the "global default cadence + per-endpoint
-- override" model the ticket specifies: the sweep's due-selection treats a null
-- `discovery_cadence_seconds` as "use the global default cadence" (the configurable
-- `APIOME_MCP_DISCOVERY_DEFAULT_CADENCE`, ~hourly by default), *not* "never discover".
--
-- The genuine on/off switch is the `enabled` column: an operator opts an endpoint out of the sweep by
-- disabling it (or the global `APIOME_MCP_DISCOVERY_ENABLED` kill switch), never by clearing its
-- cadence. This migration only corrects the now-stale column comment to match that behaviour; it makes
-- no schema or data change. The existing `idx_mcp_endpoints_enabled_last_discovered` index (V126) still
-- backs the sweep's due-selection scan.
--
-- Rollback notes: comment-only migration. To roll back, restore the V126 comment text via
-- `COMMENT ON COLUMN apiome.mcp_endpoints.discovery_cadence_seconds IS ...`. No structural change to undo.

SET search_path TO apiome, public;

COMMENT ON COLUMN mcp_endpoints.discovery_cadence_seconds IS
    'Per-endpoint re-discovery cadence (seconds) overriding the global default; null means use the global default cadence (MCAT-5.1). The on/off switch is the enabled column, not this value.';
