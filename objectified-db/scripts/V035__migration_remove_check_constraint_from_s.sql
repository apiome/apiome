-- Migration: Remove CHECK constraint from shared_path_response_content to allow incremental schema building
-- This allows users to create content types with empty inline schemas and add properties incrementally

SET search_path TO odb, public;

-- Drop the CHECK constraint if it exists
-- This allows both class_id and inline_schema to be NULL initially, so users can build inline schemas incrementally
ALTER TABLE odb.shared_path_response_content
DROP CONSTRAINT IF EXISTS shared_path_response_content_check;

-- Update comment to reflect the new behavior
COMMENT ON TABLE odb.shared_path_response_content IS 'Content type variants for response bodies (supports multiple media types per response). Allows incremental inline schema building - both class_id and inline_schema can be NULL initially.';
