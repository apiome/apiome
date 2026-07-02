-- Persisted quality / lint score per schema revision, captured at import time (#3609 follow-up).
--
-- The deterministic quality-scoring service (app.schema_lint, #3609) computes a 0-100 score and an
-- A-F grade for the OpenAPI reconstructed from a revision. That score was only ever computed
-- on-demand (GET .../lint), so a project imported via the CLI / REST worker showed no score in the
-- projects list. These columns let the import capture the score onto the new revision so the
-- projects list can surface it for every import source (not just browser-local snapshots).
--
-- Nullable: pre-existing revisions and revisions created by non-import flows have no captured score
-- until they are (re)linted.

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS quality_score SMALLINT,
  ADD COLUMN IF NOT EXISTS quality_grade TEXT,
  ADD COLUMN IF NOT EXISTS quality_report_fingerprint TEXT;

COMMENT ON COLUMN apiome.versions.quality_score IS
  'Captured deterministic 0-100 quality score (app.schema_lint) for this revision, or NULL if not yet scored.';
COMMENT ON COLUMN apiome.versions.quality_grade IS
  'Captured A-F letter grade derived from quality_score, or NULL if not yet scored.';
COMMENT ON COLUMN apiome.versions.quality_report_fingerprint IS
  'Stable fingerprint of the lint report the captured score came from (lets callers detect staleness).';
