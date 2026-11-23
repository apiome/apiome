-- Stored is_importable flag for the repository spec-quality sweep (DBP-1.12, #7195).
--
-- The scoring sweep (Database.claim_repository_files_for_quality_scoring in apiome-rest) claims
-- rows WHERE quality_scored_blob_sha IS DISTINCT FROM blob_sha AND <the importable predicate>,
-- ORDER BY repository_id, path. Its index, idx_tenant_repository_files_quality_pending (V222),
-- was partial on the first condition only. A file that is not an importable spec (README.md,
-- package.json, every unclassified blob — most of a monorepo) is never scored, so its
-- quality_scored_blob_sha stays NULL and it stays in that index forever: each sweep tick walked
-- every one of them and threw them away with the importable predicate, a dozen ILIKEs per row.
--
-- The predicate now lives in a stored generated column, so the index can carry it:
--
--   * tenant_repository_files.is_importable — the same expression as
--     REPOSITORY_FILE_IMPORTABLE_SQL in apiome-rest/src/app/database.py (keep the two in
--     lockstep; apiome-rest/tests/test_repository_importable_json_schema.py compares them). It is
--     derived from detected_kind and path, so it follows every rescan and needs no writer.
--   * idx_tenant_repository_files_quality_due replaces the V222 index: partial on importable rows
--     with a blob whose score is missing or stale. The claim query filters on f.is_importable, so
--     the planner matches the predicate and reads only due rows, in claim order.
--
-- Large databases: adding a stored generated column rewrites tenant_repository_files under an
-- ACCESS EXCLUSIVE lock (scans and repository browsing wait for it; about a second per few hundred
-- thousand rows). Schedule the upgrade accordingly. The index build that follows blocks writes to
-- the table; to avoid that part, run the CREATE INDEX below by hand with CONCURRENTLY (same name
-- and definition) after the column exists — the statement is IF NOT EXISTS.
--
-- Rollback notes:
--   CREATE INDEX idx_tenant_repository_files_quality_pending
--     ON apiome.tenant_repository_files (repository_id, path)
--     WHERE quality_scored_blob_sha IS DISTINCT FROM blob_sha;
--   DROP INDEX IF EXISTS apiome.idx_tenant_repository_files_quality_due;
--   ALTER TABLE apiome.tenant_repository_files DROP COLUMN IF EXISTS is_importable;
--   (and restore the importable predicate in the REST claim query).

ALTER TABLE apiome.tenant_repository_files
    ADD COLUMN IF NOT EXISTS is_importable boolean NOT NULL GENERATED ALWAYS AS (COALESCE((
          detected_kind IS NOT NULL AND (
            detected_kind ILIKE 'openapi%' OR detected_kind ILIKE 'arazzo%' OR
            detected_kind ILIKE 'asyncapi%' OR detected_kind ILIKE 'graphql%' OR
            detected_kind ILIKE 'protobuf%' OR detected_kind ILIKE 'postman%' OR
            detected_kind ILIKE 'prisma%' OR detected_kind ILIKE 'sql-ddl%' OR
            detected_kind ILIKE 'avro%' OR detected_kind ILIKE 'dbml%' OR
            (detected_kind ILIKE 'json%' AND (
              path ILIKE '%.schema.json' OR
              path ILIKE '%/schemas/%.json' OR path ILIKE 'schemas/%.json'
            ))
          )
        ), false)) STORED;

COMMENT ON COLUMN apiome.tenant_repository_files.is_importable IS
  'True when the scanner classified the file as an importable spec: the REPOSITORY_FILE_IMPORTABLE_SQL predicate of apiome-rest, stored so the quality sweep index can carry it (DBP-1.12, #7195).';

DROP INDEX IF EXISTS apiome.idx_tenant_repository_files_quality_pending;

CREATE INDEX IF NOT EXISTS idx_tenant_repository_files_quality_due
    ON apiome.tenant_repository_files (repository_id, path)
    WHERE is_importable AND blob_sha IS NOT NULL AND quality_scored_blob_sha IS DISTINCT FROM blob_sha;
