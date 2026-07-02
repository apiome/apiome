-- Nested canvas groups (#155): optional parent_group_id, max depth enforced in application (3 levels).

SET search_path TO apiome, public;

ALTER TABLE apiome.groups
    ADD COLUMN IF NOT EXISTS parent_group_id UUID REFERENCES apiome.groups(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_groups_parent_group_id ON apiome.groups(parent_group_id);

COMMENT ON COLUMN apiome.groups.parent_group_id IS 'Parent group for hierarchical nesting; null = top-level. App limits nesting to 3 levels.';
