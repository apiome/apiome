-- Retire the legacy sign-up request queue (#5652, SGN-1.3, Epic SGN-EPIC-1 #5649; closes #4962).
--
-- `apiome.signup` (V009) held "request an account" submissions that a super-admin turned into
-- accounts from the admin console's Signups tab. Real self-service sign-up (SGN-1.1, #5650) makes
-- the queue redundant, and it was unsafe: the request form revealed whether an address was already
-- queued (#4962), and approving a request created a verified account from a password nobody had
-- confirmed. The app no longer reads or writes the queue.
--
-- This migration:
--
--   * makes `apiome.signup` read-only: a trigger refuses INSERT, UPDATE, DELETE and TRUNCATE, so no
--     code path can write it again. The table is kept for one release so the people still waiting
--     can be invited; a later migration drops it (and the ledger below);
--   * adds `apiome.legacy_signup_invitation`, one row per queued address the app has handled. On
--     startup, when an email sender is configured, apiome-ui sends each queued address that has no
--     row here a "finish creating your account" email pointing at /signup, and records it. The
--     primary key is the claim, so several app replicas starting together send each email once.
--     A failed send deletes its claim, so the next start retries it.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS signup_read_only_trg ON apiome.signup;
--   DROP TRIGGER IF EXISTS signup_read_only_truncate_trg ON apiome.signup;
--   DROP FUNCTION IF EXISTS apiome.signup_read_only();
--   DROP TABLE IF EXISTS apiome.legacy_signup_invitation;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.legacy_signup_invitation (
  -- The queued address, exactly as `apiome.signup.email_address` holds it.
  email_address VARCHAR(255) PRIMARY KEY,
  -- `sent`: the invitation went out. `account_exists`: the address already had an account, so
  -- nothing was sent (the person can sign in).
  outcome VARCHAR(32) NOT NULL,
  handled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT legacy_signup_invitation_outcome_ck CHECK (outcome IN ('sent', 'account_exists'))
);

COMMENT ON TABLE apiome.legacy_signup_invitation IS
  'Queued legacy sign-up requests the app has invited to finish sign-up (SGN-1.3, #5652). Dropped with apiome.signup.';
COMMENT ON COLUMN apiome.legacy_signup_invitation.outcome IS
  'sent = invitation emailed; account_exists = the address already had an account, nothing sent.';

CREATE OR REPLACE FUNCTION apiome.signup_read_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'apiome.signup is read-only: the legacy sign-up request queue was retired (SGN-1.3, #5652)'
    USING ERRCODE = 'read_only_sql_transaction';
END;
$$;

DROP TRIGGER IF EXISTS signup_read_only_trg ON apiome.signup;
CREATE TRIGGER signup_read_only_trg
  BEFORE INSERT OR UPDATE OR DELETE ON apiome.signup
  FOR EACH ROW EXECUTE FUNCTION apiome.signup_read_only();

DROP TRIGGER IF EXISTS signup_read_only_truncate_trg ON apiome.signup;
CREATE TRIGGER signup_read_only_truncate_trg
  BEFORE TRUNCATE ON apiome.signup
  FOR EACH STATEMENT EXECUTE FUNCTION apiome.signup_read_only();

COMMENT ON TABLE apiome.signup IS
  'Retired legacy sign-up request queue (V009). Read-only since SGN-1.3 (#5652); dropped by a later migration.';
