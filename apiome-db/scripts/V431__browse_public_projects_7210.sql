-- Public Browse: a maintained summary of the public catalog, and a stored MCP host (DBP-1.27, #7210).
--
-- The Browse home page, the directory counters in the navbar, an organization's project list and
-- the search scope all need the same facts about every public project: how many public versions it
-- has, which one is the latest, which protocols and formats it publishes. Each read worked them out
-- again from apiome.versions — a pass over every published public version (100,000 on the scale
-- database), four times on a cold home page, and once per search before any term was matched.
--
-- 1. apiome.browse_public_projects — one row per public project
--
-- A project has a row exactly while it is in the public catalog: it and its tenant are not deleted
-- and it has at least one version that is published, public and not deleted (the gates every Browse
-- statement applies). The row holds
--
--   * tenant_id            — a copy of projects.tenant_id;
--   * version_count        — its published public versions;
--   * latest_version_id    — the newest of them (published_at DESC NULLS LAST, created_at DESC, the
--                            order every Browse surface uses; id breaks a tie);
--   * latest_published_at  — that version's published_at;
--   * protocols, formats   — the distinct lower-cased versions.protocol / versions.source_format
--                            across its published public versions, sorted;
--   * operation_count, schema_count, quality_grade, quality_score — of the latest version. The
--                            counts are always filled: versions.operation_count / schema_count
--                            (V424) when recorded, a count otherwise.
--
-- Readers that need more about the latest version (mock, SDK, format) join apiome.versions on
-- latest_version_id — a primary-key lookup per card shown.
--
-- 2. Who maintains it
--
-- apiome.refresh_browse_public_projects(uuid[]) recomputes the rows of the given projects in one
-- statement: it inserts, updates (only when a value differs) or deletes each. It first locks the
-- project rows FOR NO KEY UPDATE, so two transactions that change the same project's versions at
-- once refresh one after the other and the second sees the first's versions.
--
--   * versions — three AFTER … FOR EACH STATEMENT triggers with transition tables (insert, update,
--                delete). The update trigger refreshes only projects with a row that is, or was,
--                published and public and in which a summarized column changed; an edit to a
--                draft or to a private version costs one comparison and no write. A statement
--                that changes many versions (retention pruning) is one refresh.
--   * versions — one DEFERRED constraint trigger for content written to a published public
--                version. A class, path or operation write moves versions.content_stamp once per
--                transaction (V403) and clears the stored counts (V424) — on the transaction's
--                first write, when the rest of its content is not there yet. The trigger fires on
--                that content_stamp change and runs at commit, so the refresh counts everything
--                the transaction wrote. One refresh per version and transaction.
--   * projects — AFTER UPDATE OF deleted_at, tenant_id (row; fires only when one changes).
--   * tenants  — AFTER UPDATE OF deleted_at (row; refreshes the tenant's projects).
--
-- A hard DELETE of a project removes its row through the foreign key. Nothing here writes
-- apiome.versions, so no content stamp moves and no other trigger fires.
--
-- Rows written under session_replication_role = replica (the scale seed, a restore that disables
-- triggers) are not summarized; run
--     SELECT apiome.refresh_browse_public_projects(ARRAY(SELECT id FROM apiome.projects));
-- afterwards. It is always safe to run.
--
-- 3. apiome.mcp_endpoints.host
--
-- apiome.mcp_v_public_endpoints derived each endpoint's host from endpoint_url with a regular
-- expression on every read, so the public MCP index sorted on an expression no index could serve
-- and the registry de-duplication compared lower(host) row by row. host is now a stored generated
-- column with the same expression (userinfo stripped, case kept; NULL for a URL without "://"), the
-- view selects it, and two partial indexes cover the public endpoints: one in host order, one on
-- lower(host). A third covers the registry server name of public endpoints.
--
-- Adding a stored generated column rewrites apiome.mcp_endpoints under ACCESS EXCLUSIVE. The table
-- holds one row per registered MCP server (2,000 on the scale database: under 50 ms).
--
-- Backfill: one INSERT … SELECT over the published public versions (100,000 on the scale database).
--
-- Rollback notes:
--   1. DROP TRIGGER IF EXISTS trg_versions_browse_public_insert ON apiome.versions;
--      DROP TRIGGER IF EXISTS trg_versions_browse_public_update ON apiome.versions;
--      DROP TRIGGER IF EXISTS trg_versions_browse_public_delete ON apiome.versions;
--      DROP TRIGGER IF EXISTS trg_versions_browse_public_content ON apiome.versions;
--      DROP TRIGGER IF EXISTS trg_projects_browse_public ON apiome.projects;
--      DROP TRIGGER IF EXISTS trg_tenants_browse_public ON apiome.tenants;
--   2. DROP FUNCTION IF EXISTS apiome.trg_versions_browse_public();
--      DROP FUNCTION IF EXISTS apiome.trg_versions_browse_public_content();
--      DROP FUNCTION IF EXISTS apiome.trg_projects_browse_public();
--      DROP FUNCTION IF EXISTS apiome.trg_tenants_browse_public();
--      DROP FUNCTION IF EXISTS apiome.refresh_browse_public_projects(uuid[]);
--   3. DROP TABLE IF EXISTS apiome.browse_public_projects;
--   4. Re-run V134's CREATE OR REPLACE VIEW apiome.mcp_v_public_endpoints, then
--      ALTER TABLE apiome.mcp_endpoints DROP COLUMN IF EXISTS host;  (drops its three indexes)
--   Deploy the previous apiome-browse first: this release reads the table and the column.

SET search_path TO apiome, public;

-- ───────────────────────────── the summary table ─────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.browse_public_projects (
  project_id          uuid PRIMARY KEY REFERENCES apiome.projects(id) ON DELETE CASCADE,
  tenant_id           uuid NOT NULL,
  version_count       integer NOT NULL CONSTRAINT browse_public_projects_version_count_check CHECK (version_count > 0),
  latest_version_id   uuid NOT NULL,
  latest_published_at timestamptz NULL,
  protocols           text[] NOT NULL DEFAULT ARRAY[]::text[],
  formats             text[] NOT NULL DEFAULT ARRAY[]::text[],
  operation_count     integer NOT NULL DEFAULT 0 CONSTRAINT browse_public_projects_operation_count_check CHECK (operation_count >= 0),
  schema_count        integer NOT NULL DEFAULT 0 CONSTRAINT browse_public_projects_schema_count_check CHECK (schema_count >= 0),
  quality_grade       text NULL,
  quality_score       integer NULL
);

COMMENT ON TABLE apiome.browse_public_projects IS
  'One row per project in the public catalog — not deleted, in a tenant that is not deleted, with at least one published public version (DBP-1.27, #7210). Derived data: rebuilt from versions by apiome.refresh_browse_public_projects.';
COMMENT ON COLUMN apiome.browse_public_projects.tenant_id IS
  'Copy of projects.tenant_id. Refreshed with the row.';
COMMENT ON COLUMN apiome.browse_public_projects.version_count IS
  'Published public versions of the project that are not deleted.';
COMMENT ON COLUMN apiome.browse_public_projects.latest_version_id IS
  'The newest published public version: published_at DESC NULLS LAST, created_at DESC, id DESC. A copy, not a foreign key: the row is refreshed when that version changes or is deleted.';
COMMENT ON COLUMN apiome.browse_public_projects.latest_published_at IS
  'published_at of latest_version_id.';
COMMENT ON COLUMN apiome.browse_public_projects.protocols IS
  'Distinct lower-cased versions.protocol of the published public versions, sorted; blank values left out.';
COMMENT ON COLUMN apiome.browse_public_projects.formats IS
  'Distinct lower-cased versions.source_format of the published public versions, sorted; blank values left out.';
COMMENT ON COLUMN apiome.browse_public_projects.operation_count IS
  'Operations in latest_version_id: versions.operation_count when recorded (V424), a count otherwise.';
COMMENT ON COLUMN apiome.browse_public_projects.schema_count IS
  'Schemas (live classes) in latest_version_id: versions.schema_count when recorded (V424), a count otherwise.';
COMMENT ON COLUMN apiome.browse_public_projects.quality_grade IS
  'Trimmed versions.quality_grade of latest_version_id; NULL when it has not been scored.';
COMMENT ON COLUMN apiome.browse_public_projects.quality_score IS
  'versions.quality_score of latest_version_id.';

-- ───────────────────────────── the refresh ─────────────────────────────

CREATE OR REPLACE FUNCTION apiome.refresh_browse_public_projects(p_project_ids uuid[])
RETURNS void
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  IF p_project_ids IS NULL OR cardinality(p_project_ids) = 0 THEN
    RETURN;
  END IF;

  -- One refresh of a project at a time, in id order (no deadlock between two refreshes). The
  -- statement below starts after the lock is held, so it sees what the other refresh committed.
  -- NO KEY UPDATE does not block a version insert's KEY SHARE lock on its project.
  PERFORM 1
     FROM apiome.projects p
    WHERE p.id = ANY (p_project_ids)
    ORDER BY p.id
      FOR NO KEY UPDATE;

  WITH wanted AS (
    SELECT DISTINCT w.project_id FROM unnest(p_project_ids) AS w(project_id) WHERE w.project_id IS NOT NULL
  ),
  rolled AS (
    SELECT p.id AS project_id,
           p.tenant_id,
           COUNT(*)::int AS version_count,
           COALESCE(
             array_agg(DISTINCT NULLIF(LOWER(TRIM(COALESCE(v.protocol, ''))), ''))
               FILTER (WHERE NULLIF(TRIM(COALESCE(v.protocol, '')), '') IS NOT NULL),
             ARRAY[]::text[]) AS protocols,
           COALESCE(
             array_agg(DISTINCT NULLIF(LOWER(TRIM(COALESCE(v.source_format, ''))), ''))
               FILTER (WHERE NULLIF(TRIM(COALESCE(v.source_format, '')), '') IS NOT NULL),
             ARRAY[]::text[]) AS formats
      FROM wanted w
      JOIN apiome.projects p ON p.id = w.project_id AND p.deleted_at IS NULL
      JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL
      JOIN apiome.versions v ON v.project_id = p.id
     WHERE v.published = true
       AND v.visibility = 'public'
       AND v.deleted_at IS NULL
     GROUP BY p.id, p.tenant_id
  ),
  computed AS (
    SELECT r.project_id, r.tenant_id, r.version_count, lv.id AS latest_version_id,
           lv.published_at AS latest_published_at, r.protocols, r.formats,
           COALESCE(lv.operation_count,
             (SELECT COUNT(*)::int
                FROM apiome.version_path vp
                JOIN apiome.path_operation po ON po.version_path_id = vp.id
               WHERE vp.version_id = lv.id)) AS operation_count,
           COALESCE(lv.schema_count,
             (SELECT COUNT(*)::int
                FROM apiome.classes c
               WHERE c.version_id = lv.id AND c.deleted_at IS NULL)) AS schema_count,
           NULLIF(TRIM(lv.quality_grade), '') AS quality_grade,
           lv.quality_score::int AS quality_score
      FROM rolled r
      JOIN LATERAL (
        SELECT l.id, l.published_at, l.operation_count, l.schema_count, l.quality_grade, l.quality_score
          FROM apiome.versions l
         WHERE l.project_id = r.project_id
           AND l.published = true
           AND l.visibility = 'public'
           AND l.deleted_at IS NULL
         ORDER BY l.published_at DESC NULLS LAST, l.created_at DESC, l.id DESC
         LIMIT 1
      ) lv ON TRUE
  ),
  removed AS (
    DELETE FROM apiome.browse_public_projects b
     USING wanted w
     WHERE b.project_id = w.project_id
       AND NOT EXISTS (SELECT 1 FROM computed c WHERE c.project_id = b.project_id)
  )
  INSERT INTO apiome.browse_public_projects AS b
         (project_id, tenant_id, version_count, latest_version_id, latest_published_at,
          protocols, formats, operation_count, schema_count, quality_grade, quality_score)
  SELECT c.project_id, c.tenant_id, c.version_count, c.latest_version_id, c.latest_published_at,
         c.protocols, c.formats, c.operation_count, c.schema_count, c.quality_grade, c.quality_score
    FROM computed c
  ON CONFLICT (project_id) DO UPDATE
     SET tenant_id = EXCLUDED.tenant_id,
         version_count = EXCLUDED.version_count,
         latest_version_id = EXCLUDED.latest_version_id,
         latest_published_at = EXCLUDED.latest_published_at,
         protocols = EXCLUDED.protocols,
         formats = EXCLUDED.formats,
         operation_count = EXCLUDED.operation_count,
         schema_count = EXCLUDED.schema_count,
         quality_grade = EXCLUDED.quality_grade,
         quality_score = EXCLUDED.quality_score
   WHERE (b.tenant_id, b.version_count, b.latest_version_id, b.latest_published_at, b.protocols,
          b.formats, b.operation_count, b.schema_count, b.quality_grade, b.quality_score)
         IS DISTINCT FROM
         (EXCLUDED.tenant_id, EXCLUDED.version_count, EXCLUDED.latest_version_id,
          EXCLUDED.latest_published_at, EXCLUDED.protocols, EXCLUDED.formats,
          EXCLUDED.operation_count, EXCLUDED.schema_count, EXCLUDED.quality_grade,
          EXCLUDED.quality_score);
END;
$$;

COMMENT ON FUNCTION apiome.refresh_browse_public_projects(uuid[]) IS
  'Recomputes the apiome.browse_public_projects rows of the given projects from their published public versions: inserts, updates only when a value differs, or deletes. Ids of projects that no longer exist are ignored (DBP-1.27, #7210).';

-- ───────────────────────────── triggers ─────────────────────────────

-- One function for the three statement triggers on versions. Every trigger names its transition
-- tables old_rows / new_rows; an insert has no old_rows and a delete no new_rows, hence the three
-- branches (a missing transition table cannot be referenced, even in a branch not taken, so each
-- branch is its own statement).
CREATE OR REPLACE FUNCTION apiome.trg_versions_browse_public()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
DECLARE
  v_projects uuid[];
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT array_agg(DISTINCT n.project_id) INTO v_projects
      FROM new_rows n
     WHERE n.published AND n.visibility = 'public' AND n.deleted_at IS NULL;
  ELSIF TG_OP = 'DELETE' THEN
    SELECT array_agg(DISTINCT o.project_id) INTO v_projects
      FROM old_rows o
     WHERE o.published AND o.visibility = 'public' AND o.deleted_at IS NULL;
  ELSE
    SELECT array_agg(DISTINCT x.project_id) INTO v_projects
      FROM old_rows o
      JOIN new_rows n ON n.id = o.id
      CROSS JOIN LATERAL (VALUES (o.project_id), (n.project_id)) AS x(project_id)
     WHERE ((o.published AND o.visibility = 'public' AND o.deleted_at IS NULL)
         OR (n.published AND n.visibility = 'public' AND n.deleted_at IS NULL))
       AND (o.published, o.visibility, o.deleted_at, o.project_id, o.published_at, o.created_at,
            o.protocol, o.source_format, o.operation_count, o.schema_count, o.quality_grade,
            o.quality_score)
           IS DISTINCT FROM
           (n.published, n.visibility, n.deleted_at, n.project_id, n.published_at, n.created_at,
            n.protocol, n.source_format, n.operation_count, n.schema_count, n.quality_grade,
            n.quality_score);
  END IF;

  PERFORM apiome.refresh_browse_public_projects(v_projects);
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION apiome.trg_versions_browse_public() IS
  'Statement trigger on versions: refreshes apiome.browse_public_projects for the projects whose published public versions the statement changed (DBP-1.27, #7210).';

DROP TRIGGER IF EXISTS trg_versions_browse_public_insert ON apiome.versions;
CREATE TRIGGER trg_versions_browse_public_insert
AFTER INSERT ON apiome.versions
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION apiome.trg_versions_browse_public();

DROP TRIGGER IF EXISTS trg_versions_browse_public_update ON apiome.versions;
CREATE TRIGGER trg_versions_browse_public_update
AFTER UPDATE ON apiome.versions
REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION apiome.trg_versions_browse_public();

DROP TRIGGER IF EXISTS trg_versions_browse_public_delete ON apiome.versions;
CREATE TRIGGER trg_versions_browse_public_delete
AFTER DELETE ON apiome.versions
REFERENCING OLD TABLE AS old_rows
FOR EACH STATEMENT
EXECUTE FUNCTION apiome.trg_versions_browse_public();

CREATE OR REPLACE FUNCTION apiome.trg_versions_browse_public_content()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  PERFORM apiome.refresh_browse_public_projects(ARRAY[NEW.project_id]);
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION apiome.trg_versions_browse_public_content() IS
  'Deferred to commit: refreshes the project''s apiome.browse_public_projects row after content was written to one of its published public versions, so the counts include everything the transaction wrote (DBP-1.27, #7210).';

DROP TRIGGER IF EXISTS trg_versions_browse_public_content ON apiome.versions;
CREATE CONSTRAINT TRIGGER trg_versions_browse_public_content
AFTER UPDATE ON apiome.versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
WHEN (OLD.content_stamp IS DISTINCT FROM NEW.content_stamp
      AND NEW.published AND NEW.visibility = 'public' AND NEW.deleted_at IS NULL)
EXECUTE FUNCTION apiome.trg_versions_browse_public_content();

CREATE OR REPLACE FUNCTION apiome.trg_projects_browse_public()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  PERFORM apiome.refresh_browse_public_projects(ARRAY[NEW.id]);
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION apiome.trg_projects_browse_public() IS
  'Refreshes a project''s apiome.browse_public_projects row when the project is deleted, restored or moved to another tenant (DBP-1.27, #7210).';

DROP TRIGGER IF EXISTS trg_projects_browse_public ON apiome.projects;
CREATE TRIGGER trg_projects_browse_public
AFTER UPDATE OF deleted_at, tenant_id ON apiome.projects
FOR EACH ROW
WHEN (OLD.deleted_at IS DISTINCT FROM NEW.deleted_at OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id)
EXECUTE FUNCTION apiome.trg_projects_browse_public();

CREATE OR REPLACE FUNCTION apiome.trg_tenants_browse_public()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  PERFORM apiome.refresh_browse_public_projects(
    ARRAY(SELECT p.id FROM apiome.projects p WHERE p.tenant_id = NEW.id));
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION apiome.trg_tenants_browse_public() IS
  'Refreshes the apiome.browse_public_projects rows of a tenant''s projects when the tenant is deleted or restored (DBP-1.27, #7210).';

DROP TRIGGER IF EXISTS trg_tenants_browse_public ON apiome.tenants;
CREATE TRIGGER trg_tenants_browse_public
AFTER UPDATE OF deleted_at ON apiome.tenants
FOR EACH ROW
WHEN (OLD.deleted_at IS DISTINCT FROM NEW.deleted_at)
EXECUTE FUNCTION apiome.trg_tenants_browse_public();

-- ───────────────────────────── backfill ─────────────────────────────

-- The refresh itself, over the projects that have a published public version. Projects without
-- one get no row, so they are not passed.
SELECT apiome.refresh_browse_public_projects(ARRAY(
  SELECT DISTINCT v.project_id
    FROM apiome.versions v
   WHERE v.published = true
     AND v.visibility = 'public'
     AND v.deleted_at IS NULL));

-- ───────────────────────────── indexes ─────────────────────────────

-- An organization's public projects (the organization page; the search scope of an org: filter).
CREATE INDEX IF NOT EXISTS idx_browse_public_projects_tenant
    ON apiome.browse_public_projects (tenant_id);

-- The three orders of the home page's project rail, so each reads its first rows from an index.
CREATE INDEX IF NOT EXISTS idx_browse_public_projects_by_versions
    ON apiome.browse_public_projects (version_count DESC, latest_published_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_browse_public_projects_by_operations
    ON apiome.browse_public_projects (operation_count DESC, version_count DESC, latest_published_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_browse_public_projects_by_grade
    ON apiome.browse_public_projects (quality_grade ASC NULLS LAST, quality_score DESC NULLS LAST, latest_published_at DESC NULLS LAST);

-- ───────────────────────────── the stored MCP host ─────────────────────────────

ALTER TABLE apiome.mcp_endpoints
  ADD COLUMN IF NOT EXISTS host text
  GENERATED ALWAYS AS (substring(endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)')) STORED;

COMMENT ON COLUMN apiome.mcp_endpoints.host IS
  'Host of endpoint_url with userinfo stripped, case kept; NULL for a URL without "://" (stdio). Stored generated column: the expression apiome.mcp_v_public_endpoints computed per read until DBP-1.27 (#7210).';

-- Same columns, names and order as V134; host now reads the stored column.
CREATE OR REPLACE VIEW apiome.mcp_v_public_endpoints AS
SELECT
  e.id,
  e.tenant_id,
  e.name,
  e.slug,
  e.category,
  e.transport,
  e.description,
  e.current_version_id,
  e.host,
  s.score,
  s.grade,
  s.scored_at,
  e.last_discovered_at,
  e.updated_at
FROM apiome.mcp_endpoints e
LEFT JOIN apiome.mcp_version_scores s ON s.version_id = e.current_version_id
WHERE e.deleted_at IS NULL
  AND e.enabled IS TRUE
  AND e.published IS TRUE
  AND e.visibility = 'public'::apiome.visibility_type;

-- The predicates below are the view's, so the planner can use the indexes through it.

-- The public MCP index, which lists endpoints in host order.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_public_host
    ON apiome.mcp_endpoints (host, id)
    WHERE deleted_at IS NULL AND enabled IS TRUE AND published IS TRUE
      AND visibility = 'public'::apiome.visibility_type;

-- Registry de-duplication: "is a public endpoint on this host?" …
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_public_host_lower
    ON apiome.mcp_endpoints (lower(host))
    WHERE deleted_at IS NULL AND enabled IS TRUE AND published IS TRUE
      AND visibility = 'public'::apiome.visibility_type;

-- … and "is a public endpoint this registry server?", across tenants
-- (idx_mcp_endpoints_registry_server_name leads with tenant_id).
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_public_registry_server_name
    ON apiome.mcp_endpoints (lower(registry_metadata->>'serverName'))
    WHERE deleted_at IS NULL AND enabled IS TRUE AND published IS TRUE
      AND visibility = 'public'::apiome.visibility_type;
