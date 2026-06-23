-- Fork lineage: cross-project copy from a source revision (#503)
SET search_path TO odb, public;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS forked_from_revision_id UUID REFERENCES versions(id) ON DELETE SET NULL;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS upstream_project_id UUID REFERENCES projects(id) ON DELETE SET NULL;

COMMENT ON COLUMN versions.forked_from_revision_id IS 'Source schema revision (versions.id) this row was forked from; NULL if not a fork';
COMMENT ON COLUMN versions.upstream_project_id IS 'Project that owns the upstream line for merge/sync; optional, usually the source project';

CREATE INDEX IF NOT EXISTS idx_versions_forked_from_revision_id ON versions(forked_from_revision_id) WHERE forked_from_revision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_versions_upstream_project_id ON versions(upstream_project_id) WHERE upstream_project_id IS NOT NULL;
