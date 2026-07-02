-- Remove enabled and deleted_at columns from primitives table
-- These are no longer used since we switched to hard deletes

SET search_path TO apiome, public;

-- Remove the enabled column (no longer used)
ALTER TABLE primitives DROP COLUMN IF EXISTS enabled;

-- Remove the deleted_at column (using hard deletes now)
ALTER TABLE primitives DROP COLUMN IF EXISTS deleted_at;

-- Update table comment
COMMENT ON TABLE primitives IS 'Stores reusable primitive type definitions for JSON schemas. Primitives are tenant-scoped and can be imported from JSON schema files. Uses hard deletes.';
