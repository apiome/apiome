-- Backfill source format & protocol on existing revisions (#3758, MFI-7.3).
--
-- V136 (MFI-7.1, #3756) added `versions.source_format` / `versions.protocol` and the import path
-- has populated them since (`set_version_source_format`, with `protocol` holding the canonical
-- paradigm: rest, rpc, event, graph, data_schema, agent). Every revision created before that — the
-- OpenAPI/Arazzo specs Apiome stored long before multi-format import — still carries NULLs, so the
-- browse protocol/format facets (MFI-6.1) silently leave them out. This one-off backfill tags them.
--
-- Values use the vocabulary the live import path writes, so a backfilled row and a fresh import of
-- the same document facet identically:
--
--   1. Canonical artifact — when the revision has an `api_artifacts` row (MFI-2.2, V135), its
--      `format` (e.g. openapi-3.1, swagger-2.0, arazzo) and `paradigm` are the authoritative answer.
--      The live artifact wins over a soft-deleted one, then the most recent.
--      An Arazzo revision with persisted workflows (`api_workflows`, V225) always has one, since
--      every workflow row hangs off its artifact.
--   2. Arazzo repository import — no artifact, but the revision came from a repository file the
--      scanner or its import spec classed as Arazzo (the same detection V223 used): `arazzo` /
--      `rest`. Arazzo is a REST-paradigm format (`ArazzoImportSource.paradigm`), so its protocol is
--      `rest`, never a separate value the protocol facet does not offer.
--   3. Everything else — Apiome's original model is OpenAPI (designer-authored versions, the seeded
--      Pet Store, historical OpenAPI imports): `openapi` / `rest`. The bare `openapi` key is used
--      because no stored document pins the OpenAPI version for these rows; the facet labels it
--      "OpenAPI / Swagger".
--
-- Safety:
--   * Only NULL or blank values are filled; a value an import adapter already wrote is never
--     overwritten, and each column is filled independently (a row with a format but no protocol
--     keeps its format).
--   * `updated_at` is deliberately not touched: a backfill is not an edit, so "recently updated"
--     lists and the mock-publish NOTIFY trigger (V157, fires on `updated_at`) stay quiet. No trigger
--     watches `source_format` / `protocol`.
--   * Soft-deleted revisions are tagged too, so a restored revision is already faceted.
--   * Idempotent: a re-run finds no NULLs and changes nothing.
--
-- Rollback notes: data-only, no schema change. The backfilled values look exactly like values an
-- import writes (an Arazzo import also stores `arazzo` / `rest`), so they cannot be told apart
-- afterwards. Undoing it precisely means restoring the two columns from a pre-migration backup; the
-- values are harmless to keep, since they only make the revisions visible to the facets.

SET search_path TO apiome, public;

-- Step 1: revisions with a canonical artifact take its format and paradigm.
UPDATE apiome.versions v
SET source_format = COALESCE(NULLIF(TRIM(v.source_format), ''), a.format),
    protocol = COALESCE(NULLIF(TRIM(v.protocol), ''), a.paradigm)
FROM (
  SELECT DISTINCT ON (art.version_id)
    art.version_id,
    NULLIF(LOWER(TRIM(art.format)), '') AS format,
    NULLIF(LOWER(TRIM(art.paradigm)), '') AS paradigm
  FROM apiome.api_artifacts art
  ORDER BY art.version_id, (art.deleted_at IS NULL) DESC, art.created_at DESC
) a
WHERE a.version_id = v.id
  AND (
    (NULLIF(TRIM(v.source_format), '') IS NULL AND a.format IS NOT NULL)
    OR (NULLIF(TRIM(v.protocol), '') IS NULL AND a.paradigm IS NOT NULL)
  );

-- Step 2: revisions imported from a repository file classed as Arazzo are Arazzo.
UPDATE apiome.versions v
SET source_format = 'arazzo',
    protocol = COALESCE(NULLIF(TRIM(v.protocol), ''), 'rest')
WHERE NULLIF(TRIM(v.source_format), '') IS NULL
  AND EXISTS (
    SELECT 1
    FROM apiome.tenant_repository_imports tri
    LEFT JOIN apiome.tenant_repository_files trf
      ON trf.repository_id = tri.repository_id
     AND trf.branch = tri.branch
     AND trf.path = tri.path
    LEFT JOIN apiome.repository_import_spec s
      ON s.repository_id = tri.repository_id
     AND s.branch = tri.branch
     AND s.path = tri.path
    WHERE tri.version_id = v.id
      AND (
        trf.detected_kind ILIKE 'arazzo%'
        OR s.source_kind = 'arazzo'
        OR (
          regexp_replace(lower(tri.path), '^.*/', '') LIKE '%arazzo%'
          AND (lower(tri.path) LIKE '%.yaml' OR lower(tri.path) LIKE '%.yml'
               OR lower(tri.path) LIKE '%.json')
        )
      )
  );

-- Step 3: every remaining untagged revision is an OpenAPI spec.
UPDATE apiome.versions v
SET source_format = 'openapi',
    protocol = COALESCE(NULLIF(TRIM(v.protocol), ''), 'rest')
WHERE NULLIF(TRIM(v.source_format), '') IS NULL;

-- Step 4: a revision with a known OpenAPI/Swagger/Arazzo format but no protocol is REST.
UPDATE apiome.versions v
SET protocol = 'rest'
WHERE NULLIF(TRIM(v.protocol), '') IS NULL
  AND (
    LOWER(v.source_format) IN ('openapi', 'arazzo')
    OR LOWER(v.source_format) LIKE 'openapi-%'
    OR LOWER(v.source_format) LIKE 'swagger-%'
  );
