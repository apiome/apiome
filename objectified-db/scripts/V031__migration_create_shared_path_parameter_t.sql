-- Migration: Create shared path parameter tables
-- This allows path parameters to be reused across multiple operations

-- Set the search path to use odb schema by default
SET search_path TO odb, public;

-- Table for shared path parameters (one per path, not per operation)
CREATE TABLE IF NOT EXISTS odb.shared_path_parameter (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_path_id UUID NOT NULL REFERENCES odb.version_path(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    in_location VARCHAR(50) NOT NULL CHECK (in_location IN ('path', 'query', 'header', 'cookie')),
    summary VARCHAR(4096),
    description TEXT,
    data JSONB NOT NULL DEFAULT '{"type": "string", "required": true}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_path_id, name, in_location)
);

-- Linking table between operations and shared parameters
CREATE TABLE IF NOT EXISTS odb.path_operation_parameter_link (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES odb.path_operation(id) ON DELETE CASCADE,
    shared_path_parameter_id UUID NOT NULL REFERENCES odb.shared_path_parameter(id) ON DELETE CASCADE,
    metadata JSONB, -- For storing canvas position, styling, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path_operation_id, shared_path_parameter_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_shared_path_parameter_version_path
    ON odb.shared_path_parameter(version_path_id);

CREATE INDEX IF NOT EXISTS idx_shared_path_parameter_name
    ON odb.shared_path_parameter(name);

CREATE INDEX IF NOT EXISTS idx_path_operation_parameter_link_operation
    ON odb.path_operation_parameter_link(path_operation_id);

CREATE INDEX IF NOT EXISTS idx_path_operation_parameter_link_parameter
    ON odb.path_operation_parameter_link(shared_path_parameter_id);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_shared_path_parameter_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_shared_path_parameter_updated_at
    BEFORE UPDATE ON odb.shared_path_parameter
    FOR EACH ROW
    EXECUTE FUNCTION update_shared_path_parameter_updated_at();

CREATE TRIGGER trigger_update_path_operation_parameter_link_updated_at
    BEFORE UPDATE ON odb.path_operation_parameter_link
    FOR EACH ROW
    EXECUTE FUNCTION update_shared_path_parameter_updated_at();

-- Migration script to move existing path_parameter data to shared structure
-- Note: Run this after creating the tables above

DO $$
DECLARE
    param_record RECORD;
    shared_param_id UUID;
    path_id UUID;
BEGIN
    -- For each existing path_parameter
    FOR param_record IN
        SELECT DISTINCT pp.*, po.version_path_id
        FROM odb.path_parameter pp
        INNER JOIN odb.path_operation po ON pp.path_operation_id = po.id
    LOOP
        -- Check if a shared parameter already exists for this path
        SELECT id INTO shared_param_id
        FROM odb.shared_path_parameter
        WHERE version_path_id = param_record.version_path_id
          AND name = param_record.name
          AND in_location = param_record.in_location;

        -- If not, create it
        IF shared_param_id IS NULL THEN
            INSERT INTO odb.shared_path_parameter (
                version_path_id, name, in_location, summary, description, data
            ) VALUES (
                param_record.version_path_id,
                param_record.name,
                param_record.in_location,
                param_record.summary,
                param_record.description,
                COALESCE(param_record.data, '{"type": "string", "required": true}'::jsonb)
            ) RETURNING id INTO shared_param_id;
        END IF;

        -- Create link between operation and shared parameter
        INSERT INTO odb.path_operation_parameter_link (
            path_operation_id, shared_path_parameter_id, metadata
        ) VALUES (
            param_record.path_operation_id,
            shared_param_id,
            param_record.metadata
        ) ON CONFLICT (path_operation_id, shared_path_parameter_id) DO NOTHING;
    END LOOP;

    RAISE NOTICE 'Migration completed: Existing path_parameter data has been migrated to shared structure';
END $$;

-- Optional: After verifying the migration worked correctly, you can drop the old path_parameter table
-- DROP TABLE IF EXISTS odb.path_parameter CASCADE;

