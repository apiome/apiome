-- Section 4.3 Server Definitions: variables (enum values) and environment (dev/staging/prod)
-- Adds variables JSONB and environment to version_server

SET search_path TO odb, public;

-- variables: OpenAPI Server variables { "varName": { "default": "...", "enum": [...], "description": "..." } }
ALTER TABLE odb.version_server
  ADD COLUMN IF NOT EXISTS variables JSONB DEFAULT NULL;

-- environment: Label for environment-specific servers (dev, staging, prod)
ALTER TABLE odb.version_server
  ADD COLUMN IF NOT EXISTS environment VARCHAR(50) DEFAULT NULL;

COMMENT ON COLUMN odb.version_server.variables IS 'OpenAPI Server variables: default, enum, description per variable';
COMMENT ON COLUMN odb.version_server.environment IS 'Environment label: dev, staging, prod (for UI and x-environment)';
