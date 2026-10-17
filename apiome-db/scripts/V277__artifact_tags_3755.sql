-- Free-form artifact tags (#3755, MFI-6.3 — catalog categorization).
--
-- A catalog item is categorized three ways: its **paradigm** (auto-derived — the latest revision's
-- `versions.protocol`, MFI-7.1), its **domain** (manual — the existing `projects.metadata.domainCategory`
-- allow-list), and free-form **tags** (manual — this table). All three are browse facets on
-- `GET /v1/catalog/{tenant}`.
--
-- The table is generic over the artifact kind so the still-open MCP categorization (MCAT-9.3, #3693:
-- "free tags table per endpoint") can tag `mcp_endpoints` rows without a second table. Each row tags
-- exactly one artifact, held by a real foreign key so deleting the artifact deletes its tags.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.artifact_tags;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.artifact_tags (
    id               UUID          NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id        UUID          NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    project_id       UUID          REFERENCES apiome.projects(id) ON DELETE CASCADE,
    mcp_endpoint_id  UUID          REFERENCES apiome.mcp_endpoints(id) ON DELETE CASCADE,
    tag              VARCHAR(64)   NOT NULL,
    created_by       UUID          REFERENCES apiome.users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Exactly one artifact per row.
    CONSTRAINT artifact_tags_one_artifact_check
        CHECK (num_nonnulls(project_id, mcp_endpoint_id) = 1),

    -- A tag is trimmed, non-empty text; the API lower-cases it before writing.
    CONSTRAINT artifact_tags_tag_check
        CHECK (tag = btrim(tag) AND length(tag) BETWEEN 1 AND 64)
);

COMMENT ON TABLE apiome.artifact_tags IS
  'Free-form tags on an artifact (#3755, MFI-6.3): a catalog item or Project (project_id) or, for '
  'MCAT-9.3, an MCP endpoint (mcp_endpoint_id). Exactly one artifact column is set per row. Tags are '
  'stored lower-cased and are unique per artifact.';

COMMENT ON COLUMN apiome.artifact_tags.tag IS
  'The tag, lower-cased and trimmed by the API (1-64 characters).';

-- One tag per artifact, case-insensitively (the API also lower-cases on write).
CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_tags_project_tag
  ON apiome.artifact_tags(project_id, lower(tag))
  WHERE project_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_tags_mcp_endpoint_tag
  ON apiome.artifact_tags(mcp_endpoint_id, lower(tag))
  WHERE mcp_endpoint_id IS NOT NULL;

-- The tag facet: which artifacts in a tenant carry a tag, and how many carry each.
CREATE INDEX IF NOT EXISTS idx_artifact_tags_tenant_tag
  ON apiome.artifact_tags(tenant_id, lower(tag));
