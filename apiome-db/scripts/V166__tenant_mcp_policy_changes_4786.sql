-- Tenant MCP policy change audit ledger — MTG-5.2 (#4786).
--
-- Problem: compliance reviewers need who changed which MCP tool settings and when.
-- Live policy rows in tenant_mcp_policies / tenant_mcp_policy_tools are overwrite-only
-- (MTG-3.1 / #4775); there is no before/after history.
--
-- Solution: append-only sibling table storing JSONB policy snapshots on each admin PUT.
-- Shape mirrors the REST TenantMcpPolicy body (no secrets):
--   { default_mode, allow_anonymous_mcp,
--     tools: [{ tool_id, in_ceiling, default_enabled, anonymous_enabled }] }
--
-- Retention: recommend purging rows older than 90 days via a future sweep job.
-- No sweeper ships in this migration.
--
-- Rollback notes: purely additive.
--   DROP TABLE IF EXISTS apiome.tenant_mcp_policy_changes;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS tenant_mcp_policy_changes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    actor_user_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_label     TEXT,
    before_policy   JSONB NOT NULL,
    after_policy    JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenant_mcp_policy_changes_tenant_at
    ON apiome.tenant_mcp_policy_changes (tenant_id, created_at DESC);

COMMENT ON TABLE apiome.tenant_mcp_policy_changes IS
    'Append-only audit of tenant MCP policy PUT changes (MTG-5.2 / #4786). '
    'Stores before/after JSONB snapshots of default_mode, allow_anonymous_mcp, and tool flags. '
    'Never store API keys, Authorization headers, or secrets. '
    'Intended retention: purge rows older than 90 days via a future sweep job (not implemented here).';

COMMENT ON COLUMN apiome.tenant_mcp_policy_changes.tenant_id IS
    'Tenant whose MCP policy was replaced.';

COMMENT ON COLUMN apiome.tenant_mcp_policy_changes.actor_user_id IS
    'User who performed the PUT; NULL if the user row was deleted after the event.';

COMMENT ON COLUMN apiome.tenant_mcp_policy_changes.actor_label IS
    'Human-readable actor email or name at write time (access_audit style).';

COMMENT ON COLUMN apiome.tenant_mcp_policy_changes.before_policy IS
    'JSONB snapshot of the policy before the PUT (or empty/default shape when unseeded).';

COMMENT ON COLUMN apiome.tenant_mcp_policy_changes.after_policy IS
    'JSONB snapshot of the policy after the PUT.';

COMMENT ON COLUMN apiome.tenant_mcp_policy_changes.created_at IS
    'When the policy change was recorded.';
