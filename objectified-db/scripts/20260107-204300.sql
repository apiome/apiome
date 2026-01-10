-- Pathing and operations

-- Set the search path to use odb schema by default
SET search_path TO odb, public;

DROP INDEX IF EXISTS idx_version_path_version_id CASCADE;
DROP INDEX IF EXISTS idx_version_path_created_at CASCADE;
DROP TABLE IF EXISTS version_path CASCADE;

CREATE TABLE IF NOT EXISTS version_path(
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    pathname VARCHAR(255) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_id, pathname)
);

-- Table comment
COMMENT ON TABLE version_path IS 'Service Paths associated to a project version';

-- Column comments
COMMENT ON COLUMN version_path.id IS 'Unique identifier for the version path record';
COMMENT ON COLUMN version_path.version_id IS 'Foreign key reference to the parent version (cascades on deletion)';
COMMENT ON COLUMN version_path.pathname IS 'The service path definition';
COMMENT ON COLUMN version_path.metadata IS 'Additional metadata for the service path in JSONB format';
COMMENT ON COLUMN version_path.created_at IS 'Timestamp when this path record was created';
COMMENT ON COLUMN version_path.updated_at IS 'Timestamp when this path record was last modified';

-- Indices for performance optimization
CREATE INDEX idx_version_path_version_id ON version_path(version_id);
CREATE INDEX idx_version_path_created_at ON version_path(created_at);

-- Path Operation

DROP INDEX IF EXISTS idx_path_operation_version_path_id CASCADE;
DROP INDEX IF EXISTS idx_path_operation_created_at CASCADE;
DROP TABLE IF EXISTS path_operation CASCADE;

CREATE TABLE IF NOT EXISTS path_operation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_path_id UUID NOT NULL REFERENCES version_path(id) ON DELETE CASCADE,
    operation VARCHAR(50) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_path_id, operation)
);

-- Table comment
COMMENT ON TABLE path_operation IS 'Operations associated with a specific service path';

-- Column comments
COMMENT ON COLUMN path_operation.id IS 'Unique identifier for the path operation record';
COMMENT ON COLUMN path_operation.version_path_id IS 'Foreign key reference to the parent version path (cascades on deletion)';
COMMENT ON COLUMN path_operation.operation IS 'The HTTP operation (e.g., GET, POST, PUT, DELETE, OPTIONS, HEAD)';
COMMENT ON COLUMN path_operation.metadata IS 'Additional metadata for the operation in JSONB format';
COMMENT ON COLUMN path_operation.created_at IS 'Timestamp when this operation record was created';
COMMENT ON COLUMN path_operation.updated_at IS 'Timestamp when this operation record was last modified';

-- Indices for performance optimization
CREATE INDEX idx_path_operation_version_path_id ON path_operation(version_path_id);
CREATE INDEX idx_path_operation_created_at ON path_operation(created_at);

-- Path operation description
DROP INDEX IF EXISTS idx_path_operation_description_path_operation_id CASCADE;
DROP INDEX IF EXISTS idx_path_operation_description_created_at CASCADE;
DROP TABLE IF EXISTS path_operation_description CASCADE;

CREATE TABLE IF NOT EXISTS path_operation_description (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES path_operation(id) ON DELETE CASCADE,
    summary VARCHAR(4096),
    description TEXT,
    operation_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path_operation_id)
);

-- Table comment
COMMENT ON TABLE path_operation_description IS 'Detailed descriptions for path operations';

-- Column comments
COMMENT ON COLUMN path_operation_description.id IS 'Unique identifier for the path operation description record';
COMMENT ON COLUMN path_operation_description.path_operation_id IS 'Foreign key reference to the parent path operation (cascades on deletion)';
COMMENT ON COLUMN path_operation_description.summary IS 'A brief summary of the operation';
COMMENT ON COLUMN path_operation_description.description IS 'A detailed description of the operation';
COMMENT ON COLUMN path_operation_description.operation_id IS 'An optional identifier for the operation';
COMMENT ON COLUMN path_operation_description.metadata IS 'Additional metadata for the operation description in JSONB format';
COMMENT ON COLUMN path_operation_description.created_at IS 'Timestamp when this operation description record was created';
COMMENT ON COLUMN path_operation_description.updated_at IS 'Timestamp when this operation description record was last modified';

