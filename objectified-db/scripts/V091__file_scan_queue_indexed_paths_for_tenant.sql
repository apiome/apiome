-- File scan queue + indexed paths for tenant repositories (default branch).
SET search_path TO odb, public;

ALTER TABLE odb.tenant_repositories
  ADD COLUMN IF NOT EXISTS linked_account_id UUID REFERENCES odb.external_auth_providers(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS last_scanned_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS total_files INTEGER,
  ADD COLUMN IF NOT EXISTS importable_count INTEGER;

COMMENT ON COLUMN odb.tenant_repositories.linked_account_id IS
  'OAuth link used for this registration (linked_account source); used by scan worker to fetch GitHub tree.';

CREATE TABLE IF NOT EXISTS odb.tenant_repository_file_scan_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES odb.tenant_repositories(id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tenant_repo_file_scan_jobs_queued
  ON odb.tenant_repository_file_scan_jobs (created_at)
  WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_tenant_repo_file_scan_jobs_repository
  ON odb.tenant_repository_file_scan_jobs (repository_id);

COMMENT ON TABLE odb.tenant_repository_file_scan_jobs IS
  'Postgres-backed queue for indexing repository tree contents (GitHub API for now).';

CREATE TABLE IF NOT EXISTS odb.tenant_repository_files (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  repository_id UUID NOT NULL REFERENCES odb.tenant_repositories(id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  ext VARCHAR(64),
  size_bytes BIGINT,
  blob_sha VARCHAR(64),
  detected_kind VARCHAR(128),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_tenant_repository_files_repo_branch_path UNIQUE (repository_id, branch, path)
);

CREATE INDEX IF NOT EXISTS idx_tenant_repository_files_repo_branch
  ON odb.tenant_repository_files (repository_id, branch);

CREATE INDEX IF NOT EXISTS idx_tenant_repository_files_detected_kind
  ON odb.tenant_repository_files (repository_id, detected_kind);

COMMENT ON TABLE odb.tenant_repository_files IS
  'One row per file path discovered on a branch (Git tree blob); re-written each successful scan.';
