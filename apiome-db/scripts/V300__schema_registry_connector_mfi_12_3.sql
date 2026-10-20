-- Schema-registry discovery connector: where a mirrored subject came from (MFI-12.3, #3784).
--
-- A `schema-registry` connector crawls an upstream Confluent, Apicurio (ccompat API) or Karapace
-- registry and mirrors each upstream subject into the CDG-4.2 subject model: the subject keeps its
-- name, each upstream version becomes a subject version backed by a catalog item revision, and the
-- upstream compatibility level is copied onto the subject. The rows need to say where they came from:
--
--   * `schema_subjects.source_ref` — `registry:<registry url>` for a mirrored subject, NULL for a
--     subject registered or attached in Apiome.
--   * `schema_subjects.source_connector_id` — the connector that mirrors the subject. A subject owned
--     by one connector is never written by another connector, nor taken over from a local subject.
--     SET NULL, never CASCADE: deleting the connector leaves the mirrored subjects and their history.
--   * `schema_subject_versions.upstream_version` / `upstream_schema_id` — the upstream registry's
--     version number and global schema id. Local version numbers are Apiome's own (an upstream
--     registry may have gaps from deleted versions); these keep the upstream coordinates beside them.
--     NULL for a version registered in Apiome.
--
-- Rollback:
--   DROP INDEX IF EXISTS apiome.uq_schema_subject_versions_upstream;
--   DROP INDEX IF EXISTS apiome.idx_schema_subjects_source_connector;
--   ALTER TABLE apiome.schema_subject_versions
--     DROP COLUMN IF EXISTS upstream_version, DROP COLUMN IF EXISTS upstream_schema_id;
--   ALTER TABLE apiome.schema_subjects
--     DROP COLUMN IF EXISTS source_ref, DROP COLUMN IF EXISTS source_connector_id;
SET search_path TO apiome, public;

ALTER TABLE apiome.schema_subjects
    ADD COLUMN IF NOT EXISTS source_ref TEXT
        CHECK (source_ref IS NULL OR (length(source_ref) <= 2100 AND source_ref LIKE 'registry:%')),
    ADD COLUMN IF NOT EXISTS source_connector_id UUID
        REFERENCES apiome.catalog_connectors(id) ON DELETE SET NULL;

ALTER TABLE apiome.schema_subject_versions
    ADD COLUMN IF NOT EXISTS upstream_version INTEGER
        CHECK (upstream_version IS NULL OR upstream_version >= 1),
    ADD COLUMN IF NOT EXISTS upstream_schema_id INTEGER
        CHECK (upstream_schema_id IS NULL OR upstream_schema_id >= 0);

CREATE INDEX IF NOT EXISTS idx_schema_subjects_source_connector
    ON apiome.schema_subjects (source_connector_id)
    WHERE source_connector_id IS NOT NULL;

-- One local version per upstream version of a mirrored subject.
CREATE UNIQUE INDEX IF NOT EXISTS uq_schema_subject_versions_upstream
    ON apiome.schema_subject_versions (subject_id, upstream_version)
    WHERE upstream_version IS NOT NULL;

COMMENT ON COLUMN apiome.schema_subjects.source_ref IS
    'registry:<url> for a subject mirrored from an upstream schema registry by a schema-registry connector (MFI-12.3); NULL for a subject registered or attached in Apiome.';
COMMENT ON COLUMN apiome.schema_subjects.source_connector_id IS
    'The schema-registry connector that mirrors this subject (MFI-12.3). Only that connector writes it.';
COMMENT ON COLUMN apiome.schema_subject_versions.upstream_version IS
    'The upstream registry''s version number of a mirrored version (MFI-12.3); NULL when registered in Apiome.';
COMMENT ON COLUMN apiome.schema_subject_versions.upstream_schema_id IS
    'The upstream registry''s global schema id of a mirrored version (MFI-12.3); NULL when registered in Apiome.';
