-- Tenant MCP policy data model — MTG-1.2 (#4766).
--
-- Problem: there is no tenant-scoped place to store which apiome-mcp tools this tenant
-- allows (ceiling) and which tools new MCP keys inherit by default. Governance cannot
-- live only in env vars or client headers (contrast GitHub’s X-MCP-Tools, which is
-- client-chosen, not org-enforced).
--
-- Solution: two tables + an idempotent per-tenant seed function.
--
--   * tenant_mcp_policies      — one row per tenant; default_mode controls how missing
--                                tool rows are interpreted
--   * tenant_mcp_policy_tools  — per-tool flags splitting ceiling vs default enable-set
--
-- Ceiling vs default enable-set (documented split):
--   * Ceiling (in_ceiling):         max tools any key in the tenant may enable.
--   * Default enable-set
--     (default_enabled):            applied when a new MCP key is created with inherit.
--   Constraint: default_enabled ⇒ in_ceiling (defaults ⊆ ceiling).
--
-- default_mode semantics:
--   * all              — ceiling and default enable-set are the full MTG-1.1 registry;
--                        tool rows may be empty and are ignored at resolve time.
--   * inherit_registry — ceiling/defaults track the registry dynamically; tool rows may
--                        refine but are optional.
--   * explicit         — tool rows are authoritative for both ceiling and defaults.
--
-- Seed on tenant create: call apiome.seed_tenant_mcp_policy(tenant) (idempotent) to
-- insert a policy row with default_mode = 'all' and no tool rows. Existing-tenant
-- backfill and materializing full-catalog tool rows are deferred to MTG-1.5 (#4769)
-- so upgrade remains a no-op for live MCP clients until that migration.
--
-- Rollback notes: purely additive. To roll back:
--   DROP FUNCTION IF EXISTS apiome.seed_tenant_mcp_policy(UUID);
--   DROP TABLE IF EXISTS apiome.tenant_mcp_policy_tools;
--   DROP TABLE IF EXISTS apiome.tenant_mcp_policies;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------
-- tenant_mcp_policies — one policy row per tenant
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_mcp_policies (
    tenant_id    UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    default_mode TEXT NOT NULL DEFAULT 'all'
                 CONSTRAINT tenant_mcp_policies_default_mode_ck
                 CHECK (default_mode IN ('all', 'inherit_registry', 'explicit')),
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by   UUID REFERENCES users(id) ON DELETE SET NULL
);

COMMENT ON TABLE tenant_mcp_policies IS
    'Per-tenant MCP tool governance policy: default_mode plus timestamps/updated_by (#4766, MTG-1.2). '
    'One row per tenant; ceiling and default enable-set live in tenant_mcp_policy_tools.';

COMMENT ON COLUMN tenant_mcp_policies.default_mode IS
    'How missing/empty tool rows resolve: all = full registry for ceiling and defaults; '
    'inherit_registry = track registry dynamically; explicit = tool rows are authoritative.';

COMMENT ON COLUMN tenant_mcp_policies.updated_by IS
    'Tenant admin (or system) who last changed the policy; NULL until first update after seed.';

-- ---------------------------------------------------------------------------
-- tenant_mcp_policy_tools — ceiling + default enable-set per tool
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_mcp_policy_tools (
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    tool_id          TEXT NOT NULL,
    in_ceiling       BOOLEAN NOT NULL DEFAULT true,
    default_enabled  BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tenant_mcp_policy_tools_pk PRIMARY KEY (tenant_id, tool_id),
    CONSTRAINT tenant_mcp_policy_tools_tool_id_nonempty
        CHECK (char_length(trim(tool_id)) > 0),
    CONSTRAINT tenant_mcp_policy_tools_default_subseteq_ceiling_ck
        CHECK (NOT default_enabled OR in_ceiling)
);

CREATE INDEX IF NOT EXISTS idx_tenant_mcp_policy_tools_tenant
    ON tenant_mcp_policy_tools (tenant_id);

COMMENT ON TABLE tenant_mcp_policy_tools IS
    'Per-tool MCP policy flags for a tenant (#4766, MTG-1.2). Unique (tenant_id, tool_id). '
    'Ceiling vs default enable-set split: in_ceiling is the max tools any key may enable; '
    'default_enabled is the enable-set applied when a new MCP key is created with inherit. '
    'Under default_mode all/inherit_registry, empty rows mean the full registry; under explicit, '
    'these rows are authoritative.';

COMMENT ON COLUMN tenant_mcp_policy_tools.tool_id IS
    'Stable MTG-1.1 mcp_tool_registry id (e.g. ping, spec.list); never renamed once shipped.';

COMMENT ON COLUMN tenant_mcp_policy_tools.in_ceiling IS
    'Ceiling membership: when true, any key in the tenant may enable this tool. Keys cannot '
    'exceed the tenant ceiling.';

COMMENT ON COLUMN tenant_mcp_policy_tools.default_enabled IS
    'Default enable-set: when true (and in_ceiling), the tool is enabled for new MCP keys '
    'created with capability_mode=inherit. Must be false whenever in_ceiling is false.';

-- ---------------------------------------------------------------------------
-- Seed for tenant create (idempotent; no existing-tenant backfill — see MTG-1.5)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.seed_tenant_mcp_policy(p_tenant UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO apiome.tenant_mcp_policies (tenant_id, default_mode)
    VALUES (p_tenant, 'all')
    ON CONFLICT (tenant_id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.seed_tenant_mcp_policy(UUID) IS
    'Idempotently seed a tenant_mcp_policies row with default_mode=all and no tool rows '
    '(full-catalog meaning). Call on tenant create; existing-tenant backfill is MTG-1.5 (#4769).';
