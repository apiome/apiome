-- Primitives Table
-- Stores reusable primitive type definitions that can be used in JSON schemas
-- Primitives are tenant-scoped and provide predefined type definitions

SET search_path TO odb, public;

-- Drop existing table if exists
DROP TABLE IF EXISTS primitives CASCADE;

CREATE TABLE primitives (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Primitive metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,  -- e.g., 'string', 'number', 'integer', 'boolean', 'array', 'object'

    -- JSON Schema primitive definition
    schema JSONB NOT NULL,  -- The actual primitive schema (type, format, constraints, etc.)

    -- Classification
    tags TEXT[] DEFAULT '{}',  -- Array of tags for discoverability

    -- Ownership and visibility
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- Primitives are always tenant-scoped
    created_by UUID REFERENCES users(id),
    is_system BOOLEAN NOT NULL DEFAULT false,  -- True for built-in system primitives
    is_public BOOLEAN NOT NULL DEFAULT false,  -- Whether primitive is visible to other tenants (future use)

    -- Usage tracking
    usage_count INTEGER NOT NULL DEFAULT 0,

    -- Soft delete and timestamps
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure primitive names are unique within tenant and category
    CONSTRAINT primitives_name_category_unique
        UNIQUE (tenant_id, category, name)
);

-- Table comment
COMMENT ON TABLE primitives IS 'Stores reusable primitive type definitions for JSON schemas. Primitives are tenant-scoped and can be imported from JSON schema files.';

-- Column comments
COMMENT ON COLUMN primitives.id IS 'Unique identifier for the primitive';
COMMENT ON COLUMN primitives.name IS 'Display name of the primitive (e.g., "Email Address", "UUID", "Percentage")';
COMMENT ON COLUMN primitives.description IS 'Description of the primitive and its intended use';
COMMENT ON COLUMN primitives.category IS 'Type category of the primitive (string, number, integer, boolean, array, object)';
COMMENT ON COLUMN primitives.schema IS 'JSON Schema definition of the primitive including type, format, constraints, and validation rules';
COMMENT ON COLUMN primitives.tags IS 'Tags for categorization and search (e.g., ["email", "contact"], ["uuid", "identifier"])';
COMMENT ON COLUMN primitives.tenant_id IS 'The tenant that owns this primitive';
COMMENT ON COLUMN primitives.created_by IS 'The user who created this primitive';
COMMENT ON COLUMN primitives.is_system IS 'True for built-in system primitives';
COMMENT ON COLUMN primitives.is_public IS 'Whether this primitive can be shared with other tenants (future use)';
COMMENT ON COLUMN primitives.usage_count IS 'Number of times this primitive has been used in projects';
COMMENT ON COLUMN primitives.enabled IS 'Whether this primitive is currently active';

-- Indices for primitives table
CREATE INDEX idx_primitives_tenant_id ON primitives(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_primitives_created_by ON primitives(created_by) WHERE deleted_at IS NULL;
CREATE INDEX idx_primitives_category ON primitives(category) WHERE deleted_at IS NULL;
CREATE INDEX idx_primitives_enabled ON primitives(enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_primitives_deleted_at ON primitives(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_primitives_created_at ON primitives(created_at);
CREATE INDEX idx_primitives_name ON primitives(name) WHERE deleted_at IS NULL;
CREATE INDEX idx_primitives_tags ON primitives USING GIN(tags);
CREATE INDEX idx_primitives_tenant_category ON primitives(tenant_id, category) WHERE deleted_at IS NULL;

-- Insert some system primitives for common use cases
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'Email Address',
    'A valid email address following RFC 5322 format',
    'string',
    '{"type": "string", "format": "email", "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", "maxLength": 254}'::jsonb,
    ARRAY['email', 'contact', 'communication'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'UUID',
    'A universally unique identifier (UUID) in standard format',
    'string',
    '{"type": "string", "format": "uuid", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}'::jsonb,
    ARRAY['uuid', 'identifier', 'id'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'Percentage',
    'A number representing a percentage value (0-100)',
    'number',
    '{"type": "number", "minimum": 0, "maximum": 100, "description": "Percentage value between 0 and 100"}'::jsonb,
    ARRAY['percentage', 'ratio', 'number'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'URL',
    'A valid URL following RFC 3986 format',
    'string',
    '{"type": "string", "format": "uri", "pattern": "^https?://[^\\s/$.?#].[^\\s]*$", "maxLength": 2048}'::jsonb,
    ARRAY['url', 'link', 'web'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'ISO Date',
    'A date in ISO 8601 format (YYYY-MM-DD)',
    'string',
    '{"type": "string", "format": "date", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}'::jsonb,
    ARRAY['date', 'iso', 'time'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'ISO DateTime',
    'A date-time in ISO 8601 format with timezone',
    'string',
    '{"type": "string", "format": "date-time", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{3})?Z?$"}'::jsonb,
    ARRAY['datetime', 'iso', 'timestamp'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'Positive Integer',
    'An integer greater than zero',
    'integer',
    '{"type": "integer", "minimum": 1, "exclusiveMinimum": false}'::jsonb,
    ARRAY['integer', 'positive', 'number'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public, created_by)
SELECT
    t.id,
    'Phone Number',
    'An international phone number in E.164 format',
    'string',
    '{"type": "string", "format": "phone", "pattern": "^\\+[1-9]\\d{1,14}$", "minLength": 7, "maxLength": 15}'::jsonb,
    ARRAY['phone', 'contact', 'telephone'],
    true,
    true,
    NULL
FROM tenants t
WHERE t.slug = 'test-tenant'
LIMIT 1;

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_primitives_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_primitives_updated_at
    BEFORE UPDATE ON primitives
    FOR EACH ROW
    EXECUTE FUNCTION update_primitives_updated_at();