-- Indices for performance optimization
CREATE INDEX idx_path_operation_description_path_operation_id ON path_operation_description(path_operation_id);
CREATE INDEX idx_path_operation_description_created_at ON path_operation_description(created_at);

-- Path Parameters
DROP INDEX IF EXISTS idx_path_parameter_path_operation_id CASCADE;
DROP INDEX IF EXISTS idx_path_parameter_created_at CASCADE;
DROP TABLE IF EXISTS path_parameter CASCADE;

CREATE TABLE IF NOT EXISTS path_parameter (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES path_operation(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    in_location VARCHAR(50) NOT NULL,
    summary VARCHAR(4096),
    description TEXT,
    metadata JSONB,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path_operation_id, name, in_location)
);

-- Table comment
COMMENT ON TABLE path_parameter IS 'Parameters associated with a specific path operation';

-- Column comments
COMMENT ON COLUMN path_parameter.id IS 'Unique identifier for the path parameter record';
COMMENT ON COLUMN path_parameter.path_operation_id IS 'Foreign key reference to the parent path operation (cascades on deletion)';
COMMENT ON COLUMN path_parameter.name IS 'The name of the parameter';
COMMENT ON COLUMN path_parameter.in_location IS 'The location of the parameter (e.g., query, path)';
COMMENT ON COLUMN path_parameter.summary IS 'A brief summary of the parameter';
COMMENT ON COLUMN path_parameter.description IS 'A detailed description of the parameter';
COMMENT ON COLUMN path_parameter.metadata IS 'Additional metadata for the parameter in JSONB format';
COMMENT ON COLUMN path_parameter.data IS 'The JSONB representation of the parameter in JSON Schema format';
COMMENT ON COLUMN path_parameter.created_at IS 'Timestamp when this parameter record was created';
COMMENT ON COLUMN path_parameter.updated_at IS 'Timestamp when this parameter record was last modified';

-- Indices for performance optimization
CREATE INDEX idx_path_parameter_path_operation_id ON path_parameter(path_operation_id);
CREATE INDEX idx_path_parameter_created_at ON path_parameter(created_at);

-- Path parameter class
DROP INDEX IF EXISTS idx_path_operation_schema_path_parameter_id CASCADE;
DROP INDEX IF EXISTS idx_path_operation_schema_property_id CASCADE;
DROP INDEX IF EXISTS idx_path_operation_schema_name CASCADE;
DROP TABLE IF EXISTS path_operation_schema CASCADE;

CREATE TABLE path_operation_schema (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES path_operation(id) ON DELETE CASCADE,
    class_id UUID NULL REFERENCES classes(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    data JSONB NOT NULL,

    -- Ensure property names are unique within each class
    CONSTRAINT path_path_operation_schema_unique UNIQUE (path_parameter_id, name)
);

-- Table comment
COMMENT ON TABLE path_parameter_schema IS 'Schema definitions for path parameters using class-property structure';

-- Column comments
COMMENT ON COLUMN path_operation_schema.id IS 'Unique identifier for the path parameter schema record';
COMMENT ON COLUMN path_operation_schema.path_parameter_id IS 'Foreign key reference to the parent path parameter (cascades on deletion)';
COMMENT ON COLUMN path_operation_schema.class_id IS 'Foreign key reference to the associated class (cascades on deletion) - if null, this is a freeform property';
COMMENT ON COLUMN path_operation_schema.property_id IS 'Foreign key reference to the associated property';
COMMENT ON COLUMN path_operation_schema.name IS 'The name of the schema element';
COMMENT ON COLUMN path_operation_schema.description IS 'A detailed description of the schema element';
COMMENT ON COLUMN path_operation_schema.data IS 'The JSONB representation of the schema data';

-- Indices for performance optimization
CREATE INDEX idx_path_operation_schema_path_operation_id ON path_operation_schema(path_operation_id);
CREATE INDEX idx_path_operation_schema_property_id ON path_operation_schema(property_id);
CREATE INDEX idx_path_operation_schema_name ON path_operation_schema(name);

-- Path responses
DROP INDEX IF EXISTS idx_path_response_path_operation_id CASCADE;
DROP INDEX IF EXISTS idx_path_response_created_at CASCADE;
DROP TABLE IF EXISTS path_response CASCADE;

CREATE TABLE IF NOT EXISTS path_response (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES path_operation(id) ON DELETE CASCADE,
    status_code VARCHAR(10) NOT NULL,
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path_operation_id, status_code)
);

