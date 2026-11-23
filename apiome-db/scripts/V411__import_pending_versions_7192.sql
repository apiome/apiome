-- Staged imports awaiting approval (DBP-1.9, #7192).
--
-- The UI import wizard used to keep its database transaction open, on a pooled connection, until
-- the reviewer chose Accept or Reject. From DBP-1.9 the import is committed in a staged state
-- and no connection is held while a person decides:
--
--   * import_pending_at: when the version was staged. A staged version is written with
--     deleted_at set (and so is the project, when the import created it), so every reader that
--     filters on deleted_at IS NULL already leaves it out. Accept clears both columns; Reject
--     deletes the staged rows; a sweeper in apiome-ui deletes the ones nobody decided on.
--   * import_pending: what Reject and the sweeper must undo besides the version itself — whether
--     the import created the project, the project properties it added, and the repository source
--     rows it added or moved. Cleared on Accept.
--   * idx_versions_import_pending: the sweeper's lookup (staged versions, oldest first). Partial,
--     so it stays empty apart from the imports under review.
--
-- Online: both columns are nullable with no default (a catalog-only change), and the partial
-- index is built over zero rows.
--
-- Rollback notes (discard or accept every staged import first — a staged version would otherwise
-- read as an ordinary deleted one):
--   DROP INDEX IF EXISTS apiome.idx_versions_import_pending;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS import_pending;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS import_pending_at;

SET search_path TO apiome, public;

ALTER TABLE apiome.versions
    ADD COLUMN IF NOT EXISTS import_pending_at timestamptz,
    ADD COLUMN IF NOT EXISTS import_pending jsonb;

COMMENT ON COLUMN apiome.versions.import_pending_at IS
  'When an import staged this version for review; NULL for every other version. A staged version '
  'also has deleted_at set, which hides it until the reviewer accepts (DBP-1.9, #7192).';

COMMENT ON COLUMN apiome.versions.import_pending IS
  'What discarding a staged import must undo besides the version: projectCreated, propertyIds, '
  'sourcesCreated, sourcesTouched. NULL once accepted (DBP-1.9, #7192).';

CREATE INDEX IF NOT EXISTS idx_versions_import_pending
    ON apiome.versions (import_pending_at)
    WHERE import_pending_at IS NOT NULL;

DO $$
BEGIN
    RAISE NOTICE 'versions.import_pending_at, import_pending and idx_versions_import_pending added (#7192, DBP-1.9).';
END $$;
