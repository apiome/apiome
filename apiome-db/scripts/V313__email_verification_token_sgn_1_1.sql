-- Email verification tokens for credential sign-up (#5650, SGN-1.1, Epic SGN-EPIC-1 #5649).
--
-- A person who signs up with an email address and a password gets an unverified `users` row
-- (`verified = false`, so neither sign-in engine admits it) and an email carrying a one-time link.
-- Opening the link marks the account verified and signs the person in. This table holds those links:
--
--   * only the SHA-256 of the token is stored (`token_hash`), never the token itself, so a database
--     read cannot be replayed as a link;
--   * `expires_at` is 24 hours after issue; an expired link is refused and the page offers a resend;
--   * `used_at` makes the link single-use: a second click is refused rather than signing in again;
--   * issuing a new link for a user deletes that user's unused links, so only the latest one works.
--
-- Rows go with their user (ON DELETE CASCADE). Used and expired rows are kept for a short audit
-- trail and are cheap; the app deletes a user's unused rows on every re-issue.
--
-- Rollback notes: additive (one table, two indexes). To roll back:
--   DROP TABLE IF EXISTS apiome.email_verification_token;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.email_verification_token (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,
  -- Lowercase hex SHA-256 of the token sent in the link.
  token_hash CHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT email_verification_token_hash_format_ck CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT email_verification_token_expiry_ck CHECK (expires_at > created_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS email_verification_token_hash_uq
  ON apiome.email_verification_token (token_hash);

CREATE INDEX IF NOT EXISTS email_verification_token_user_idx
  ON apiome.email_verification_token (user_id);

COMMENT ON TABLE apiome.email_verification_token IS
  'One-time email verification links for credential sign-up (SGN-1.1, #5650). Stores the token hash only; single-use (used_at), 24h expiry.';
COMMENT ON COLUMN apiome.email_verification_token.token_hash IS
  'Lowercase hex SHA-256 of the token in the emailed link; the token itself is never stored.';
COMMENT ON COLUMN apiome.email_verification_token.used_at IS
  'Set when the link verified the account; a used link is refused.';
