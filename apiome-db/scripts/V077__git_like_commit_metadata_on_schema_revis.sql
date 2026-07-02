-- Git-like commit metadata on schema revisions (#2563, P0-01): author, full message, external ticket ref.
SET search_path TO apiome, public;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS commit_author TEXT,
  ADD COLUMN IF NOT EXISTS commit_message TEXT,
  ADD COLUMN IF NOT EXISTS external_ref TEXT;

COMMENT ON COLUMN versions.commit_author IS 'Optional commit author string (may differ from creator account; audit / CI identity)';
COMMENT ON COLUMN versions.commit_message IS 'Optional full commit message body (distinct from description/shortMessage one-liner)';
COMMENT ON COLUMN versions.external_ref IS 'External work item reference (e.g. Jira, Linear issue key or URL)';
