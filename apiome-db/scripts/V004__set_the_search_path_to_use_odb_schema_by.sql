-- Set the search path to use apiome schema by default
SET search_path TO apiome, public;

DROP TABLE IF EXISTS properties CASCADE;

CREATE TABLE properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    data JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure property names are unique within each project
    CONSTRAINT properties_project_name_unique UNIQUE (project_id, name)
);

-- Table comment
COMMENT ON TABLE properties IS 'Stores property definitions for projects. Properties represent configurable attributes or metadata that can be associated with classes and objects within a project.';

-- Column comments
COMMENT ON COLUMN properties.id IS 'Unique identifier for the property';
COMMENT ON COLUMN properties.project_id IS 'Reference to the project this property belongs to';
COMMENT ON COLUMN properties.name IS 'Name of the property, must be unique within the project';
COMMENT ON COLUMN properties.description IS 'Optional detailed description of the property and its purpose';
COMMENT ON COLUMN properties.data IS 'JSONB data containing property configuration, schema, type information, and metadata';
COMMENT ON COLUMN properties.enabled IS 'Flag indicating if the property is currently active and available for use';
COMMENT ON COLUMN properties.deleted_at IS 'Soft delete timestamp - when set, indicates the property has been deleted';
COMMENT ON COLUMN properties.created_at IS 'Timestamp when the property was created';
COMMENT ON COLUMN properties.updated_at IS 'Timestamp when the property was last modified';

-- Indices for performance optimization

-- Index on project_id for efficient querying of all properties in a project
CREATE INDEX idx_properties_project_id ON properties(project_id) WHERE deleted_at IS NULL;

-- Index on enabled status for filtering active properties
CREATE INDEX idx_properties_enabled ON properties(enabled) WHERE deleted_at IS NULL;

-- Index on deleted_at for soft delete queries
CREATE INDEX idx_properties_deleted_at ON properties(deleted_at);

-- Composite index for project queries with enabled filter
CREATE INDEX idx_properties_project_enabled ON properties(project_id, enabled) WHERE deleted_at IS NULL;

-- GIN index on JSONB data column for efficient querying of property configuration
CREATE INDEX idx_properties_data_gin ON properties USING GIN (data);

-- Index on name for text searches
CREATE INDEX idx_properties_name ON properties(name) WHERE deleted_at IS NULL;

-- Index on created_at for chronological queries
CREATE INDEX idx_properties_created_at ON properties(created_at DESC);

