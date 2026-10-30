-- Refresh URL-sourced imports (RAR-6.1, #3538).
--
-- The repository auto-refresh (RAR-EPIC-1..5) covers files in a linked Git repository. A spec a
-- person imported into a project from a URL (the import wizard's **URL Import** source) never
-- refreshed, though the document behind the URL keeps changing. This table is the URL lineage:
-- one row per (project, URL), recorded after a successful URL import, holding
--
--   * the stored import spec (source kind, source descriptor, verbatim options blob) so a refresh
--     replays the original import (RAR-1.x, RAR-4.1);
--   * the HTTP validators the server answered with (`etag`, `last_modified`) and the SHA-256 of the
--     document, the freshness anchors: a refresh sends `If-None-Match` / `If-Modified-Since`, a
--     304 skips, and a 200 is gated by the RAR-2.2 newer-than comparator on Last-Modified and the
--     checksum;
--   * the version the last import produced and a checksum of its rendered OpenAPI, so an edit made
--     in Apiome after the import holds the refresh instead of being overwritten (RAR-4.4);
--   * the cadence, the opt-out, backoff, and the in-flight import job.
--
-- Only public URLs refresh: an import fetched with credentials is recorded with
-- `authenticated = TRUE`, which the sweep never selects, and no credential is stored anywhere.
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.url_import_specs;
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.url_import_specs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    source_kind VARCHAR(128) NOT NULL DEFAULT 'openapi',
    format_override VARCHAR(64),
    content_type VARCHAR(128),
    options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    spec_schema_version SMALLINT NOT NULL DEFAULT 1,
    created_by UUID,
    authenticated BOOLEAN NOT NULL DEFAULT FALSE,
    auto_refresh_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    refresh_interval_seconds INTEGER CHECK (refresh_interval_seconds IS NULL OR refresh_interval_seconds > 0),
    etag TEXT,
    last_modified TEXT,
    content_checksum VARCHAR(64),
    last_version_id UUID,
    post_import_checksum VARCHAR(64),
    last_checked_at TIMESTAMPTZ,
    last_refreshed_at TIMESTAMPTZ,
    last_status VARCHAR(32)
        CHECK (last_status IS NULL OR last_status IN ('up-to-date', 'refreshing', 'refreshed', 'diverged', 'failed')),
    last_reason VARCHAR(64),
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    backoff_until TIMESTAMPTZ,
    pending_job_id TEXT,
    pending_etag TEXT,
    pending_last_modified TEXT,
    pending_checksum VARCHAR(64),
    pending_started_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_url_import_specs_project_url UNIQUE (project_id, url)
);

-- Due-selection: refresh-eligible rows by when they were last checked.
CREATE INDEX IF NOT EXISTS idx_url_import_specs_due
    ON apiome.url_import_specs (last_checked_at NULLS FIRST)
    WHERE auto_refresh_enabled AND NOT authenticated;

CREATE INDEX IF NOT EXISTS idx_url_import_specs_tenant
    ON apiome.url_import_specs (tenant_id, updated_at DESC);

COMMENT ON TABLE apiome.url_import_specs IS
    'URL-sourced import lineage for auto-refresh (RAR-6.1): the stored import spec, the HTTP validators and checksum of the imported document, the version it produced, and refresh state.';
COMMENT ON COLUMN apiome.url_import_specs.authenticated IS
    'The import was fetched with credentials. Never refreshed: credentials are not stored.';
COMMENT ON COLUMN apiome.url_import_specs.post_import_checksum IS
    'SHA-256 of the rendered OpenAPI of last_version_id right after it was imported; a different current checksum means the version was edited in Apiome (RAR-4.4 hold).';
COMMENT ON COLUMN apiome.url_import_specs.pending_job_id IS
    'The spec-import job a refresh started; the validators it fetched (pending_*) become the anchors once the job succeeds.';
