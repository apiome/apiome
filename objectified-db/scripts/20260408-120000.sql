-- OAuth self-signup pending sessions, post-signup login tokens, and free-tier entitlements (#66)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS oauth_signup_pending (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider VARCHAR(32) NOT NULL,
    provider_account_id VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    account_json JSONB NOT NULL DEFAULT '{}',
    profile_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_oauth_signup_provider_account UNIQUE (provider, provider_account_id)
);

CREATE INDEX IF NOT EXISTS idx_oauth_signup_pending_expires ON oauth_signup_pending (expires_at);

COMMENT ON TABLE oauth_signup_pending IS 'Temporary store between OAuth callback and tenant/profile completion for new users';

CREATE TABLE IF NOT EXISTS auth_one_time_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES odb.users(id) ON DELETE CASCADE,
    tenant_id UUID REFERENCES odb.tenants(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_auth_one_time_codes_expires ON auth_one_time_codes (expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_one_time_codes_user ON auth_one_time_codes (user_id);

COMMENT ON TABLE auth_one_time_codes IS 'Single-use codes to establish a session after OAuth signup completes';

CREATE TABLE IF NOT EXISTS user_entitlements (
    user_id UUID PRIMARY KEY REFERENCES odb.users(id) ON DELETE CASCADE,
    plan_code VARCHAR(64) NOT NULL DEFAULT 'free',
    max_tenants INT NOT NULL DEFAULT 1,
    max_projects INT NOT NULL DEFAULT 1,
    max_versions INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE user_entitlements IS 'Plan limits per user; absence of a row means legacy/unenforced accounts';
