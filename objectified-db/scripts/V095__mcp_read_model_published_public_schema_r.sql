-- MCP read model: published + public schema revisions as a stable spec catalog (#3004).
SET search_path TO odb, public;

CREATE OR REPLACE VIEW odb.mcp_v_public_specs AS
SELECT
  v.id,
  p.tenant_id,
  v.project_id,
  p.name AS title,
  v.version_id AS version,
  v.description,
  COALESCE(tg.tags, ARRAY[]::TEXT[]) AS tags,
  GREATEST(v.updated_at, p.updated_at, COALESCE(tg.max_tag_updated_at, '-infinity'::timestamptz)) AS updated_at
FROM odb.versions v
INNER JOIN odb.projects p ON p.id = v.project_id
LEFT JOIN LATERAL (
  SELECT
    array_agg(vt.name ORDER BY vt.name) AS tags,
    max(vt.updated_at) AS max_tag_updated_at
  FROM odb.version_tags vt
  WHERE vt.version_id = v.id
    AND vt.project_id = v.project_id
) tg ON TRUE
WHERE v.deleted_at IS NULL
  AND p.deleted_at IS NULL
  AND v.enabled IS TRUE
  AND p.enabled IS TRUE
  AND v.published IS TRUE
  AND v.visibility = 'public'::odb.visibility_type;

COMMENT ON VIEW odb.mcp_v_public_specs IS
  'MCP spec discovery: one row per schema revision (versions.id) that is published and public-visible (#3004).';

COMMENT ON COLUMN odb.mcp_v_public_specs.id IS
  'Schema revision id (versions.id); stable spec identity for MCP tools.';

COMMENT ON COLUMN odb.mcp_v_public_specs.tenant_id IS
  'Owning tenant (projects.tenant_id).';

COMMENT ON COLUMN odb.mcp_v_public_specs.project_id IS
  'Project id (versions.project_id).';

COMMENT ON COLUMN odb.mcp_v_public_specs.title IS
  'Human-readable project title (projects.name).';

COMMENT ON COLUMN odb.mcp_v_public_specs.version IS
  'Semantic version label (versions.version_id).';

COMMENT ON COLUMN odb.mcp_v_public_specs.description IS
  'Revision description (versions.description); nullable.';

COMMENT ON COLUMN odb.mcp_v_public_specs.tags IS
  'Sorted distinct git-like tag names (version_tags.name) pointing at this revision; empty array if none.';

COMMENT ON COLUMN odb.mcp_v_public_specs.updated_at IS
  'Freshness cursor: GREATEST of versions.updated_at, projects.updated_at, and the latest version_tags.updated_at for this revision. Advances on project renames and tag mutations, not just revision edits.';
