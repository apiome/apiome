-- Multiple server definitions for OpenAPI (Ticket #565)
-- Adds version_server table: name, url, description per version

SET search_path TO odb, public;

-- version_server: Stores server definitions per version (OpenAPI servers array)
CREATE TABLE IF NOT EXISTS odb.version_server (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES odb.versions(id) ON DELETE CASCADE,
    -- Display name (e.g. "Production", "Staging") for UI; not in OpenAPI spec
    name VARCHAR(255),
    -- Server URL (required in OpenAPI)
    url VARCHAR(2048) NOT NULL,
    -- Optional description (OpenAPI Server description)
    description TEXT,
    -- Order for display and spec output
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE odb.version_server IS 'OpenAPI server definitions per version (multiple servers: name, url, description)';
COMMENT ON COLUMN odb.version_server.name IS 'Display name for UI (e.g. Production, Staging)';
COMMENT ON COLUMN odb.version_server.url IS 'Server URL (OpenAPI Server.url)';
COMMENT ON COLUMN odb.version_server.description IS 'Optional description (OpenAPI Server.description)';
COMMENT ON COLUMN odb.version_server.sort_order IS 'Display order (lower first)';

CREATE INDEX idx_version_server_version_id ON odb.version_server(version_id);
