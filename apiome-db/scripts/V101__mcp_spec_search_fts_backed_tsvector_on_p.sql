-- MCP spec.search: FTS-backed tsvector on published public revisions (GIN index).
SET search_path TO apiome, public;

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS mcp_public_doc_tsv tsvector NULL;

COMMENT ON COLUMN apiome.versions.mcp_public_doc_tsv IS
  'English FTS document for MCP spec.search over public catalog rows (project title, description, version label, tag names); NULL when revision is not in apiome.mcp_v_public_specs.';

CREATE OR REPLACE FUNCTION apiome.compute_mcp_public_doc_tsv_for_version(p_version_id uuid)
RETURNS tsvector
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
      AND v.visibility = 'public'::apiome.visibility_type
    THEN to_tsvector(
      'english',
      coalesce(p.name, '') || ' ' ||
      coalesce(v.description, '') || ' ' ||
      coalesce(v.version_id, '') || ' ' ||
      coalesce(tag_txt.tags_blob, '')
    )
    ELSE NULL
  END
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
  LEFT JOIN LATERAL (
    SELECT string_agg(vt.name, ' ' ORDER BY vt.name) AS tags_blob
    FROM apiome.version_tags vt
    WHERE vt.version_id = v.id AND vt.project_id = v.project_id
  ) tag_txt ON TRUE
  WHERE v.id = p_version_id;
$$;

CREATE OR REPLACE FUNCTION apiome.trg_versions_refresh_mcp_public_doc_tsv()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  UPDATE apiome.versions v
  SET mcp_public_doc_tsv = apiome.compute_mcp_public_doc_tsv_for_version(v.id)
  WHERE v.id = NEW.id;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.trg_projects_touch_versions_mcp_public_doc_tsv()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
BEGIN
  UPDATE apiome.versions v
  SET mcp_public_doc_tsv = apiome.compute_mcp_public_doc_tsv_for_version(v.id)
  WHERE v.project_id = NEW.id;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION apiome.trg_version_tags_touch_mcp_public_doc_tsv()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO apiome, public
AS $$
DECLARE
  vid uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    vid := OLD.version_id;
  ELSE
    vid := NEW.version_id;
  END IF;

  UPDATE apiome.versions v
  SET mcp_public_doc_tsv = apiome.compute_mcp_public_doc_tsv_for_version(v.id)
  WHERE v.id = vid;

  RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_versions_refresh_mcp_public_doc_tsv ON apiome.versions;
CREATE TRIGGER trg_versions_refresh_mcp_public_doc_tsv
AFTER INSERT OR UPDATE OF description, version_id, enabled, published, deleted_at, visibility, project_id
ON apiome.versions
FOR EACH ROW
EXECUTE FUNCTION apiome.trg_versions_refresh_mcp_public_doc_tsv();

DROP TRIGGER IF EXISTS trg_projects_touch_versions_mcp_public_doc_tsv ON apiome.projects;
CREATE TRIGGER trg_projects_touch_versions_mcp_public_doc_tsv
AFTER UPDATE OF name, enabled, deleted_at
ON apiome.projects
FOR EACH ROW
EXECUTE FUNCTION apiome.trg_projects_touch_versions_mcp_public_doc_tsv();

DROP TRIGGER IF EXISTS trg_version_tags_touch_mcp_public_doc_tsv ON apiome.version_tags;
CREATE TRIGGER trg_version_tags_touch_mcp_public_doc_tsv
AFTER INSERT OR UPDATE OR DELETE
ON apiome.version_tags
FOR EACH ROW
EXECUTE FUNCTION apiome.trg_version_tags_touch_mcp_public_doc_tsv();

UPDATE apiome.versions v
SET mcp_public_doc_tsv = apiome.compute_mcp_public_doc_tsv_for_version(v.id);

CREATE INDEX IF NOT EXISTS idx_versions_mcp_public_doc_tsv_gin
  ON apiome.versions USING gin (mcp_public_doc_tsv)
  WHERE mcp_public_doc_tsv IS NOT NULL;
