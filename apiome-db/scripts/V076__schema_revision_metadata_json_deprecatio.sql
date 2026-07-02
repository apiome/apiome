-- Schema revision metadata (JSON): deprecation, sunset, successor pointers (#507, aligns with #748/#749).
SET search_path TO apiome, public;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN versions.metadata IS 'Extensible JSON: revisionDeprecation flags (deprecated, message, successorRevisionId, sunsetDate), etc.';

CREATE INDEX IF NOT EXISTS idx_versions_metadata_deprecated
  ON versions ((metadata->>'deprecated'))
  WHERE deleted_at IS NULL AND COALESCE(metadata->>'deprecated', '') IN ('true', '1');
