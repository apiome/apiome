-- Owner routing of findings — CDG-2.3 (#5962).
--
-- Lint regressions, breaking changes, verification drift, blocked deploy gates, MCP trust drift,
-- shadow APIs and connector sync failures used to reach "the tenant" (every webhook) or nobody.
-- They now reach the entity's confirmed owner team (CDG-2.2): an inbox row per team member and one
-- post to the team's chat channel. This migration adds what that needs:
--
--   1. **Seven inbox types**, by the constraint swap V263 planned for: owner_finding,
--      owner_breaking_change, owner_verification_drift, owner_gate_blocked, owner_trust_drift,
--      owner_shadow_api, owner_sync_failed.
--
--   2. **unowned_findings** — a finding on an entity with no confirmed owner is recorded here rather
--      than dropped: one row per (entity, finding type), counting occurrences, holding the latest
--      payload. CDG-2.5 adds the catch-all team that drains it.
--
--   3. **owner_notification_throttle** — one routed event per (team, entity, finding type) per
--      window, so a gate read in a loop or a flapping schedule does not flood a team. Same claim
--      shape as the repository and connector throttles (V232, V283).
--
--   4. **Direct-URL webhook deliveries.** A team's chat_url is not a push-webhook subscription (a
--      subscription receives every tenant event). A delivery row may now name a `target_url` (and
--      the `team_id` it is for) instead of a subscription; the existing worker sends it with the
--      same retries and dead-letter handling.
--
-- Rollback notes (reverse carefully in shared environments):
--   DELETE FROM apiome.push_webhook_delivery_events WHERE subscription_id IS NULL;
--   ALTER TABLE apiome.push_webhook_delivery_events DROP CONSTRAINT IF EXISTS push_webhook_delivery_events_target_check,
--     DROP COLUMN IF EXISTS target_url, DROP COLUMN IF EXISTS team_id, ALTER COLUMN subscription_id SET NOT NULL;
--   DROP TABLE IF EXISTS apiome.owner_notification_throttle;
--   DROP TABLE IF EXISTS apiome.unowned_findings;
--   DELETE FROM apiome.notifications WHERE type LIKE 'owner\_%';  -- then restore the V263 CHECK

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. Inbox types
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications
    ADD CONSTRAINT notifications_type_check
        CHECK (type IN (
            'mention', 'review_requested', 'review_decision', 'thread_resolved', 'version_published',
            'owner_finding', 'owner_breaking_change', 'owner_verification_drift', 'owner_gate_blocked',
            'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed'
        ));

COMMENT ON COLUMN notifications.type IS
    'mention | review_requested | review_decision | thread_resolved | version_published | owner_finding | owner_breaking_change | owner_verification_drift | owner_gate_blocked | owner_trust_drift | owner_shadow_api | owner_sync_failed';

-- ---------------------------------------------------------------------------------------------------
-- 2. Unowned findings
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unowned_findings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    entity_kind VARCHAR(32) NOT NULL
        CONSTRAINT unowned_findings_kind_check
            CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector')),
    entity_id UUID NOT NULL,
    finding_type VARCHAR(32) NOT NULL
        CONSTRAINT unowned_findings_type_check
            CHECK (finding_type IN (
                'owner_finding', 'owner_breaking_change', 'owner_verification_drift',
                'owner_gate_blocked', 'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed'
            )),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT unowned_findings_payload_object_check CHECK (jsonb_typeof(payload) = 'object'),
    occurrences INTEGER NOT NULL DEFAULT 1
        CONSTRAINT unowned_findings_occurrences_check CHECK (occurrences >= 1),
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unowned_findings_entity_type_key UNIQUE (tenant_id, entity_kind, entity_id, finding_type)
);

CREATE INDEX IF NOT EXISTS idx_unowned_findings_tenant_recent
    ON unowned_findings (tenant_id, last_seen_at DESC);

COMMENT ON TABLE unowned_findings IS
    'Findings on entities with no confirmed owner team, kept so they are never dropped (CDG-2.3, #5962)';
COMMENT ON COLUMN unowned_findings.payload IS 'The latest occurrence''s payload (summary, link, finding id)';

-- ---------------------------------------------------------------------------------------------------
-- 3. Owner throttle
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS owner_notification_throttle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    entity_kind VARCHAR(32) NOT NULL,
    entity_id UUID NOT NULL,
    finding_type VARCHAR(32) NOT NULL,
    last_notified_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    suppressed_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT owner_notification_throttle_suppressed_check CHECK (suppressed_count >= 0),
    CONSTRAINT uq_owner_notification_throttle UNIQUE (team_id, entity_kind, entity_id, finding_type)
);

COMMENT ON TABLE owner_notification_throttle IS
    'At most one routed owner event per (team, entity, finding type) per window (CDG-2.3, #5962)';

-- ---------------------------------------------------------------------------------------------------
-- 4. Direct-URL deliveries (team chat channels)
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE push_webhook_delivery_events
    ALTER COLUMN subscription_id DROP NOT NULL;
ALTER TABLE push_webhook_delivery_events
    ADD COLUMN IF NOT EXISTS target_url TEXT,
    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE CASCADE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'push_webhook_delivery_events_target_check'
    ) THEN
        ALTER TABLE push_webhook_delivery_events
            ADD CONSTRAINT push_webhook_delivery_events_target_check
            CHECK (subscription_id IS NOT NULL OR (target_url IS NOT NULL AND target_url ~* '^https?://'));
    END IF;
END;
$$;

COMMENT ON COLUMN push_webhook_delivery_events.target_url IS
    'Direct destination for a delivery that has no subscription — a team chat channel (CDG-2.3); sent unsigned';
COMMENT ON COLUMN push_webhook_delivery_events.team_id IS 'The team a direct-URL delivery is for (CDG-2.3)';
