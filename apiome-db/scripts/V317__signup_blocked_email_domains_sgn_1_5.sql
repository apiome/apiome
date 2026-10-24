-- Sign-up abuse protection: admin-extendable disposable-email blocklist (#5654, SGN-1.5).
--
-- Email sign-up refuses addresses at disposable (throwaway) email providers. apiome-ui ships a
-- bundled list of those domains (`lib/auth/disposable-email-domains.ts`); this migration adds the
-- place a super-admin extends it from the System settings **Sign-up** card:
--
--   * `apiome.signup_policy.blocked_email_domains` — extra lower-case bare domains refused for
--     email sign-up, on top of the bundled list. Empty ⇒ only the bundled list applies.
--
-- The blocklist applies to **email** sign-up only. An OAuth provider has already verified the
-- address it hands over, so OAuth sign-up is never refused by it. With no stored policy row (env
-- governs) the bundled list still applies; the extra domains live on the row, so clearing the
-- stored policy also clears them.
--
-- Blocked attempts themselves are recorded in `apiome.auth_events` (V193) as failed `sign_up`
-- rows whose `detail.guard` names the guard; no schema change is needed for that.
--
-- Rollback notes: additive (one column, one CHECK, one comment). To roll back:
--   ALTER TABLE apiome.signup_policy DROP COLUMN IF EXISTS blocked_email_domains;

SET search_path TO apiome, public;

ALTER TABLE apiome.signup_policy
  ADD COLUMN IF NOT EXISTS blocked_email_domains TEXT[] NOT NULL DEFAULT '{}'::text[];

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'signup_policy_blocked_email_domains_bounded'
    ) THEN
        -- Bounded so a runaway write cannot bloat a row read on every sign-up.
        ALTER TABLE apiome.signup_policy
          ADD CONSTRAINT signup_policy_blocked_email_domains_bounded
          CHECK (cardinality(blocked_email_domains) <= 1000);
    END IF;
END $$;

COMMENT ON COLUMN apiome.signup_policy.blocked_email_domains IS
  'Extra lower-case email domains refused for email sign-up, on top of the bundled disposable-domain list (#5654).';

DO $$
BEGIN
    RAISE NOTICE 'apiome.signup_policy.blocked_email_domains added (#5654, SGN-1.5).';
END $$;
