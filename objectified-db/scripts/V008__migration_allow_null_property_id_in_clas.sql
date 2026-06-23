-- Migration: Allow NULL property_id in class_properties for reference properties
-- Date: 2025-11-14
-- Purpose: Support reference properties that are not stored in the property library

-- Remove NOT NULL constraint from property_id column
-- This allows references to exist as class_properties without a link to the properties table
ALTER TABLE odb.class_properties
ALTER COLUMN property_id DROP NOT NULL;

-- Update comment to reflect the new behavior
COMMENT ON COLUMN odb.class_properties.property_id IS 'Reference to the property definition (NULL for reference properties that are class-specific)';

-- Add a check to ensure that if property_id is NULL, the data contains $ref
-- This validates that NULL property_id entries are indeed references
ALTER TABLE odb.class_properties
ADD CONSTRAINT class_properties_null_property_id_is_reference
CHECK (
    property_id IS NOT NULL
    OR data::jsonb ? '$ref'
    OR (data::jsonb->>'type' = 'array' AND data::jsonb->'items' ? '$ref')
);

COMMENT ON CONSTRAINT class_properties_null_property_id_is_reference ON odb.class_properties
IS 'Ensures that if property_id is NULL, the data must contain a $ref (direct or in items for arrays), indicating it is a reference property';

