-- Frozen schemas as document store objects (COA-5.5, #7081).
--
-- A frozen version's OpenAPI document (#3214, V279) was stored in
-- apiome.version_spec_snapshots.content. From COA-5.5 the bytes are a document store object
-- linked to the revision by a version_documents row with role 'frozen_schema'; the snapshot row
-- keeps the metadata (sha256, size, counts, who froze it, download count).
--
--   * content becomes nullable. With the s3 and filesystem backends a new freeze leaves it NULL;
--     the db backend keeps writing it, as it does for import sources (COA-5.3). Rows written
--     before this migration keep their bytes until the migration job (COA-5.8, #7084) moves them.
--
-- The rendered document cache (apiome-rest app.rendered_documents) needs no schema change: it
-- reads version_documents through version_documents_slot_key (V403).
--
-- Online: DROP NOT NULL is a catalog-only change.
--
-- Rollback notes (only while no row has a NULL content):
--   ALTER TABLE apiome.version_spec_snapshots ALTER COLUMN content SET NOT NULL;

SET search_path TO apiome, public;

ALTER TABLE apiome.version_spec_snapshots ALTER COLUMN content DROP NOT NULL;

COMMENT ON COLUMN apiome.version_spec_snapshots.content IS
  'Exact response bytes served by GET /v1/schema while frozen. NULL when the bytes live in the '
  'document store as the revision''s frozen_schema object (COA-5.5, #7081); sha256 names it.';

DO $$
BEGIN
    RAISE NOTICE 'version_spec_snapshots.content is nullable (#7081, COA-5.5).';
END $$;
