-- Nested canvas groups (#155): optional parent_group_id, max depth enforced in application (3 levels).

SET search_path TO odb, public;

ALTER TABLE odb.groups
    ADD COLUMN IF NOT EXISTS parent_group_id UUID REFERENCES odb.groups(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_groups_parent_group_id ON odb.groups(parent_group_id);

COMMENT ON COLUMN odb.groups.parent_group_id IS 'Parent group for hierarchical nesting; null = top-level. App limits nesting to 3 levels.';
