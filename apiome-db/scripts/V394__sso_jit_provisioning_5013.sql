-- Enterprise SSO — workspace linking and just-in-time provisioning (EID-1.3, #5013)
--
-- A person who signs in through a workspace's identity provider for the first time becomes a member
-- of that workspace with the provider's default role. Three changes make that possible:
--
--   1. Every provider belongs to a workspace. V312 left `sso_provider.tenant_id` nullable so the
--      foundation could land first; from here on a provider without a workspace cannot be written.
--      The rule is a CHECK rather than `SET NOT NULL` so that a provider an installation admin
--      registered with no workspace is kept, not deleted: it is switched off (it has nowhere to
--      provision into) and stays in the admin console until it is given a workspace. Every later
--      write to such a row must supply one. With no such rows the CHECK is validated at once and is
--      then exactly a NOT NULL.
--
--   2. `tenant_users.provisioned_by` records how a membership came to be: `sso:<slug>` for a
--      membership this feature created, NULL for one that was invited or created by hand. The
--      members screen prints it as "SSO · <provider>".
--
--   3. A new inbox type, `seat_cap_blocked_sso`: what a workspace's owners receive when a sign-in
--      could not be given a membership because every licensed seat is taken.
--
-- Idempotent.
--
-- Rollback notes (reverse carefully in shared environments):
--   ALTER TABLE apiome.sso_provider DROP CONSTRAINT IF EXISTS sso_provider_tenant_required_ck;
--   ALTER TABLE apiome.tenant_users DROP COLUMN IF EXISTS provisioned_by;
--   DELETE FROM apiome.notifications WHERE type = 'seat_cap_blocked_sso';  -- then restore the V383 CHECK

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. A provider belongs to a workspace
-- ---------------------------------------------------------------------------------------------------

-- Before the rule exists: a provider with no workspace can no longer complete a sign-in, so it must
-- not route one. (Once the CHECK is in place this row could not be updated without a workspace.)
UPDATE apiome.sso_provider
   SET enabled = FALSE, updated_at = now(), updated_by = 'migration:V394'
 WHERE tenant_id IS NULL AND enabled;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sso_provider_tenant_required_ck'
          AND conrelid = 'apiome.sso_provider'::regclass
    ) THEN
        ALTER TABLE apiome.sso_provider
            ADD CONSTRAINT sso_provider_tenant_required_ck CHECK (tenant_id IS NOT NULL) NOT VALID;
    END IF;

    -- With no workspace-less provider left over from before, hold every row to the rule.
    IF NOT EXISTS (SELECT 1 FROM apiome.sso_provider WHERE tenant_id IS NULL) THEN
        ALTER TABLE apiome.sso_provider VALIDATE CONSTRAINT sso_provider_tenant_required_ck;
    ELSE
        RAISE NOTICE 'V394: SSO providers without a workspace were disabled; assign each a workspace in the admin console to use it again.';
    END IF;
END
$$;

COMMENT ON COLUMN apiome.sso_provider.tenant_id IS
    'EID-1.3 (#5013): the workspace this provider signs people in to and provisions them into. Required for every new or changed row.';

-- ---------------------------------------------------------------------------------------------------
-- 2. Where a membership came from
-- ---------------------------------------------------------------------------------------------------

ALTER TABLE apiome.tenant_users
    ADD COLUMN IF NOT EXISTS provisioned_by VARCHAR(64);

COMMENT ON COLUMN apiome.tenant_users.provisioned_by IS
    'EID-1.3 (#5013): how the membership was created — sso:<provider slug> for just-in-time provisioning, NULL for an invited or hand-made membership.';

-- ---------------------------------------------------------------------------------------------------
-- 3. The inbox type
-- ---------------------------------------------------------------------------------------------------

ALTER TABLE apiome.notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE apiome.notifications
    ADD CONSTRAINT notifications_type_check
        CHECK (type IN (
            'mention', 'review_requested', 'review_decision', 'thread_resolved', 'version_published',
            'export_auto_halted', 'sunset_still_used', 'seat_cap_blocked_sso',
            'owner_finding', 'owner_breaking_change', 'owner_verification_drift', 'owner_gate_blocked',
            'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed'
        ));
