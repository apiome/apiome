-- Webhooks UI and execution log — PFX-5.6 (#6950).
--
-- The **Webhooks** page lists every contract webhook of a workspace with its latest delivery, a
-- webhook's page lists its delivery log newest first, and a **Deliveries** tab lists every firing
-- of the workspace. Those reads are
--
--   latest per webhook:  WHERE webhook_id = $1 AND tenant_id = $2 ORDER BY created_at DESC, id DESC LIMIT 1
--   one webhook's log:   WHERE tenant_id = $1 AND webhook_id = $2 AND (created_at, id) < $cursor
--                        ORDER BY created_at DESC, id DESC LIMIT $n
--   the workspace's log: WHERE tenant_id = $1 AND (created_at, id) < $cursor
--                        ORDER BY created_at DESC, id DESC LIMIT $n
--
-- idx_pact_triggered_webhook_webhook (webhook_id, tenant_id) finds a webhook's firings but sorts
-- them all; idx_pact_triggered_webhook_history adds the order and replaces it (it still serves the
-- webhook reference's referential check). Nothing indexed the workspace's firings by tenant;
-- idx_pact_triggered_webhook_recent does.
--
-- Redelivering a firing writes a new pact_triggered_webhook row (trigger_type `user`) and a new
-- queued delivery; nothing here changes the table's columns or rules.
--
-- Online: two index builds on a small table; operators can pre-build them with CREATE INDEX
-- CONCURRENTLY, the migration then skips them.
--
-- Rollback notes:
--   CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_webhook
--       ON apiome.pact_triggered_webhook (webhook_id, tenant_id);
--   DROP INDEX IF EXISTS apiome.idx_pact_triggered_webhook_history;
--   DROP INDEX IF EXISTS apiome.idx_pact_triggered_webhook_recent;

SET search_path TO apiome, public;

CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_history
    ON pact_triggered_webhook (webhook_id, tenant_id, created_at DESC, id DESC);

DROP INDEX IF EXISTS idx_pact_triggered_webhook_webhook;

CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_recent
    ON pact_triggered_webhook (tenant_id, created_at DESC, id DESC);

COMMENT ON INDEX idx_pact_triggered_webhook_history IS
    'A webhook''s delivery log, newest first, and the webhook reference''s check (PFX-5.6, #6950)';
COMMENT ON INDEX idx_pact_triggered_webhook_recent IS
    'The workspace''s delivery log, newest first (PFX-5.6, #6950)';
