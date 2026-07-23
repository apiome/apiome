-- Issuer-aware provider registries — supported-provider vocabulary (#4984, OLO-9.1, Epic OLO-EPIC-9)
--
-- OLO-9.1 makes the provider registries able to declare required fields beyond client id/secret
-- (an OIDC `issuer`/`domain` URL), unblocking the issuer-based providers of OLO-9.3–9.7 (Okta,
-- Cognito/Keycloak, Auth0, generic OIDC, Atlassian, Bitbucket). Those providers persist rows keyed
-- by their slug, so the two controlled vocabularies that gate provider slugs must accept the
-- upcoming values *ahead* of the providers going live — otherwise 9.3–9.7 would each need their own
-- migration. This widens both CHECKs to one shared, forward-looking vocabulary:
--
--   * `external_auth_providers.provider` — the OLO-2.2 identity vocabulary (V010 column, V181 CHECK
--     `external_auth_providers_provider_supported_ck`), the slug a linked identity is stored under.
--   * `auth_provider_config.provider_id` — the OLO-8.2 config vocabulary (V196 CHECK
--     `auth_provider_config_provider_id_check`), the slug a stored provider-config row is keyed by.
--
-- The runtime gate on what can actually be *enabled* stays the PROVIDER_REGISTRY (provider-
-- registry.ts / auth_provider_registry.py): a slug in the CHECK but absent from the registry is
-- still un-enableable. The CHECK remains only a typo backstop, now permissive for the roadmap set.
--
-- Idempotent: each constraint is dropped (if present) and re-added with the widened list, so the
-- migration is a no-op on a database already carrying the target vocabulary.

-- external_auth_providers.provider (OLO-2.2 identity vocabulary): existing slugs
-- (github/gitlab/azure/aws/gcp/bitbucket/google, V181) plus the OLO-9.3–9.7 issuer-based providers.
ALTER TABLE external_auth_providers
    DROP CONSTRAINT IF EXISTS external_auth_providers_provider_supported_ck;
ALTER TABLE external_auth_providers
    ADD CONSTRAINT external_auth_providers_provider_supported_ck
    CHECK (provider IN (
        'github', 'gitlab', 'azure', 'google', 'aws', 'gcp', 'bitbucket',
        'okta', 'keycloak', 'auth0', 'oidc', 'atlassian'
    ));

-- auth_provider_config.provider_id (OLO-8.2 config vocabulary): the same shared set, so an admin
-- can store config for any registry provider once it ships.
ALTER TABLE apiome.auth_provider_config
    DROP CONSTRAINT IF EXISTS auth_provider_config_provider_id_check;
ALTER TABLE apiome.auth_provider_config
    ADD CONSTRAINT auth_provider_config_provider_id_check
    CHECK (provider_id IN (
        'github', 'gitlab', 'azure', 'google', 'aws', 'gcp', 'bitbucket',
        'okta', 'keycloak', 'auth0', 'oidc', 'atlassian'
    ));

COMMENT ON COLUMN apiome.auth_provider_config.provider_id IS
    'Provider slug matching PROVIDER_REGISTRY ids; primary key, one row per provider. Vocabulary widened for OLO-9.1 (#4984) to accept the OLO-9.3-9.7 issuer-based providers (okta|keycloak|auth0|oidc|atlassian|bitbucket) ahead of their launch.';
