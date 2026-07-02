-- Tenant-registered Git repositories (dashboard / control panel).
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS tenant_repositories (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  source VARCHAR(32) NOT NULL CHECK (source IN ('public_url', 'linked_account')),
  provider VARCHAR(32) NOT NULL,
  clone_url TEXT NOT NULL,
  clone_url_normalized TEXT NOT NULL,
  repository_full_name VARCHAR(512),
  description TEXT,
  default_branch VARCHAR(255) NOT NULL DEFAULT 'main',
  visibility VARCHAR(16),
  status VARCHAR(32) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'scanning', 'ready', 'error', 'archived')),
  created_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_repositories_tenant_clone_norm_active
  ON apiome.tenant_repositories (tenant_id, clone_url_normalized)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tenant_repositories_tenant_id
  ON apiome.tenant_repositories (tenant_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE apiome.tenant_repositories IS
  'Repositories registered per tenant for scanning/import (dashboard).';

COMMENT ON COLUMN apiome.tenant_repositories.clone_url_normalized IS
  'Normalized clone URL for deduplication within a tenant';
