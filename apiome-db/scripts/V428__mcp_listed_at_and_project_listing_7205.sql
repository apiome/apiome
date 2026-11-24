-- MCP catalog listing: a stored sort key and a per-project rollup (DBP-1.22, #7205).
--
-- apiome-mcp's spec.list, spec.list_my_specs and project.list page through apiome.mcp_v_public_specs
-- in "last changed" order. The view computes that timestamp for every row,
--
--     GREATEST(versions.updated_at, projects.updated_at, max(version_tags.updated_at))
--
-- from three tables, so no index can serve the ORDER BY: every page read and sorted every public
-- revision and ran one version_tags aggregate per revision (measured on the scale database: see
-- section 5). project.list grouped the same set by project before it applied its cursor.
--
-- 1. versions.mcp_listed_at
--
-- The same timestamp, stored. It is NOT NULL exactly for the revisions the MCP catalog can list —
-- published, enabled and not deleted, in an enabled project that is not deleted — whatever their
-- visibility: public revisions are the rows of mcp_v_public_specs and private ones are what an API
-- key lists for its own tenant. For a public revision it always equals the view's updated_at
-- (apiome.compute_mcp_listed_at_for_version is the view's expression).
--
-- Two partial indexes make a page an index scan:
--
--   * idx_versions_mcp_public_listed  (mcp_listed_at DESC, id DESC)
--       WHERE mcp_listed_at IS NOT NULL AND visibility = 'public' — the public catalog in list order;
--   * idx_versions_mcp_project_listed (project_id, mcp_listed_at DESC, id DESC)
--       WHERE mcp_listed_at IS NOT NULL — one project's revisions in list order (the project_id
--       filter, and a key's private revisions, which are read project by project). It is not
--       limited to public revisions so that both uses share it.
--
-- 2. Who maintains it
--
-- The three triggers that already maintain versions.mcp_public_doc_tsv (V101), with updated_at
-- added to the columns they fire on:
--
--   * versions  — AFTER INSERT OR UPDATE OF description, version_id, enabled, published, deleted_at,
--                 visibility, project_id, updated_at;
--   * projects  — AFTER UPDATE OF name, enabled, deleted_at, updated_at, tenant_id (a change of
--                 updated_at alone rewrites mcp_listed_at of the project's listed revisions only);
--   * version_tags — AFTER INSERT OR UPDATE OR DELETE. A tag moved to another revision now also
--                 refreshes the revision it left (before, that revision kept the tag's name in
--                 its search document until its next write).
--
-- Nothing in the product sets updated_at from a trigger: every writer names it in its UPDATE, which
-- is what a column trigger fires on. A writer that changes a row without naming updated_at leaves
-- the timestamp, and therefore mcp_listed_at, as it was — the same value the view shows.
--
-- The refresh writes a revision only when its search document or mcp_listed_at actually changes
-- (it wrote every time before), so inserting or editing a draft revision no longer costs a second
-- row version. The content-stamp trigger function (V427) is re-created with mcp_listed_at in its
-- list of derived columns; nothing else in it changes.
--
-- 3. apiome.mcp_project_listing — the rollup behind project.list
--
-- One row per project that has, or had, a listed revision:
--
--   * public_listed_at — the newest mcp_listed_at of its public revisions (what an anonymous caller
--                        and a key of another tenant see);
--   * listed_at        — the newest mcp_listed_at of all its listed revisions (what a key of the
--                        owning tenant sees);
--   * tenant_id        — a copy of projects.tenant_id, so that the list order
--                        (timestamp DESC, tenant_id DESC, project_id DESC) is one index.
--
-- apiome.refresh_mcp_project_listing(project) recomputes one row from the project's listed
-- revisions (an index range of idx_versions_mcp_project_listed). The three triggers call it after
-- they refresh a revision, and a fourth, on DELETE of a listed revision, calls it too.
--
-- 4. The semantic-search index
--
-- V102's HNSW index covered every embedded revision. A search that also filters on visibility then
-- discards candidates after the index returns them, and the planner — which cannot know that
-- embedded revisions are almost all public — priced that above reading every embedding (it chose
-- a sequential scan on the scale database). idx_versions_mcp_public_listed_embedding_hnsw has the
-- catalog's predicate (embedded, listed, public), so there is nothing left to discard; it replaces
-- V102's index. apiome-mcp before DBP-1.22 never used that index (it ordered by a value derived
-- from the distance), so dropping it changes nothing for an older apiome-mcp.
--
-- 5. Measured on the scale database (PostgreSQL 18; 200,000 revisions, 45,000 of them public and
--    published, 20,000 projects; 125,000 tags and 20,000 embeddings added by hand), median of five
--    runs, planning included:
--
--     spec.list page 1 (50 rows)       before  70.0 ms   after 0.19 ms   (196,840 → 446 buffers)
--     spec.list page 500               before  66.9 ms   after 0.17 ms
--     project.list page 1              before  52.6 ms   after 0.07 ms
--     spec.search, 45,000 matches      before 138.4 ms   after 34.1 ms
--     spec.search, 5,000 matches       before  20.8 ms   after  6.6 ms
--     spec.search_semantic page 1      before  45.3 ms   after  7.5 ms   (HNSW, hnsw.ef_search 200)
--     spec.list_tags                   before  83.0 ms a page; after one count of 96.6 ms (30,000
--                                      distinct tags), then pages from memory for 45 s
--
-- 6. What it costs writers (same database, rolled-back transactions, median of three):
--
--     insert 20,000 revisions, a quarter published    1,843 ms → 1,241 ms  (a draft is no longer
--                                                     rewritten by its own insert trigger)
--     publish 5,000 drafts                              876 ms → 1,327 ms  (two index entries and the
--                                                     rollup row each)
--     change a project's updated_at                   its listed revisions are rewritten, which the
--                                                     view's definition requires (they all move in
--                                                     the list): 0.05 ms a revision, 4.8 ms for one
--                                                     project of nine. A revision that has an
--                                                     embedding is re-inserted into the HNSW index
--                                                     as well, like on any non-HOT update: about
--                                                     2 ms each. Before, this write touched no
--                                                     revision (0.05 ms a project).
--
--    An UPDATE of a listed revision that names updated_at now changes an indexed column, so it
--    cannot be a heap-only (HOT) update; drafts are unaffected (their mcp_listed_at stays NULL).
--
-- Large databases: the backfill below updates every listed revision once and the CREATE INDEX
-- statements block writes to versions while they build (the whole migration took 84 s on the
-- scale database, most of it re-inserting the 20,000 embedded revisions into the HNSW index). To
-- avoid the index locks, create the three versions indexes by hand first with CREATE INDEX
-- CONCURRENTLY (same names and definitions) after adding the column; the statements here are
-- IF NOT EXISTS.
--
-- Rollback notes:
--   1. Re-run V101's three CREATE OR REPLACE FUNCTION apiome.trg_* statements and its three
--      DROP TRIGGER / CREATE TRIGGER pairs (they restore the search-document-only triggers).
--   2. DROP TRIGGER IF EXISTS trg_versions_delete_mcp_project_listing ON apiome.versions;
--      DROP FUNCTION IF EXISTS apiome.trg_versions_delete_mcp_project_listing();
--      DROP FUNCTION IF EXISTS apiome.refresh_mcp_listing_for_version(uuid);
--      DROP FUNCTION IF EXISTS apiome.refresh_mcp_project_listing(uuid);
--      DROP FUNCTION IF EXISTS apiome.compute_mcp_listed_at_for_version(uuid);
--   3. DROP TABLE IF EXISTS apiome.mcp_project_listing;
--   4. CREATE INDEX IF NOT EXISTS idx_versions_mcp_public_embedding_hnsw ON apiome.versions
--        USING hnsw (mcp_public_embedding vector_cosine_ops) WHERE mcp_public_embedding IS NOT NULL;
--   5. Re-run V427's CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp(), then
--      ALTER TABLE apiome.versions DROP COLUMN IF EXISTS mcp_listed_at;  (drops its three indexes)
--   apiome-mcp from before this migration runs unchanged against a database that has it.

SET search_path TO apiome, public;

-- ───────────────────────────── the stored sort key ─────────────────────────────

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS mcp_listed_at timestamptz NULL;

COMMENT ON COLUMN apiome.versions.mcp_listed_at IS
  'MCP catalog list order (DBP-1.22, #7205): GREATEST of versions.updated_at, projects.updated_at and the newest version_tags.updated_at of this revision — the updated_at of apiome.mcp_v_public_specs, stored. NOT NULL exactly when the revision is published, enabled and not deleted in an enabled, not deleted project (public or private). Maintained by the mcp_public_doc_tsv triggers.';

CREATE OR REPLACE FUNCTION apiome.compute_mcp_listed_at_for_version(p_version_id uuid)
RETURNS timestamptz
LANGUAGE sql
STABLE
SET search_path TO apiome, public
AS $$
  SELECT CASE
    WHEN v.deleted_at IS NULL
      AND p.deleted_at IS NULL
      AND v.enabled IS TRUE
      AND p.enabled IS TRUE
      AND v.published IS TRUE
    THEN GREATEST(
      v.updated_at,
      p.updated_at,
      COALESCE(
        (SELECT max(vt.updated_at)
           FROM apiome.version_tags vt
          WHERE vt.version_id = v.id AND vt.project_id = v.project_id),
        '-infinity'::timestamptz
      )
    )
    ELSE NULL
  END
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
  WHERE v.id = p_version_id;
$$;

COMMENT ON FUNCTION apiome.compute_mcp_listed_at_for_version(uuid) IS
  'The value versions.mcp_listed_at should hold for a revision: the updated_at expression of apiome.mcp_v_public_specs, or NULL when the MCP catalog cannot list the revision (DBP-1.22, #7205).';

-- ───────────────────────────── the per-project rollup ─────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.mcp_project_listing (
  project_id       uuid PRIMARY KEY REFERENCES apiome.projects(id) ON DELETE CASCADE,
  tenant_id        uuid NOT NULL,
  public_listed_at timestamptz NULL,
  listed_at        timestamptz NULL
);

COMMENT ON TABLE apiome.mcp_project_listing IS
  'Per-project rollup of versions.mcp_listed_at for the MCP project.list tool (DBP-1.22, #7205). Derived data: rebuilt from versions by apiome.refresh_mcp_project_listing.';
COMMENT ON COLUMN apiome.mcp_project_listing.tenant_id IS
  'Copy of projects.tenant_id, so the list order (timestamp, tenant_id, project_id) is one index. Refreshed with the row.';
COMMENT ON COLUMN apiome.mcp_project_listing.public_listed_at IS
  'Newest mcp_listed_at of the project''s public listed revisions; NULL when it has none.';
COMMENT ON COLUMN apiome.mcp_project_listing.listed_at IS
  'Newest mcp_listed_at of all the project''s listed revisions (public and private); NULL when it has none.';

CREATE OR REPLACE FUNCTION apiome.refresh_mcp_project_listing(p_project_id uuid)
RETURNS void
LANGUAGE sql
SET search_path TO apiome, public
AS $$
  INSERT INTO apiome.mcp_project_listing AS l (project_id, tenant_id, public_listed_at, listed_at)
  SELECT p.id,
         p.tenant_id,
         max(v.mcp_listed_at) FILTER (WHERE v.visibility = 'public'::apiome.visibility_type),
         max(v.mcp_listed_at)
    FROM apiome.projects p
    LEFT JOIN apiome.versions v ON v.project_id = p.id AND v.mcp_listed_at IS NOT NULL
   WHERE p.id = p_project_id
   GROUP BY p.id, p.tenant_id
  ON CONFLICT (project_id) DO UPDATE
     SET tenant_id = EXCLUDED.tenant_id,
         public_listed_at = EXCLUDED.public_listed_at,
         listed_at = EXCLUDED.listed_at
   WHERE (l.tenant_id, l.public_listed_at, l.listed_at)
         IS DISTINCT FROM (EXCLUDED.tenant_id, EXCLUDED.public_listed_at, EXCLUDED.listed_at);
$$;

COMMENT ON FUNCTION apiome.refresh_mcp_project_listing(uuid) IS
  'Recomputes one project''s apiome.mcp_project_listing row from its listed revisions; does nothing for a project that no longer exists (DBP-1.22, #7205).';

-- ───────────────────────────── the refresh and its triggers ─────────────────────────────

CREATE OR REPLACE FUNCTION apiome.refresh_mcp_listing_for_version(p_version_id uuid)
RETURNS void
LANGUAGE sql
SET search_path TO apiome, public
AS $$
  UPDATE apiome.versions v
     SET mcp_public_doc_tsv = n.doc_tsv,
         mcp_listed_at = n.listed_at
    FROM (SELECT apiome.compute_mcp_public_doc_tsv_for_version(p_version_id) AS doc_tsv,
                 apiome.compute_mcp_listed_at_for_version(p_version_id) AS listed_at) n
   WHERE v.id = p_version_id
     AND (v.mcp_public_doc_tsv IS DISTINCT FROM n.doc_tsv OR v.mcp_listed_at IS DISTINCT FROM n.listed_at);
$$;

COMMENT ON FUNCTION apiome.refresh_mcp_listing_for_version(uuid) IS
  'Sets a revision''s MCP search document and mcp_listed_at to their computed values, writing the row only when one of them changes (DBP-1.22, #7205).';

CREATE OR REPLACE FUNCTION apiome.trg_versions_refresh_mcp_public_doc_tsv()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  PERFORM apiome.refresh_mcp_listing_for_version(NEW.id);
  -- The rollup changes only when the revision was listed (NEW still carries the stored value) or
  -- can be listed now; a draft costs nothing here.
  IF NEW.mcp_listed_at IS NOT NULL
     OR (NEW.published IS TRUE AND NEW.enabled IS TRUE AND NEW.deleted_at IS NULL) THEN
    PERFORM apiome.refresh_mcp_project_listing(NEW.project_id);
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id THEN
    PERFORM apiome.refresh_mcp_project_listing(OLD.project_id);
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.trg_projects_touch_versions_mcp_public_doc_tsv()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  IF NEW.name IS DISTINCT FROM OLD.name
     OR NEW.enabled IS DISTINCT FROM OLD.enabled
     OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
    -- The search document or the listed state of every revision of the project may change.
    UPDATE apiome.versions v
       SET mcp_public_doc_tsv = n.doc_tsv,
           mcp_listed_at = n.listed_at
      FROM apiome.versions s
     CROSS JOIN LATERAL (
       SELECT apiome.compute_mcp_public_doc_tsv_for_version(s.id) AS doc_tsv,
              apiome.compute_mcp_listed_at_for_version(s.id) AS listed_at
     ) n
     WHERE s.project_id = NEW.id
       AND v.id = s.id
       AND (v.mcp_public_doc_tsv IS DISTINCT FROM n.doc_tsv OR v.mcp_listed_at IS DISTINCT FROM n.listed_at);
  ELSIF NEW.updated_at IS DISTINCT FROM OLD.updated_at THEN
    -- Only the timestamp moved: listed revisions follow it, nothing else changes.
    UPDATE apiome.versions v
       SET mcp_listed_at = apiome.compute_mcp_listed_at_for_version(v.id)
     WHERE v.project_id = NEW.id
       AND v.mcp_listed_at IS NOT NULL
       AND v.mcp_listed_at IS DISTINCT FROM apiome.compute_mcp_listed_at_for_version(v.id);
  END IF;
  PERFORM apiome.refresh_mcp_project_listing(NEW.id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.trg_version_tags_touch_mcp_public_doc_tsv()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  IF TG_OP <> 'DELETE' THEN
    PERFORM apiome.refresh_mcp_listing_for_version(NEW.version_id);
    PERFORM apiome.refresh_mcp_project_listing(NEW.project_id);
  END IF;
  -- The revision a tag left: deleted, or moved to another revision.
  IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.version_id IS DISTINCT FROM NEW.version_id) THEN
    PERFORM apiome.refresh_mcp_listing_for_version(OLD.version_id);
    PERFORM apiome.refresh_mcp_project_listing(OLD.project_id);
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION apiome.trg_versions_delete_mcp_project_listing()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  PERFORM apiome.refresh_mcp_project_listing(OLD.project_id);
  RETURN OLD;
END;
$$;

COMMENT ON FUNCTION apiome.trg_versions_delete_mcp_project_listing() IS
  'Recomputes the project''s MCP listing rollup after one of its listed revisions is deleted (DBP-1.22, #7205).';

-- The content-stamp function, with mcp_listed_at added to the derived columns of versions (the
-- only change from V427): the triggers below and the backfill must not count as content changes.
CREATE OR REPLACE FUNCTION apiome.bump_version_content_stamp()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    -- Versions columns that are bookkeeping or derived from the content, not content. The stored
    -- generated columns are listed too (V422): in a BEFORE trigger NEW does not carry their new
    -- values yet, so comparing them would count every bookkeeping UPDATE as a content change. The
    -- publish counts (V424) are derived from the content. mcp_listed_at (V428) is the listing timestamp
    -- the MCP search-document triggers derive from updated_at, the project and the tags.
    v_version_ignored CONSTANT text[] := ARRAY[
        'content_stamp', 'updated_at', 'mcp_public_doc_tsv', 'mcp_public_embedding',
        'quality_score', 'quality_grade', 'quality_report', 'quality_report_fingerprint',
        'lint_error_count', 'sunset_at', 'operation_count', 'schema_count', 'mcp_listed_at'];
    -- Tables whose rows the publish counts count (V424).
    v_counted  CONSTANT boolean := TG_TABLE_NAME IN ('classes', 'version_path', 'path_operation');
    v_template text;
    v_sql      text;
    v_filters  record;
    v_ids      uuid[];
    v_claimed  uuid[];
BEGIN
    IF TG_LEVEL = 'ROW' THEN
        IF TG_TABLE_SCHEMA = 'apiome' AND TG_TABLE_NAME = 'versions'
           AND TG_OP = 'UPDATE' AND TG_WHEN = 'BEFORE'
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
    v_template := CASE WHEN TG_ARGV[0] ~ '^[a-z_][a-z0-9_]*$'
                       THEN format('SELECT r.%I FROM {rows} r', TG_ARGV[0])
                       ELSE TG_ARGV[0] END;

    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
        v_sql := replace(v_template, '{rows}', 'new_rows');
    ELSIF TG_OP = 'DELETE' THEN
        IF NOT EXISTS (SELECT 1 FROM old_rows) THEN RETURN NULL; END IF;
        v_sql := replace(v_template, '{rows}', 'old_rows');
    ELSE
        IF NOT EXISTS (SELECT 1 FROM new_rows) THEN RETURN NULL; END IF;
        -- Rows without an identical (on the counting columns) partner on the other side of the
        -- UPDATE; both sides are resolved so a row moved between revisions bumps both.
        SELECT * INTO v_filters FROM apiome.content_stamp_row_filters(TG_RELID);
        v_sql := '(' || replace(v_template, '{rows}', format(
                     '(SELECT n.* FROM new_rows n WHERE NOT EXISTS '
                     '(SELECT 1 FROM old_rows o WHERE %s AND NOT (%s)))',
                     v_filters.key_match, v_filters.any_diff))
              || ') UNION ('
              || replace(v_template, '{rows}', format(
                     '(SELECT o.* FROM old_rows o WHERE NOT EXISTS '
                     '(SELECT 1 FROM new_rows n WHERE %s AND NOT (%s)))',
                     v_filters.key_match, v_filters.any_diff))
              || ')';
    END IF;

    EXECUTE format('SELECT coalesce(array_agg(DISTINCT v), ARRAY[]::uuid[]) FROM (%s) AS q(v)', v_sql)
       INTO v_ids;
    IF cardinality(v_ids) = 0 THEN
        RETURN NULL;
    END IF;

    v_claimed := apiome.claim_versions('apiome.content_stamp_bumped', v_ids);
    IF cardinality(v_claimed) > 0 THEN
        UPDATE apiome.versions SET content_stamp = content_stamp + 1 WHERE id = ANY (v_claimed);
    END IF;
    IF v_counted THEN
        v_claimed := apiome.claim_versions('apiome.publish_counts_cleared', v_ids);
        IF cardinality(v_claimed) > 0 THEN
            UPDATE apiome.versions SET operation_count = NULL, schema_count = NULL
             WHERE id = ANY (v_claimed) AND (operation_count IS NOT NULL OR schema_count IS NOT NULL);
        END IF;
    END IF;
    RETURN NULL;
END;
$fn$;


COMMENT ON FUNCTION apiome.bump_version_content_stamp() IS
    'The single trigger function that bumps versions.content_stamp once per transaction (COA-5.2, #7078; generated columns ignored since DBP-1.15, #7198; clears the publish counts on a class, path or operation write since DBP-1.16, #7199; statement-level with transition tables since DBP-1.19, #7202; mcp_listed_at ignored since DBP-1.22, #7205).';

DROP TRIGGER IF EXISTS trg_versions_refresh_mcp_public_doc_tsv ON apiome.versions;
CREATE TRIGGER trg_versions_refresh_mcp_public_doc_tsv
AFTER INSERT OR UPDATE OF description, version_id, enabled, published, deleted_at, visibility, project_id, updated_at
ON apiome.versions
FOR EACH ROW
EXECUTE FUNCTION apiome.trg_versions_refresh_mcp_public_doc_tsv();

DROP TRIGGER IF EXISTS trg_versions_delete_mcp_project_listing ON apiome.versions;
CREATE TRIGGER trg_versions_delete_mcp_project_listing
AFTER DELETE
ON apiome.versions
FOR EACH ROW
WHEN (OLD.mcp_listed_at IS NOT NULL)
EXECUTE FUNCTION apiome.trg_versions_delete_mcp_project_listing();

DROP TRIGGER IF EXISTS trg_projects_touch_versions_mcp_public_doc_tsv ON apiome.projects;
CREATE TRIGGER trg_projects_touch_versions_mcp_public_doc_tsv
AFTER UPDATE OF name, enabled, deleted_at, updated_at, tenant_id
ON apiome.projects
FOR EACH ROW
EXECUTE FUNCTION apiome.trg_projects_touch_versions_mcp_public_doc_tsv();

-- trg_version_tags_touch_mcp_public_doc_tsv (AFTER INSERT OR UPDATE OR DELETE, V101) keeps its
-- definition; its function is replaced above.

-- ───────────────────────────── backfill ─────────────────────────────

-- One pass over the published revisions (the only ones that can be listed). The UPDATE names
-- mcp_listed_at only, so no column trigger fires, and the content stamp ignores the column.
UPDATE apiome.versions v
   SET mcp_listed_at = GREATEST(v.updated_at, p.updated_at, COALESCE(tg.max_tag_updated_at, '-infinity'::timestamptz))
  FROM apiome.versions s
  INNER JOIN apiome.projects p ON p.id = s.project_id
  LEFT JOIN (
    SELECT vt.version_id, vt.project_id, max(vt.updated_at) AS max_tag_updated_at
      FROM apiome.version_tags vt
     GROUP BY vt.version_id, vt.project_id
  ) tg ON tg.version_id = s.id AND tg.project_id = s.project_id
 WHERE v.id = s.id
   AND s.published IS TRUE
   AND s.enabled IS TRUE
   AND s.deleted_at IS NULL
   AND p.enabled IS TRUE
   AND p.deleted_at IS NULL
   AND v.mcp_listed_at IS NULL;

INSERT INTO apiome.mcp_project_listing (project_id, tenant_id, public_listed_at, listed_at)
SELECT p.id,
       p.tenant_id,
       max(v.mcp_listed_at) FILTER (WHERE v.visibility = 'public'::apiome.visibility_type),
       max(v.mcp_listed_at)
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
 WHERE v.mcp_listed_at IS NOT NULL
 GROUP BY p.id, p.tenant_id
ON CONFLICT (project_id) DO UPDATE
   SET tenant_id = EXCLUDED.tenant_id,
       public_listed_at = EXCLUDED.public_listed_at,
       listed_at = EXCLUDED.listed_at;

-- ───────────────────────────── indexes ─────────────────────────────

CREATE INDEX IF NOT EXISTS idx_versions_mcp_public_listed
    ON apiome.versions (mcp_listed_at DESC, id DESC)
    WHERE mcp_listed_at IS NOT NULL AND visibility = 'public';

CREATE INDEX IF NOT EXISTS idx_versions_mcp_project_listed
    ON apiome.versions (project_id, mcp_listed_at DESC, id DESC)
    WHERE mcp_listed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_project_listing_public
    ON apiome.mcp_project_listing (public_listed_at DESC, tenant_id DESC, project_id DESC)
    WHERE public_listed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_project_listing_tenant
    ON apiome.mcp_project_listing (tenant_id, listed_at DESC, project_id DESC)
    WHERE listed_at IS NOT NULL;

-- The semantic-search index moves onto the public listed revisions (section 4 above).
CREATE INDEX IF NOT EXISTS idx_versions_mcp_public_listed_embedding_hnsw
    ON apiome.versions USING hnsw (mcp_public_embedding vector_cosine_ops)
    WHERE mcp_public_embedding IS NOT NULL AND mcp_listed_at IS NOT NULL AND visibility = 'public';

DROP INDEX IF EXISTS apiome.idx_versions_mcp_public_embedding_hnsw;
