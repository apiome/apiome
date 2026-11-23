-- Sign-in table and log search indexes (DBP-1.11, #7194).
--
-- Measured on the scale database with the side tables filled (200k verification rows, 100k
-- sessions over 2,000 users, 1M slate_insight_logs lines):
--
--   * idx_verification_value — the two-factor reset (Database.reset_member_two_factor) deletes a
--     member's trusted devices and pending codes WHERE "value" = <user id>. verification was
--     indexed on "identifier" only, so each reset scanned the table: 8.3 ms / 3,072 buffers ->
--     0.01 ms / 37.
--   * idx_session_user_updated — the admin Users list (apiome-ui getAllUsersWithLicenses) reads
--     MAX("updatedAt") of each user's sessions. On ("userId") alone that read every session of
--     every user; on ("userId", "updatedAt" DESC) it is one index-only probe per user: 21.4 ms /
--     104,051 buffers -> 5.5 ms / 6,058 for 2,000 users. It replaces idx_session_user_id, a
--     leading prefix of it that still serves the per-user session deletes. Better Auth stamps
--     "updatedAt" when it refreshes a session (once a day per session by default), and that
--     update can no longer be HOT; that is the one added write cost.
--   * idx_slate_insight_logs_message_trgm — the lane log search (slate_insights_store.list_logs
--     with a query: message ILIKE '%text%'). Without it the search read every line of the lane
--     newest first until it found a match: 19.8 ms / 21,721 buffers -> 0.02 ms / 49 for a rare
--     term in a 50,000-line lane.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to its table while it builds. To avoid that, build the
-- CREATE INDEX statements first by hand with CREATE INDEX CONCURRENTLY (same names and
-- definitions); every statement is IF [NOT] EXISTS, so the migration then only drops the replaced
-- index.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_verification_value;
--   CREATE INDEX idx_session_user_id ON apiome.session ("userId");
--   DROP INDEX IF EXISTS apiome.idx_session_user_updated;
--   DROP INDEX IF EXISTS apiome.idx_slate_insight_logs_message_trgm;

-- pg_trgm lives in the apiome schema (V230); gin_trgm_ops resolves through the search path.
SET search_path TO apiome, public;

CREATE INDEX IF NOT EXISTS idx_verification_value
    ON apiome.verification ("value");

CREATE INDEX IF NOT EXISTS idx_session_user_updated
    ON apiome.session ("userId", "updatedAt" DESC);
DROP INDEX IF EXISTS apiome.idx_session_user_id;  -- leading prefix of idx_session_user_updated

CREATE INDEX IF NOT EXISTS idx_slate_insight_logs_message_trgm
    ON apiome.slate_insight_logs USING gin (message gin_trgm_ops);
