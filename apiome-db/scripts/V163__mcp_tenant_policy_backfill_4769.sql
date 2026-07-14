-- Backward-compatible MCP policy seed & migrate — MTG-1.5 (#4769).
--
-- Problem: turning on tenant MCP governance must not break existing MCP clients
-- overnight. V161 deferred existing-tenant backfill; V162 added per-key grant
-- columns with DEFAULT inherit. Until every tenant has a policy row, resolvers
-- treat missing policy as default_mode=all (full catalog) — but upgrade must
-- materialize that contract explicitly so later admin edits and write-time
-- ceiling checks have a stable row.
--
-- Upgrade path (documented contract):
--   1. Pre-V161/V162: unseeded tenants / keys without capability columns.
--      MTG-1.4 / V162 write-time treat missing policy as default_mode=all
--      (full registry ceiling + defaults). Live tool calls stay open.
--   2. V162: ADD COLUMN capability_mode DEFAULT 'inherit', enabled_tools DEFAULT [].
--      Existing keys pick up inherit without a row rewrite.
--   3. V163 (this migration):
--        * FOR each tenant: PERFORM apiome.seed_tenant_mcp_policy(id)
--          → tenant_mcp_policies.default_mode='all', no tool rows.
--          Under default_mode=all, empty tenant_mcp_policy_tools means the full
--          MTG-1.1 registry for ceiling and defaults (no SQL hardcoding of
--          Python registry ids — those live in app.mcp_tool_registry).
--        * Affirm non-explicit mcp_api_keys rows to capability_mode=inherit
--          and enabled_tools=[]. Do not rewrite capability_mode='explicit'
--          (admin-edited grants after V162).
--   4. Behavior after V163 is unchanged for clients until an admin edits
--      tenant policy or a key's capability mode. Published mcp-quickstart
--      flows remain valid (no doc change required for this ticket).
--
-- Idempotent: seed_tenant_mcp_policy uses ON CONFLICT DO NOTHING; the key
-- UPDATE is a no-op for rows already at inherit + [].
--
-- Rollback notes: data backfill — do not DELETE tenant_mcp_policies rows that
-- may have been admin-edited after seed. Leaving V163 rows in place is safe
-- (default_mode=all matches pre-backfill resolve semantics). To fully wipe
-- MTG policy tables, follow V161 rollback (DROP seed function + tables) and
-- V162 rollback for key columns — only on environments that can sacrifice
-- governance data.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------
-- Existing tenants: full-catalog policy (default_mode=all, empty tool rows)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT id FROM apiome.tenants LOOP
        PERFORM apiome.seed_tenant_mcp_policy(t.id);
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- Affirm legacy / pre-governance keys stay open via inherit
-- ---------------------------------------------------------------------------
-- Do not touch capability_mode='explicit' (admin-edited grants).
UPDATE apiome.mcp_api_keys
SET capability_mode = 'inherit',
    enabled_tools = '[]'::jsonb
WHERE capability_mode IS DISTINCT FROM 'explicit';
