-- Migration: Create shared request body tables for path operations
-- This allows request bodies to be reused across multiple operations (POST, PUT, PATCH)
-- Request bodies can reference existing apiome.classes (class_id) or use inline schemas (inline_schema)

-- Set the search path to use apiome schema by default
SET search_path TO apiome, public;

-- =============================================================================
-- SHARED REQUEST BODY TABLE
-- =============================================================================

-- Table for shared request bodies (one per path, not per operation)
-- Multiple operations can link to the same request body definition
CREATE TABLE IF NOT EXISTS apiome.shared_path_request_body (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_path_id UUID NOT NULL REFERENCES apiome.version_path(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    required BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_path_id, name)
);

-- Table comments
COMMENT ON TABLE apiome.shared_path_request_body IS 'Shared request body definitions that can be linked to multiple operations (POST, PUT, PATCH) within a path';
COMMENT ON COLUMN apiome.shared_path_request_body.id IS 'Unique identifier for the shared request body';
COMMENT ON COLUMN apiome.shared_path_request_body.version_path_id IS 'The path this request body belongs to';
COMMENT ON COLUMN apiome.shared_path_request_body.name IS 'Display name for the request body (e.g., "CreateUserRequest", "UpdateProductPayload")';
COMMENT ON COLUMN apiome.shared_path_request_body.description IS 'Description of the request body purpose and contents';
COMMENT ON COLUMN apiome.shared_path_request_body.required IS 'Whether the request body is required for the operation (default true)';
COMMENT ON COLUMN apiome.shared_path_request_body.created_at IS 'Timestamp when this request body was created';
COMMENT ON COLUMN apiome.shared_path_request_body.updated_at IS 'Timestamp when this request body was last modified';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_shared_path_request_body_version_path
    ON apiome.shared_path_request_body(version_path_id);

CREATE INDEX IF NOT EXISTS idx_shared_path_request_body_name
    ON apiome.shared_path_request_body(name);

-- =============================================================================
-- OPERATION REQUEST BODY LINK TABLE
-- =============================================================================

-- Linking table between operations and shared request bodies (many-to-many)
CREATE TABLE IF NOT EXISTS apiome.path_operation_request_body_link (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES apiome.path_operation(id) ON DELETE CASCADE,
    shared_path_request_body_id UUID NOT NULL REFERENCES apiome.shared_path_request_body(id) ON DELETE CASCADE,
    metadata JSONB, -- For storing canvas position, styling, overrides, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Each operation can only link to one request body (OpenAPI spec allows only one requestBody per operation)
    UNIQUE(path_operation_id)
);

-- Table comments
COMMENT ON TABLE apiome.path_operation_request_body_link IS 'Links operations to shared request bodies - each operation can have at most one request body';
COMMENT ON COLUMN apiome.path_operation_request_body_link.path_operation_id IS 'The operation this link belongs to';
COMMENT ON COLUMN apiome.path_operation_request_body_link.shared_path_request_body_id IS 'The shared request body being linked';
COMMENT ON COLUMN apiome.path_operation_request_body_link.metadata IS 'Canvas positioning, styling, and operation-specific overrides';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_path_operation_request_body_link_operation
    ON apiome.path_operation_request_body_link(path_operation_id);

CREATE INDEX IF NOT EXISTS idx_path_operation_request_body_link_request_body
    ON apiome.path_operation_request_body_link(shared_path_request_body_id);

-- =============================================================================
-- REQUEST BODY CONTENT TABLE
-- =============================================================================

-- Content types for request bodies (application/json, multipart/form-data, etc.)
-- Each content type can reference an existing class OR define an inline schema
CREATE TABLE IF NOT EXISTS apiome.shared_path_request_body_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shared_path_request_body_id UUID NOT NULL REFERENCES apiome.shared_path_request_body(id) ON DELETE CASCADE,

    -- Media type (e.g., 'application/json', 'multipart/form-data', 'application/xml')
    media_type VARCHAR(255) NOT NULL,

    -- Schema definition: EITHER class_id OR inline_schema must be set
    -- When class_id is set: schema is a $ref to an existing apiome.classes entry
    -- When class_id is NULL: schema is defined inline in inline_schema JSONB
    class_id UUID REFERENCES apiome.classes(id) ON DELETE SET NULL,

    -- Inline schema definition when not referencing an existing class
    -- Structure: {
    --   type: 'object',
    --   description: 'optional description',
    --   properties: [
    --     { id: 'uuid', name: 'propName', description: 'optional', data: { type: 'string', format: 'email', ... }, parent_id: 'uuid-or-null' }
    --   ]
    -- }
    inline_schema JSONB,

    -- OpenAPI 3.1 encoding object for multipart/form-data and application/x-www-form-urlencoded
    -- Structure per property: {
    --   "propertyName": {
    --     "contentType": "image/png",
    --     "headers": { "X-Custom-Header": { "schema": { "type": "string" } } },
    --     "style": "form" | "spaceDelimited" | "pipeDelimited" | "deepObject",
    --     "explode": true | false,
    --     "allowReserved": true | false
    --   }
    -- }
    encoding JSONB,

    -- Examples for this content type (array of example objects)
    -- Structure: [
    --   { "name": "example1", "summary": "Basic example", "value": { ... } },
    --   { "name": "example2", "summary": "Advanced example", "value": { ... } }
    -- ]
    examples JSONB,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Each request body can only have one content definition per media type
    UNIQUE(shared_path_request_body_id, media_type),

    -- Ensure either class_id or inline_schema is provided (not both empty)
    CONSTRAINT request_body_content_schema_check CHECK (
        class_id IS NOT NULL OR inline_schema IS NOT NULL
    )
);

