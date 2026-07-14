-- Anonymous / unauthenticated MCP call policy — MTG-2.3 (#4772).
--
-- Problem: several apiome-mcp tools accept anonymous callers (public catalog), but
-- tenant governance is key-based; anonymous traffic has no key. Admins need a way to
-- shut off anonymous search (etc.) without affecting authenticated keys.
--
-- Solution: extend the MTG-1.2 policy tables with:
--   * tenant_mcp_policies.allow_anonymous_mcp — kill switch for anonymous tools/call
--   * tenant_mcp_policy_tools.anonymous_enabled — per-tool anonymous enable-set
--
-- Runtime binding (apiome-mcp): optional APIOME_MCP_ANONYMOUS_POLICY_TENANT_ID selects
-- which tenant's row governs anonymous calls on a shared catalog server. When unset,
-- anonymous tools/call stays legacy passthrough. tools/list remains unfiltered (MTG-2.1).
-- Authenticated callers ignore these fields (MTG-2.2 / MTG-1.4 only).
--
-- Anonymous enable-set is independent of key ceiling for MVP ("tenant ceiling optional").
-- Private-spec tools continue to require keys via require_mcp_auth at the tool layer.
--
-- Defaults true preserve today's public behavior after migration.
--
-- Rollback notes: purely additive.
--   ALTER TABLE apiome.tenant_mcp_policy_tools DROP COLUMN IF EXISTS anonymous_enabled;
--   ALTER TABLE apiome.tenant_mcp_policies DROP COLUMN IF EXISTS allow_anonymous_mcp;

SET search_path TO apiome, public;

ALTER TABLE tenant_mcp_policies
    ADD COLUMN IF NOT EXISTS allow_anonymous_mcp BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN tenant_mcp_policies.allow_anonymous_mcp IS
    'When false, anonymous (unauthenticated) MCP tools/call is denied for every tool '
    '(MTG-2.3 / #4772). Authenticated keys are unaffected. Default true preserves '
    'legacy public-catalog behavior. Applied only when apiome-mcp is bound to this '
    'tenant via APIOME_MCP_ANONYMOUS_POLICY_TENANT_ID.';

ALTER TABLE tenant_mcp_policy_tools
    ADD COLUMN IF NOT EXISTS anonymous_enabled BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN tenant_mcp_policy_tools.anonymous_enabled IS
    'Anonymous enable-set membership (MTG-2.3 / #4772). Independent of in_ceiling for MVP. '
    'Under default_mode all, tool rows including this flag are ignored (full registry). '
    'Under inherit_registry / explicit, absent rows and anonymous_enabled follow the same '
    'missing-row rules as default_enabled. Private-spec tools still require API keys at '
    'the tool layer regardless of this flag.';
