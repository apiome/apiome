-- MCP discovery provenance (#4659, V2-MCP-34.5 / MCAT-20.5): how each endpoint was added and how
-- each version snapshot came to be known.
--
-- `mcp_discovery_jobs.trigger` (V130) already records what enqueued every discovery run
-- (`manual` / `sweep` / `registry`), but that fact is only reachable *from the job side* — the job's
-- `result` JSONB carries a one-way `version_id` reference, while the version row itself says nothing
-- about which run produced it, and the endpoint row says nothing about how it entered the catalog.
-- The provenance strip on the identity card / report card needs both answers directly on the rows
-- the catalog reads, without scanning the job log's JSONB on every render.
--
-- This migration adds:
--
--   * mcp_endpoints.added_via                    — how the endpoint came to be known to the catalog:
--                                                  `manual` (registered via the UI/API — today's only
--                                                  creation path), `registry` (a registry-driven
--                                                  import), or `import` (a bulk/file import). NOT NULL
--                                                  DEFAULT 'manual': every existing row *was* added
--                                                  manually, so the default doubles as an exact
--                                                  backfill.
--   * mcp_endpoint_versions.discovery_trigger    — what enqueued the discovery run that produced this
--                                                  snapshot (`manual`/`sweep`/`registry`), denormalized
--                                                  from the producing job so the provenance survives
--                                                  any future pruning of the job log. NULL means the
--                                                  producing run predates provenance tracking and no
--                                                  completed job row could attribute it ("unrecorded").
--   * mcp_endpoint_versions.discovery_job_id     — audit pointer to the `mcp_discovery_jobs` row that
--                                                  produced the snapshot. Deliberately **not** a
--                                                  foreign key: versions are write-once (the V128
--                                                  `mcp_forbid_row_mutation` trigger rejects UPDATEs),
--                                                  and an `ON DELETE SET NULL` FK would have to UPDATE
--                                                  version rows when jobs are purged — which the
--                                                  endpoint teardown path does *before* deleting
--                                                  versions — tripping the immutability trigger and
--                                                  breaking the purge. A dangling id after job pruning
--                                                  is acceptable for an audit pointer; the denormalized
--                                                  `discovery_trigger` keeps the provenance itself.
--
-- Backfill (acceptance criterion): existing snapshots are attributed from the job history where
-- possible. The producing job for a version is the earliest *completed* job whose `result` records
-- `version_id` = the snapshot AND `changed = true` (a later unchanged run re-references the same
-- version id, so `changed` must gate the match or pre-V130 snapshots could be mis-attributed to a
-- later no-op sweep). The immutability trigger is disabled around the one-time UPDATE, exactly as the
-- V131 `version_tag` backfill did. Snapshots with no attributable job keep NULLs and read as
-- "unrecorded" — never silently mis-attributed.
--
-- Rollback notes: this migration is additive (three nullable-or-defaulted columns + two CHECKs).
-- To roll back:
--   ALTER TABLE apiome.mcp_endpoint_versions DROP COLUMN IF EXISTS discovery_job_id;
--   ALTER TABLE apiome.mcp_endpoint_versions DROP COLUMN IF EXISTS discovery_trigger;
--   ALTER TABLE apiome.mcp_endpoints DROP CONSTRAINT IF EXISTS mcp_endpoints_added_via_check;
--   ALTER TABLE apiome.mcp_endpoints DROP COLUMN IF EXISTS added_via;
-- (Dropping the version columns also drops their CHECK constraint.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. Endpoint-level provenance: how the endpoint entered the catalog.
--    The DEFAULT is also the backfill: the manual registration route is the only creation path that
--    has ever existed, so stamping every pre-existing row 'manual' is exact, not a guess.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE mcp_endpoints
    ADD COLUMN IF NOT EXISTS added_via VARCHAR(32) NOT NULL DEFAULT 'manual';

ALTER TABLE mcp_endpoints
    DROP CONSTRAINT IF EXISTS mcp_endpoints_added_via_check;
ALTER TABLE mcp_endpoints
    ADD CONSTRAINT mcp_endpoints_added_via_check
        CHECK (added_via IN ('manual', 'registry', 'import'));

COMMENT ON COLUMN mcp_endpoints.added_via IS 'How the endpoint came to be known to the catalog: manual (registered via UI/API), registry, or import (#4659, V2-MCP-34.5)';

-- ---------------------------------------------------------------------------------------------------
-- 2. Version-level provenance: which discovery run produced the snapshot.
--    Nullable: NULL reads as "unrecorded" (a pre-provenance snapshot with no attributable job) and is
--    deliberately never presented as any concrete origin.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE mcp_endpoint_versions
    ADD COLUMN IF NOT EXISTS discovery_trigger VARCHAR(32),
    ADD COLUMN IF NOT EXISTS discovery_job_id UUID;

ALTER TABLE mcp_endpoint_versions
    DROP CONSTRAINT IF EXISTS mcp_endpoint_versions_discovery_trigger_check;
ALTER TABLE mcp_endpoint_versions
    ADD CONSTRAINT mcp_endpoint_versions_discovery_trigger_check
        CHECK (discovery_trigger IS NULL OR discovery_trigger IN ('manual', 'sweep', 'registry'));

COMMENT ON COLUMN mcp_endpoint_versions.discovery_trigger IS 'What enqueued the discovery run that produced this snapshot: manual, sweep, or registry; NULL when unrecorded (pre-provenance snapshot) (#4659, V2-MCP-34.5)';
COMMENT ON COLUMN mcp_endpoint_versions.discovery_job_id IS 'Audit pointer to the mcp_discovery_jobs row that produced this snapshot; intentionally not a FK (versions are write-once, so FK SET NULL on job purge would trip the immutability trigger); may dangle after job pruning (#4659, V2-MCP-34.5)';

-- ---------------------------------------------------------------------------------------------------
-- 3. Back-fill existing snapshots from the job history where possible.
--    The producing job is the earliest completed job whose result references the snapshot with
--    changed=true; unchanged re-runs re-reference an existing version id and must never claim it.
--    The V128 immutability trigger rejects UPDATEs, so it is disabled for this one-time attribution
--    and re-enabled immediately after (the V131 version_tag backfill precedent).
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE mcp_endpoint_versions DISABLE TRIGGER trigger_mcp_endpoint_versions_immutable;

WITH producing AS (
    SELECT DISTINCT ON (j.version_id)
           j.id,
           j.trigger,
           j.version_id
    FROM (
        SELECT id,
               trigger,
               created_at,
               (result ->> 'version_id')::uuid AS version_id
        FROM mcp_discovery_jobs
        WHERE state = 'completed'
          AND result ->> 'changed' = 'true'
          AND result ->> 'version_id'
              ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ) j
    ORDER BY j.version_id, j.created_at ASC, j.id ASC
)
UPDATE mcp_endpoint_versions v
SET discovery_trigger = p.trigger,
    discovery_job_id  = p.id
FROM producing p
WHERE v.id = p.version_id
  AND v.discovery_trigger IS NULL
  AND v.discovery_job_id IS NULL;

ALTER TABLE mcp_endpoint_versions ENABLE TRIGGER trigger_mcp_endpoint_versions_immutable;
