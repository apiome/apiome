-- External Authentication Providers Table
-- Links external provider accounts (GitHub, GitLab, AWS, GCP, etc.) to master user accounts
-- Allows users to login using OAuth providers

SET search_path TO odb, public;

DROP TABLE IF EXISTS odb.external_auth_providers CASCADE;
DROP INDEX IF EXISTS idx_external_auth_providers_user_id;
DROP INDEX IF EXISTS idx_external_auth_providers_provider;
DROP INDEX IF EXISTS idx_external_auth_providers_provider_email;
DROP INDEX IF EXISTS idx_external_auth_providers_provider_user_id;
DROP INDEX IF EXISTS idx_external_auth_providers_created_at;
DROP INDEX IF EXISTS idx_external_auth_providers_last_login_at;

-- External Auth Providers table: Stores linked external authentication provider accounts
CREATE TABLE external_auth_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,  -- e.g., 'github', 'gitlab', 'aws', 'gcp', 'azure', 'bitbucket'
    provider_user_id VARCHAR(255) NOT NULL,  -- The user ID from the provider
    provider_email VARCHAR(255),  -- Email address from the provider
    provider_username VARCHAR(255),  -- Username from the provider (if available)
    access_token TEXT,  -- OAuth access token (encrypted in production)
    refresh_token TEXT,  -- OAuth refresh token (encrypted in production)
    token_expires_at TIMESTAMP WITH TIME ZONE,  -- When the access token expires
    profile_data JSONB,  -- Additional profile data from the provider
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE,
    -- Ensure a user can only link one account per provider
    UNIQUE(user_id, provider),
    -- Ensure a provider account can only be linked to one user
    UNIQUE(provider, provider_user_id)
);

-- Indices for external_auth_providers table
CREATE INDEX idx_external_auth_providers_user_id ON external_auth_providers(user_id);
CREATE INDEX idx_external_auth_providers_provider ON external_auth_providers(provider);
CREATE INDEX idx_external_auth_providers_provider_email ON external_auth_providers(provider_email);
CREATE INDEX idx_external_auth_providers_provider_user_id ON external_auth_providers(provider, provider_user_id);
CREATE INDEX idx_external_auth_providers_created_at ON external_auth_providers(created_at);
CREATE INDEX idx_external_auth_providers_last_login_at ON external_auth_providers(last_login_at);

-- Add table and column comments
COMMENT ON TABLE external_auth_providers IS 'Links external OAuth provider accounts to master user accounts for SSO authentication';
COMMENT ON COLUMN external_auth_providers.user_id IS 'Reference to the master user account in odb.users';
COMMENT ON COLUMN external_auth_providers.provider IS 'Name of the OAuth provider (github, gitlab, aws, gcp, azure, etc.)';
COMMENT ON COLUMN external_auth_providers.provider_user_id IS 'The unique user ID from the external provider';
COMMENT ON COLUMN external_auth_providers.provider_email IS 'Email address provided by the external OAuth provider';
COMMENT ON COLUMN external_auth_providers.provider_username IS 'Username from the provider (GitHub username, GitLab username, etc.)';
COMMENT ON COLUMN external_auth_providers.access_token IS 'OAuth access token (should be encrypted at rest in production)';
COMMENT ON COLUMN external_auth_providers.refresh_token IS 'OAuth refresh token (should be encrypted at rest in production)';
COMMENT ON COLUMN external_auth_providers.token_expires_at IS 'Expiration timestamp for the access token';
COMMENT ON COLUMN external_auth_providers.profile_data IS 'Additional profile information from the provider stored as JSON';
COMMENT ON COLUMN external_auth_providers.last_login_at IS 'Timestamp of the last successful login using this provider';

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_external_auth_providers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at
CREATE TRIGGER trigger_update_external_auth_providers_updated_at
    BEFORE UPDATE ON external_auth_providers
    FOR EACH ROW
    EXECUTE FUNCTION update_external_auth_providers_updated_at();

