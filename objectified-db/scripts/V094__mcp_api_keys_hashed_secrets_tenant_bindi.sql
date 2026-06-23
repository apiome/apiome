-- MCP API keys: hashed secrets, tenant binding, JSON scopes (#2997).
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS mcp_api_keys (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  key_hash VARCHAR(255) NOT NULL UNIQUE,
  prefix VARCHAR(32) NOT NULL,
  label TEXT NOT NULL,
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  scope_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES odb.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  CONSTRAINT chk_mcp_api_keys_expires_after_created
    CHECK (expires_at IS NULL OR expires_at >= created_at),
  CONSTRAINT chk_mcp_api_keys_revoked_after_created
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_prefix ON odb.mcp_api_keys (prefix);

COMMENT ON TABLE odb.mcp_api_keys IS
  'MCP authentication keys (#2997); column and constraint comments document invariants.';

COMMENT ON COLUMN odb.mcp_api_keys.key_hash IS
  'Bcrypt (or equivalent) hash of the full secret; never store plaintext.';

COMMENT ON COLUMN odb.mcp_api_keys.prefix IS
  'Non-secret prefix copied from the issued key for indexed lookup before hash verification.';

COMMENT ON COLUMN odb.mcp_api_keys.scope_json IS
  'Read scope JSON: {"tenants":[uuid,...],"projects":[uuid,...]}. Empty lists = public at that dimension; see objectified_mcp.scope.Scope (#3001).';

COMMENT ON COLUMN odb.mcp_api_keys.revoked_at IS
  'When set, the key must be rejected regardless of expires_at.';

COMMENT ON CONSTRAINT chk_mcp_api_keys_expires_after_created ON odb.mcp_api_keys IS
  'expires_at must be NULL or on/after created_at.';

COMMENT ON CONSTRAINT chk_mcp_api_keys_revoked_after_created ON odb.mcp_api_keys IS
  'revoked_at must be NULL or on/after created_at.';
