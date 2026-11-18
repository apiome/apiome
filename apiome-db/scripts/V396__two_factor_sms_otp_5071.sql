-- SMS / phone OTP as a second factor (#5071, OLO-9.51).
--
-- Better Auth's twoFactor plugin has a single one-time-code channel (`otpOptions.sendOTP`), which
-- email OTP (#5070) already uses. SMS rides on the same channel: the app decides per user whether
-- the code goes to their inbox or to their phone. That needs two things on users:
--
--   "phoneNumber" / "phoneNumberVerified"
--       The Better Auth phoneNumber plugin's own fields, kept in its native quoted camelCase (like
--       "twoFactorEnabled") so the plugin reads and writes them with no field mapping. A number is
--       stored only once the user has typed back the code sent to it, so "phoneNumberVerified" is
--       true for every stored number; it is still a column because the plugin owns it. One account
--       per number (unique index; NULLs do not collide).
--
--   two_factor_otp_channel
--       apiome's own column (snake_case): where the sign-in code goes — 'email' (the default, the
--       #5070 behaviour) or 'sms'. 'sms' is only ever written for a user with a verified number.
--
-- Additive and idempotent: existing users keep email delivery and have no number.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.users_phone_number_key;
--   ALTER TABLE apiome.users DROP CONSTRAINT IF EXISTS users_two_factor_otp_channel_check,
--                            DROP COLUMN IF EXISTS two_factor_otp_channel,
--                            DROP COLUMN IF EXISTS "phoneNumberVerified",
--                            DROP COLUMN IF EXISTS "phoneNumber";

SET search_path TO apiome, public;

ALTER TABLE apiome.users
  ADD COLUMN IF NOT EXISTS "phoneNumber" TEXT,
  ADD COLUMN IF NOT EXISTS "phoneNumberVerified" BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS two_factor_otp_channel TEXT NOT NULL DEFAULT 'email';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_two_factor_otp_channel_check'
    ) THEN
        ALTER TABLE apiome.users
            ADD CONSTRAINT users_two_factor_otp_channel_check
            CHECK (two_factor_otp_channel IN ('email', 'sms'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS users_phone_number_key ON apiome.users ("phoneNumber");

COMMENT ON COLUMN apiome.users."phoneNumber" IS
  'E.164 phone number the user verified by SMS code (Better Auth phoneNumber plugin, #5071). Used for SMS two-factor codes; never for sign-in.';
COMMENT ON COLUMN apiome.users."phoneNumberVerified" IS
  'Better Auth phoneNumber plugin flag (#5071): true once the stored number has been confirmed with a code.';
COMMENT ON COLUMN apiome.users.two_factor_otp_channel IS
  'Where two-factor sign-in codes are delivered (#5071): email (default) or sms (requires a verified phone number).';

DO $$
BEGIN
    RAISE NOTICE 'apiome.users phone number + two_factor_otp_channel added (#5071, OLO-9.51).';
END $$;
