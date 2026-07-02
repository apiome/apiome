-- Migration: Add schema_mode column to shared_path_response
-- This column explicitly indicates what type of schema is being used for the response
-- Eliminates ambiguity when determining how to display/process the response

SET search_path TO apiome, public;

-- =============================================================================
-- ADD SCHEMA_MODE COLUMN
-- =============================================================================

-- Add schema_mode column to explicitly track the response schema type
-- Modes: 'class' (references a class), 'object' (inline object schema), 'primitive' (string, number, etc.), 'array' (array type)
ALTER TABLE apiome.shared_path_response
ADD COLUMN IF NOT EXISTS schema_mode VARCHAR(20) DEFAULT 'object';

-- Update existing rows based on current data
-- If class_id is set, mode is 'class'
UPDATE apiome.shared_path_response
SET schema_mode = 'class'
WHERE class_id IS NOT NULL AND schema_mode = 'object';

-- If data contains a primitive type, mode is 'primitive'
UPDATE apiome.shared_path_response
SET schema_mode = 'primitive'
WHERE class_id IS NULL
  AND data IS NOT NULL
  AND data->>'type' IS NOT NULL
  AND data->>'type' IN ('string', 'number', 'integer', 'boolean', 'null')
  AND schema_mode = 'object';

-- If data contains array type, mode is 'array'
UPDATE apiome.shared_path_response
SET schema_mode = 'array'
WHERE class_id IS NULL
  AND data IS NOT NULL
  AND data->>'type' = 'array'
  AND schema_mode = 'object';

-- Add comment for the new column
COMMENT ON COLUMN apiome.shared_path_response.schema_mode IS 'Explicitly indicates the schema type: class (references apiome.classes), object (inline object schema), primitive (string/number/integer/boolean/null), array (array type)';

-- Add index for schema_mode for potential filtering
CREATE INDEX IF NOT EXISTS idx_shared_path_response_schema_mode
ON apiome.shared_path_response(schema_mode);
