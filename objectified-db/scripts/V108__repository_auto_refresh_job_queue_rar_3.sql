-- Repository auto-refresh job queue (RAR-3.2, #3523).
--
-- RAR-3.1 made the refresh cadence configurable and gave the sweep its
-- due-selection anchor (`last_refreshed_at`). RAR-3.2 is the sweep itself: per
-- due repo it rescans the branch (REPO-2 walker), computes stale + newer files
-- (RAR-2.2/2.3), loads each file's stored import spec (RAR-1.5), and **enqueues a
-- spec-faithful re-import** for the spec-faithful execution epic (RAR-4.1) to
-- consume. This table is that hand-off queue.
--
-- Each job carries a self-contained snapshot of the stored spec — project,
-- source descriptor, and the full `SpecImportOptions` blob — plus the remote
-- freshness signals that triggered it, so the EPIC-4 worker can replay the user's
-- original import without re-reading the spec table (the spec row may change
-- between enqueue and execution). `import_spec_id` is kept as a back-reference but
-- the snapshot is authoritative.
--
-- The partial unique index enforces file-level single-flight: at most one active
-- (queued/running) job per `(repository_id, branch, path)` lineage, so a repeated
-- sweep tick cannot pile up duplicate jobs for the same file before the previous
-- one finishes. Per-repo single-flight across the sweep itself is enforced by a
-- session advisory lock in the worker (RAR-3.2), not in the schema.
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS odb.tenant_repository_refresh_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES odb.tenant_repositories(id) ON DELETE CASCADE,
  import_spec_id UUID REFERENCES odb.repository_import_spec(id) ON DELETE SET NULL,
  branch TEXT NOT NULL,
  path TEXT NOT NULL,
  project_id UUID,
  source_kind VARCHAR(128),
  format_override VARCHAR(64),
  content_type VARCHAR(128),
  options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  spec_schema_version SMALLINT NOT NULL DEFAULT 1,
  created_by UUID,
  remote_commit_sha VARCHAR(64),
  remote_committed_at TIMESTAMPTZ,
  remote_blob_sha VARCHAR(64),
  refresh_reason VARCHAR(64),
  status VARCHAR(32) NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);

-- Queue claim path: oldest queued job first (mirrors the file-scan queue).
CREATE INDEX IF NOT EXISTS idx_tenant_repo_refresh_jobs_queued
  ON odb.tenant_repository_refresh_jobs (created_at)
  WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_tenant_repo_refresh_jobs_repository
  ON odb.tenant_repository_refresh_jobs (repository_id);

-- File-level single-flight: only one active job per imported-file lineage so a
-- re-run of the sweep before EPIC-4 drains the queue does not duplicate work.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_repo_refresh_jobs_active_lineage
  ON odb.tenant_repository_refresh_jobs (repository_id, branch, path)
  WHERE status IN ('queued', 'running');

COMMENT ON TABLE odb.tenant_repository_refresh_jobs IS
  'Postgres-backed queue of spec-faithful re-import jobs produced by the auto-refresh sweep (RAR-3.2) and consumed by spec-faithful execution (RAR-4.1). Each row snapshots the stored import spec plus the remote freshness signals that triggered it.';

COMMENT ON COLUMN odb.tenant_repository_refresh_jobs.options_json IS
  'Snapshot of the full SpecImportOptions blob from the stored import spec at enqueue time; authoritative for replay even if the source spec row later changes.';

COMMENT ON COLUMN odb.tenant_repository_refresh_jobs.refresh_reason IS
  'Stable RAR-2.2 RefreshReason code (for example newer-content) explaining why the sweep enqueued this file.';
