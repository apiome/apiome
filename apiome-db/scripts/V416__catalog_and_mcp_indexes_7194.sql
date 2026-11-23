-- Catalog graph and MCP registry indexes (DBP-1.11, #7194).
--
-- Measured on the scale database with the side tables filled (200k consumer_contract,
-- 500k catalog_edges, 2,000 mcp_endpoints over 10k snapshots):
--
--   * idx_consumer_contract_tenant_current — catalog_graph's "consumes" family re-derive
--     (WHERE tenant_id AND is_current). Every consumer_contract index starts with the consumer,
--     the project or the version, so the re-derive scanned the table: 4.5 ms / 7,126 buffers ->
--     0.24 ms / 1,066 for one tenant.
--   * idx_catalog_edges_tenant_from_id, idx_catalog_edges_tenant_to_id — graph_export
--     _neighbourhood_edges, which walks the graph one hop at a time with
--     (from_id = ANY($2) OR to_id = ANY($2)) inside a tenant. The two indexes that hold those
--     columns put from_kind / to_kind in front of them. PostgreSQL 18 can skip over that column
--     (99 -> 57 buffers per hop on the scale database), but the supported PostgreSQL 16 cannot:
--     there each hop reads every edge of the tenant.
--   * idx_mcp_endpoints_registry_server_name — Database.find_mcp_endpoint_by_registry_server_name
--     and the bulk registry dedupe (WHERE tenant_id AND added_via = 'registry' AND
--     lower(registry_metadata->>'serverName') = ...): 24 -> 3 buffers. Partial on live registry
--     endpoints.
--   * idx_mcp_endpoints_current_version — the joins from a snapshot to the endpoint whose current
--     snapshot it is (mcp semantic search, similar servers, capability directory:
--     JOIN mcp_endpoints e ON e.current_version_id = ...). Nothing indexed current_version_id:
--     0.08 ms / 135 buffers -> 0.004 ms / 5 per snapshot.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to its table while it builds. To avoid that, build them first
-- by hand with CREATE INDEX CONCURRENTLY (same names and definitions); every statement is
-- IF NOT EXISTS, so the migration then does nothing.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_consumer_contract_tenant_current;
--   DROP INDEX IF EXISTS apiome.idx_catalog_edges_tenant_from_id;
--   DROP INDEX IF EXISTS apiome.idx_catalog_edges_tenant_to_id;
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_registry_server_name;
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_current_version;

CREATE INDEX IF NOT EXISTS idx_consumer_contract_tenant_current
    ON apiome.consumer_contract (tenant_id)
    WHERE is_current;

CREATE INDEX IF NOT EXISTS idx_catalog_edges_tenant_from_id
    ON apiome.catalog_edges (tenant_id, from_id);

CREATE INDEX IF NOT EXISTS idx_catalog_edges_tenant_to_id
    ON apiome.catalog_edges (tenant_id, to_id);

CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_registry_server_name
    ON apiome.mcp_endpoints (tenant_id, lower(registry_metadata ->> 'serverName'))
    WHERE deleted_at IS NULL AND added_via = 'registry';

CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_current_version
    ON apiome.mcp_endpoints (current_version_id)
    WHERE deleted_at IS NULL;
