-- Webhook payload upgrade — CTG-3.3 (#4477).
--
-- Problem: publish-event webhooks say only *that* a version was published, not
-- whether it breaks anyone. Consumers who want "tell me when something breaking
-- ships" need a per-subscription severity threshold.
--
-- Solution: add min_severity to apiome.push_webhook_subscriptions:
--   * NULL           — no filter; the subscription receives every publish event
--                      (backwards compatible with all existing rows)
--   * 'docs-only'    — receive publishes whose classified max severity is at
--                      least docs-only (i.e. any classified change)
--   * 'non-breaking' — receive non-breaking and breaking publishes
--   * 'breaking'     — receive breaking publishes only
--
-- The severity vocabulary matches apiome.version_changelogs.max_severity
-- (CTG-3.1 / V178). Non-publish webhook events (repository.refresh.*, lint.*,
-- mcp.*) are unaffected by this filter.
--
-- Rollback:
--   ALTER TABLE apiome.push_webhook_subscriptions DROP COLUMN IF EXISTS min_severity;

SET search_path TO apiome, public;

ALTER TABLE push_webhook_subscriptions
    ADD COLUMN IF NOT EXISTS min_severity TEXT;

ALTER TABLE push_webhook_subscriptions
    DROP CONSTRAINT IF EXISTS push_webhook_subscriptions_min_severity_ck;

ALTER TABLE push_webhook_subscriptions
    ADD CONSTRAINT push_webhook_subscriptions_min_severity_ck
        CHECK (
            min_severity IS NULL
            OR min_severity IN ('breaking', 'non-breaking', 'docs-only')
        );

COMMENT ON COLUMN push_webhook_subscriptions.min_severity IS
    'Publish-event severity threshold (CTG-3.3 / #4477); NULL = deliver all publishes';
