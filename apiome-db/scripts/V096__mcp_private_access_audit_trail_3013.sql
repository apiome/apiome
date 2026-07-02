-- MCP private access audit trail (#3013).
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_access_audit (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  key_id UUID REFERENCES apiome.mcp_api_keys(id) ON DELETE SET NULL,
  tool TEXT NOT NULL,
  spec_id UUID NOT NULL REFERENCES apiome.versions(id),
  at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  success BOOLEAN NOT NULL,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_access_audit_key_at ON apiome.mcp_access_audit (key_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_access_audit_spec_at ON apiome.mcp_access_audit (spec_id, at DESC);

COMMENT ON TABLE apiome.mcp_access_audit IS
  'Append-only audit of MCP tool reads that expose private published revisions (#3013).';

COMMENT ON COLUMN apiome.mcp_access_audit.key_id IS
  'API key used for the read; NULL if the key row was deleted after the event.';

COMMENT ON COLUMN apiome.mcp_access_audit.tool IS
  'MCP tool name (e.g. spec.list, spec.describe).';

COMMENT ON COLUMN apiome.mcp_access_audit.spec_id IS
  'Schema revision id (versions.id) that was returned from the private branch.';

COMMENT ON COLUMN apiome.mcp_access_audit.success IS
  'Whether the read completed successfully (reserved for future failure logging).';

COMMENT ON COLUMN apiome.mcp_access_audit.error IS
  'Optional error detail when success is false.';
