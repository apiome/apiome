-- Contract health rollup and analytics — PFX-6.3 (#6955).
--
-- The Contracts workspace's **Health** page rolls every consumer ↔ provider pair up into one state
-- from its verification results over a window (7, 30 or 90 days): pass rate, flakiness (how often
-- the verdict flips) and mean duration. That read is
--
--   WHERE tenant_id = $1 AND created_at >= $since [AND provider_id = $2 [AND consumer_id = $3]]
--
-- idx_verification_result_pair (provider_id, tenant_id, consumer_id, seq DESC) serves it once the
-- provider is known, but across the whole workspace nothing leads with the tenant, so the read
-- scanned every result of every workspace. idx_verification_result_tenant_window bounds it to the
-- workspace's window. Results are immutable (V434's trigger) and only grow, so the window is what
-- keeps the read cheap.
--
-- Nothing here changes the table's columns or rules.
--
-- Online: one index build; operators can pre-build it with CREATE INDEX CONCURRENTLY, the
-- migration then skips it.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_verification_result_tenant_window;

SET search_path TO apiome, public;

CREATE INDEX IF NOT EXISTS idx_verification_result_tenant_window
    ON verification_result (tenant_id, created_at);

COMMENT ON INDEX idx_verification_result_tenant_window IS
    'A workspace''s verification results inside a health window (PFX-6.3, #6955)';
