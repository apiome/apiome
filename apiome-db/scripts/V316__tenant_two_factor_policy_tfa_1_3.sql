-- Tenant two-factor policy — TFA-1.3 (#5657).
--
-- Three tenant settings let an owner require two-factor authentication for every member:
--
--   require_two_factor        — the switch. Off by default.
--   two_factor_grace_days     — days a member without two-factor may keep working (default 7,
--                               0–90). A member's deadline is the later of the policy being turned
--                               on and the member joining, plus these days.
--   two_factor_required_since — when the switch was last turned on; NULL while it is off. Turning
--                               the policy off and on again restarts everyone's grace period.
--
-- Past the deadline, a member without two-factor is shown a blocking enrolment screen when they
-- open the app (apiome-ui). API keys are unaffected.
--
-- Rollback notes:
--   ALTER TABLE apiome.tenants DROP CONSTRAINT IF EXISTS tenants_two_factor_grace_days_range,
--                              DROP COLUMN IF EXISTS two_factor_required_since,
--                              DROP COLUMN IF EXISTS two_factor_grace_days,
--                              DROP COLUMN IF EXISTS require_two_factor;

SET search_path TO apiome, public;

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS require_two_factor BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS two_factor_grace_days INTEGER NOT NULL DEFAULT 7,
    ADD COLUMN IF NOT EXISTS two_factor_required_since TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tenants_two_factor_grace_days_range'
    ) THEN
        ALTER TABLE tenants
            ADD CONSTRAINT tenants_two_factor_grace_days_range
            CHECK (two_factor_grace_days BETWEEN 0 AND 90);
    END IF;
END $$;

COMMENT ON COLUMN tenants.require_two_factor IS
    'When true, every member must turn on two-factor authentication within the grace period (TFA-1.3)';
COMMENT ON COLUMN tenants.two_factor_grace_days IS
    'Days a member without two-factor may keep working after the policy is on or they join (0-90, TFA-1.3)';
COMMENT ON COLUMN tenants.two_factor_required_since IS
    'When require_two_factor was last turned on; NULL while off (TFA-1.3)';
