-- Class names are unique among a version's *live* classes only (#3231, CLI 7.3 `apiome classes create`).
--
-- Deleting a class is a soft delete (deleted_at), but classes_version_name_unique (V005) covered
-- every row, so a deleted class kept its name taken: re-creating "Refund" after deleting it failed
-- with 409, in the Studio as much as in the CLI — and `classes create` could not roll back a
-- half-made class (delete it) and let the user retry with the same name.
--
-- The table constraint becomes a partial unique index over live rows. Live classes stay unique by
-- (version_id, name); soft-deleted ones no longer count. No code uses ON CONFLICT on the old
-- constraint, and violations still read "violates unique constraint", which apiome-rest maps to 409.
--
-- Rollback (fails while a deleted class shares a live class's name in the same version):
--   DROP INDEX IF EXISTS apiome.classes_version_name_live_unique;
--   ALTER TABLE apiome.classes ADD CONSTRAINT classes_version_name_unique UNIQUE (version_id, name);

SET search_path TO apiome, public;

ALTER TABLE apiome.classes DROP CONSTRAINT IF EXISTS classes_version_name_unique;

CREATE UNIQUE INDEX IF NOT EXISTS classes_version_name_live_unique
    ON apiome.classes (version_id, name)
    WHERE deleted_at IS NULL;

COMMENT ON INDEX apiome.classes_version_name_live_unique IS
    'Class names are unique among a version''s live classes; soft-deleted classes free their name (#3231).';
