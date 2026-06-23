-- Git-like version branches and merge lineage (DAG edges on versions rows)
SET search_path TO odb, public;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS parent_version_id UUID REFERENCES versions(id) ON DELETE SET NULL;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS merge_parent_version_id UUID REFERENCES versions(id) ON DELETE SET NULL;

COMMENT ON COLUMN versions.parent_version_id IS 'Linear parent revision (first parent) for history; NULL for roots';
COMMENT ON COLUMN versions.merge_parent_version_id IS 'Second parent for merge commits; NULL unless this row is a merge revision';

CREATE INDEX IF NOT EXISTS idx_versions_parent_version_id ON versions(parent_version_id) WHERE parent_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_versions_merge_parent_version_id ON versions(merge_parent_version_id) WHERE merge_parent_version_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS version_branches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    tip_version_id UUID NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT version_branches_project_name_unique UNIQUE (project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_version_branches_project_id ON version_branches(project_id);
CREATE INDEX IF NOT EXISTS idx_version_branches_tip_version_id ON version_branches(tip_version_id);

COMMENT ON TABLE version_branches IS 'Named branch whose tip points at a version row (schema revision)';
COMMENT ON COLUMN version_branches.tip_version_id IS 'Current head version id for this branch';
