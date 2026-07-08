-- Saved catalog searches — per-user named filter sets (#4662, V2-MCP-35.3 / MCAT-21.3).
--
-- Problem: operators re-apply the same catalog filters repeatedly (e.g. "ungraded servers with
-- destructive tools") with no way to save and recall them.
--
-- Solution: a lightweight ``mcp_saved_searches`` table that persists a named filter bundle per
-- (tenant, user). Each row stores the composable facet filter state (JSONB), optional free-text
-- query, sort key, and an ``is_pinned`` flag so a saved search can surface as a catalog "view".
-- Rows cascade with their tenant and owner; names are unique per (tenant, user).
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_saved_searches;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.mcp_saved_searches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Tenant scope — cascade when the tenant is removed.
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,

    -- Owner — cascade when the user is removed; saved searches are personal, not shared.
    user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,

    -- Human label shown in the catalog UI; unique per owner within a tenant.
    name TEXT NOT NULL,

    -- Composable catalog filter state (hosts, grades, transports, visibilities, auths,
    -- categories, safeties, complexities, protocols, healths) — mirrors the ADE catalog toolbar.
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Optional free-text search box value saved with the filter set.
    query TEXT NOT NULL DEFAULT '',

    -- Sort key saved with the filter set (grade / name / recency / capabilities / health).
    sort TEXT NOT NULL DEFAULT 'grade',

    -- When TRUE the saved search is pinned as a catalog "view" (quick-access chip).
    is_pinned BOOLEAN NOT NULL DEFAULT false,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_saved_searches_name_unique UNIQUE (tenant_id, user_id, name),
    CONSTRAINT mcp_saved_searches_name_nonempty CHECK (char_length(trim(name)) > 0)
);

-- List a user's saved searches (newest first) and pinned-view lookups.
CREATE INDEX IF NOT EXISTS idx_mcp_saved_searches_tenant_user
    ON apiome.mcp_saved_searches (tenant_id, user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_mcp_saved_searches_pinned
    ON apiome.mcp_saved_searches (tenant_id, user_id)
    WHERE is_pinned = true;

COMMENT ON TABLE apiome.mcp_saved_searches IS
    'Per-user named catalog filter sets backing saved searches and pinned catalog views (MCAT-21.3). '
    'One row per (tenant, user, name); filters are JSONB matching the ADE catalog toolbar state.';
COMMENT ON COLUMN apiome.mcp_saved_searches.filters IS
    'Composable catalog filters (hosts, grades, transports, visibilities, auths, categories, '
    'safeties, complexities, protocols, healths) as JSONB';
COMMENT ON COLUMN apiome.mcp_saved_searches.is_pinned IS
    'When TRUE the saved search surfaces as a pinned catalog view chip in the toolbar';
