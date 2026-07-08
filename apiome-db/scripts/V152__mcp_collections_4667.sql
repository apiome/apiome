-- MCP catalog collections — named, tenant-scoped curated endpoint lists (#4667, V2-MCP-36.4 / MCAT-22.4).
--
-- Problem: the catalog is a flat list per tenant; users want to group related servers for navigation
-- and sharing ("our approved MCP servers", "geo tools").
--
-- Solution: ``mcp_collections`` holds named, optionally published collections; ``mcp_collection_members``
-- is the many-to-many join so endpoints can appear in multiple collections. Published collections are
-- exposed on apiome-browse and only surface endpoints that pass the public visibility gate
-- (``mcp_v_public_endpoints``).
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_collection_members;
--   DROP TABLE IF EXISTS apiome.mcp_collections;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_collections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Tenant scope — cascade when the tenant is removed.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Human-facing identity within the tenant.
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,

    -- When true, the collection is visible on apiome-browse (public endpoints only).
    is_published BOOLEAN NOT NULL DEFAULT FALSE,

    -- Author audit — RESTRICT on user delete so authorship is preserved while collections exist.
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_collections_name_nonempty CHECK (char_length(trim(name)) > 0),
    CONSTRAINT mcp_collections_slug_nonempty CHECK (char_length(trim(slug)) > 0),
    CONSTRAINT mcp_collections_tenant_slug_unique UNIQUE (tenant_id, slug),
    CONSTRAINT mcp_collections_tenant_name_unique UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS mcp_collection_members (
    collection_id UUID NOT NULL REFERENCES mcp_collections(id) ON DELETE CASCADE,

    -- Denormalized tenant scope for endpoint lookups and integrity checks.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- Stable ordering within a collection (lower first).
    position INT NOT NULL DEFAULT 0,

    added_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (collection_id, endpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_mcp_collections_tenant
    ON mcp_collections (tenant_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_mcp_collection_members_collection
    ON mcp_collection_members (collection_id, position ASC, added_at ASC);

CREATE INDEX IF NOT EXISTS idx_mcp_collection_members_endpoint
    ON mcp_collection_members (tenant_id, endpoint_id);

COMMENT ON TABLE mcp_collections IS
    'Named, tenant-scoped curated lists of MCP catalog endpoints (MCAT-22.4). Optionally published '
    'for anonymous browse; members are stored in mcp_collection_members.';
COMMENT ON COLUMN mcp_collections.is_published IS
    'When true, the collection is listed on apiome-browse; only public published endpoints are shown.';
COMMENT ON TABLE mcp_collection_members IS
    'Many-to-many membership between collections and endpoints (MCAT-22.4). An endpoint may belong '
    'to multiple collections within the same tenant.';
