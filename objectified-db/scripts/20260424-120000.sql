-- REPO-2.6 / #2767: scan job history tables for repository connector.
SET search_path TO odb, public;

DO $$
BEGIN
  CREATE TYPE odb.repository_scan_trigger AS ENUM ('manual', 'scheduled', 'webhook', 'register');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  CREATE TYPE odb.repository_scan_status AS ENUM (
    'pending',
    'walking',
    'sniffing',
    'complete',
    'failed',
    'skipped_unchanged'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  CREATE TYPE odb.repository_file_status AS ENUM (
    'new',
    'unchanged',
    'modified',
    'removed',
    'parse_error',
    'manifest_error'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE TABLE IF NOT EXISTS odb.repository_scan (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  repository_id UUID NOT NULL REFERENCES odb.repository(id) ON DELETE CASCADE,
  branch VARCHAR(255) NOT NULL,
  commit_sha VARCHAR(64) NOT NULL,
  trigger odb.repository_scan_trigger NOT NULL,
  status odb.repository_scan_status NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  duration_ms INTEGER,
  files_seen INTEGER NOT NULL DEFAULT 0,
  files_classified INTEGER NOT NULL DEFAULT 0,
  files_unknown INTEGER NOT NULL DEFAULT 0,
  files_failed INTEGER NOT NULL DEFAULT 0,
  event_log JSONB NOT NULL DEFAULT '[]'::jsonb,
  diff_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_code VARCHAR(64),
  error_detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_repository_scan_repository_id
  ON odb.repository_scan (repository_id);

CREATE INDEX IF NOT EXISTS idx_repository_scan_repository_created_at
  ON odb.repository_scan (repository_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_repository_scan_repository_branch
  ON odb.repository_scan (repository_id, branch);

CREATE TABLE IF NOT EXISTS odb.repository_file (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  repository_id UUID NOT NULL REFERENCES odb.repository(id) ON DELETE CASCADE,
  scan_id UUID NOT NULL REFERENCES odb.repository_scan(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  blob_sha VARCHAR(64),
  size_bytes INTEGER,
  format VARCHAR(32),
  confidence NUMERIC(3,2),
  discriminator TEXT,
  tracked BOOLEAN NOT NULL DEFAULT FALSE,
  project_slug VARCHAR(128),
  version_strategy VARCHAR(32),
  status odb.repository_file_status NOT NULL,
  quality_score SMALLINT,
  last_import_job_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_repository_file_repository_path
  ON odb.repository_file (repository_id, path);

CREATE INDEX IF NOT EXISTS idx_repository_file_scan_id
  ON odb.repository_file (scan_id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_repository_last_scan_id'
      AND connamespace = 'odb'::regnamespace
      AND conrelid = 'odb.repository'::regclass
  ) THEN
    ALTER TABLE odb.repository
      ADD CONSTRAINT fk_repository_last_scan_id
      FOREIGN KEY (last_scan_id) REFERENCES odb.repository_scan(id) ON DELETE SET NULL;
  END IF;
END
$$;
