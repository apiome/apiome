-- Upstream MCP registry connector: inventory rows that become MCP servers (CDG-4.4, #5976).
--
-- An `mcp-registry` connector pulls `GET /v0.1/servers` from an upstream MCP registry (the official
-- registry, Azure API Center, a Kong registry or another Apiome tenant). Each registry server is an
-- inventory row like any other connector's, but it lands in the MCP server catalog
-- (`apiome.mcp_endpoints`, `added_via = 'registry'`), not in `projects`, so the row needs its own
-- pointer:
--
--   * `mcp_endpoint_id` — the MCP server this registry entry created or refreshed. SET NULL, never
--     CASCADE: deleting the server must not erase the inventory's memory that the entry exists.
--   * `discovered_reason` — why the entry is still `discovered` rather than `imported`: it lists no
--     remote Apiome can call (a package-only server runs locally), its remote is refused by the
--     address policy, or discovery could not reach it. NULL once the server answered.
--
-- Rollback:
--   DROP INDEX IF EXISTS apiome.idx_catalog_connector_items_mcp_endpoint;
--   ALTER TABLE apiome.catalog_connector_items
--     DROP COLUMN IF EXISTS mcp_endpoint_id, DROP COLUMN IF EXISTS discovered_reason;
SET search_path TO apiome, public;

ALTER TABLE apiome.catalog_connector_items
    ADD COLUMN IF NOT EXISTS mcp_endpoint_id   UUID REFERENCES apiome.mcp_endpoints(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS discovered_reason TEXT
        CHECK (discovered_reason IS NULL OR length(discovered_reason) <= 1000);

CREATE INDEX IF NOT EXISTS idx_catalog_connector_items_mcp_endpoint
    ON apiome.catalog_connector_items (mcp_endpoint_id)
    WHERE mcp_endpoint_id IS NOT NULL;

COMMENT ON COLUMN apiome.catalog_connector_items.mcp_endpoint_id IS
    'The MCP server (mcp_endpoints row) an mcp-registry connector entry created or refreshed (CDG-4.4). NULL for every other kind.';
COMMENT ON COLUMN apiome.catalog_connector_items.discovered_reason IS
    'Why an mcp-registry entry is still discovered, not imported: no reachable remote, a refused remote address, or discovery could not reach it (CDG-4.4). NULL once the server answered.';
