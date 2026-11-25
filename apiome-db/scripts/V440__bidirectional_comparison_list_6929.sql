-- Comparison fidelity report — PFX-2.5 (#6929).
--
-- The workspace's **Pact comparisons** page lists its most recent bi-directional results (V439)
-- so a reader can open each one's fidelity report: what was compared, which matching rules were
-- not supported, and what could not be compared. The list reads
--
--   WHERE tenant_id = $1 AND kind = 'bidirectional' ORDER BY seq DESC LIMIT $2
--
-- and no existing index leads with `tenant_id` (idx_verification_result_pair leads with the
-- provider). This partial index serves it without touching the native results.
--
-- Online: one index; operators can pre-build it with CREATE INDEX CONCURRENTLY, the migration
-- then skips it.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_verification_result_tenant_bidirectional;

SET search_path TO apiome, public;

CREATE INDEX IF NOT EXISTS idx_verification_result_tenant_bidirectional
    ON verification_result (tenant_id, seq DESC)
    WHERE kind = 'bidirectional';
