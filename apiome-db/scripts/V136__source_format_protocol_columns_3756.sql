-- Source-format & protocol columns on the version/revision model (#3756, MFI-7.1).
--
-- Problem: the catalog cannot currently say what *kind* of API a revision is. The canonical-model
-- persistence tables (MFI-2.2, V135) do carry `format`/`protocol` on `api_artifacts`, but an
-- `api_artifacts` row only exists once the full normalizer pipeline has run; every import — including
-- OpenAPI/Arazzo specs that predate the canonical model, and imports where only the spec is stored —
-- always produces a `versions` row. Browse/search facets (MFI-EPIC-6) and the catalog-item projection
-- therefore need the source format + protocol on the universally-present `versions` row so *every*
-- revision is faceted, regardless of whether its canonical model has been persisted.
--
-- This mirrors V124 (quality score/grade captured at import on `versions`): purely additive, nullable
-- columns the import adapters populate as they ingest a source, plus facet indexes.
--
--   source_format         -- the detected source format key (e.g. openapi-3.1, asyncapi-3, grpc,
--                            graphql, avro, arazzo); same vocabulary as api_artifacts.format.
--   protocol              -- primary transport protocol (http, grpc, kafka, graphql-over-http, …);
--                            same vocabulary as api_artifacts.protocol.
--   source_tool_versions  -- JSONB map of the tools/parsers used at import → their version
--                            (e.g. {"protoc": "3.21.12", "buf": "1.28.1"}); informational provenance,
--                            surfaced by the catalog endpoint as `tool_versions`.
--
-- Nullability: all three are nullable / default-empty. Pre-existing revisions and revisions created
-- by non-import flows carry no format/protocol until the one-off backfill (MFI-7.3, #3758) tags them.
-- Population by the format adapters at import is wired in the import path (apiome-rest/CLI); this
-- migration only provides the schema home + facet indexes.
--
-- Indexing: the two facet dimensions (source_format, protocol) each get a partial btree index scoped
-- to live, non-null rows. They are sparse until backfill, so `WHERE deleted_at IS NULL AND <col> IS
-- NOT NULL` keeps the indexes lean while still serving equality filters and per-facet counts; a
-- combined protocol+format filter is served by a bitmap-AND of the two. `source_tool_versions` is
-- provenance, not a facet, so it is intentionally not indexed.
--
-- Rollback notes: purely additive. To roll back:
--   DROP INDEX IF EXISTS apiome.idx_versions_source_format, apiome.idx_versions_protocol;
--   ALTER TABLE apiome.versions
--     DROP COLUMN IF EXISTS source_format,
--     DROP COLUMN IF EXISTS protocol,
--     DROP COLUMN IF EXISTS source_tool_versions;

SET search_path TO apiome, public;

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS source_format VARCHAR(128),
  ADD COLUMN IF NOT EXISTS protocol VARCHAR(64),
  ADD COLUMN IF NOT EXISTS source_tool_versions JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN apiome.versions.source_format IS
  'Detected source format key for this revision (e.g. openapi-3.1, asyncapi-3, grpc, graphql, avro, arazzo); same vocabulary as api_artifacts.format. NULL until populated by an import adapter or the MFI-7.3 backfill.';
COMMENT ON COLUMN apiome.versions.protocol IS
  'Primary transport protocol of the source (http, grpc, kafka, graphql-over-http, …); same vocabulary as api_artifacts.protocol. NULL when not applicable or not yet populated.';
COMMENT ON COLUMN apiome.versions.source_tool_versions IS
  'JSONB map of the tools/parsers used at import to their version (e.g. {"protoc": "3.21.12"}); informational provenance surfaced by the catalog endpoint as tool_versions. Empty object when none recorded.';

-- Facet indexes for browse-by-protocol/format (MFI-6.1). Partial: live, non-null rows only, since the
-- columns are sparse until the MFI-7.3 backfill populates existing revisions.
CREATE INDEX IF NOT EXISTS idx_versions_source_format
  ON apiome.versions(source_format)
  WHERE deleted_at IS NULL AND source_format IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_versions_protocol
  ON apiome.versions(protocol)
  WHERE deleted_at IS NULL AND protocol IS NOT NULL;
