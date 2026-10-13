-- Linked-account tokens are encrypted at rest (#4960, OLO-7.3 follow-up).
--
-- V010 and V199 declared the provider token columns "encrypted in production", but nothing
-- encrypted them: OAuth access / refresh tokens and personal access tokens sat in plaintext TEXT,
-- so any database read (backup leak, replica, SQL injection) yielded live credentials to users'
-- external repositories. From this release:
--
--   * external_auth_providers.access_token / refresh_token hold a sealed, self-describing value —
--         enc:v1:<key_version>:<base64 AES-256-GCM envelope>
--     written by apiome-ui (lib/auth/linked-account-token-crypto.ts) and opened by apiome-ui and
--     apiome-rest (app/linked_account_token_crypto.py). The master keys live in the environment
--     (APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS), never in the database.
--   * account."accessToken" / "refreshToken" / "idToken" are sealed by Better Auth itself
--     (account.encryptOAuthTokens), keyed on the Better Auth secret.
--   * oauth_signup_pending.account_json carries its token fields in the same enc:v1 form.
--
-- A migration cannot seal existing values — the keys are deliberately out of the database's reach.
-- So this script only removes the plaintext copies nothing needs, and corrects the column comments:
--
--   * external_auth_providers rows are left as they are. Both services still read a legacy
--     plaintext value, and apiome-rest's `python -m app.seal_linked_account_tokens` seals them in place
--     once the key is configured (see the production deploy runbook).
--   * account token columns are cleared. apiome never reads them (it reads external_auth_providers),
--     and Better Auth rewrites them, sealed, at each account's next OAuth sign-in.
--   * oauth_signup_pending loses its expired rows and the plaintext token fields of the live ones.
--     A sign-up in flight during the upgrade still completes; its linked account simply starts
--     without a stored provider token, exactly as when encryption is not configured.

SET search_path TO apiome, public;

-- Better Auth's own token copies: unread by apiome, so they are not kept in plaintext.
UPDATE apiome.account
   SET "accessToken" = NULL,
       "refreshToken" = NULL,
       "idToken" = NULL
 WHERE "providerId" <> 'credential'
   AND ("accessToken" IS NOT NULL OR "refreshToken" IS NOT NULL OR "idToken" IS NOT NULL);

-- Staged OAuth sign-ups: drop what has expired, and the plaintext tokens of what has not.
DELETE FROM apiome.oauth_signup_pending
 WHERE expires_at < CURRENT_TIMESTAMP;

UPDATE apiome.oauth_signup_pending
   SET account_json = account_json - 'access_token' - 'refresh_token' - 'id_token'
 WHERE account_json ?| ARRAY['access_token', 'refresh_token', 'id_token'];

COMMENT ON COLUMN apiome.external_auth_providers.access_token IS
  'OAuth access token or personal access token, sealed at rest (#4960): enc:v1:<key_version>:<base64 AES-256-GCM envelope>. A value without the enc:v1: prefix is legacy plaintext until apiome-rest''s "python -m app.seal_linked_account_tokens" seals it.';
COMMENT ON COLUMN apiome.external_auth_providers.refresh_token IS
  'OAuth refresh token, sealed at rest (#4960): enc:v1:<key_version>:<base64 AES-256-GCM envelope>. A value without the enc:v1: prefix is legacy plaintext until apiome-rest''s "python -m app.seal_linked_account_tokens" seals it.';
COMMENT ON COLUMN apiome.account."accessToken" IS
  'OAuth access token, sealed by Better Auth (account.encryptOAuthTokens, #4960). Not read by apiome.';
COMMENT ON COLUMN apiome.account."refreshToken" IS
  'OAuth refresh token, sealed by Better Auth (account.encryptOAuthTokens, #4960). Not read by apiome.';
COMMENT ON COLUMN apiome.account."idToken" IS
  'OIDC id token, sealed by Better Auth (account.encryptOAuthTokens, #4960). Not read by apiome.';
COMMENT ON COLUMN apiome.oauth_signup_pending.account_json IS
  'Provider account payload staged for an OAuth sign-up. Its access_token / refresh_token / id_token fields are sealed at rest (#4960) in the enc:v1 form.';

DO $$
BEGIN
    RAISE NOTICE 'Linked-account tokens are sealed at rest (#4960): plaintext account / pending-signup copies cleared, column comments corrected.';
END $$;
