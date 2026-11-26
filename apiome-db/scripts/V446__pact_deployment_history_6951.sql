-- Environments and deployments dashboard — PFX-5.7 (#6951).
--
-- An environment's page in the Contracts workspace lists its **Deployment history**: every
-- deployment recorded to it, current or replaced, newest first, one page at a time, optionally for
-- one pacticipant. That read is
--
--   WHERE tenant_id = $1 AND environment_id = $2 [AND pacticipant_id = $3] AND seq < $cursor
--   ORDER BY seq DESC LIMIT $n
--
-- idx_deployed_version_environment (environment_id, tenant_id) finds an environment's deployments
-- but sorts them all; idx_deployed_version_environment_history adds the order and replaces it (it
-- still serves the environment reference's referential check). History rows are never deleted
-- (V435's guard), so the table only grows; the order is what keeps the page cheap.
--
-- Nothing here changes the table's columns or rules.
--
-- Online: one index build; operators can pre-build it with CREATE INDEX CONCURRENTLY, the
-- migration then skips it.
--
-- Rollback notes:
--   CREATE INDEX IF NOT EXISTS idx_deployed_version_environment
--       ON apiome.deployed_version (environment_id, tenant_id);
--   DROP INDEX IF EXISTS apiome.idx_deployed_version_environment_history;

SET search_path TO apiome, public;

CREATE INDEX IF NOT EXISTS idx_deployed_version_environment_history
    ON deployed_version (environment_id, tenant_id, seq DESC);

DROP INDEX IF EXISTS idx_deployed_version_environment;

COMMENT ON INDEX idx_deployed_version_environment_history IS
    'An environment''s deployment history, newest first, and the environment reference''s check (PFX-5.7, #6951)';
