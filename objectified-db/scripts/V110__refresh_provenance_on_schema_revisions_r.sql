-- Refresh provenance on schema revisions (RAR-4.2, #3528).
--
-- A repository auto-refresh (RAR-EPIC-4) re-imports a changed file and creates a
-- NEW catalog version. That version must be traceable back to the exact source
-- commit that triggered the refresh and to the prior version it supersedes.
--
-- `parent_version_id` (the prior-version link) already exists on `versions`
-- (20260409-140000.sql); REPO-12.3 added commit metadata (20260411-120000.sql).
-- This migration extends that provenance with the refresh lineage tuple the auto-
-- refresh request carries on the `odb.tenant_repository_refresh_jobs` row
-- (`remote_commit_sha` / `remote_committed_at`, RAR-3.2):
--
--   prior version --parent_version_id--> new version { source_commit_sha, source_committed_at }
SET search_path TO odb, public;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS source_commit_sha VARCHAR(64),
  ADD COLUMN IF NOT EXISTS source_committed_at TIMESTAMPTZ;

COMMENT ON COLUMN versions.source_commit_sha IS
  'Repository source commit SHA that triggered this revision (RAR-4.2 refresh provenance); NULL for non-repository / hand-authored revisions.';
COMMENT ON COLUMN versions.source_committed_at IS
  'Commit timestamp of source_commit_sha (RAR-4.2 refresh provenance); pairs with source_commit_sha to record refresh lineage.';

-- Trace every revision produced from a given source commit (refresh audit / dedup).
CREATE INDEX IF NOT EXISTS idx_versions_source_commit_sha
  ON versions (source_commit_sha)
  WHERE source_commit_sha IS NOT NULL;
