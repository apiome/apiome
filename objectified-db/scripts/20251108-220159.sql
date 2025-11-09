SET search_path TO odb, public;

-- Create enum type for visibility (only if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'visibility_type') THEN
        CREATE TYPE visibility_type AS ENUM ('public', 'private');
    END IF;
END $$;

-- Add visibility column to versions table with default value (only if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'odb'
        AND table_name = 'versions'
        AND column_name = 'visibility'
    ) THEN
        ALTER TABLE versions ADD COLUMN visibility visibility_type NOT NULL DEFAULT 'private';
    END IF;
END $$;

-- Add comment to the column
COMMENT ON COLUMN versions.visibility IS 'Visibility level of the version: public (accessible to all) or private (restricted access)';

-- Create API Keys table for external REST API access (only if it doesn't exist)
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    key_hash VARCHAR(255) NOT NULL UNIQUE,
    key_prefix VARCHAR(20) NOT NULL,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure API key names are unique within each tenant
    CONSTRAINT api_keys_tenant_name_unique UNIQUE (tenant_id, name)
);

-- Add comments to api_keys table
COMMENT ON TABLE api_keys IS 'Stores API keys for external REST API access to tenant data';
COMMENT ON COLUMN api_keys.id IS 'Unique identifier for the API key';
COMMENT ON COLUMN api_keys.tenant_id IS 'Reference to the tenant this API key belongs to';
COMMENT ON COLUMN api_keys.name IS 'Human-readable name for the API key (unique within a tenant)';
COMMENT ON COLUMN api_keys.description IS 'Optional description of the API key purpose and usage';
COMMENT ON COLUMN api_keys.key_hash IS 'Hashed version of the API key for secure storage';
COMMENT ON COLUMN api_keys.key_prefix IS 'Prefix of the API key for identification (e.g., first 8 characters)';
COMMENT ON COLUMN api_keys.last_used_at IS 'Timestamp when the API key was last used';
COMMENT ON COLUMN api_keys.expires_at IS 'Expiration timestamp - NULL means no expiration';
COMMENT ON COLUMN api_keys.enabled IS 'Flag to enable/disable the API key without deleting it';
COMMENT ON COLUMN api_keys.deleted_at IS 'Soft delete timestamp - NULL means not deleted';
COMMENT ON COLUMN api_keys.created_at IS 'Timestamp when the API key was created';
COMMENT ON COLUMN api_keys.updated_at IS 'Timestamp when the API key was last updated';

-- Create indices for api_keys table (only if they don't exist)
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_id ON api_keys(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash) WHERE deleted_at IS NULL AND enabled = true;
CREATE INDEX IF NOT EXISTS idx_api_keys_key_prefix ON api_keys(key_prefix) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_enabled ON api_keys(enabled) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_deleted_at ON api_keys(deleted_at);
CREATE INDEX IF NOT EXISTS idx_api_keys_expires_at ON api_keys(expires_at) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_last_used_at ON api_keys(last_used_at);
CREATE INDEX IF NOT EXISTS idx_api_keys_created_at ON api_keys(created_at);

