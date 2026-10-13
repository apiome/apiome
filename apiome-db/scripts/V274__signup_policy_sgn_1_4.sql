-- Installation sign-up policy (#5653, SGN-1.4, Epic SGN-EPIC-1 #5649).
--
-- Whether a new person may create an account has been one env flag (AUTH_SIGNUP_DISABLED). This
-- migration adds the database home for that decision so a super-admin can change it from the admin
-- console without a redeploy:
--
--   * `apiome.signup_policy`       — at most ONE row: the installation's stored sign-up policy.
--   * `apiome.signup_policy_audit` — append-only ledger of every change to that row.
--
-- DB-first with env fallback (the OLO-8 pattern, cf. auth_provider_config V196):
--   * NO ROW      ⇒ the policy is governed entirely by env (AUTH_SIGNUP_DISABLED), unchanged.
--   * ROW PRESENT ⇒ the stored `mode` and `allowed_email_domains` win over env.
-- The table is created empty, so a deployment that never opens the admin card behaves exactly as
-- before. Clearing the stored policy deletes the row (and records `cleared` in the ledger).
--
-- Modes:
--   open        — anyone may create an account (restricted to `allowed_email_domains` when set).
--   invite_only — no self-service account creation; people who already hold an account (including
--                 one with a pending tenant invitation) still sign in.
--   closed      — no self-service account creation at all.
-- `allowed_email_domains` narrows `open` only; an empty array means "any domain".
--
-- Server-global, like auth_provider_config: sign-up is an installation decision, not a tenant one,
-- so neither table carries a tenant_id and `updated_by` / `actor` are TEXT (the super-admin session
-- need not correspond to a users row).
--
-- Rollback notes: additive (two tables, one trigger function + trigger, comments). To roll back:
--   DROP TABLE IF EXISTS apiome.signup_policy_audit;
--   DROP TABLE IF EXISTS apiome.signup_policy CASCADE;   -- also drops its trigger
--   DROP FUNCTION IF EXISTS apiome.update_signup_policy_updated_at();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- signup_policy — the installation's stored sign-up policy. Singleton: zero rows or one.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.signup_policy (
  -- Singleton key: the only admissible value is TRUE, so a second row can never be inserted.
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE,

  -- Who may create an account. See the header for what each mode means.
  mode TEXT NOT NULL,

  -- Email domains allowed to sign up while `mode = 'open'`. Lower-case bare domains
  -- ('example.com'), matched exactly against the part after '@'. Empty ⇒ any domain.
  allowed_email_domains TEXT[] NOT NULL DEFAULT '{}'::text[],

  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Who last changed the policy. TEXT (not a users FK): see the header.
  updated_by TEXT,

  CONSTRAINT signup_policy_singleton_check CHECK (singleton),

  -- Enum guard (cf. auth_provider_config_provider_id_check): a bad mode can never be persisted,
  -- even by a direct SQL write.
  CONSTRAINT signup_policy_mode_check CHECK (mode IN ('open', 'invite_only', 'closed')),

  -- The list is bounded so a runaway write cannot bloat a row read on every sign-up.
  CONSTRAINT signup_policy_allowed_email_domains_bounded
    CHECK (cardinality(allowed_email_domains) <= 200)
);

COMMENT ON TABLE apiome.signup_policy IS
  'Installation sign-up policy (#5653, SGN-1.4). At most one row; no row ⇒ env (AUTH_SIGNUP_DISABLED) governs.';
COMMENT ON COLUMN apiome.signup_policy.singleton IS 'Singleton key; always TRUE so the table holds at most one row.';
COMMENT ON COLUMN apiome.signup_policy.mode IS 'Who may create an account: open | invite_only | closed.';
COMMENT ON COLUMN apiome.signup_policy.allowed_email_domains IS 'Lower-case email domains allowed to sign up while mode = open; empty ⇒ any domain.';
COMMENT ON COLUMN apiome.signup_policy.updated_at IS 'When the policy was last changed (maintained by trigger).';
COMMENT ON COLUMN apiome.signup_policy.updated_by IS 'Identity of the super-admin who last changed the policy; TEXT (not a users FK).';

CREATE OR REPLACE FUNCTION update_signup_policy_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_signup_policy_updated_at ON apiome.signup_policy;
CREATE TRIGGER trigger_update_signup_policy_updated_at
    BEFORE UPDATE ON apiome.signup_policy
    FOR EACH ROW
    EXECUTE FUNCTION update_signup_policy_updated_at();

COMMENT ON FUNCTION update_signup_policy_updated_at() IS 'Trigger function that refreshes updated_at on any change to the signup_policy row (#5653).';

-- ---------------------------------------------------------------------------------------------------
-- signup_policy_audit — append-only ledger of policy changes. Written in the same transaction as
-- the change it records, so a change is never stored without its audit row (or the reverse).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.signup_policy_audit (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- 'updated' — the policy was stored or changed; 'cleared' — the stored policy was removed and
  -- the installation reverted to env.
  action TEXT NOT NULL,

  -- Identity of the super-admin who made the change.
  actor TEXT,

  -- The stored policy before and after the change, as {"mode": …, "allowed_email_domains": […]}.
  -- NULL means "no stored policy" (env governed) on that side of the change.
  before_policy JSONB,
  after_policy JSONB,

  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT signup_policy_audit_action_check CHECK (action IN ('updated', 'cleared'))
);

CREATE INDEX IF NOT EXISTS idx_signup_policy_audit_created_at
  ON apiome.signup_policy_audit (created_at DESC);

COMMENT ON TABLE apiome.signup_policy_audit IS
  'Append-only ledger of sign-up policy changes (#5653, SGN-1.4), written in the same transaction as each change.';
COMMENT ON COLUMN apiome.signup_policy_audit.action IS 'updated (policy stored/changed) | cleared (stored policy removed; env governs).';
COMMENT ON COLUMN apiome.signup_policy_audit.actor IS 'Identity of the super-admin who made the change.';
COMMENT ON COLUMN apiome.signup_policy_audit.before_policy IS 'Stored policy before the change; NULL ⇒ none was stored.';
COMMENT ON COLUMN apiome.signup_policy_audit.after_policy IS 'Stored policy after the change; NULL ⇒ none is stored.';
COMMENT ON COLUMN apiome.signup_policy_audit.created_at IS 'When the change was made.';

DO $$
BEGIN
    RAISE NOTICE 'apiome.signup_policy and apiome.signup_policy_audit created (#5653, SGN-1.4).';
END $$;
