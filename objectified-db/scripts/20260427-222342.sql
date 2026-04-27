-- REPO-11.3 / #2943: per-tenant user settings (dashboard import-attention dismissals, etc.)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS odb.user_settings (
  user_id UUID NOT NULL REFERENCES odb.users(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_user_settings_tenant_id
  ON odb.user_settings (tenant_id);

COMMENT ON TABLE odb.user_settings IS
  'Tenant-scoped preferences JSON per user (dashboard dismissals, UI flags).';
