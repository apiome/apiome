-- Provider-slug vocabulary — full Better Auth catalog (OLO-9.16, #5029, Epic OLO-EPIC-9)
--
-- The two controlled vocabularies that gate provider slugs were widened one provider at a time
-- (V198 for the issuer-based providers, then V202 `line`, V203 `vk`, V204 `wechat`). The remaining
-- Better Auth catalog (OLO-9.17–9.49) is 30 more providers; one colliding one-line migration per
-- provider ticket does not scale. This migration widens both CHECKs once, to the whole catalog:
--
--   * `external_auth_providers.provider` — the OLO-2.2 identity vocabulary
--     (`external_auth_providers_provider_supported_ck`), the slug a linked identity is stored under.
--     V312 (EID-1.1, #5011) added the enterprise SSO identity kind `sso:<slug>` to this CHECK; that
--     pattern is kept unchanged here.
--   * `auth_provider_config.provider_id` — the OLO-8.2 config vocabulary
--     (`auth_provider_config_provider_id_check`), the slug a stored provider-config row is keyed by.
--
-- The new slugs are INERT until their provider ticket ships a registry entry: the runtime gate on
-- what can be enabled, linked or signed in with stays the PROVIDER_REGISTRY (provider-registry.ts /
-- auth_provider_registry.py) and `LINKABLE_PROVIDERS` (account-resolution.ts). A slug in the CHECK
-- but absent from the registry is still un-enableable; the CHECK is only a typo backstop (V198).
--
-- Whether a provider's verified email may auto-link an account is NOT decided here. That is the
-- per-provider trust class recorded in `apiome-ui/lib/auth/provider-trust-classes.ts`.
--
-- Slugs are Better Auth's own provider ids (`@better-auth/core` social providers and the
-- generic-oauth presets), so `account."providerId"` and this vocabulary never diverge.
--
-- Idempotent: each constraint is dropped (if present) and re-added with the widened list, so the
-- migration is a no-op on a database already carrying the target vocabulary. Every slug accepted
-- before this migration is still accepted, so no existing identity or config row is invalidated.

SET search_path TO apiome, public;

-- external_auth_providers.provider: the V204 set, the 30 remaining catalog slugs, and the V312
-- `sso:<slug>` identity kind.
ALTER TABLE external_auth_providers
    DROP CONSTRAINT IF EXISTS external_auth_providers_provider_supported_ck;
ALTER TABLE external_auth_providers
    ADD CONSTRAINT external_auth_providers_provider_supported_ck
    CHECK (
        provider IN (
            -- Accepted before this migration (V198, V202–V204).
            'github', 'gitlab', 'azure', 'google', 'aws', 'gcp', 'bitbucket',
            'okta', 'keycloak', 'auth0', 'oidc', 'atlassian',
            'line', 'vk', 'wechat',
            -- Wave 1 — developer and work tools (OLO-9.17–9.29).
            'slack', 'linkedin', 'discord', 'salesforce', 'notion', 'figma', 'linear',
            'dropbox', 'zoom', 'huggingface', 'vercel', 'railway', 'hubspot',
            -- Wave 2 — consumer social (OLO-9.30–9.38).
            'apple', 'facebook', 'twitter', 'reddit', 'spotify', 'twitch', 'tiktok',
            'roblox', 'kick',
            -- Wave 3 — regional identity providers not yet admitted (OLO-9.39, 9.40, 9.44).
            'kakao', 'naver', 'yandex',
            -- Wave 4 — payments and creator platforms (OLO-9.45–9.49).
            'paypal', 'polar', 'patreon', 'gumroad', 'paybin'
        )
        OR provider ~ '^sso:[a-z0-9][a-z0-9-]{1,27}$'
    );

-- auth_provider_config.provider_id: the same slug set (no `sso:` kind — SSO providers are
-- configured per workspace in `sso_providers`, not in this installation-wide table).
ALTER TABLE apiome.auth_provider_config
    DROP CONSTRAINT IF EXISTS auth_provider_config_provider_id_check;
ALTER TABLE apiome.auth_provider_config
    ADD CONSTRAINT auth_provider_config_provider_id_check
    CHECK (provider_id IN (
        -- Accepted before this migration (V198, V202–V204).
        'github', 'gitlab', 'azure', 'google', 'aws', 'gcp', 'bitbucket',
        'okta', 'keycloak', 'auth0', 'oidc', 'atlassian',
        'line', 'vk', 'wechat',
        -- Wave 1 — developer and work tools (OLO-9.17–9.29).
        'slack', 'linkedin', 'discord', 'salesforce', 'notion', 'figma', 'linear',
        'dropbox', 'zoom', 'huggingface', 'vercel', 'railway', 'hubspot',
        -- Wave 2 — consumer social (OLO-9.30–9.38).
        'apple', 'facebook', 'twitter', 'reddit', 'spotify', 'twitch', 'tiktok',
        'roblox', 'kick',
        -- Wave 3 — regional identity providers not yet admitted (OLO-9.39, 9.40, 9.44).
        'kakao', 'naver', 'yandex',
        -- Wave 4 — payments and creator platforms (OLO-9.45–9.49).
        'paypal', 'polar', 'patreon', 'gumroad', 'paybin'
    ));

COMMENT ON COLUMN apiome.auth_provider_config.provider_id IS
    'Provider slug matching PROVIDER_REGISTRY ids; primary key, one row per provider. Vocabulary widened for OLO-9.16 (#5029) to the full Better Auth catalog; a slug is inert until its registry entry ships.';
