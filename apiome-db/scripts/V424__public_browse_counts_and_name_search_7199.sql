-- Public Browse: stored card counts and trigram indexes for name search (DBP-1.16, #7199).
--
-- 1. Stored operation and schema counts on versions
--
-- Every Browse card (home rails, a tenant's project list, the project header, project search hits)
-- shows "N operations · M schemas" of one published version. apiome-browse lib/cardFacts.ts counted
-- them per card with two correlated sub-selects; ranking the home project rail by operations
-- therefore counted every public project before it could keep eight (1.76 s for 20,000 projects in
-- the 2026-11-22 audit).
--
--   * versions.operation_count — path_operation rows under the revision's paths;
--   * versions.schema_count    — live classes (classes.deleted_at IS NULL).
--
-- Both are NULL until recorded, and a reader falls back to counting when they are NULL
-- (COALESCE(stored, count)), so a NULL is slower, never wrong.
--
--   * Recorded at publish: trg_versions_publish_counts (BEFORE UPDATE OF published) counts when a
--     revision becomes published, or is published again while the counts are NULL. It covers both
--     writers (apiome-rest Database.publish_version, apiome-ui publishVersion) with no writer
--     change. Unpublishing clears them.
--   * Cleared on a write that changes them: a published revision is normally frozen, but a
--     revision can be published mutable and a tenant administrator can override the freeze. The
--     content-stamp trigger function (V403, re-created by V422) already runs for every row written
--     to classes, version_path and path_operation; for those three tables it now also sets both
--     counts to NULL, once per revision and transaction
--     (apiome.claim_version_publish_counts_clear, the same transaction-local mark the stamp bump
--     uses). On a draft that is one UPDATE that matches no row. The body is otherwise V422's. A
--     revision edited that way is counted per card again until it is next published. Writes to
--     other content tables (class_schema capture, the canonical model) leave the counts alone.
--     (One case is not covered: rows written to those tables *after* the publish UPDATE in the
--     same transaction, when an earlier statement of that transaction already wrote to them. No
--     writer does that; publish is the last content step. DBP-1.19, #7202, which makes this
--     trigger statement-level, must keep the clearing.)
--   * Both columns join the function's non-content list, so recording or clearing them does not
--     bump versions.content_stamp (the backfill below would otherwise mark every published
--     revision's rendered documents stale).
--   * A revision inserted already published (seeds, fixtures) is left NULL: its content rows do not
--     exist yet when the versions row is written.
--
-- Backfill: every published live revision is counted once, in one statement.
--
-- 2. Trigram indexes on name columns
--
-- The search palette asks for suggestions on every keystroke. It used the full catalog search (a
-- twelve-member UNION of ILIKE over concatenated names, descriptions and JSONB cast to text), which
-- no index can serve: 0.2 to 1.2 s per keystroke on the scale database. Suggestions now match
-- names only (apiome-browse lib/search/suggestSql.ts), one ILIKE per word on a bare name
-- expression, and these GIN trigram indexes serve them:
--
--   * idx_projects_name_slug_trgm               — (name || ' ' || slug) of live projects
--   * idx_classes_name_trgm                     — live class (schema) names
--   * idx_class_properties_name_trgm            — class property names
--   * idx_version_path_pathname_trgm            — path names
--   * idx_path_operation_description_name_trgm  — (summary || ' ' || operation_id) of an operation
--
-- pg_trgm lives in the apiome schema (V230); gin_trgm_ops resolves through the search path, which
-- this script sets itself: a database upgraded from V418 or later starts a new migrator session
-- without V417's SET, and the index builds failed there ("operator class gin_trgm_ops does not
-- exist"). The checksum this script had before that line is accepted (apiome-db src/migrate.ts). The
-- expressions here must stay identical to the ones in suggestSql.ts (a test there reads this
-- file), or the planner will not use the index. A word shorter than three characters has no
-- trigram; the suggestion statement does not run a name scan of these tables for such a query.
--
-- Organizations and API products are matched by name too, but their tables are small and are
-- scanned. Tags, parameters, request bodies and responses are not suggested, so they get no index.
--
-- The full-text index over the normalized model is BDX-1.1 (#6285); these indexes cover names only
-- and are not a second search index.
--
-- Write cost, measured on the scale database with row triggers on: inserting 20,000 classes,
-- 60,000 class properties, 12,000 paths, 12,000 operations and 12,000 operation descriptions in
-- one transaction took a median 6.8 s without the four large indexes and 7.9 s with them (+15 %,
-- about 9 µs a row). That is the price of a suggestion in tens of milliseconds instead of a
-- second; an import that cannot afford it can drop idx_class_properties_name_trgm first (property
-- suggestions then come from the recent versions only).
--
-- Large databases: adding two nullable columns does not rewrite versions. The backfill updates
-- every published revision (9.9 s for 180,000 on the scale database). Each CREATE INDEX blocks
-- writes to its table while it builds; on the scale database: projects 0.06 s (20,000 rows),
-- classes 1.2 s (1.0M), class_properties 1.6 s (3.1M), version_path 1.0 s (600,000),
-- path_operation_description 3.8 s (1.2M). To avoid that, build them first by hand with
-- CREATE INDEX CONCURRENTLY (same names and definitions); every statement here is IF NOT EXISTS,
-- so the migration then does nothing.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS trg_versions_publish_counts ON apiome.versions;
--   DROP FUNCTION IF EXISTS apiome.set_version_publish_counts();
--   DROP FUNCTION IF EXISTS apiome.claim_version_publish_counts_clear(uuid);
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS operation_count;
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS schema_count;
--   DROP INDEX IF EXISTS apiome.idx_projects_name_slug_trgm, apiome.idx_classes_name_trgm,
--     apiome.idx_class_properties_name_trgm, apiome.idx_version_path_pathname_trgm,
--     apiome.idx_path_operation_description_name_trgm;
--   (and restore bump_version_content_stamp from V422; the readers fall back to counting as soon
--    as the columns are NULL, but they name the columns, so restore apiome-browse first).

SET search_path TO apiome, public;

ALTER TABLE apiome.versions
    ADD COLUMN IF NOT EXISTS operation_count integer
        CONSTRAINT versions_operation_count_check CHECK (operation_count >= 0),
    ADD COLUMN IF NOT EXISTS schema_count integer
        CONSTRAINT versions_schema_count_check CHECK (schema_count >= 0);

COMMENT ON COLUMN apiome.versions.operation_count IS
    'DBP-1.16 (#7199): operations of the revision, recorded at publish. NULL = not recorded; '
    'readers then count. Cleared by a class, path or operation write and by unpublish.';

COMMENT ON COLUMN apiome.versions.schema_count IS
    'DBP-1.16 (#7199): live classes of the revision, recorded at publish. NULL = not recorded; '
    'readers then count. Cleared by a class, path or operation write and by unpublish.';

-- Marks a revision's publish counts as cleared in the current transaction. Returns true the first
-- time per transaction, false afterwards — the twin of claim_version_content_stamp (V403), with its
-- own mark so a stamp bump by another table does not hide a later write to a counted table.
CREATE OR REPLACE FUNCTION apiome.claim_version_publish_counts_clear(p_version_id uuid)
RETURNS boolean
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_marks text := coalesce(current_setting('apiome.publish_counts_cleared', true), '');
BEGIN
    IF p_version_id IS NULL OR position(p_version_id::text IN v_marks) > 0 THEN
        RETURN false;
    END IF;
    PERFORM set_config('apiome.publish_counts_cleared', v_marks || p_version_id::text || ',', true);
    RETURN true;
END;
$fn$;

COMMENT ON FUNCTION apiome.claim_version_publish_counts_clear(uuid) IS
    'True the first time a revision''s publish counts are claimed for clearing in the current transaction (DBP-1.16, #7199).';

-- The content-stamp trigger function: V422's body with (a) the two count columns in the versions
-- non-content list and (b) the counts cleared when a row of classes, version_path or
-- path_operation is written.
CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    -- Columns whose change alone is not a content change, on any table.
    v_ignored         CONSTANT text[] := ARRAY['updated_at', 'canvas_metadata'];
    -- Versions columns that are bookkeeping or derived from the content, not content. The stored
    -- generated columns are listed too (V422): in a BEFORE trigger NEW does not carry their new
    -- values yet, so comparing them would count every bookkeeping UPDATE as a content change. The
    -- publish counts (V424) are derived from the content.
    v_version_ignored CONSTANT text[] := ARRAY[
        'content_stamp', 'updated_at', 'mcp_public_doc_tsv', 'mcp_public_embedding',
        'quality_score', 'quality_grade', 'quality_report', 'quality_report_fingerprint',
        'lint_error_count', 'sunset_at', 'operation_count', 'schema_count'];
    -- Tables whose rows the publish counts count (V424).
    v_counted  CONSTANT boolean := TG_TABLE_NAME IN ('classes', 'version_path', 'path_operation');
    v_resolver text;
    v_old      jsonb;
    v_new      jsonb;
    v_row      jsonb;
    v_version  uuid;
BEGIN
    IF TG_TABLE_SCHEMA = 'apiome' AND TG_TABLE_NAME = 'versions' THEN
        IF TG_OP = 'UPDATE' AND TG_WHEN = 'BEFORE'
           AND (to_jsonb(NEW) - v_version_ignored) IS DISTINCT FROM (to_jsonb(OLD) - v_version_ignored)
           AND apiome.claim_version_content_stamp(NEW.id) THEN
            NEW.content_stamp := OLD.content_stamp + 1;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_NARGS <> 1 THEN
        RAISE EXCEPTION 'bump_version_content_stamp on %.% needs one revision resolver argument',
            TG_TABLE_SCHEMA, TG_TABLE_NAME;
    END IF;
    v_resolver := TG_ARGV[0];

    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        v_old := to_jsonb(OLD);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        v_new := to_jsonb(NEW);
    END IF;
    IF TG_OP = 'UPDATE' AND (v_new - v_ignored) = (v_old - v_ignored) THEN
        RETURN NULL;
    END IF;

    FOREACH v_row IN ARRAY array_remove(ARRAY[v_old, v_new], NULL) LOOP
        IF v_resolver ~ '^[a-z_][a-z0-9_]*$' THEN
            v_version := (v_row ->> v_resolver)::uuid;
            IF apiome.claim_version_content_stamp(v_version) THEN
                UPDATE apiome.versions SET content_stamp = content_stamp + 1 WHERE id = v_version;
            END IF;
            IF v_counted AND apiome.claim_version_publish_counts_clear(v_version) THEN
                UPDATE apiome.versions SET operation_count = NULL, schema_count = NULL
                 WHERE id = v_version AND (operation_count IS NOT NULL OR schema_count IS NOT NULL);
            END IF;
        ELSE
            FOR v_version IN EXECUTE v_resolver USING v_row LOOP
                IF apiome.claim_version_content_stamp(v_version) THEN
                    UPDATE apiome.versions SET content_stamp = content_stamp + 1 WHERE id = v_version;
                END IF;
                IF v_counted AND apiome.claim_version_publish_counts_clear(v_version) THEN
                    UPDATE apiome.versions SET operation_count = NULL, schema_count = NULL
                     WHERE id = v_version AND (operation_count IS NOT NULL OR schema_count IS NOT NULL);
                END IF;
            END LOOP;
        END IF;
    END LOOP;
    RETURN NULL;
END;
$fn$;

COMMENT ON FUNCTION apiome.bump_version_content_stamp() IS
    'The single trigger function that bumps versions.content_stamp once per transaction (COA-5.2, #7078; generated columns ignored since DBP-1.15, #7198; clears the publish counts on a class, path or operation write since DBP-1.16, #7199).';

CREATE OR REPLACE FUNCTION apiome.set_version_publish_counts()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF NOT NEW.published THEN
        NEW.operation_count := NULL;
        NEW.schema_count := NULL;
    ELSIF NOT OLD.published OR NEW.operation_count IS NULL OR NEW.schema_count IS NULL THEN
        SELECT COUNT(*)::int INTO NEW.operation_count
          FROM apiome.version_path vp
          JOIN apiome.path_operation po ON po.version_path_id = vp.id
         WHERE vp.version_id = NEW.id;
        SELECT COUNT(*)::int INTO NEW.schema_count
          FROM apiome.classes c
         WHERE c.version_id = NEW.id AND c.deleted_at IS NULL;
    END IF;
    RETURN NEW;
END;
$fn$;

COMMENT ON FUNCTION apiome.set_version_publish_counts() IS
    'DBP-1.16 (#7199): records versions.operation_count and schema_count when a revision is published; clears them when it is unpublished.';

DROP TRIGGER IF EXISTS trg_versions_publish_counts ON apiome.versions;
CREATE TRIGGER trg_versions_publish_counts
    BEFORE UPDATE OF published ON apiome.versions
    FOR EACH ROW EXECUTE FUNCTION apiome.set_version_publish_counts();

-- Backfill: count every published live revision once. The two columns are in the stamp function's
-- non-content list, so this does not bump content_stamp.
UPDATE apiome.versions v
   SET operation_count = COALESCE(o.operation_count, 0),
       schema_count = COALESCE(s.schema_count, 0)
  FROM apiome.versions pv
  LEFT JOIN (
        SELECT vp.version_id, COUNT(*)::int AS operation_count
          FROM apiome.version_path vp
          JOIN apiome.path_operation po ON po.version_path_id = vp.id
         GROUP BY vp.version_id
       ) o ON o.version_id = pv.id
  LEFT JOIN (
        SELECT c.version_id, COUNT(*)::int AS schema_count
          FROM apiome.classes c
         WHERE c.deleted_at IS NULL
         GROUP BY c.version_id
       ) s ON s.version_id = pv.id
 WHERE v.id = pv.id
   AND pv.published
   AND pv.deleted_at IS NULL
   AND (v.operation_count IS NULL OR v.schema_count IS NULL);

CREATE INDEX IF NOT EXISTS idx_projects_name_slug_trgm
    ON apiome.projects USING gin ((name || ' ' || slug) gin_trgm_ops)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_classes_name_trgm
    ON apiome.classes USING gin (name gin_trgm_ops)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_class_properties_name_trgm
    ON apiome.class_properties USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_version_path_pathname_trgm
    ON apiome.version_path USING gin (pathname gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_path_operation_description_name_trgm
    ON apiome.path_operation_description
    USING gin ((COALESCE(summary, '') || ' ' || COALESCE(operation_id, '')) gin_trgm_ops);
