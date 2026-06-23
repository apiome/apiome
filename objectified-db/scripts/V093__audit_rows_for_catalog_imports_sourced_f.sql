-- Audit rows for catalog imports sourced from a registered tenant repository (dashboard metrics).
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS odb.tenant_repository_imports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES odb.tenant_repositories(id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  path TEXT NOT NULL,
  blob_sha VARCHAR(64),
  project_id UUID NOT NULL REFERENCES odb.projects(id) ON DELETE CASCADE,
  version_id UUID NOT NULL REFERENCES odb.versions(id) ON DELETE CASCADE,
  imported_by UUID REFERENCES odb.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenant_repository_imports_repo_created
  ON odb.tenant_repository_imports (repository_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tenant_repository_imports_tenant_repo
  ON odb.tenant_repository_imports (tenant_id, repository_id);

COMMENT ON TABLE odb.tenant_repository_imports IS
  'One row per successful catalog import whose source was a file from tenant_repositories (repository browser).';
