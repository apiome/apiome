-- Sunset readiness — RDG-5.3 (#5788).
--
-- The sunset timeline schedules a version's end; nothing said whether anyone was still on it. The
-- usage sweep now checks, once a tick, every revision whose sunset is at most 30 days away and that
-- still carried traffic from a *bound* consumer (RDG-1.8) in the last 7 days. For each, it tells the
-- version's collaborators (COL-3.1) and sends a `sunset.still_used` push-webhook event. Two changes:
--
--   1. `sunset_still_used_alert` — one row per revision, the stored state behind "once per version per
--      week". The sweep claims a revision with one upsert that only succeeds when the row is new or its
--      `last_notified_at` is at least 7 days old, and writes the inbox rows in the same transaction. So
--      the weekly rule holds across restarts and REST replicas: it is a fact in this table, never a
--      worker's memory. The row keeps what the last alert said (`consumer_count`, `calls`,
--      `sunset_at`), and `alert_count` how many were sent.
--
--   2. A new inbox type, `sunset_still_used`. The payload carries its own `summary` and `link`.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.sunset_still_used_alert;
--   DELETE FROM apiome.notifications WHERE type = 'sunset_still_used';  -- then restore the V359 CHECK

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS sunset_still_used_alert (
    -- The revision (`versions.id`, the `usage_daily.version_record_id` the traffic matched).
    version_record_id UUID PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- When the last alert was sent. The next is due 7 days later at the earliest.
    last_notified_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- What the last alert said: the sunset it warned about, and the 7-day bound traffic it counted.
    sunset_at VARCHAR(64),
    consumer_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT sunset_still_used_alert_consumers_check CHECK (consumer_count >= 0),
    calls BIGINT NOT NULL DEFAULT 0
        CONSTRAINT sunset_still_used_alert_calls_check CHECK (calls >= 0),
    alert_count INTEGER NOT NULL DEFAULT 1
        CONSTRAINT sunset_still_used_alert_count_check CHECK (alert_count >= 1),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sunset_still_used_alert_project
    ON sunset_still_used_alert (tenant_id, project_id);

COMMENT ON TABLE sunset_still_used_alert IS
    'RDG-5.3 (#5788): the last "still used before its sunset" alert per revision. The usage sweep sends '
    'at most one per revision per 7 days, enforced by an upsert on last_notified_at.';
COMMENT ON COLUMN sunset_still_used_alert.last_notified_at IS
    'When the last sunset_still_used alert was sent; the next is due 7 days later at the earliest.';

-- ---------------------------------------------------------------------------------------------------
-- The inbox type
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications
    ADD CONSTRAINT notifications_type_check
        CHECK (type IN (
            'mention', 'review_requested', 'review_decision', 'thread_resolved', 'version_published',
            'export_auto_halted', 'sunset_still_used',
            'owner_finding', 'owner_breaking_change', 'owner_verification_drift', 'owner_gate_blocked',
            'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed'
        ));

COMMENT ON COLUMN notifications.type IS
    'mention | review_requested | review_decision | thread_resolved | version_published | export_auto_halted | sunset_still_used | owner_finding | owner_breaking_change | owner_verification_drift | owner_gate_blocked | owner_trust_drift | owner_shadow_api | owner_sync_failed';