-- Table comments
COMMENT ON TABLE apiome.shared_path_request_body_content IS 'Content type definitions for request bodies with either class reference or inline schema';
COMMENT ON COLUMN apiome.shared_path_request_body_content.id IS 'Unique identifier for the content type definition';
COMMENT ON COLUMN apiome.shared_path_request_body_content.shared_path_request_body_id IS 'The request body this content type belongs to';
COMMENT ON COLUMN apiome.shared_path_request_body_content.media_type IS 'MIME type (e.g., application/json, multipart/form-data, application/xml)';
COMMENT ON COLUMN apiome.shared_path_request_body_content.class_id IS 'Reference to existing apiome.classes entry - when set, generates $ref in OpenAPI export';
COMMENT ON COLUMN apiome.shared_path_request_body_content.inline_schema IS 'Inline schema definition with properties array - used when class_id is NULL';
COMMENT ON COLUMN apiome.shared_path_request_body_content.encoding IS 'OpenAPI 3.1 encoding object for multipart/form-data content types';
COMMENT ON COLUMN apiome.shared_path_request_body_content.examples IS 'Array of example values for this content type';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_shared_path_request_body_content_request_body
    ON apiome.shared_path_request_body_content(shared_path_request_body_id);

CREATE INDEX IF NOT EXISTS idx_shared_path_request_body_content_media_type
    ON apiome.shared_path_request_body_content(media_type);

CREATE INDEX IF NOT EXISTS idx_shared_path_request_body_content_class_id
    ON apiome.shared_path_request_body_content(class_id)
    WHERE class_id IS NOT NULL;

-- GIN index on inline_schema for JSON queries
CREATE INDEX IF NOT EXISTS idx_shared_path_request_body_content_inline_schema_gin
    ON apiome.shared_path_request_body_content USING GIN (inline_schema)
    WHERE inline_schema IS NOT NULL;

-- =============================================================================
-- TRIGGERS FOR UPDATED_AT
-- =============================================================================

-- Trigger function for updating updated_at timestamp
CREATE OR REPLACE FUNCTION update_shared_path_request_body_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for shared_path_request_body
DROP TRIGGER IF EXISTS trigger_update_shared_path_request_body_updated_at ON apiome.shared_path_request_body;
CREATE TRIGGER trigger_update_shared_path_request_body_updated_at
    BEFORE UPDATE ON apiome.shared_path_request_body
    FOR EACH ROW
    EXECUTE FUNCTION update_shared_path_request_body_updated_at();

-- Trigger for path_operation_request_body_link
DROP TRIGGER IF EXISTS trigger_update_path_operation_request_body_link_updated_at ON apiome.path_operation_request_body_link;
CREATE TRIGGER trigger_update_path_operation_request_body_link_updated_at
    BEFORE UPDATE ON apiome.path_operation_request_body_link
    FOR EACH ROW
    EXECUTE FUNCTION update_shared_path_request_body_updated_at();

-- Trigger for shared_path_request_body_content
DROP TRIGGER IF EXISTS trigger_update_shared_path_request_body_content_updated_at ON apiome.shared_path_request_body_content;
CREATE TRIGGER trigger_update_shared_path_request_body_content_updated_at
    BEFORE UPDATE ON apiome.shared_path_request_body_content
    FOR EACH ROW
    EXECUTE FUNCTION update_shared_path_request_body_updated_at();

-- =============================================================================
-- COMPLETION NOTICE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration completed: Created shared_path_request_body, path_operation_request_body_link, and shared_path_request_body_content tables';
END $$;
