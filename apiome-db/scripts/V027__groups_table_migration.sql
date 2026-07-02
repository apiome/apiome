-- Groups Table Migration
-- Moves groups from JSONB in canvas_layouts to dedicated tables
-- Groups are linked to versions and store class groupings with positional metadata

SET search_path TO apiome, public;

-- ============================================================================
-- REMOVE GROUPS FROM CANVAS_LAYOUTS
-- Groups are now stored in dedicated tables, not as JSONB in layouts
-- ============================================================================

-- Remove the groups column from canvas_layouts
ALTER TABLE canvas_layouts DROP COLUMN IF EXISTS groups;

-- ============================================================================
-- GROUPS TABLE
-- Stores group information linked to a version with positional metadata
-- ============================================================================
DROP TABLE IF EXISTS apiome.group_classes CASCADE;
DROP TABLE IF EXISTS apiome.groups CASCADE;

CREATE TABLE groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(32),  -- Hex color code or named color (e.g., '#3B82F6', 'blue')
    -- Positional metadata
    position_x DOUBLE PRECISION NOT NULL DEFAULT 0,
    position_y DOUBLE PRECISION NOT NULL DEFAULT 0,
    width DOUBLE PRECISION NOT NULL DEFAULT 200,
    height DOUBLE PRECISION NOT NULL DEFAULT 200,
    z_index INTEGER NOT NULL DEFAULT 0,  -- Layer ordering
    -- Visual settings
    is_collapsed BOOLEAN NOT NULL DEFAULT FALSE,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,  -- Prevent moving/resizing
    opacity DOUBLE PRECISION NOT NULL DEFAULT 1.0,  -- 0.0 to 1.0
    border_style VARCHAR(32) DEFAULT 'solid',  -- solid, dashed, dotted, none
    metadata JSONB,  -- Additional group-specific settings
    -- Timestamps
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    -- Unique group name per version
    CONSTRAINT groups_version_name_unique UNIQUE (version_id, name)
);

COMMENT ON TABLE groups IS 'Visual groupings of classes on the canvas, linked to a version';
COMMENT ON COLUMN groups.id IS 'Unique identifier for the group';
COMMENT ON COLUMN groups.version_id IS 'Reference to the version this group belongs to';
COMMENT ON COLUMN groups.name IS 'Display name for the group (unique within a version)';
COMMENT ON COLUMN groups.description IS 'Optional description of the group purpose';
COMMENT ON COLUMN groups.color IS 'Background/border color for the group container';
COMMENT ON COLUMN groups.position_x IS 'X coordinate of the group on the canvas';
COMMENT ON COLUMN groups.position_y IS 'Y coordinate of the group on the canvas';
COMMENT ON COLUMN groups.width IS 'Width of the group container in pixels';
COMMENT ON COLUMN groups.height IS 'Height of the group container in pixels';
COMMENT ON COLUMN groups.z_index IS 'Layer ordering for overlapping groups (higher = on top)';
COMMENT ON COLUMN groups.is_collapsed IS 'Whether the group is visually collapsed';
COMMENT ON COLUMN groups.is_locked IS 'Whether the group position/size is locked from editing';
COMMENT ON COLUMN groups.opacity IS 'Visual opacity of the group (0.0 = transparent, 1.0 = opaque)';
COMMENT ON COLUMN groups.border_style IS 'Border style: solid, dashed, dotted, or none';
COMMENT ON COLUMN groups.metadata IS 'Additional group-specific settings and custom properties';

-- Indices for groups table
CREATE INDEX idx_groups_version_id ON groups(version_id);
CREATE INDEX idx_groups_name ON groups(name);
CREATE INDEX idx_groups_z_index ON groups(z_index);
CREATE INDEX idx_groups_created_at ON groups(created_at);

-- ============================================================================
-- GROUP CLASSES TABLE
-- Junction table linking groups to classes
-- ============================================================================
CREATE TABLE group_classes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    class_id UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    -- Positional metadata within the group (relative to group origin)
    position_x DOUBLE PRECISION,  -- NULL means auto-layout
    position_y DOUBLE PRECISION,  -- NULL means auto-layout
    sort_order INTEGER NOT NULL DEFAULT 0,  -- Order within the group
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    -- Each class can only be in one group (within the same version)
    CONSTRAINT group_classes_unique UNIQUE (group_id, class_id)
);

COMMENT ON TABLE group_classes IS 'Junction table linking groups to their member classes';
COMMENT ON COLUMN group_classes.id IS 'Unique identifier for the group-class relationship';
COMMENT ON COLUMN group_classes.group_id IS 'Reference to the parent group';
COMMENT ON COLUMN group_classes.class_id IS 'Reference to the class in this group';
COMMENT ON COLUMN group_classes.position_x IS 'X position of class within group (NULL for auto-layout)';
COMMENT ON COLUMN group_classes.position_y IS 'Y position of class within group (NULL for auto-layout)';
COMMENT ON COLUMN group_classes.sort_order IS 'Display order of the class within the group';

-- Indices for group_classes table
CREATE INDEX idx_group_classes_group_id ON group_classes(group_id);
CREATE INDEX idx_group_classes_class_id ON group_classes(class_id);
CREATE INDEX idx_group_classes_sort_order ON group_classes(sort_order);

-- ============================================================================
-- TRIGGER TO UPDATE updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION update_groups_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_groups_updated_at
    BEFORE UPDATE ON groups
    FOR EACH ROW
    EXECUTE FUNCTION update_groups_updated_at();

