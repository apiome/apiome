-- Checkpoints of the document migration job (COA-5.8, #7084).
--
-- From COA-5.3 / COA-5.5 new imports, freezes and large exports write their bytes to the document
-- store. Rows written before that still hold them in the database:
--
--   * versions.format_metadata.sourceContent       — adapter-pipeline import sources;
--   * version_import_snapshots.source_text         — OpenAPI / Swagger imported through the worker;
--   * version_spec_snapshots.content               — frozen schemas;
--   * export_job_artifact.content                  — export downloads (backend 'db').
--
-- The apiome-rest job app.document_migration (scripts/migrate_documents_to_store.py, or
-- POST /v1/ops/document-migration) copies them into the store in two separate steps, `copy` and
-- `purge`. This table records how far each step got for each source, so an interrupted run resumes
-- after the last row it finished instead of starting over. One row per (scope, step, source):
--
--   * scope    — 'all' for a run over every tenant, else the tenant id the run was limited to;
--   * last_key — the ordering key of the last row the step finished (a revision id or export job id);
--   * counts   — the step's running totals (scanned, copied, purged, skipped, failed, …);
--   * completed_at — set when the step reached the end of the source. The next run then starts
--     from the beginning again, and finds nothing left to do (a re-run is a no-op).
--
-- Online: a new, empty table. Nothing else changes.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.document_migration_checkpoints;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.document_migration_checkpoints (
    scope         text NOT NULL CHECK (length(scope) BETWEEN 1 AND 128),
    step          text NOT NULL CHECK (step IN ('copy', 'purge')),
    source        text NOT NULL
                      CHECK (source IN ('adapter_source', 'import_snapshot', 'frozen_schema', 'export_artifact')),
    last_key      text,
    counts        jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz,
    PRIMARY KEY (scope, step, source)
);

COMMENT ON TABLE apiome.document_migration_checkpoints IS
    'How far the document migration job (COA-5.8, #7084) got per scope, step and source, so an interrupted run resumes.';
COMMENT ON COLUMN apiome.document_migration_checkpoints.scope IS
    '''all'' for a run over every tenant, else the tenant id the run was limited to.';
COMMENT ON COLUMN apiome.document_migration_checkpoints.step IS
    'copy (write to the store, verify, link) or purge (drop the verified database copy).';
COMMENT ON COLUMN apiome.document_migration_checkpoints.source IS
    'adapter_source | import_snapshot | frozen_schema | export_artifact.';
COMMENT ON COLUMN apiome.document_migration_checkpoints.last_key IS
    'Ordering key of the last row the step finished; the next run of an unfinished step starts after it.';
COMMENT ON COLUMN apiome.document_migration_checkpoints.counts IS
    'Running totals of the step: scanned, copied, purged, skipped, failed and similar.';
COMMENT ON COLUMN apiome.document_migration_checkpoints.completed_at IS
    'When the step reached the end of the source; NULL while it is unfinished (resumable).';
