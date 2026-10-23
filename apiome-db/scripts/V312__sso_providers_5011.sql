-- Enterprise SSO providers — SAML 2.0 / OIDC bring-your-own IdP (EID-1.1, #5011)
--
-- A workspace's own identity provider, registered by an installation admin (EID-1.2 adds the
-- owner-facing page and DNS verification). apiome-ui hands the *enabled* providers with *verified*
-- domains to Better Auth's SSO plugin as `defaultSSO`, so these two tables — not the plugin's own
-- `ssoProvider` table — are the source of truth:
--
--   * sso_provider         one IdP connection; secrets only as OLO-8.3 envelope ciphertext
--   * sso_provider_domain  the email domains it signs in, unique across the installation
--
-- `tenant_id` is nullable so this foundation can land before JIT provisioning (EID-1.3 adds the
-- NOT NULL swap). Identities still live only in `users`, `external_auth_providers` and
-- `session`: an SSO identity is an `external_auth_providers` row with provider `sso:<slug>`.
--
-- Idempotent.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.sso_provider (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- `sso:<slug>` must fit auth_events.provider and oauth_signup_pending.provider (VARCHAR(32)).
    slug VARCHAR(28) NOT NULL UNIQUE
        CONSTRAINT sso_provider_slug_format_ck CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,27}$'),
    protocol VARCHAR(8) NOT NULL
        CONSTRAINT sso_provider_protocol_ck CHECK (protocol IN ('oidc', 'saml')),
    display_name VARCHAR(120) NOT NULL,
    issuer TEXT NOT NULL,
    tenant_id UUID REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    -- Non-secret configuration only. Secrets live in the *_encrypted columns.
    oidc_config JSONB,
    saml_config JSONB,
    -- OLO-8.3 envelope (seal_provider_secret): ciphertext + the key generation that sealed it,
    -- both-or-neither per secret, so one secret can be re-sealed under a rotated key alone.
    client_secret_encrypted BYTEA,
    client_secret_key_id VARCHAR(64),
    sp_private_key_encrypted BYTEA,
    sp_private_key_key_id VARCHAR(64),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    preset VARCHAR(32),
    default_role_slug VARCHAR(64),
    -- Who changed it: 'admin' for the installation admin console (its session carries no user);
    -- EID-1.2's owner flow records the user id.
    created_by VARCHAR(64),
    updated_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sso_provider_client_secret_pair_ck CHECK (
        (client_secret_encrypted IS NULL) = (client_secret_key_id IS NULL)
    ),
    CONSTRAINT sso_provider_sp_key_pair_ck CHECK (
        (sp_private_key_encrypted IS NULL) = (sp_private_key_key_id IS NULL)
    ),
    CONSTRAINT sso_provider_config_matches_protocol_ck CHECK (
        (protocol = 'oidc' AND oidc_config IS NOT NULL AND saml_config IS NULL)
        OR (protocol = 'saml' AND saml_config IS NOT NULL AND oidc_config IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS sso_provider_tenant_idx ON apiome.sso_provider (tenant_id);

COMMENT ON TABLE apiome.sso_provider IS
    'EID-1.1 (#5011): a workspace''s own SAML 2.0 / OIDC identity provider. Secrets are OLO-8.3 envelope ciphertext; the JSONB config never holds one.';

CREATE TABLE IF NOT EXISTS apiome.sso_provider_domain (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id UUID NOT NULL REFERENCES apiome.sso_provider(id) ON DELETE CASCADE,
    -- Lower-case, no wildcard, unique installation-wide: one domain routes to one IdP.
    domain VARCHAR(253) NOT NULL UNIQUE
        CONSTRAINT sso_provider_domain_format_ck
        CHECK (domain = lower(domain) AND domain ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'),
    verification_token VARCHAR(128) NOT NULL,
    verified_at TIMESTAMPTZ,
    verified_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sso_provider_domain_provider_idx ON apiome.sso_provider_domain (provider_id);

COMMENT ON TABLE apiome.sso_provider_domain IS
    'EID-1.1 (#5011): email domains an SSO provider signs in. Only verified domains route.';

-- Better Auth's SSO plugin falls back to its own `ssoProvider` model when a provider id or domain
-- is not in `defaultSSO`. Pointing that model at an always-empty view means a disabled or
-- unverified provider can never be found that way, and nothing can be written there.
CREATE OR REPLACE VIEW apiome.sso_provider_plugin_stub AS
SELECT
    NULL::text AS id,
    NULL::text AS "issuer",
    NULL::text AS "oidcConfig",
    NULL::text AS "samlConfig",
    NULL::text AS "userId",
    NULL::text AS "providerId",
    NULL::text AS "organizationId",
    NULL::text AS "domain",
    NULL::boolean AS "domainVerified"
WHERE FALSE;

COMMENT ON VIEW apiome.sso_provider_plugin_stub IS
    'EID-1.1 (#5011): always empty. Better Auth SSO plugin model target, so providers only come from defaultSSO.';

-- An SSO identity is `sso:<slug>` in the identity table (OLO-9.16 #5029 vocabulary pattern).
ALTER TABLE external_auth_providers
    DROP CONSTRAINT IF EXISTS external_auth_providers_provider_supported_ck;
ALTER TABLE external_auth_providers
    ADD CONSTRAINT external_auth_providers_provider_supported_ck
    CHECK (
        provider IN (
            'github', 'gitlab', 'azure', 'google', 'aws', 'gcp', 'bitbucket',
            'okta', 'keycloak', 'auth0', 'oidc', 'atlassian',
            'line', 'vk', 'wechat'
        )
        OR provider ~ '^sso:[a-z0-9][a-z0-9-]{1,27}$'
    );
