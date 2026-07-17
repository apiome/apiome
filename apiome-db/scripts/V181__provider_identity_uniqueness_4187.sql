-- Provider-identity uniqueness + verified-email columns (OLO-1.2, #4187).
--
-- `apiome.external_auth_providers` (V010) links an OAuth identity (GitHub/GitLab/Azure/…) to a
-- master `users` row. Two invariants the OAuth/login epic depends on must be guaranteed at the DB
-- level, independent of whatever state a deployed schema is in:
--
--   1. A single provider identity `(provider, provider_user_id)` maps to exactly one row, so the
--      same GitHub/GitLab/Azure account can never be linked to two different users (account
--      takeover / identity confusion). See §1.1 of the roadmap.
--   2. A user carries at most one identity per provider `(user_id, provider)` — the assumption the
--      existing link route already makes.
--
-- V010 defines both as table `UNIQUE(...)` constraints, but this forward migration re-asserts them
-- so any hand-built or drifted schema converges to the same guarantee (guarded, idempotent).
--
-- It also adds the columns the account-resolution engine (1.3) and Azure persistence (2.2) read:
--   - `email` / `provider_email`: the address the provider asserts for this identity.
--   - `email_verified`: whether the provider proved that address is verified. Auto-linking on an
--     *unverified* address is an account-takeover vector (Auth.js `allowDangerousEmailAccountLinking`
--     guidance; the Entra nOAuth advisory), so the resolution engine keys off this flag. It defaults
--     to false — "not proven verified" — and is refreshed on every OAuth sign-in.
--   - `last_login_at`: timestamp of the most recent sign-in through this identity.
--
-- Finally it pins the supported provider vocabulary, extending it to include `azure` (Microsoft
-- Entra ID) alongside the providers already carried in the V010 column comment.
SET search_path TO apiome, public;

-- Verified-email + email columns the resolution engine reads. `provider_email` and `last_login_at`
-- already exist from V010; the IF NOT EXISTS guards make this migration self-contained on schemas
-- that predate them. `email_verified` is genuinely new.
ALTER TABLE external_auth_providers
    ADD COLUMN IF NOT EXISTS provider_email   VARCHAR(255);
ALTER TABLE external_auth_providers
    ADD COLUMN IF NOT EXISTS email_verified   BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE external_auth_providers
    ADD COLUMN IF NOT EXISTS last_login_at    TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN external_auth_providers.email_verified IS
    'Whether the provider proved this identity''s email address is verified. Drives auto-link '
    'decisions (1.3): auto-linking on an unverified address is forbidden. Defaults to false.';

-- Backfill `email_verified` from stored profile JSON where the provider recorded a verified signal.
-- OIDC providers (GitLab openid, Azure/Entra) place a boolean/string `email_verified` claim in the
-- profile; accept both `true` and the string "true". Rows without the signal stay false ("not
-- proven"), which is the safe default for the resolution engine.
UPDATE external_auth_providers
SET email_verified = true
WHERE email_verified = false
  AND profile_data IS NOT NULL
  AND lower(coalesce(profile_data->>'email_verified', '')) = 'true';

-- Re-assert the two uniqueness invariants. V010 already declares them as table constraints; guard on
-- pg_constraint by the Postgres-generated names so this is a no-op on a normal schema yet still
-- repairs a drifted one.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'external_auth_providers_provider_provider_user_id_key'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_external_auth_provider_identity'
    ) THEN
        ALTER TABLE external_auth_providers
            ADD CONSTRAINT uq_external_auth_provider_identity
            UNIQUE (provider, provider_user_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'external_auth_providers_user_id_provider_key'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_external_auth_user_provider'
    ) THEN
        ALTER TABLE external_auth_providers
            ADD CONSTRAINT uq_external_auth_user_provider
            UNIQUE (user_id, provider);
    END IF;
END $$;

-- Pin the supported provider vocabulary, now including `azure` (Entra ID). The set mirrors the
-- providers documented in V010 plus azure; a controlled vocabulary keeps typo'd provider slugs out
-- of the identity table. Guarded so re-runs are no-ops.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'external_auth_providers_provider_supported_ck'
    ) THEN
        ALTER TABLE external_auth_providers
            ADD CONSTRAINT external_auth_providers_provider_supported_ck
            CHECK (provider IN ('github', 'gitlab', 'azure', 'aws', 'gcp', 'bitbucket', 'google'));
    END IF;
END $$;
