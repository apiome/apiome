-- Better Auth credential-password relocation (#5000, OLO-10.5, Epic OLO-EPIC-10 #4995).
--
-- Design of record: docs/BETTER_AUTH_MIGRATION.md §2.3 (account model) and §4 (additive, reversible
-- cutover). This is the DATA half of the credential move: 10.4 (#4999, V199) created the `account`
-- table WITH the `"password"` column but deliberately moved no password DATA. This migration relocates
-- the credential password hashes off `apiome.users.password` into `apiome.account` rows with
-- `providerId='credential'`, so the Better Auth engine can authenticate password users from the place
-- Better Auth expects (an `account` row) instead of a bespoke column on the user record.
--
-- WHY A DEDICATED CREDENTIAL ACCOUNT ROW.
--   Better Auth stores BOTH OAuth identities and the credential password in one `account` table keyed
--   by `providerId`. OAuth rows use the provider slug ('github'/'gitlab'/…) and were backfilled by
--   V199. The credential password is just another account whose provider is the literal string
--   'credential'; Better Auth's email/password sign-in reads `account.password` for the
--   `providerId='credential'` row of the matched user. `accountId` for that row is the user's own id
--   (§2.3) — a credential "account" is self-owned, it has no external provider-side id.
--
-- BCRYPT IS PRESERVED, NOT RE-HASHED.
--   The hashes copied here are the exact bcrypt strings already stored on `users.password` (cost 10,
--   `$2a$`/`$2b$`). Nothing is re-hashed: the relocation is a byte-for-byte copy so every existing
--   password keeps verifying. The app side (apiome-ui/lib/auth/better-auth-credentials.ts) registers a
--   bcrypt `password.verify`/`password.hash` on the Better Auth `emailAndPassword` config precisely so
--   these relocated bcrypt hashes verify under Better Auth (whose default is scrypt, which would reject
--   them). See that module and docs/BETTER_AUTH_MIGRATION.md §2.3.
--
-- WHICH USERS GET A CREDENTIAL ROW.
--   Only users with a USABLE password: `password IS NOT NULL AND password <> ''` and not soft-deleted
--   (`deleted_at IS NULL`). OAuth-provisioned accounts carry an empty-string password sentinel (the
--   "no usable credential" marker — see apiome-ui/lib/db/admin-helper.ts clearUserPassword) and must
--   NOT get a credential row, otherwise they would appear to have a password login they never set. The
--   `enabled` flag is intentionally NOT filtered on: a disabled user's password is still relocated so
--   re-enabling them restores password login; the enabled/verified gates are enforced at sign-in, not
--   by row presence.
--
-- ADDITIVE / REVERSIBLE (cutover model §4).
--   * `users.password` is left completely intact — it stays the source of truth for rollback until the
--     epic's final ticket (10.14 #5009) drops it. During parallel-run the legacy NextAuth engine keeps
--     reading `users.password`; the relocated copy is kept in sync by dual-writes on every password
--     write (apiome-ui/lib/db credential-account helpers), so a flip to Better Auth (or back) loses no
--     password.
--   * Rollback of THIS migration removes only the relocated credential rows and leaves OAuth accounts
--     and `users.password` untouched:
--         DELETE FROM apiome.account WHERE "providerId" = 'credential';
--     After that, `users.password` is exactly as before and the legacy engine is unaffected. Because
--     the backfill is `ON CONFLICT DO NOTHING`, re-applying the migration after a partial rollback (or
--     onto a hand-drifted schema) converges without error and never clobbers a live Better Auth-written
--     credential row.
--
-- SCOPE BOUNDARY.
--   The `account."password"` COLUMN and the identity-uniqueness constraints already exist (V199). The
--   `two_factor` table / `users.twoFactorEnabled` flag are 10.10 (#5005) and out of scope here.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Relocate credential password hashes: one `account` row per password user, keyed by the literal
-- provider 'credential' with `accountId` = the user's own id (§2.3). The bcrypt hash is copied
-- verbatim from `users.password`; `provider_email`/`email_verified` carry the user's email + verified
-- state so the row is self-describing (they are not used to gate credential auto-linking, but keep the
-- account shape consistent with the OAuth rows the resolution engine reads). `profile_data` is NULL —
-- a credential identity has no external provider profile.
--
-- ON CONFLICT ("providerId","accountId") DO NOTHING keeps the backfill idempotent and, once 10.14 has
-- run and Better Auth owns credential writes, a re-run cannot overwrite a live (possibly newer) hash.
-- ---------------------------------------------------------------------------------------------------
INSERT INTO apiome.account (
  "id", "userId", "accountId", "providerId",
  "password",
  "createdAt", "updatedAt",
  provider_email, email_verified, profile_data
)
SELECT
  uuid_generate_v4()::text,
  u.id,
  u.id::text,
  'credential',
  u.password,
  COALESCE(u.created_at, CURRENT_TIMESTAMP),
  COALESCE(u.updated_at, CURRENT_TIMESTAMP),
  u.email,
  COALESCE(u.verified, false),
  NULL
FROM apiome.users u
WHERE u.deleted_at IS NULL
  AND u.password IS NOT NULL
  AND u.password <> ''
ON CONFLICT ("providerId", "accountId") DO NOTHING;

COMMENT ON COLUMN apiome.account."password" IS
  'Credential password hash (bcrypt, cost 10). Relocated from apiome.users.password by OLO-10.5 '
  '(#5000) for account rows with providerId=''credential''; NULL for OAuth rows. users.password is '
  'kept in sync by dual-write and remains the rollback source until 10.14 (#5009).';
