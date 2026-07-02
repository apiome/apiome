-- Migration: Add inline schema support to response bodies
-- This allows responses to reference existing apiome.classes (class_id) or use inline schemas (inline_schema)
-- Matches the request body implementation for consistency

-- Set the search path to use apiome schema by default
SET search_path TO apiome, public;

-- =============================================================================
-- ALTER SHARED_PATH_RESPONSE TABLE
-- =============================================================================

-- Add class_id column to support class references (like request bodies)
ALTER TABLE apiome.shared_path_response
ADD COLUMN IF NOT EXISTS class_id UUID REFERENCES apiome.classes(id) ON DELETE SET NULL;

-- Add inline_schema column to support free-form inline schemas (like request bodies)
ALTER TABLE apiome.shared_path_response
ADD COLUMN IF NOT EXISTS inline_schema JSONB;

-- For existing rows that have NULL in all schema fields, set data to empty object
-- This ensures backwards compatibility and allows the constraint to pass
UPDATE apiome.shared_path_response
SET data = '{}'::jsonb
WHERE class_id IS NULL
  AND inline_schema IS NULL
  AND data IS NULL;

-- Add check constraint to ensure either class_id OR inline_schema OR data is provided
-- (data is the legacy field, keeping it for backwards compatibility)
ALTER TABLE apiome.shared_path_response
DROP CONSTRAINT IF EXISTS check_response_schema_defined;

ALTER TABLE apiome.shared_path_response
ADD CONSTRAINT check_response_schema_defined
CHECK (
  class_id IS NOT NULL OR
  inline_schema IS NOT NULL OR
  data IS NOT NULL
);

-- Add index for class_id lookups
CREATE INDEX IF NOT EXISTS idx_shared_path_response_class_id
ON apiome.shared_path_response(class_id);

-- Update table and column comments
COMMENT ON COLUMN apiome.shared_path_response.class_id IS 'Optional reference to existing class in apiome.classes for response schema';
COMMENT ON COLUMN apiome.shared_path_response.inline_schema IS 'Optional inline schema definition (JSONB) with structure: {type: "object", description, properties: [{id, name, data, parent_id}]}';
COMMENT ON COLUMN apiome.shared_path_response.data IS 'Legacy additional response data (schema, examples, etc.) - prefer class_id or inline_schema';

-- =============================================================================
-- CREATE RESPONSE CONTENT TYPES TABLE (LIKE REQUEST BODY)
-- =============================================================================

-- Create table for response content types (similar to request body content types)
-- This allows multiple content-types per response (application/json, application/xml, etc.)
CREATE TABLE IF NOT EXISTS apiome.shared_path_response_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shared_path_response_id UUID NOT NULL REFERENCES apiome.shared_path_response(id) ON DELETE CASCADE,
    media_type VARCHAR(255) NOT NULL DEFAULT 'application/json',
    class_id UUID REFERENCES apiome.classes(id) ON DELETE SET NULL,
    inline_schema JSONB,
    examples JSONB, -- Array of example objects
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(shared_path_response_id, media_type)
    -- Note: No CHECK constraint here - we allow both NULL to start, then user can set class_id or build inline_schema
);

-- Table comments
COMMENT ON TABLE apiome.shared_path_response_content IS 'Content type variants for response bodies (supports multiple media types per response)';
COMMENT ON COLUMN apiome.shared_path_response_content.id IS 'Unique identifier for the response content type';
COMMENT ON COLUMN apiome.shared_path_response_content.shared_path_response_id IS 'The response this content type belongs to';
COMMENT ON COLUMN apiome.shared_path_response_content.media_type IS 'Content-Type header value (e.g., application/json, application/xml)';
COMMENT ON COLUMN apiome.shared_path_response_content.class_id IS 'Reference to existing class in apiome.classes (mutually exclusive with inline_schema)';
COMMENT ON COLUMN apiome.shared_path_response_content.inline_schema IS 'Inline schema definition with properties array (mutually exclusive with class_id)';
COMMENT ON COLUMN apiome.shared_path_response_content.examples IS 'Array of example response objects for documentation';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_shared_path_response_content_response_id
    ON apiome.shared_path_response_content(shared_path_response_id);

CREATE INDEX IF NOT EXISTS idx_shared_path_response_content_class_id
    ON apiome.shared_path_response_content(class_id);

CREATE INDEX IF NOT EXISTS idx_shared_path_response_content_media_type
    ON apiome.shared_path_response_content(media_type);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_shared_path_response_content_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_shared_path_response_content_updated_at
    BEFORE UPDATE ON apiome.shared_path_response_content
    FOR EACH ROW
    EXECUTE FUNCTION update_shared_path_response_content_updated_at();

-- =============================================================================
-- MIGRATION NOTES
-- =============================================================================

-- This migration adds:
-- 1. class_id and inline_schema columns to shared_path_response (backwards compatible)
-- 2. shared_path_response_content table for multi-content-type support
-- 3. Constraints to ensure schema is defined
-- 4. Indexes for performance
-- 5. Triggers for timestamp updates

-- Backwards compatibility:
-- - Existing responses with 'data' JSONB will continue to work
-- - New responses can use class_id or inline_schema
-- - Response content types table is optional (for multi-content-type support)

-- Usage patterns:
-- 1. Simple response with class reference: Set class_id on shared_path_response
-- 2. Simple response with inline schema: Set inline_schema on shared_path_response
-- 3. Multi-content-type response: Create entries in shared_path_response_content
-- 4. Legacy response: Continue using data JSONB
