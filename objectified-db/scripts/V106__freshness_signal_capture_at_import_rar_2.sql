-- Freshness signal capture at import (RAR-2.1, #3518).
--
-- The system stored `blob_sha` but no comparable recency signal, and the scan
-- does a wholesale DELETE/INSERT, so per-file recency was lost. Without a recency
-- anchor there is nothing to compare "newer than" against (RAR-2.2).
--
-- Two changes:
--   1. The scan now records the branch tip commit it observed (the commit SHA and
--      its committed-at timestamp, already returned by the provider branch/tree API
--      used in repository_file_scan.py) on every indexed file row.
--   2. The import lineage (`odb.repository_import_spec`) now records the freshness
--      signals captured at the moment of import — `last_imported_commit_sha`,
--      `last_imported_committed_at`, `last_imported_blob_sha` — copied from the
--      indexed file row when the spec is written. A later auto-refresh compares the
--      repository's current state against these anchors to gate "newer-than"
--      re-imports (RAR-2.2) and surfaces them via the RAR-1.5 read endpoint.
SET search_path TO odb, public;

-- 1. Scan-side recency: the branch tip commit observed for each indexed file.
ALTER TABLE odb.tenant_repository_files
  ADD COLUMN IF NOT EXISTS commit_sha VARCHAR(64),
  ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ;

COMMENT ON COLUMN odb.tenant_repository_files.commit_sha IS
  'Branch tip commit SHA observed by the scan that indexed this file row (RAR-2.1).';

COMMENT ON COLUMN odb.tenant_repository_files.committed_at IS
  'Committed-at timestamp of the branch tip commit observed by the scan (RAR-2.1); the recency signal compared against the import anchor for newer-than gating (RAR-2.2).';

-- 2. Import-anchor: freshness signals captured at import time on the file lineage.
ALTER TABLE odb.repository_import_spec
  ADD COLUMN IF NOT EXISTS last_imported_commit_sha VARCHAR(64),
  ADD COLUMN IF NOT EXISTS last_imported_committed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_imported_blob_sha VARCHAR(64);

COMMENT ON COLUMN odb.repository_import_spec.last_imported_commit_sha IS
  'Branch tip commit SHA observed for this file at the time of import (RAR-2.1).';

COMMENT ON COLUMN odb.repository_import_spec.last_imported_committed_at IS
  'Committed-at timestamp of the file at the time of import; the anchor a later auto-refresh compares the remote committed_at against to gate newer-than re-imports (RAR-2.1/RAR-2.2).';

COMMENT ON COLUMN odb.repository_import_spec.last_imported_blob_sha IS
  'Blob SHA of the file content at the time of import (RAR-2.1).';
