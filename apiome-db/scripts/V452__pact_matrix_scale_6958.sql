-- Pact matrix at 100,000 versions — PFX-6.6 (#6958).
--
-- A matrix query that names a pacticipant without a version ("every row of provider-1", a
-- consumer and provider's history) reads that pacticipant's newest publications. With only
-- idx_pact_publication_pair (provider_id, consumer_id) the read collected every publication of the
-- pacticipant and sorted them to keep the newest hundred: 50,000 rows sorted per query at 250,000
-- pacts, growing with history. These two indexes hand them over newest first, so the read stops
-- at its limit:
--
--   * idx_pact_publication_consumer_recent (consumer_id, created_at DESC, id) — the pacts a
--     consumer published;
--   * idx_pact_publication_provider_recent (provider_id, created_at DESC, id) — the pacts for a
--     provider.
--
-- The order matches the matrix's `ORDER BY p.created_at DESC, p.id` exactly. apiome-rest reads each
-- named pacticipant in its own LATERAL branch (app.pact_matrix_store), because `= ANY(array)`
-- cannot keep the index order on PostgreSQL 16. Nothing here changes a column or a rule.
--
-- Online: two index builds on pact_publication; operators with a large table can pre-build them
-- with CREATE INDEX CONCURRENTLY (same names and columns), the migration then skips them.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_pact_publication_consumer_recent;
--   DROP INDEX IF EXISTS apiome.idx_pact_publication_provider_recent;

SET search_path TO apiome, public;

CREATE INDEX IF NOT EXISTS idx_pact_publication_consumer_recent
    ON pact_publication (consumer_id, created_at DESC, id);

CREATE INDEX IF NOT EXISTS idx_pact_publication_provider_recent
    ON pact_publication (provider_id, created_at DESC, id);

COMMENT ON INDEX idx_pact_publication_consumer_recent IS
    'A consumer''s pacts, newest first: the matrix reads its newest publications without sorting them all (PFX-6.6, #6958)';
COMMENT ON INDEX idx_pact_publication_provider_recent IS
    'A provider''s pacts, newest first: the matrix reads its newest publications without sorting them all (PFX-6.6, #6958)';
