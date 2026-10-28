-- Version retention for live refresh: keep the last N refresh-created versions (MFI-31.5, #4402).
--
-- A daily sweep on a churning endpoint adds a version every day (MFI-31.2). Each catalog item's
-- refresh setting now says how many of those versions to keep:
--
--   1. `catalog_item_refresh.keep_versions` — keep the newest N versions a live refresh created
--      (default 50, 1–1000). Older ones are pruned after each refresh-created version, except
--      versions that are always kept: tagged versions, versions a conversion was made from
--      (`conversion_provenance.source_version_id`), versions whose drift was graded breaking and
--      the version each of them was compared with, locked revisions, and the item's newest version.
--      Versions imported by hand are never pruned.
--   2. `versions.pruned_at` — pruning is a soft delete (`deleted_at`) stamped with `pruned_at`, so a
--      read or diff of a pruned version can answer "pruned by retention" (HTTP 410) rather than
--      "not found".
--
-- Rollback:
--   DROP INDEX IF EXISTS apiome.idx_versions_pruned;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS pruned_at;
--   ALTER TABLE apiome.catalog_item_refresh DROP COLUMN IF EXISTS keep_versions;
SET search_path TO apiome, public;

ALTER TABLE apiome.catalog_item_refresh
    ADD COLUMN IF NOT EXISTS keep_versions INTEGER NOT NULL DEFAULT 50
        CHECK (keep_versions BETWEEN 1 AND 1000);

COMMENT ON COLUMN apiome.catalog_item_refresh.keep_versions IS
    'How many refresh-created versions to keep (MFI-31.5). Older ones are soft-deleted (pruned) unless tagged, a conversion source, breaking drift (or its baseline), locked, or the newest.';

ALTER TABLE apiome.versions
    ADD COLUMN IF NOT EXISTS pruned_at TIMESTAMPTZ;

COMMENT ON COLUMN apiome.versions.pruned_at IS
    'Set with deleted_at when live-refresh retention pruned the version (MFI-31.5); NULL for any other delete.';

CREATE INDEX IF NOT EXISTS idx_versions_pruned
    ON apiome.versions (project_id)
    WHERE pruned_at IS NOT NULL;
