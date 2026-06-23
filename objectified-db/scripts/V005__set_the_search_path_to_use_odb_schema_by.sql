-- Set the search path to use odb schema by default
SET search_path TO odb, public;

DROP TABLE IF EXISTS class_properties CASCADE;
DROP TABLE IF EXISTS classes CASCADE;

CREATE TABLE classes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES versions(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    schema JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure class names are unique within each version
    CONSTRAINT classes_version_name_unique UNIQUE (version_id, name)
);

-- Add comments to classes table
COMMENT ON TABLE classes IS 'Stores class definitions that define the structure and validation rules for data objects';
COMMENT ON COLUMN classes.id IS 'Unique identifier for the class';
COMMENT ON COLUMN classes.version_id IS 'Reference to the version this class belongs to';
COMMENT ON COLUMN classes.name IS 'Name of the class (unique within a version)';
COMMENT ON COLUMN classes.description IS 'Optional description of the class purpose and usage';
COMMENT ON COLUMN classes.schema IS 'JSON Schema definition containing properties and validation rules';
COMMENT ON COLUMN classes.enabled IS 'Flag to enable/disable the class without deleting it';
COMMENT ON COLUMN classes.deleted_at IS 'Soft delete timestamp - NULL means not deleted';
COMMENT ON COLUMN classes.created_at IS 'Timestamp when the class was created';
COMMENT ON COLUMN classes.updated_at IS 'Timestamp when the class was last updated';

-- Create indices for classes table
CREATE INDEX idx_classes_version_id ON classes(version_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_classes_name ON classes(name) WHERE deleted_at IS NULL;
CREATE INDEX idx_classes_enabled ON classes(enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_classes_deleted_at ON classes(deleted_at);
CREATE INDEX idx_classes_created_at ON classes(created_at);

-- Create GIN index for JSONB schema queries
CREATE INDEX idx_classes_schema ON classes USING GIN (schema);

CREATE TABLE class_properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    class_id UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    data JSONB NOT NULL,

    -- Ensure property names are unique within each class
    CONSTRAINT class_properties_class_name_unique UNIQUE (class_id, name)
);

-- Add comments to class_properties table
COMMENT ON TABLE class_properties IS 'Junction table linking classes to their properties with property-specific configuration';
COMMENT ON COLUMN class_properties.id IS 'Unique identifier for the class-property relationship';
COMMENT ON COLUMN class_properties.class_id IS 'Reference to the parent class';
COMMENT ON COLUMN class_properties.property_id IS 'Reference to the property definition';
COMMENT ON COLUMN class_properties.name IS 'Property name as used in this class (unique within the class)';
COMMENT ON COLUMN class_properties.description IS 'Optional description of how this property is used in this class';
COMMENT ON COLUMN class_properties.data IS 'Additional configuration data for this property in JSON format';

-- Create indices for class_properties table
CREATE INDEX idx_class_properties_class_id ON class_properties(class_id);
CREATE INDEX idx_class_properties_property_id ON class_properties(property_id);
CREATE INDEX idx_class_properties_name ON class_properties(name);

-- Create GIN index for JSONB data queries
CREATE INDEX idx_class_properties_data ON class_properties USING GIN (data);

