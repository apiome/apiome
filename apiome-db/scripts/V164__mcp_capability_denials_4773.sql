-- Denied-call audit trail — MTG-2.4 (#4773).
--
-- Problem: governance without telemetry is incomplete—admins need to know when
-- agents attempted blocked MCP tools (MTG-2.2 capability gate).
--
-- Solution: append-only sibling of mcp_access_audit (V096/#3013) focused on
-- capability denials. mcp_access_audit is private-spec-read shaped (spec_id
-- NOT NULL); this table records key_id (nullable), tenant_id, tool_id, at,
-- transport, and DenyReason — never tool arguments or secrets.
--
-- Retention: recommend purging rows older than 90 days via a future sweep job.
-- No sweeper ships in this migration.
--
-- Rollback notes: purely additive.
--   DROP TABLE IF EXISTS apiome.mcp_capability_denials;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_capability_denials (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_id     UUID REFERENCES apiome.mcp_api_keys(id) ON DELETE SET NULL,
    tenant_id  UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    tool_id    TEXT NOT NULL
               CONSTRAINT mcp_capability_denials_tool_id_nonempty
               CHECK (char_length(trim(tool_id)) > 0),
    at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transport  TEXT NOT NULL
               CONSTRAINT mcp_capability_denials_transport_ck
               CHECK (transport IN ('stdio', 'http')),
    reason     TEXT NOT NULL
               CONSTRAINT mcp_capability_denials_reason_nonempty
               CHECK (char_length(trim(reason)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_mcp_capability_denials_tenant_at
    ON apiome.mcp_capability_denials (tenant_id, at DESC);

CREATE INDEX IF NOT EXISTS idx_mcp_capability_denials_key_at
    ON apiome.mcp_capability_denials (key_id, at DESC)
    WHERE key_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_capability_denials_tool_at
    ON apiome.mcp_capability_denials (tool_id, at DESC);

COMMENT ON TABLE apiome.mcp_capability_denials IS
    'Append-only audit of authenticated MCP tools/call capability denials (MTG-2.4 / #4773). '
    'Never store tool arguments, Authorization headers, or secrets. '
    'Intended retention: purge rows older than 90 days via a future sweep job (not implemented here).';

COMMENT ON COLUMN apiome.mcp_capability_denials.key_id IS
    'MCP API key that attempted the call; NULL if the key row was deleted after the event.';

COMMENT ON COLUMN apiome.mcp_capability_denials.tenant_id IS
    'Tenant that owns the key / policy that denied the call.';

COMMENT ON COLUMN apiome.mcp_capability_denials.tool_id IS
    'MCP tool name from tools/call (e.g. spec.search); never includes arguments.';

COMMENT ON COLUMN apiome.mcp_capability_denials.at IS
    'When the denial occurred (issue field ts).';

COMMENT ON COLUMN apiome.mcp_capability_denials.transport IS
    'MCP transport that carried the call: stdio or http (streamable HTTP).';

COMMENT ON COLUMN apiome.mcp_capability_denials.reason IS
    'First failing DenyReason from the MTG-1.4 effective resolver '
    '(not_in_registry, not_in_ceiling, not_in_default_enable_set, '
    'not_in_key_enable_set, invalid_key_mode) or stable capability_disabled fallback.';
