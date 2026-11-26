-- Verification results and operations — PFX-5.5 (#6949).
--
-- The **Verification** page of a provider lists every verification result it has, newest first,
-- re-runs one pact on demand and verifies every stale pact at once. Each result now says how it
-- came to be, how long the run took, and which evidence run (ECA-1.3) holds its log:
--
--   verification_result.trigger         — `published` (a Pact verifier posted it), `hosted` (the
--                                         hosted verifier, PFX-3.2), `manual` (a re-run from the
--                                         console), `stale-recheck` (Verify all stale) or
--                                         `bidirectional` (a pact ↔ OpenAPI comparison, PFX-2.3).
--                                         NULL on results recorded before this migration.
--   verification_result.duration_ms     — wall-clock time of the run, when Apiome ran it.
--   verification_result.evidence_run_id — the evidence run with every request's assertions, when
--                                         Apiome ran it. Not a foreign key: evidence is its own
--                                         immutable ledger with its own retention, and a result
--                                         outlives a pruned run (the reader then says so).
--
-- Rules kept by the database:
--
--   1. **Closed list.** `trigger` is one of the five values above (apiome-rest
--      `app.verification_result.TRIGGERS`).
--   2. **A duration is never negative.**
--   3. Rows stay immutable (V434 trigger): the new columns are written once, at publish time.
--
-- The provider's history reads
--
--   WHERE tenant_id = $1 AND provider_id = $2 [AND consumer_id = $3] AND seq < $cursor
--   ORDER BY seq DESC LIMIT $n
--
-- which idx_verification_result_pair serves once the consumer is known, but not across all of a
-- provider's consumers; idx_verification_result_provider_history serves that.
--
-- Online: three nullable columns (no rewrite) and one index; operators can pre-build the index
-- with CREATE INDEX CONCURRENTLY, the migration then skips it.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_verification_result_provider_history;
--   ALTER TABLE apiome.verification_result
--       DROP CONSTRAINT IF EXISTS verification_result_trigger_check,
--       DROP CONSTRAINT IF EXISTS verification_result_duration_check,
--       DROP COLUMN IF EXISTS evidence_run_id,
--       DROP COLUMN IF EXISTS duration_ms,
--       DROP COLUMN IF EXISTS trigger;

SET search_path TO apiome, public;

ALTER TABLE verification_result
    ADD COLUMN IF NOT EXISTS trigger VARCHAR(16),
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS evidence_run_id UUID;

-- Rules 1 and 2.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_result_trigger_check'
          AND conrelid = 'apiome.verification_result'::regclass
    ) THEN
        ALTER TABLE apiome.verification_result
            ADD CONSTRAINT verification_result_trigger_check CHECK (
                trigger IS NULL
                OR trigger IN ('published', 'hosted', 'manual', 'stale-recheck', 'bidirectional')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_result_duration_check'
          AND conrelid = 'apiome.verification_result'::regclass
    ) THEN
        ALTER TABLE apiome.verification_result
            ADD CONSTRAINT verification_result_duration_check CHECK (duration_ms IS NULL OR duration_ms >= 0);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_verification_result_provider_history
    ON verification_result (tenant_id, provider_id, seq DESC);

COMMENT ON COLUMN verification_result.trigger IS
    'How the result came to be: published, hosted, manual, stale-recheck or bidirectional (PFX-5.5); NULL before V444';
COMMENT ON COLUMN verification_result.duration_ms IS
    'Wall-clock duration of the run in milliseconds, when Apiome ran it (PFX-5.5)';
COMMENT ON COLUMN verification_result.evidence_run_id IS
    'The ECA-1.3 evidence run holding the run''s assertions, when Apiome ran it (PFX-5.5); not a foreign key';
