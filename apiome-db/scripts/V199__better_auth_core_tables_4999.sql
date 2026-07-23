-- Better Auth core schema — session / account / verification tables (#4999, OLO-10.4, Epic OLO-EPIC-10 #4995).
--
-- Design of record: docs/BETTER_AUTH_MIGRATION.md §2 (field-by-field schema map). This migration is
-- the DB half of the Better Auth core install (the app half — the `betterAuth(...)` instance — landed
-- in 10.2 #4997). Better Auth's core is four models: `user`, `session`, `account`, `verification`.
-- apiome already has `users` (mapped in place as the `user` model — no table needed here) and
-- `external_auth_providers`; `session`, `account`, and `verification` DO NOT EXIST and are created
-- here with Better Auth's exact shape.
--
-- WHY THE UNUSUAL camelCase, QUOTED COLUMN NAMES.
--   Better Auth talks to Postgres through its Kysely adapter, which quotes every identifier, and its
--   default field names are camelCase (`userId`, `expiresAt`, `providerId`, `accessTokenExpiresAt`,
--   …). The 10.2 instance (apiome-ui/lib/auth/auth.ts) is constructed with NO field mapping for these
--   three tables, so Better Auth reads/writes the literal quoted identifiers `"userId"`, `"expiresAt"`,
--   … . To be readable by Better Auth out of the box these columns MUST be quoted camelCase, which is
--   why they deviate from the snake_case convention used everywhere else in `apiome`. Only the reused
--   `users` table keeps its snake_case columns (Better Auth maps `emailVerified → verified` etc. via
--   config, per §2.1); the *new* tables use Better Auth's native names so no mapping is required.
--   The singular table names (`session`/`account`/`verification`) are likewise Better Auth's defaults.
--
-- ID TYPES.
--   Better Auth generates the primary key for rows it creates (an opaque string), so `id` is TEXT on
--   the new tables — matching what Better Auth's own migration generator emits for Postgres. `"userId"`
--   is UUID because it is a foreign key onto the pre-existing `apiome.users.id` (UUID); Better Auth
--   passes the user's UUID as a string and Postgres accepts it into the UUID column.
--
-- ADDITIVE / REVERSIBLE (cutover model §4).
--   This migration only CREATES new tables and BACKFILLS `account` from the existing OAuth identities;
--   it never drops or rewrites `users`, `users.password`, or `external_auth_providers`. Those remain
--   the source of truth for rollback until 10.14 (#5009). Rollback of this migration is simply:
--       DROP TABLE IF EXISTS apiome.session CASCADE;
--       DROP TABLE IF EXISTS apiome.account CASCADE;
--       DROP TABLE IF EXISTS apiome.verification CASCADE;
--   Every statement is guarded (CREATE TABLE/INDEX IF NOT EXISTS, ON CONFLICT DO NOTHING) so a re-run
--   or a hand-drifted schema converges without error.
--
-- SCOPE BOUNDARY.
--   * The credential-password relocation into `account(providerId='credential', password=…)` is 10.5
--     (#5000) — the `password` COLUMN is created here (Better Auth's account shape), but no password
--     DATA is moved by this migration.
--   * The `two_factor` table and `users.twoFactorEnabled` flag are 10.10 (#5005).
--   Both are intentionally out of scope; see §2.3/§2.5.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- session — Better Auth database sessions (design §2.2). One row per live session; the opaque `token`
-- rides the session cookie and is validated per request. Replaces NextAuth's stateless JWE cookie.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.session (
  -- Better Auth-generated opaque string id (not a UUID) — TEXT to match Better Auth's own schema.
  "id"          TEXT PRIMARY KEY,
  -- Owning user. UUID FK onto the reused `users` table; cascade so deleting a user clears its sessions.
  "userId"      UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,
  -- Opaque session token carried in the cookie; unique so a token identifies exactly one session.
  "token"       TEXT NOT NULL,
  -- Absolute expiry (30-day TTL, design §1).
  "expiresAt"   TIMESTAMPTZ NOT NULL,
  -- Request metadata Better Auth captures for free; feeds the auth_events ledger (V193), hashed there.
  "ipAddress"   TEXT,
  "userAgent"   TEXT,
  "createdAt"   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT session_token_key UNIQUE ("token")
);

-- Hot-path indexes: validate-by-token is covered by the UNIQUE constraint; add owner lookup
-- ("sign out everywhere" / list-my-sessions) and an expiry index for sweep/cleanup jobs.
CREATE INDEX IF NOT EXISTS idx_session_user_id    ON apiome.session ("userId");
CREATE INDEX IF NOT EXISTS idx_session_expires_at ON apiome.session ("expiresAt");

COMMENT ON TABLE apiome.session IS
  'Better Auth database sessions (OLO-10.4). Opaque token in the session cookie is validated against '
  'this table per request; replaces the legacy stateless JWE session.';

-- ---------------------------------------------------------------------------------------------------
-- account — Better Auth account model (design §2.3). Stores BOTH OAuth identities (backfilled below
-- from external_auth_providers) AND, from 10.5, the relocated credential password. Keyed by
-- (providerId, accountId); the credential row uses the literal providerId 'credential'.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.account (
  "id"                     TEXT PRIMARY KEY,
  -- Owning user; UUID FK onto `users`, cascade on user delete (mirrors external_auth_providers.user_id).
  "userId"                 UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,
  -- Provider-side account id. For OAuth: external_auth_providers.provider_user_id. For the credential
  -- row (10.5): the user's own id.
  "accountId"              TEXT NOT NULL,
  -- Provider slug ('github'/'gitlab'/'azure'/'google'/…) verbatim, or the literal 'credential' (10.5).
  "providerId"             TEXT NOT NULL,
  -- OAuth tokens (encrypted at rest in production, as in external_auth_providers).
  "accessToken"            TEXT,
  "refreshToken"           TEXT,
  "idToken"                TEXT,
  "accessTokenExpiresAt"   TIMESTAMPTZ,
  "refreshTokenExpiresAt"  TIMESTAMPTZ,
  "scope"                  TEXT,
  -- Credential password hash (bcrypt). Column created here; DATA relocated by 10.5 (#5000). NULL for
  -- OAuth rows.
  "password"               TEXT,
  "createdAt"              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- Carried-over app columns (§2.3): the account-resolution engine reads provider_email / email_verified
  -- / profile_data for nOAuth re-validation (§3.2) and verified-email parity (§3.3). snake_case because
  -- they are read by the resolution store, not by Better Auth core.
  provider_email           VARCHAR(255),
  email_verified           BOOLEAN NOT NULL DEFAULT false,
  profile_data             JSONB,
  -- Identity-uniqueness invariant (OLO-1.2, §3.1) — re-expressed from external_auth_providers and
  -- landed WITH the table (not later): one provider identity maps to exactly one row, and a user holds
  -- at most one account per provider.
  CONSTRAINT account_provider_identity_key UNIQUE ("providerId", "accountId"),
  CONSTRAINT account_user_provider_key     UNIQUE ("userId", "providerId")
);

-- "userId" and "providerId" lookups are served by the leftmost columns of the two UNIQUE constraints.
-- Add an email lookup index to preserve the capability external_auth_providers had (idx_..._provider_email).
CREATE INDEX IF NOT EXISTS idx_account_provider_email ON apiome.account (provider_email);

COMMENT ON TABLE apiome.account IS
  'Better Auth account model (OLO-10.4): OAuth identities (backfilled from external_auth_providers) and '
  'the relocated credential password (10.5). UNIQUE(providerId,accountId)+UNIQUE(userId,providerId) '
  'carry the OLO-1.2 identity-uniqueness invariant.';
COMMENT ON COLUMN apiome.account.email_verified IS
  'Whether the provider proved this identity''s email is verified — read by the resolution engine to '
  'gate auto-linking (§3.2). Carried from external_auth_providers.email_verified; defaults to false.';
COMMENT ON COLUMN apiome.account.profile_data IS
  'Raw provider profile/claims (e.g. Entra oid/tid/upn/xms_edov) the resolution engine re-validates '
  'against (§3.2). Carried from external_auth_providers.profile_data.';

-- ---------------------------------------------------------------------------------------------------
-- verification — Better Auth verification store (design §2.4). Backs email-verification / OTP / 2FA
-- challenge tokens. No legacy source table (apiome only had the users.verified boolean).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.verification (
  "id"          TEXT PRIMARY KEY,
  -- What is being verified — e.g. an email address or a '2fa:<userId>' key.
  "identifier"  TEXT NOT NULL,
  -- The token/code being checked (replaces NextAuth's `token`).
  "value"       TEXT NOT NULL,
  -- Token expiry (replaces NextAuth's `expires`).
  "expiresAt"   TIMESTAMPTZ NOT NULL,
  "createdAt"   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Better Auth looks verifications up by identifier.
CREATE INDEX IF NOT EXISTS idx_verification_identifier ON apiome.verification ("identifier");

COMMENT ON TABLE apiome.verification IS
  'Better Auth verification store (OLO-10.4): email-verification / OTP / 2FA challenge tokens keyed by '
  'identifier. New in the Better Auth migration — no legacy source table.';

-- ---------------------------------------------------------------------------------------------------
-- Backfill `account` from the existing OAuth identities (design §2.3 / §4 — "existing rows transformed").
-- One account row per external_auth_providers row: provider → providerId, provider_user_id → accountId,
-- and the carried-over columns. password / idToken / scope / refreshTokenExpiresAt stay NULL (not
-- tracked by the legacy identity table). ON CONFLICT keeps the backfill idempotent and, once 10.14 has
-- run and Better Auth owns writes, a re-run cannot clobber live rows. Credential (password) rows are
-- NOT created here — that is 10.5.
-- ---------------------------------------------------------------------------------------------------
INSERT INTO apiome.account (
  "id", "userId", "accountId", "providerId",
  "accessToken", "refreshToken", "accessTokenExpiresAt",
  "createdAt", "updatedAt",
  provider_email, email_verified, profile_data
)
SELECT
  uuid_generate_v4()::text,
  eap.user_id,
  eap.provider_user_id,
  eap.provider,
  eap.access_token,
  eap.refresh_token,
  eap.token_expires_at,
  COALESCE(eap.created_at, CURRENT_TIMESTAMP),
  COALESCE(eap.updated_at, CURRENT_TIMESTAMP),
  eap.provider_email,
  eap.email_verified,
  eap.profile_data
FROM apiome.external_auth_providers eap
ON CONFLICT ("providerId", "accountId") DO NOTHING;
