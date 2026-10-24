-- Bind each sign-up verification link to the password submitted with it (security fix, RC6 B6).
--
-- Before: email sign-up (SGN-1.1, V313) stored the FIRST submitter's password on the unverified
-- `users` row. A later sign-up for the same address only re-sent a link, and opening the link marked
-- the account verified without touching the password. An attacker could therefore pre-register a
-- victim's address with the attacker's password; once the victim verified and used the account, the
-- attacker signed in with that password (account pre-hijacking).
--
-- After: every link carries the bcrypt hash (and display name) submitted with the sign-up that
-- produced it. Opening the link asks for that password; on a match the hash becomes the account's
-- only credential (`users.password` and the Better Auth `account` row), the user's other links are
-- deleted and every session is revoked — in the same transaction that marks the account verified.
-- A link issued before this migration has no pending hash and falls back to the stored password.
--
-- Rollback notes: additive (two nullable columns). To roll back:
--   ALTER TABLE apiome.email_verification_token DROP COLUMN IF EXISTS pending_password_hash;
--   ALTER TABLE apiome.email_verification_token DROP COLUMN IF EXISTS pending_name;

SET search_path TO apiome, public;

ALTER TABLE apiome.email_verification_token
  ADD COLUMN IF NOT EXISTS pending_password_hash TEXT,
  ADD COLUMN IF NOT EXISTS pending_name TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'email_verification_token_pending_hash_ck'
  ) THEN
    ALTER TABLE apiome.email_verification_token
      ADD CONSTRAINT email_verification_token_pending_hash_ck
      CHECK (pending_password_hash IS NULL OR pending_password_hash ~ '^\$2[aby]\$[0-9]{2}\$.{53}$');
  END IF;
END $$;

COMMENT ON COLUMN apiome.email_verification_token.pending_password_hash IS
  'bcrypt hash of the password submitted with the sign-up that issued this link; the redeemer must enter it, and it becomes the account password on redemption.';
COMMENT ON COLUMN apiome.email_verification_token.pending_name IS
  'Display name submitted with the sign-up that issued this link; applied on redemption.';
