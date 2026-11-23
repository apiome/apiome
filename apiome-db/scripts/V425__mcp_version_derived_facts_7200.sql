-- MCP catalog: derived facts stored per endpoint version (DBP-1.17, #7200).
--
-- An MCP endpoint version (apiome.mcp_endpoint_versions) is an immutable snapshot of a server's
-- surface: its capability items and the changes it introduced are written once, in the
-- transaction that creates it, and never again. The catalog nevertheless recomputed the same
-- facts from mcp_capability_items on every read — per-kind counts, whether a tool is destructive,
-- whether every tool is read-only, the widest tool's property count (which detoasts every tool's
-- input_schema) — and the faceted catalog search did so in ten statements per page.
--
-- 1. Stored facts
--
--   * tool_count, resource_count, resource_template_count, prompt_count — items of each kind;
--   * has_destructive  — at least one tool asserts destructiveHint: true (a JSON boolean);
--   * read_only_only   — there is at least one tool and every tool asserts readOnlyHint: true;
--   * max_tool_props   — the largest number of top-level input_schema properties of any tool;
--                        NULL when the snapshot has no tools;
--   * change_count     — mcp_version_changes rows the snapshot introduced.
--
-- tool_count IS NULL marks a snapshot whose facts have not been derived yet. Every reader in
-- apiome-rest recomputes the fact for such a row (CASE WHEN tool_count IS NOT NULL THEN the
-- column ELSE the recomputation), so a snapshot that is not derived yet is slower, never wrong,
-- and the columns can be filled at any pace.
--
-- The recomputations are the expressions the catalog used before the columns existed, moved into
-- five functions — apiome.mcp_version_kind_count, mcp_version_has_destructive,
-- mcp_version_read_only_only, mcp_version_max_tool_props and mcp_version_change_count — so there
-- is one definition of each, shared by the readers and by the verification below. They are
-- PL/pgSQL on purpose: the planner prices a function call at its declared COST, where it priced
-- the inline sub-selects of every row at their full cost even though they run for almost none,
-- and that estimate alone was enough to switch on JIT compilation (0.7 s on a statement that
-- executes in 18 ms, measured on the scale database). They are PARALLEL SAFE (they only read):
-- a function that is not would forbid a parallel plan for every statement that mentions it.
--
-- 2. Who fills them
--
--   * A new snapshot gets its facts in its own INSERT: apiome-rest computes them from the items
--     and changes it is about to write (app/mcp_version_facts.py) in
--     Database.record_mcp_discovery_version — written once, with the row.
--   * A snapshot from before this migration is filled by apiome.backfill_mcp_version_facts(limit):
--     it derives up to `limit` snapshots that have no facts and returns how many it did. It takes
--     the rows FOR UPDATE SKIP LOCKED, so two callers never do the same snapshot, and a caller
--     that stops loses nothing: the next call continues. This migration does not backfill (it
--     would be one long transaction on a large catalog); `apiome-db migrate` calls the function
--     in batches, one transaction each, after the migrations are applied, and
--     `apiome-db backfill mcp-version-facts` does the same on demand.
--     apiome.derive_mcp_version_facts(uuid[]) is the set-based statement behind it.
--   * apiome.verify_mcp_version_facts(limit) returns the derived snapshots whose stored facts
--     differ from the facts recomputed with the readers' original expressions — no rows when all
--     is well. It checks the backfill and the Python derivation alike.
--     `apiome-db backfill mcp-version-facts --verify` runs it.
--
-- 3. The write-once guard
--
-- V128 made mcp_endpoint_versions write-once: trigger_mcp_endpoint_versions_immutable rejects
-- every UPDATE. Earlier backfills (V131, V148) disabled the trigger inside their migration, which
-- holds an ACCESS EXCLUSIVE lock on the table for the whole backfill. A resumable backfill cannot
-- do that, so the table gets its own guard function, apiome.mcp_endpoint_versions_forbid_mutation():
-- it still rejects every UPDATE, with the same message and SQLSTATE, except one — an UPDATE that
-- gives facts to a row that has none (tool_count NULL before, not NULL after) and changes no
-- other column. Facts, once stored, are as immutable as the rest of the row. The shared
-- mcp_forbid_row_mutation() function and every other table's guard are untouched.
--
-- idx_mcp_endpoint_versions_facts_pending holds only the snapshots still to derive, so finding
-- the next batch — and finding out that there is none, on every later migrate — costs nothing.
--
-- 4. Indexes for the cross-tenant duplicate hints
--
-- Database.list_published_mcp_duplicate_hints read every published endpoint of every other tenant
-- and matched them in Python. It now asks only for the published endpoints that share a surface
-- fingerprint or a URL key with one of the tenant's own:
--
--   * idx_mcp_endpoint_versions_surface_fingerprint — snapshots by fingerprint;
--   * idx_mcp_endpoints_published_dedup_key — published live endpoints by the lower-cased host of
--     their URL, or by the trimmed URL itself for a target with no host (a stdio command). Two
--     URLs that normalize to the same string always have the same key. The expression must stay
--     identical to Database._MCP_ENDPOINT_DEDUP_KEY_EXPR in apiome-rest.
--
-- Large databases: adding nullable columns does not rewrite mcp_endpoint_versions. The three
-- CREATE INDEX statements block writes to their table while they build. They are small (each under
-- 1 MB and built in milliseconds on the scale database, with 15,880 snapshots and 4,000
-- endpoints); on a much larger catalog, build them first with CREATE INDEX CONCURRENTLY (same
-- names and definitions) — every statement here is IF NOT EXISTS.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_published_dedup_key,
--     apiome.idx_mcp_endpoint_versions_surface_fingerprint,
--     apiome.idx_mcp_endpoint_versions_facts_pending;
--   DROP TRIGGER IF EXISTS trigger_mcp_endpoint_versions_immutable ON apiome.mcp_endpoint_versions;
--   CREATE TRIGGER trigger_mcp_endpoint_versions_immutable BEFORE UPDATE ON apiome.mcp_endpoint_versions
--     FOR EACH ROW EXECUTE FUNCTION apiome.mcp_forbid_row_mutation();
--   DROP FUNCTION IF EXISTS apiome.mcp_endpoint_versions_forbid_mutation();
--   DROP FUNCTION IF EXISTS apiome.verify_mcp_version_facts(integer);
--   DROP FUNCTION IF EXISTS apiome.mcp_version_kind_count(uuid, text),
--     apiome.mcp_version_has_destructive(uuid), apiome.mcp_version_read_only_only(uuid),
--     apiome.mcp_version_max_tool_props(uuid), apiome.mcp_version_change_count(uuid);
--   DROP FUNCTION IF EXISTS apiome.backfill_mcp_version_facts(integer);
--   DROP FUNCTION IF EXISTS apiome.derive_mcp_version_facts(uuid[]);
--   ALTER TABLE apiome.mcp_endpoint_versions
--     DROP COLUMN IF EXISTS tool_count, DROP COLUMN IF EXISTS resource_count,
--     DROP COLUMN IF EXISTS resource_template_count, DROP COLUMN IF EXISTS prompt_count,
--     DROP COLUMN IF EXISTS has_destructive, DROP COLUMN IF EXISTS read_only_only,
--     DROP COLUMN IF EXISTS max_tool_props, DROP COLUMN IF EXISTS change_count;
--   (restore apiome-rest first: its readers and its discovery writer name these objects.)

