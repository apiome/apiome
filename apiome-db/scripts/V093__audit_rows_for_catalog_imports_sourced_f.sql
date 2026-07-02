-- Audit rows for catalog imports sourced from a registered tenant repository (dashboard metrics).
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.tenant_repository_imports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES apiome.tenant_repositories(id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  path TEXT NOT NULL,
  blob_sha VARCHAR(64),
  project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
  version_id UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
  imported_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenant_repository_imports_repo_created
  ON apiome.tenant_repository_imports (repository_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tenant_repository_imports_tenant_repo
  ON apiome.tenant_repository_imports (tenant_id, repository_id);

COMMENT ON TABLE apiome.tenant_repository_imports IS
  'One row per successful catalog import whose source was a file from tenant_repositories (repository browser).';
