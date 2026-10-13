-- Admin reset of a user's two-factor (#5656, TFA-1.2).
--
-- A user who loses their authenticator and their backup codes cannot sign in, and until now
-- nothing could clear the factor for them. apiome-rest now resets it on behalf of a super-admin
-- or, for a member of one workspace only, that workspace's owner: the user's two_factor row,
-- trusted-device records and sessions are removed and "twoFactorEnabled" is cleared, all in one
-- transaction with the audit rows (auth_events, and access_audit for an owner's reset).
--
-- The reset needs no new table. This migration adds the one thing it has to remember afterwards:
-- that the user's two-factor was taken away by someone else, so the app can tell them — once
-- they are signed in again — to set it up again.
--
--   users.two_factor_reset_at   set by a reset; cleared when the user enrols again or dismisses
--                               the notice. NULL for everyone else.
--
-- snake_case on purpose: this is apiome's own column. The quoted camelCase columns on users
-- ("twoFactorEnabled") are the ones the Better Auth twoFactor plugin reads and writes itself.

SET search_path TO apiome, public;

ALTER TABLE apiome.users
  ADD COLUMN IF NOT EXISTS two_factor_reset_at TIMESTAMPTZ;

COMMENT ON COLUMN apiome.users.two_factor_reset_at IS
  'When an administrator last reset this user''s two-factor (#5656). Drives the "set two-factor up again" notice; cleared when the user enrols again or dismisses it. NULL = no reset outstanding.';

DO $$
BEGIN
    RAISE NOTICE 'apiome.users.two_factor_reset_at added (#5656, TFA-1.2).';
END $$;