ALTER TABLE apiome.mcp_endpoint_versions
    ADD COLUMN IF NOT EXISTS tool_count integer
        CONSTRAINT mcp_endpoint_versions_tool_count_check CHECK (tool_count >= 0),
    ADD COLUMN IF NOT EXISTS resource_count integer
        CONSTRAINT mcp_endpoint_versions_resource_count_check CHECK (resource_count >= 0),
    ADD COLUMN IF NOT EXISTS resource_template_count integer
        CONSTRAINT mcp_endpoint_versions_resource_template_count_check CHECK (resource_template_count >= 0),
    ADD COLUMN IF NOT EXISTS prompt_count integer
        CONSTRAINT mcp_endpoint_versions_prompt_count_check CHECK (prompt_count >= 0),
    ADD COLUMN IF NOT EXISTS has_destructive boolean,
    ADD COLUMN IF NOT EXISTS read_only_only boolean,
    ADD COLUMN IF NOT EXISTS max_tool_props integer
        CONSTRAINT mcp_endpoint_versions_max_tool_props_check CHECK (max_tool_props >= 0),
    ADD COLUMN IF NOT EXISTS change_count integer
        CONSTRAINT mcp_endpoint_versions_change_count_check CHECK (change_count >= 0);

COMMENT ON COLUMN apiome.mcp_endpoint_versions.tool_count IS
    'DBP-1.17 (#7200): tools in the snapshot. NULL = facts not derived yet; readers then compute them.';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.resource_count IS
    'DBP-1.17 (#7200): resources in the snapshot.';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.resource_template_count IS
    'DBP-1.17 (#7200): resource templates in the snapshot.';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.prompt_count IS
    'DBP-1.17 (#7200): prompts in the snapshot.';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.has_destructive IS
    'DBP-1.17 (#7200): a tool asserts destructiveHint: true (JSON boolean).';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.read_only_only IS
    'DBP-1.17 (#7200): the snapshot has a tool and every tool asserts readOnlyHint: true.';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.max_tool_props IS
    'DBP-1.17 (#7200): most top-level input_schema properties of any tool; NULL when there is no tool.';
