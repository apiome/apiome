-- Property Templates Table
-- Stores reusable property templates that can be added to projects
-- Templates are stored as JSON Schema format property definitions

SET search_path TO apiome, public;

-- Drop existing table if exists
DROP TABLE IF EXISTS property_templates CASCADE;

CREATE TABLE property_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Template metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,  -- e.g., 'identifiers', 'timestamps', 'audit', 'contact', etc.

    -- JSON Schema property definition
    schema JSONB NOT NULL,  -- The actual property schema (type, format, validation, etc.)

    -- Template classification
    tags TEXT[] DEFAULT '{}',  -- Array of tags for discoverability

    -- Ownership and visibility
    tenant_id UUID REFERENCES tenants(id),  -- NULL means system-wide/global template
    created_by UUID REFERENCES users(id),
    is_system BOOLEAN NOT NULL DEFAULT false,  -- True for built-in system templates
    is_public BOOLEAN NOT NULL DEFAULT true,  -- Whether template is visible to other tenants

    -- Usage tracking
    usage_count INTEGER NOT NULL DEFAULT 0,

    -- Soft delete and timestamps
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure template names are unique within category for system templates
    -- and unique per tenant for tenant-specific templates
    CONSTRAINT property_templates_name_category_unique
        UNIQUE NULLS NOT DISTINCT (tenant_id, category, name)
);

-- Table comment
COMMENT ON TABLE property_templates IS 'Stores reusable property templates that can be quickly added to projects. Templates contain JSON Schema property definitions with metadata for discoverability.';

-- Column comments
COMMENT ON COLUMN property_templates.id IS 'Unique identifier for the template';
COMMENT ON COLUMN property_templates.name IS 'Display name of the template (e.g., "UUID Identifier", "Created At Timestamp")';
COMMENT ON COLUMN property_templates.description IS 'Detailed description of what the property template represents and how to use it';
COMMENT ON COLUMN property_templates.category IS 'Category for organizing templates (identifiers, timestamps, audit, status, address, contact, money, geolocation, i18n, pagination, search)';
COMMENT ON COLUMN property_templates.schema IS 'JSON Schema property definition including type, format, validation rules, example, etc.';
COMMENT ON COLUMN property_templates.tags IS 'Array of tags for search and filtering';
COMMENT ON COLUMN property_templates.tenant_id IS 'Owner tenant - NULL for system-wide templates';
COMMENT ON COLUMN property_templates.created_by IS 'User who created the template';
COMMENT ON COLUMN property_templates.is_system IS 'True for built-in system templates that cannot be modified';
COMMENT ON COLUMN property_templates.is_public IS 'Whether template is visible to users outside the owning tenant';
COMMENT ON COLUMN property_templates.usage_count IS 'Number of times this template has been used';
COMMENT ON COLUMN property_templates.enabled IS 'Flag indicating if the template is currently active';
COMMENT ON COLUMN property_templates.deleted_at IS 'Soft delete timestamp';
COMMENT ON COLUMN property_templates.created_at IS 'Timestamp when the template was created';
COMMENT ON COLUMN property_templates.updated_at IS 'Timestamp when the template was last modified';

-- Indices for performance

-- Index on category for filtering
CREATE INDEX idx_property_templates_category ON property_templates(category) WHERE deleted_at IS NULL;

-- Index on tenant_id for tenant-specific queries
CREATE INDEX idx_property_templates_tenant_id ON property_templates(tenant_id) WHERE deleted_at IS NULL;

-- Index on is_system for finding built-in templates
CREATE INDEX idx_property_templates_is_system ON property_templates(is_system) WHERE deleted_at IS NULL AND enabled = true;

-- Index on is_public for finding shareable templates
CREATE INDEX idx_property_templates_is_public ON property_templates(is_public) WHERE deleted_at IS NULL AND enabled = true;

-- GIN index on tags for efficient tag-based searching
CREATE INDEX idx_property_templates_tags_gin ON property_templates USING GIN (tags);

-- GIN index on schema for JSON queries
CREATE INDEX idx_property_templates_schema_gin ON property_templates USING GIN (schema);

-- Index for popular templates (by usage)
CREATE INDEX idx_property_templates_usage ON property_templates(usage_count DESC) WHERE deleted_at IS NULL AND enabled = true;

-- Full text search index on name and description
CREATE INDEX idx_property_templates_search ON property_templates
    USING GIN (to_tsvector('english', COALESCE(name, '') || ' ' || COALESCE(description, '')));
