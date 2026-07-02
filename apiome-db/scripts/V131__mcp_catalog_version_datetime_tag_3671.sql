-- External MCP Catalog (#3671, V2-MCP-18.4 / MCAT-4.4): date/time version tagging.
--
-- Version history must be navigable by a tagged date/time (an explicit user requirement). V128 gave
-- every snapshot a monotonic `version_seq` and a `discovered_at` timestamp, but neither is the
-- *human-readable, addressable* tag the requirement asks for. This migration adds `version_tag` to
-- `mcp_endpoint_versions`: a compact UTC date/time label (e.g. `2026-06-26T14:03Z`) that the
-- discovery pipeline stamps on each new snapshot and that history listings (MCAT-4.5) surface.
--
-- Uniqueness (acceptance criterion). A tag must address exactly one version *within an endpoint*, so
-- the constraint is `UNIQUE(endpoint_id, version_tag)` — two different endpoints discovered in the
-- same minute legitimately share the label, but one endpoint never reuses it. Minute-precision labels
-- mean two material surface changes to the same endpoint inside one minute would collide; the
-- application disambiguates by appending `-2`, `-3`, … to the base label (mirroring how it allocates
-- `version_seq`), and this unique constraint is the backstop that makes any double-assignment fail
-- loudly rather than silently aliasing two versions to one tag.
--
-- Immutability (acceptance criterion). The tag inherits the table's existing write-once guarantee:
-- the BEFORE UPDATE trigger installed in V128 (`mcp_forbid_row_mutation`) already rejects any in-place
-- edit of a snapshot row, so once stamped a tag can never change. The only place that rule must yield
-- is this migration's own one-time backfill of pre-existing rows, for which the trigger is briefly
-- disabled and then restored (see below).
--
-- Backfill. Existing snapshots predate the column, so `version_tag` is added NULLable first,
-- back-filled from each row's `discovered_at` (falling back to `created_at` when discovery time was
-- not recorded), then made NOT NULL. Within an endpoint, rows whose labels would collide are ordered
-- by `version_seq` and the 2nd, 3rd, … get a `-N` suffix — identical to the runtime disambiguation —
-- so the backfill can never violate the unique constraint it is about to add. The immutability trigger
-- is disabled for the duration of the UPDATE and re-enabled immediately after.
--
-- Rollback notes:
--   ALTER TABLE apiome.mcp_endpoint_versions DROP CONSTRAINT IF EXISTS mcp_endpoint_versions_endpoint_tag_unique;
--   ALTER TABLE apiome.mcp_endpoint_versions DROP COLUMN IF EXISTS version_tag;

SET search_path TO apiome, public;

-- 1. Add the column NULLable so existing rows can be back-filled before the NOT NULL is enforced.
ALTER TABLE mcp_endpoint_versions
    ADD COLUMN IF NOT EXISTS version_tag TEXT;

-- 2. Back-fill existing snapshots. The immutability trigger (V128) rejects UPDATEs, so disable it for
--    this one-time data migration and restore it immediately afterwards.
ALTER TABLE mcp_endpoint_versions DISABLE TRIGGER trigger_mcp_endpoint_versions_immutable;

WITH labelled AS (
    SELECT
        id,
        to_char(
            (COALESCE(discovered_at, created_at)) AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI"Z"'
        ) AS base_tag,
        ROW_NUMBER() OVER (
            PARTITION BY
                endpoint_id,
                to_char(
                    (COALESCE(discovered_at, created_at)) AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI"Z"'
                )
            ORDER BY version_seq
        ) AS collision_rank
    FROM mcp_endpoint_versions
    WHERE version_tag IS NULL
)
UPDATE mcp_endpoint_versions v
SET version_tag = CASE
        WHEN l.collision_rank = 1 THEN l.base_tag
        ELSE l.base_tag || '-' || l.collision_rank
    END
FROM labelled l
WHERE l.id = v.id;

ALTER TABLE mcp_endpoint_versions ENABLE TRIGGER trigger_mcp_endpoint_versions_immutable;

-- 3. Every snapshot now carries a tag; enforce its presence going forward.
ALTER TABLE mcp_endpoint_versions
    ALTER COLUMN version_tag SET NOT NULL;

-- 4. A tag addresses exactly one version within an endpoint. The btree backing this also serves
--    lookups on (endpoint_id, version_tag) — the "address a version by its date/time tag" path.
ALTER TABLE mcp_endpoint_versions
    DROP CONSTRAINT IF EXISTS mcp_endpoint_versions_endpoint_tag_unique;
ALTER TABLE mcp_endpoint_versions
    ADD CONSTRAINT mcp_endpoint_versions_endpoint_tag_unique UNIQUE (endpoint_id, version_tag);

COMMENT ON COLUMN mcp_endpoint_versions.version_tag IS 'Human-readable UTC date/time tag (e.g. 2026-06-26T14:03Z), unique per endpoint and immutable; addresses the version in history listings (#3671, V2-MCP-18.4)';