COMMENT ON COLUMN apiome.mcp_endpoint_versions.change_count IS
    'DBP-1.17 (#7200): mcp_version_changes rows the snapshot introduced.';

CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_versions_facts_pending
    ON apiome.mcp_endpoint_versions (id)
    WHERE tool_count IS NULL;

-- The write-once guard of mcp_endpoint_versions: every UPDATE is refused, except filling the
-- derived facts of a row that has none while leaving every other column as it was.
CREATE OR REPLACE FUNCTION apiome.mcp_endpoint_versions_forbid_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_without_facts apiome.mcp_endpoint_versions;
BEGIN
    IF OLD.tool_count IS NULL AND NEW.tool_count IS NOT NULL THEN
        -- NEW with its facts put back to OLD's must be OLD: nothing but the facts changed.
        v_without_facts := NEW;
        v_without_facts.tool_count := OLD.tool_count;
        v_without_facts.resource_count := OLD.resource_count;
        v_without_facts.resource_template_count := OLD.resource_template_count;
        v_without_facts.prompt_count := OLD.prompt_count;
        v_without_facts.has_destructive := OLD.has_destructive;
        v_without_facts.read_only_only := OLD.read_only_only;
        v_without_facts.max_tool_props := OLD.max_tool_props;
        v_without_facts.change_count := OLD.change_count;
        IF v_without_facts IS NOT DISTINCT FROM OLD THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'Table %.% is immutable; rows are write-once and cannot be updated',
        TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

COMMENT ON FUNCTION apiome.mcp_endpoint_versions_forbid_mutation() IS
    'DBP-1.17 (#7200): write-once guard of mcp_endpoint_versions. Refuses every UPDATE except giving derived facts to a row that has none, with no other column changed.';

DROP TRIGGER IF EXISTS trigger_mcp_endpoint_versions_immutable ON apiome.mcp_endpoint_versions;
CREATE TRIGGER trigger_mcp_endpoint_versions_immutable
    BEFORE UPDATE ON apiome.mcp_endpoint_versions
    FOR EACH ROW
    EXECUTE FUNCTION apiome.mcp_endpoint_versions_forbid_mutation();

-- The recomputation of each fact for one snapshot: the expressions apiome-rest evaluated per
-- endpoint before the columns existed. Readers call them only for a snapshot with no stored facts.
CREATE OR REPLACE FUNCTION apiome.mcp_version_kind_count(p_version_id uuid, p_kind text)
RETURNS integer
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
COST 10
AS $fn$
BEGIN
    RETURN (SELECT COUNT(*)::int
              FROM apiome.mcp_capability_items i
             WHERE i.version_id = p_version_id AND i.item_type = p_kind);
END;
$fn$;

