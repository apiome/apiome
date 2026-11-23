-- Project property digest for set-based source apply (DBP-1.7, #7190).
--
-- A source apply links each class property to the project property that has the same definition
-- (apiome.properties.data). It found that property by loading the project's whole library into
-- the REST process and comparing JSON text there. From DBP-1.7 the database does the match:
--
--   * data_digest: md5 of the property's canonical jsonb text, kept by PostgreSQL as a stored
--     generated column, so every writer (REST, UI, importers) gets it without a code change and
--     it can never disagree with data. Equal jsonb values always have equal text, so equal
--     definitions have equal digests whatever key order they were written with.
--   * idx_properties_project_data_digest (project_id, data_digest): the lookup a source apply
--     makes, one index probe per distinct definition in the edit.
--
-- Not online: adding a stored generated column rewrites apiome.properties under an ACCESS
-- EXCLUSIVE lock (about a second per million rows), and the index is built in the same
-- transaction. Run it in a maintenance window on a large library.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_properties_project_data_digest;
--   ALTER TABLE apiome.properties DROP COLUMN IF EXISTS data_digest;

SET search_path TO apiome, public;

ALTER TABLE apiome.properties
    ADD COLUMN IF NOT EXISTS data_digest text GENERATED ALWAYS AS (md5(data::text)) STORED;

COMMENT ON COLUMN apiome.properties.data_digest IS
  'md5 of data''s canonical jsonb text, generated. Source apply matches a class property to the '
  'project property with the same definition through it (DBP-1.7, #7190).';

CREATE INDEX IF NOT EXISTS idx_properties_project_data_digest
    ON apiome.properties (project_id, data_digest);

DO $$
BEGIN
    RAISE NOTICE 'properties.data_digest and idx_properties_project_data_digest added (#7190, DBP-1.7).';
END $$;
