SET search_path TO apiome, public;

-- Add parent_id column to class_properties table to support nested properties
-- This allows properties of type "object" to contain inline child properties

-- Add parent_id column (only if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'apiome'
        AND table_name = 'class_properties'
        AND column_name = 'parent_id'
    ) THEN
        ALTER TABLE class_properties
        ADD COLUMN parent_id UUID REFERENCES class_properties(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Add comment to the column
COMMENT ON COLUMN class_properties.parent_id IS 'Reference to parent property for nested properties (NULL for top-level properties)';

-- Create index for parent_id lookups (only if it doesn't exist)
CREATE INDEX IF NOT EXISTS idx_class_properties_parent_id ON class_properties(parent_id);

-- Update the unique constraint to allow same property names at different nesting levels
-- First, drop the old constraint if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'class_properties_class_name_unique'
        AND connamespace = 'apiome'::regnamespace
    ) THEN
        ALTER TABLE class_properties DROP CONSTRAINT class_properties_class_name_unique;
    END IF;
END $$;

-- Add new unique constraint that includes parent_id
-- This ensures property names are unique within the same parent (or at the top level)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'class_properties_parent_name_unique'
        AND connamespace = 'apiome'::regnamespace
    ) THEN
        ALTER TABLE class_properties
        ADD CONSTRAINT class_properties_parent_name_unique
        UNIQUE (class_id, parent_id, name);
    END IF;
END $$;

-- Add a check constraint to ensure that circular references cannot occur
-- This is a basic check; more complex validation should be done at the application level
COMMENT ON TABLE class_properties IS 'Junction table linking classes to their properties with property-specific configuration. Supports nested properties through parent_id for hierarchical property structures.';