CREATE OR REPLACE FUNCTION apiome.mcp_version_has_destructive(p_version_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
COST 10
AS $fn$
BEGIN
    RETURN EXISTS (SELECT 1
                     FROM apiome.mcp_capability_items sd
                    WHERE sd.version_id = p_version_id AND sd.item_type = 'tool'
                      AND sd.annotations -> 'destructiveHint' = 'true'::jsonb);
END;
$fn$;

CREATE OR REPLACE FUNCTION apiome.mcp_version_read_only_only(p_version_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
COST 10
AS $fn$
BEGIN
    RETURN EXISTS (SELECT 1
                     FROM apiome.mcp_capability_items sr
                    WHERE sr.version_id = p_version_id AND sr.item_type = 'tool')
       AND NOT EXISTS (SELECT 1
                         FROM apiome.mcp_capability_items sr
                        WHERE sr.version_id = p_version_id AND sr.item_type = 'tool'
                          AND sr.annotations -> 'readOnlyHint' IS DISTINCT FROM 'true'::jsonb);
END;
$fn$;

CREATE OR REPLACE FUNCTION apiome.mcp_version_max_tool_props(p_version_id uuid)
RETURNS integer
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
COST 10
AS $fn$
BEGIN
    RETURN (SELECT MAX(CASE WHEN jsonb_typeof(tc.input_schema -> 'properties') = 'object'
                            THEN (SELECT COUNT(*) FROM jsonb_object_keys(tc.input_schema -> 'properties'))
                            ELSE 0 END)::int
              FROM apiome.mcp_capability_items tc
             WHERE tc.version_id = p_version_id AND tc.item_type = 'tool');
END;
$fn$;

CREATE OR REPLACE FUNCTION apiome.mcp_version_change_count(p_version_id uuid)
RETURNS integer
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
COST 10
AS $fn$
BEGIN
    RETURN (SELECT COUNT(*)::int FROM apiome.mcp_version_changes c WHERE c.version_id = p_version_id);
END;
$fn$;

COMMENT ON FUNCTION apiome.mcp_version_kind_count(uuid, text) IS
    'DBP-1.17 (#7200): capability items of one kind in an MCP endpoint version, counted from the items.';
COMMENT ON FUNCTION apiome.mcp_version_has_destructive(uuid) IS
    'DBP-1.17 (#7200): whether a tool of the version asserts destructiveHint: true, read from the items.';
COMMENT ON FUNCTION apiome.mcp_version_read_only_only(uuid) IS
    'DBP-1.17 (#7200): whether the version has a tool and every tool asserts readOnlyHint: true, read from the items.';
COMMENT ON FUNCTION apiome.mcp_version_max_tool_props(uuid) IS
    'DBP-1.17 (#7200): most top-level input_schema properties of any tool of the version; NULL without tools.';
COMMENT ON FUNCTION apiome.mcp_version_change_count(uuid) IS
    'DBP-1.17 (#7200): mcp_version_changes rows of the version, counted.';

-- Compute and store the facts of the given snapshots that have none. One statement, however
-- many snapshots: the items are aggregated per snapshot, the changes counted per snapshot, and
-- the rows updated. A snapshot that already has facts is skipped, so the call is idempotent.
CREATE OR REPLACE FUNCTION apiome.derive_mcp_version_facts(p_version_ids uuid[])
RETURNS integer
LANGUAGE sql
AS $fn$
    WITH items AS (
        SELECT ci.version_id,
               COUNT(*) FILTER (WHERE ci.item_type = 'tool')::int              AS tool_count,
               COUNT(*) FILTER (WHERE ci.item_type = 'resource')::int          AS resource_count,
               COUNT(*) FILTER (WHERE ci.item_type = 'resource_template')::int AS resource_template_count,
               COUNT(*) FILTER (WHERE ci.item_type = 'prompt')::int            AS prompt_count,
               COUNT(*) FILTER (WHERE ci.item_type = 'tool'
                                  AND ci.annotations -> 'destructiveHint' = 'true'::jsonb) > 0
                                                                               AS has_destructive,
               (COUNT(*) FILTER (WHERE ci.item_type = 'tool') > 0
                AND COUNT(*) FILTER (WHERE ci.item_type = 'tool'
                                       AND ci.annotations -> 'readOnlyHint' IS DISTINCT FROM 'true'::jsonb) = 0)
                                                                               AS read_only_only,
               MAX(CASE WHEN ci.item_type <> 'tool' THEN NULL
                        WHEN jsonb_typeof(ci.input_schema -> 'properties') = 'object'
                        THEN (SELECT COUNT(*) FROM jsonb_object_keys(ci.input_schema -> 'properties'))
                        ELSE 0 END)::int                                       AS max_tool_props
          FROM apiome.mcp_capability_items ci
         WHERE ci.version_id = ANY(p_version_ids)
         GROUP BY ci.version_id
    ),
    changes AS (
        SELECT c.version_id, COUNT(*)::int AS change_count
          FROM apiome.mcp_version_changes c
         WHERE c.version_id = ANY(p_version_ids)
         GROUP BY c.version_id
    ),
    updated AS (
        UPDATE apiome.mcp_endpoint_versions v
           SET tool_count              = COALESCE(i.tool_count, 0),
               resource_count          = COALESCE(i.resource_count, 0),
               resource_template_count = COALESCE(i.resource_template_count, 0),
               prompt_count            = COALESCE(i.prompt_count, 0),
               has_destructive         = COALESCE(i.has_destructive, false),
               read_only_only          = COALESCE(i.read_only_only, false),
               max_tool_props          = i.max_tool_props,
               change_count            = COALESCE(c.change_count, 0)
          FROM apiome.mcp_endpoint_versions target
          LEFT JOIN items i ON i.version_id = target.id
          LEFT JOIN changes c ON c.version_id = target.id
         WHERE target.id = ANY(p_version_ids)
           AND v.id = target.id
           AND v.tool_count IS NULL
        RETURNING 1
    )
    SELECT COUNT(*)::int FROM updated
$fn$;

COMMENT ON FUNCTION apiome.derive_mcp_version_facts(uuid[]) IS
    'DBP-1.17 (#7200): computes and stores the derived facts of those of the given MCP endpoint versions that have none; returns how many it updated. A snapshot that already has facts is left alone.';

-- Derive up to p_limit snapshots that have no facts yet. Safe to call from several sessions and
-- to stop at any time: each call commits (with its caller) what it did, and the next continues.
CREATE OR REPLACE FUNCTION apiome.backfill_mcp_version_facts(p_limit integer)
RETURNS integer
LANGUAGE sql
AS $fn$
    SELECT apiome.derive_mcp_version_facts(ARRAY(
        SELECT v.id
          FROM apiome.mcp_endpoint_versions v
         WHERE v.tool_count IS NULL
         ORDER BY v.id
         LIMIT GREATEST(COALESCE(p_limit, 0), 0)
           FOR UPDATE SKIP LOCKED
    ))
$fn$;

COMMENT ON FUNCTION apiome.backfill_mcp_version_facts(integer) IS
    'DBP-1.17 (#7200): derives the facts of up to p_limit MCP endpoint versions that have none; returns how many it did (0 = nothing left).';

-- The derived snapshots whose stored facts differ from the facts recomputed by the five functions
-- above — the catalog's original expressions. The backfill computes the same facts a different
-- way (one aggregate over many snapshots), and apiome-rest a third (in Python, before the
-- INSERT), so this is a real cross-check of both. No rows means every stored fact is right.
CREATE OR REPLACE FUNCTION apiome.verify_mcp_version_facts(p_limit integer DEFAULT 100)
RETURNS TABLE (version_id uuid, stored jsonb, recomputed jsonb)
LANGUAGE sql
STABLE
AS $fn$
    SELECT v.id, s.facts, r.facts
      FROM apiome.mcp_endpoint_versions v
     CROSS JOIN LATERAL (
        SELECT jsonb_build_object(
            'tool_count', v.tool_count,
            'resource_count', v.resource_count,
            'resource_template_count', v.resource_template_count,
            'prompt_count', v.prompt_count,
            'has_destructive', v.has_destructive,
            'read_only_only', v.read_only_only,
            'max_tool_props', v.max_tool_props,
            'change_count', v.change_count) AS facts
     ) s
     CROSS JOIN LATERAL (
        SELECT jsonb_build_object(
            'tool_count', apiome.mcp_version_kind_count(v.id, 'tool'),
            'resource_count', apiome.mcp_version_kind_count(v.id, 'resource'),
            'resource_template_count', apiome.mcp_version_kind_count(v.id, 'resource_template'),
            'prompt_count', apiome.mcp_version_kind_count(v.id, 'prompt'),
            'has_destructive', apiome.mcp_version_has_destructive(v.id),
            'read_only_only', apiome.mcp_version_read_only_only(v.id),
            'max_tool_props', apiome.mcp_version_max_tool_props(v.id),
            'change_count', apiome.mcp_version_change_count(v.id)) AS facts
     ) r
     WHERE v.tool_count IS NOT NULL
       AND s.facts IS DISTINCT FROM r.facts
     ORDER BY v.id
     LIMIT GREATEST(COALESCE(p_limit, 0), 0)
$fn$;

COMMENT ON FUNCTION apiome.verify_mcp_version_facts(integer) IS
    'DBP-1.17 (#7200): MCP endpoint versions whose stored facts differ from the recomputed ones (at most p_limit); no rows = all correct.';

CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_versions_surface_fingerprint
    ON apiome.mcp_endpoint_versions (surface_fingerprint)
    WHERE surface_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_published_dedup_key
    ON apiome.mcp_endpoints (
        (COALESCE(lower(substring(endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)')), btrim(endpoint_url, E' \t\n\r')))
    )
    WHERE published = true AND deleted_at IS NULL;
