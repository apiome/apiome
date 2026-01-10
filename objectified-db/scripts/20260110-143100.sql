-- Migration: Convert path_response to shared model with linking table
-- This allows multiple operations to share the same response

-- Set the search path to use odb schema by default
SET search_path TO odb, public;

-- Create the shared_path_response table
CREATE TABLE IF NOT EXISTS odb.shared_path_response (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_path_id UUID NOT NULL REFERENCES odb.version_path(id) ON DELETE CASCADE,
    status_code VARCHAR(10) NOT NULL,
    description TEXT,
    data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_path_id, status_code)
);

COMMENT ON TABLE odb.shared_path_response IS 'Shared response definitions that can be linked to multiple operations';
COMMENT ON COLUMN odb.shared_path_response.id IS 'Unique identifier for the shared response';
COMMENT ON COLUMN odb.shared_path_response.version_path_id IS 'The path this response belongs to';
COMMENT ON COLUMN odb.shared_path_response.status_code IS 'HTTP status code (e.g., 200, 2XX, 404)';
COMMENT ON COLUMN odb.shared_path_response.description IS 'Description of when this response is returned';
COMMENT ON COLUMN odb.shared_path_response.data IS 'Additional response data (schema, examples, etc.)';

CREATE INDEX idx_shared_path_response_version_path_id ON odb.shared_path_response(version_path_id);
CREATE INDEX idx_shared_path_response_status_code ON odb.shared_path_response(status_code);

-- Create the linking table
CREATE TABLE IF NOT EXISTS odb.path_operation_response_link (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_operation_id UUID NOT NULL REFERENCES odb.path_operation(id) ON DELETE CASCADE,
    shared_path_response_id UUID NOT NULL REFERENCES odb.shared_path_response(id) ON DELETE CASCADE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(path_operation_id, shared_path_response_id)
);

COMMENT ON TABLE odb.path_operation_response_link IS 'Links operations to shared responses (many-to-many)';
COMMENT ON COLUMN odb.path_operation_response_link.path_operation_id IS 'The operation this link belongs to';
COMMENT ON COLUMN odb.path_operation_response_link.shared_path_response_id IS 'The shared response being linked';
COMMENT ON COLUMN odb.path_operation_response_link.metadata IS 'Canvas positioning and styling metadata';

CREATE INDEX idx_path_operation_response_link_operation ON odb.path_operation_response_link(path_operation_id);
CREATE INDEX idx_path_operation_response_link_response ON odb.path_operation_response_link(shared_path_response_id);

-- Migrate existing data from path_response to the new structure
DO $$
DECLARE
    response_record RECORD;
    operation_record RECORD;
    new_shared_response_id UUID;
    version_path_id_var UUID;
BEGIN
    -- For each existing response
    FOR response_record IN
        SELECT pr.*, po.version_path_id
        FROM odb.path_response pr
        JOIN odb.path_operation po ON pr.path_operation_id = po.id
    LOOP
        -- Check if a shared response already exists for this path and status code
        SELECT id INTO new_shared_response_id
        FROM odb.shared_path_response
        WHERE version_path_id = response_record.version_path_id
          AND status_code = response_record.status_code;

        -- If not, create it
        IF new_shared_response_id IS NULL THEN
            INSERT INTO odb.shared_path_response (
                version_path_id,
                status_code,
                description,
                data,
                created_at,
                updated_at
            ) VALUES (
                response_record.version_path_id,
                response_record.status_code,
                response_record.description,
                response_record.metadata,
                response_record.created_at,
                response_record.updated_at
            )
            RETURNING id INTO new_shared_response_id;
        END IF;

        -- Create the link
        INSERT INTO odb.path_operation_response_link (
            path_operation_id,
            shared_path_response_id,
            created_at,
            updated_at
        ) VALUES (
            response_record.path_operation_id,
            new_shared_response_id,
            response_record.created_at,
            response_record.updated_at
        )
        ON CONFLICT (path_operation_id, shared_path_response_id) DO NOTHING;
    END LOOP;
END $$;

-- Drop old table (comment out if you want to keep it for rollback)
-- DROP TABLE IF EXISTS odb.path_response CASCADE;

-- Note: Keeping path_response for now. Once verified, uncomment the DROP above.

