-- Registry-crawl checkpoint: where a connector's crawl got to (MFI-31.4, #4401).
--
-- A schema-registry connector can front thousands of subjects. Each sync spends a bounded budget
-- (requests, pages, bytes) and records here where it stopped, so the next sync resumes instead of
-- starting from zero, and a sync that was killed loses at most the subject it was on:
--
--   * `cursor`, `pass_started_at` — the full pass in progress: the last subject settled (in name
--     order) and when the pass began. Both NULL when no full pass is in progress.
--   * `last_full_pass_at` — when the last full pass finished. Between full passes (the scope's
--     `fullPassHours`) a sync is incremental.
--   * `watermark` — the incremental watermark: the highest global schema id seen. An incremental
--     sync asks the registry which subjects use the ids above it and reads only those.
--   * `probe_supported` — whether the registry answers that question (NULL until tried).
--   * `extra` — crawl-specific state.
--
-- Deleting the connector deletes its checkpoint.
--
-- Rollback:
--   DROP TABLE IF EXISTS apiome.catalog_connector_crawl_state;
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.catalog_connector_crawl_state (
    connector_id       UUID PRIMARY KEY REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE,
    cursor             TEXT,
    pass_started_at    TIMESTAMPTZ,
    last_full_pass_at  TIMESTAMPTZ,
    watermark          BIGINT CHECK (watermark IS NULL OR watermark >= 0),
    probe_supported    BOOLEAN,
    extra              JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.catalog_connector_crawl_state IS
    'Crawl checkpoint per connector (MFI-31.4): the full pass in progress and its cursor, the last full pass, and the incremental schema-id watermark.';
