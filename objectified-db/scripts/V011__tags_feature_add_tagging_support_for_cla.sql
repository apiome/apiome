-- Tags Feature: Add tagging support for classes
-- Allows organizing and filtering classes using project-scoped tags

SET search_path TO odb, public;

DROP TABLE IF EXISTS class_tags CASCADE;
DROP TABLE IF EXISTS tags CASCADE;

-- Tags table: Stores tag definitions scoped to projects
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(50) NOT NULL DEFAULT 'default',
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure tag names are unique within each project
    CONSTRAINT tags_project_name_unique UNIQUE (project_id, name)
);

-- Add comments to tags table
COMMENT ON TABLE tags IS 'Stores tag definitions for organizing and categorizing classes within projects';
COMMENT ON COLUMN tags.id IS 'Unique identifier for the tag';
COMMENT ON COLUMN tags.project_id IS 'Reference to the project this tag belongs to';
COMMENT ON COLUMN tags.name IS 'Name of the tag (unique within a project)';
COMMENT ON COLUMN tags.color IS 'Color theme for visual display (e.g., "primary", "secondary", "success", "error", "warning", "info", or hex color)';
COMMENT ON COLUMN tags.description IS 'Optional description of the tag purpose and usage';
COMMENT ON COLUMN tags.created_at IS 'Timestamp when the tag was created';
COMMENT ON COLUMN tags.updated_at IS 'Timestamp when the tag was last modified';

-- Create indices for tags table
CREATE INDEX idx_tags_project_id ON tags(project_id);
CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_tags_created_at ON tags(created_at);

-- Class Tags: Junction table linking classes to tags
CREATE TABLE class_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    class_id UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure a tag can only be assigned to a class once
    CONSTRAINT class_tags_class_tag_unique UNIQUE (class_id, tag_id)
);

-- Add comments to class_tags table
COMMENT ON TABLE class_tags IS 'Junction table associating classes with tags for organization and filtering';
COMMENT ON COLUMN class_tags.id IS 'Unique identifier for the class-tag relationship';
COMMENT ON COLUMN class_tags.class_id IS 'Reference to the class';
COMMENT ON COLUMN class_tags.tag_id IS 'Reference to the tag';
COMMENT ON COLUMN class_tags.created_at IS 'Timestamp when the tag was assigned to the class';

-- Create indices for class_tags table
CREATE INDEX idx_class_tags_class_id ON class_tags(class_id);
CREATE INDEX idx_class_tags_tag_id ON class_tags(tag_id);
CREATE INDEX idx_class_tags_created_at ON class_tags(created_at);

-- Function to update the updated_at timestamp for tags
CREATE OR REPLACE FUNCTION update_tags_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at
CREATE TRIGGER trigger_update_tags_updated_at
    BEFORE UPDATE ON tags
    FOR EACH ROW
    EXECUTE FUNCTION update_tags_updated_at();

-- Optional: Insert some sample tags for the default tenant/project
-- Uncomment these lines if you want seed data

-- WITH default_project AS (
--     SELECT p.id
--     FROM projects p
--     JOIN tenants t ON p.tenant_id = t.id
--     WHERE t.slug = 'objectified'
--     LIMIT 1
-- )
-- INSERT INTO tags (project_id, name, color, description)
-- SELECT
--     dp.id,
--     tag_name,
--     tag_color,
--     tag_description
-- FROM default_project dp
-- CROSS JOIN (VALUES
--     ('Domain Model', 'primary', 'Core business domain entities'),
--     ('API Resource', 'info', 'REST API resource classes'),
--     ('Authentication', 'warning', 'Authentication and authorization related'),
--     ('Infrastructure', 'secondary', 'Infrastructure and technical classes'),
--     ('Deprecated', 'error', 'Classes marked for deprecation')
-- ) AS tag_data(tag_name, tag_color, tag_description);

