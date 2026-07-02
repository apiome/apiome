-- External MCP Catalog (#3651, V2-MCP-15.1 / MCAT-1.1): the root catalog table.
--
-- `mcp_endpoints` is the tenant-scoped record of an external Model Context Protocol server a tenant
-- wants to catalog, discover, and (optionally) publish for browsing. One row per logical endpoint:
-- a friendly UI `name`, a tenant-unique `slug`, the `endpoint_url`, and the `transport` it speaks
-- (`streamable_http` | `sse` | `stdio`, per the MCP transports spec
-- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
--
-- Discovery is periodic: `discovery_cadence_seconds` controls how often the discovery pipeline
-- (MCAT-7.x) re-handshakes the server, recording `last_discovered_at` / `last_discovery_status`.
-- Each successful discovery that changes the server's surface produces an immutable snapshot row in
-- `mcp_endpoint_versions` (MCAT-1.3, V128); `current_version_id` points at the latest such snapshot.
-- The FK from `current_version_id` to that table is intentionally NOT added here — it is added in
-- V128 once `mcp_endpoint_versions` exists (FK ordering, see roadmap MCAT-1.3). Until then the column
-- is a plain nullable UUID.
--
-- `visibility` reuses the `visibility_type` enum from V006. `published` gates whether a public/
-- unlisted endpoint appears in the catalog browser (MCAT-1.6 adds the public read view over this).
--
-- Rollback notes: this migration is purely additive (one new table, its indexes, and comments). To
-- roll back, `DROP TABLE IF EXISTS apiome.mcp_endpoints CASCADE;` — this also drops the dependent
-- indexes. The shared `visibility_type` enum from V006 is left in place (other tables use it).

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_endpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    creator_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    endpoint_url TEXT NOT NULL,
    transport VARCHAR(32) NOT NULL,
    description TEXT,
    category VARCHAR(255),
    visibility visibility_type NOT NULL DEFAULT 'private',
    published BOOLEAN NOT NULL DEFAULT false,
    enabled BOOLEAN NOT NULL DEFAULT true,
    discovery_cadence_seconds INTEGER,
    last_discovered_at TIMESTAMP WITH TIME ZONE,
    last_discovery_status VARCHAR(64),
    current_version_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A tenant cannot register two endpoints under the same slug. The btree index backing this
    -- constraint also serves lookups on (tenant_id, slug), so no separate index is created for it.
    CONSTRAINT mcp_endpoints_tenant_slug_unique UNIQUE (tenant_id, slug),

    -- Transport must be one of the MCP-defined transports.
    CONSTRAINT mcp_endpoints_transport_check
        CHECK (transport IN ('streamable_http', 'sse', 'stdio')),

    -- A cadence, when set, must be a positive number of seconds.
    CONSTRAINT mcp_endpoints_cadence_check
        CHECK (discovery_cadence_seconds IS NULL OR discovery_cadence_seconds > 0)
);

-- List/scope every endpoint owned by a tenant (live rows only).
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_tenant_id
    ON mcp_endpoints(tenant_id) WHERE deleted_at IS NULL;

-- Public catalog browse: find published endpoints by visibility (MCAT-1.6 view sits over this).
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_published_visibility
    ON mcp_endpoints(published, visibility) WHERE deleted_at IS NULL;

-- Discovery scheduler: pick the enabled endpoints whose last discovery is oldest / null first.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_enabled_last_discovered
    ON mcp_endpoints(enabled, last_discovered_at) WHERE deleted_at IS NULL;

COMMENT ON TABLE mcp_endpoints IS 'External MCP servers a tenant catalogs, discovers, and optionally publishes (#3651, V2-MCP-15.1)';
COMMENT ON COLUMN mcp_endpoints.id IS 'Unique identifier for the catalog endpoint';
COMMENT ON COLUMN mcp_endpoints.tenant_id IS 'Owning tenant; cascade-deleted with the tenant';
COMMENT ON COLUMN mcp_endpoints.creator_id IS 'User who registered this endpoint (deletion restricted while endpoints exist)';
COMMENT ON COLUMN mcp_endpoints.name IS 'Friendly, human-readable label shown in the UI';
COMMENT ON COLUMN mcp_endpoints.slug IS 'URL-safe identifier, unique within a tenant';
COMMENT ON COLUMN mcp_endpoints.endpoint_url IS 'The MCP server URL (or command target for stdio) to connect to';
COMMENT ON COLUMN mcp_endpoints.transport IS 'MCP transport: streamable_http, sse, or stdio (per the MCP transports spec)';
COMMENT ON COLUMN mcp_endpoints.description IS 'Optional free-text description of the endpoint';
COMMENT ON COLUMN mcp_endpoints.category IS 'Optional catalog category used for grouping/filtering in the browser';
COMMENT ON COLUMN mcp_endpoints.visibility IS 'Reuses visibility_type (V006): private (tenant-only) or public (catalog-visible when published)';
COMMENT ON COLUMN mcp_endpoints.published IS 'Whether the endpoint is published to the catalog browser; gates the public read view (MCAT-1.6)';
COMMENT ON COLUMN mcp_endpoints.enabled IS 'Soft on/off switch; disabled endpoints are skipped by the discovery scheduler';
COMMENT ON COLUMN mcp_endpoints.discovery_cadence_seconds IS 'How often (seconds) to re-discover the server; null means no automatic discovery';
COMMENT ON COLUMN mcp_endpoints.last_discovered_at IS 'Timestamp of the most recent discovery attempt; null until first run';
COMMENT ON COLUMN mcp_endpoints.last_discovery_status IS 'Outcome of the most recent discovery attempt (e.g. ok, unreachable, auth_error)';
COMMENT ON COLUMN mcp_endpoints.current_version_id IS 'Latest mcp_endpoint_versions snapshot for this endpoint; FK is added in V128 (MCAT-1.3) once that table exists';
COMMENT ON COLUMN mcp_endpoints.metadata IS 'Free-form JSONB for additional endpoint attributes not yet promoted to columns';
COMMENT ON COLUMN mcp_endpoints.deleted_at IS 'Soft delete timestamp; null means the endpoint is live';
COMMENT ON COLUMN mcp_endpoints.created_at IS 'Timestamp when the endpoint was created';
COMMENT ON COLUMN mcp_endpoints.updated_at IS 'Timestamp when the endpoint was last updated';