COMMENT ON TABLE path_response IS 'Responses associated with a specific path operation';

COMMENT ON COLUMN path_response.id IS 'Unique identifier for the path response record';
COMMENT ON COLUMN path_response.path_operation_id IS 'Foreign key reference to the parent path operation (cascades on deletion)';
COMMENT ON COLUMN path_response.status_code IS 'The HTTP status code for the response';
COMMENT ON COLUMN path_response.description IS 'A detailed description of the response';
COMMENT ON COLUMN path_response.metadata IS 'Additional metadata for the response in JSONB format';
COMMENT ON COLUMN path_response.created_at IS 'Timestamp when this response record was created';
COMMENT ON COLUMN path_response.updated_at IS 'Timestamp when this response record was last modified';

CREATE INDEX idx_path_response_path_operation_id ON path_response(path_operation_id);
CREATE INDEX idx_path_response_created_at ON path_response(created_at);

-- Path response content
DROP INDEX IF EXISTS idx_path_response_content_path_response_id CASCADE;
DROP INDEX IF EXISTS idx_path_response_content_media_type CASCADE;
DROP TABLE IF EXISTS path_response_content CASCADE;

CREATE TABLE path_response_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_response_id UUID NOT NULL REFERENCES path_response(id) ON DELETE CASCADE,
    media_type VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path_response_id, media_type)
);

COMMENT ON TABLE path_response_content IS 'Content types associated with a specific path response';

COMMENT ON COLUMN path_response_content.id IS 'Unique identifier for the path response content record';
COMMENT ON COLUMN path_response_content.path_response_id IS 'Foreign key reference to the parent path response (cascades on deletion)';
COMMENT ON COLUMN path_response_content.media_type IS 'The media type (e.g., application/json, text/html)';
COMMENT ON COLUMN path_response_content.created_at IS 'Timestamp when this response content record was created';
COMMENT ON COLUMN path_response_content.updated_at IS 'Timestamp when this response content record was last modified';

CREATE INDEX idx_path_response_content_path_response_id ON path_response_content(path_response_id);
CREATE INDEX idx_path_response_content_media_type ON path_response_content(media_type);

-- Path response content schema
DROP INDEX IF EXISTS idx_path_parameter_schema_path_response_content_id CASCADE;
DROP INDEX IF EXISTS idx_path_parameter_schema_property_id CASCADE;
DROP INDEX IF EXISTS idx_path_parameter_schema_name CASCADE;
DROP TABLE IF EXISTS path_parameter_schema CASCADE;

CREATE TABLE path_parameter_schema (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_response_content_id UUID NOT NULL REFERENCES path_response_content(id) ON DELETE CASCADE,
    class_id UUID NULL REFERENCES classes(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id),
    data JSONB NOT NULL,

    -- Ensure property names are unique within each class
    CONSTRAINT path_response_content_id_unique UNIQUE (path_response_content_id)
);

-- Table comment
COMMENT ON TABLE path_parameter_schema IS 'Schema definitions for path response content using class-property structure';

-- Column comments
COMMENT ON COLUMN path_parameter_schema.id IS 'Unique identifier for the path response content schema record';
COMMENT ON COLUMN path_parameter_schema.path_response_content_id IS 'Foreign key reference to the parent path response content (cascades on deletion)';
COMMENT ON COLUMN path_parameter_schema.class_id IS 'Foreign key reference to the associated class (cascades on deletion) - if null, this is a freeform property';
COMMENT ON COLUMN path_parameter_schema.property_id IS 'Foreign key reference to the associated property';
COMMENT ON COLUMN path_parameter_schema.data IS 'The JSONB representation of the schema data';

-- Indices for performance optimization
CREATE INDEX idx_path_parameter_schema_path_response_content_id ON path_parameter_schema(path_response_content_id);
CREATE INDEX idx_path_parameter_schema_property_id ON path_parameter_schema(property_id);
