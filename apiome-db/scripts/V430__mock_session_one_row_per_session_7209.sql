-- Mock Postgres session store: one row per session for expiry, no table-wide work on the request
-- path (DBP-1.26, #7209).
--
-- V156's mock_session_state kept the sliding expiry on every resource row of a session, so each
-- operation (a read included) rewrote up to session_max_resources rows. Each new session counted
-- the distinct sessions of the whole table, and every operation deleted all tenants' expired rows
-- inline. This migration replaces it with:
--
--   * mock_session — one row per X-Mock-Session namespace: expiry, last activity, resource count
--     and total bytes. apiome-mock touches it at most about once a minute per session, and reads
--     find a session through its unique key.
--   * mock_session_resource — the stored resources; they reference their session and cascade.
--   * mock_session_counter — the integer id / sequence counter per (session, collection), so id
--     allocation is one upsert instead of reading every id of the collection.
--   * mock_session_slots — a one-row count of mock_session rows, kept by a statement-level trigger.
--     A new session locks this row and compares the count with the cap in its own transaction, so
--     concurrent creates cannot exceed APIOME_MOCK_SESSION_MAX_SESSIONS. The count includes expired
--     sessions the sweep has not removed yet.
--
-- Expired sessions are removed by apiome-mock's periodic sweep (APIOME_MOCK_SESSION_PURGE_INTERVAL_SECONDS),
-- in batches taken with FOR UPDATE SKIP LOCKED, never on the request path.
--
-- Existing sessions that have not expired are carried over: their expiry, last activity and
-- resources are kept, and counters start from the highest numeric id (as before). Expired rows are
-- dropped with the old table. Replicas still running the previous apiome-mock fail stateful
-- requests between this migration and their restart; upgrade the mock runtime right after it.
--
-- Rollback notes:
--   Re-create V156's mock_session_state (and V381 drops idx_mock_session_state_session), then
--   DROP TABLE apiome.mock_session_counter, apiome.mock_session_resource, apiome.mock_session_slots,
--   apiome.mock_session; DROP FUNCTION apiome.mock_session_slots_count(); live sessions are lost.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_session (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_slug VARCHAR(255) NOT NULL,
    project_slug VARCHAR(255) NOT NULL,
    version_label VARCHAR(255) NOT NULL,
    session_token VARCHAR(255) NOT NULL,
    resource_count INTEGER NOT NULL DEFAULT 0 CHECK (resource_count >= 0),
    total_bytes BIGINT NOT NULL DEFAULT 0 CHECK (total_bytes >= 0),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT mock_session_namespace_unique
        UNIQUE (tenant_slug, project_slug, version_label, session_token)
);

CREATE INDEX IF NOT EXISTS idx_mock_session_expires
    ON mock_session (expires_at);

CREATE TABLE IF NOT EXISTS mock_session_resource (
    session_id BIGINT NOT NULL REFERENCES mock_session (id) ON DELETE CASCADE,
    collection_path TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource JSONB NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    PRIMARY KEY (session_id, collection_path, resource_id)
);

CREATE TABLE IF NOT EXISTS mock_session_counter (
    session_id BIGINT NOT NULL REFERENCES mock_session (id) ON DELETE CASCADE,
    collection_path TEXT NOT NULL,
    last_id BIGINT NOT NULL,
    PRIMARY KEY (session_id, collection_path)
);

CREATE TABLE IF NOT EXISTS mock_session_slots (
    slot_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (slot_id = 1),
    session_count BIGINT NOT NULL DEFAULT 0 CHECK (session_count >= 0)
);

-- Carry over live sessions (one row per namespace; the latest expiry and activity win).
INSERT INTO mock_session (
    tenant_slug, project_slug, version_label, session_token,
    resource_count, total_bytes, expires_at, last_activity_at
)
SELECT tenant_slug, project_slug, version_label, session_token,
       COUNT(*)::int, COALESCE(SUM(byte_size), 0), MAX(expires_at), MAX(last_activity_at)
FROM mock_session_state
WHERE expires_at > CURRENT_TIMESTAMP
GROUP BY tenant_slug, project_slug, version_label, session_token
ON CONFLICT (tenant_slug, project_slug, version_label, session_token) DO NOTHING;

INSERT INTO mock_session_resource (session_id, collection_path, resource_id, resource, byte_size)
SELECT s.id, r.collection_path, r.resource_id, r.resource, r.byte_size
FROM mock_session_state r
JOIN mock_session s
  ON s.tenant_slug = r.tenant_slug
 AND s.project_slug = r.project_slug
 AND s.version_label = r.version_label
 AND s.session_token = r.session_token
WHERE r.expires_at > CURRENT_TIMESTAMP
ON CONFLICT (session_id, collection_path, resource_id) DO NOTHING;

INSERT INTO mock_session_slots (slot_id, session_count)
VALUES (1, (SELECT COUNT(*) FROM mock_session))
ON CONFLICT (slot_id) DO UPDATE SET session_count = EXCLUDED.session_count;

DROP TABLE IF EXISTS mock_session_state;

-- Keep mock_session_slots.session_count equal to the number of mock_session rows. Statement-level
-- with transition tables, so a batched sweep updates the slot row once per statement.
CREATE OR REPLACE FUNCTION mock_session_slots_count() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    delta BIGINT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT COUNT(*) INTO delta FROM new_sessions;
    ELSE
        SELECT -COUNT(*) INTO delta FROM old_sessions;
    END IF;
    IF delta <> 0 THEN
        UPDATE apiome.mock_session_slots
        SET session_count = GREATEST(session_count + delta, 0)
        WHERE slot_id = 1;
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS mock_session_slots_on_insert ON mock_session;
CREATE TRIGGER mock_session_slots_on_insert
    AFTER INSERT ON mock_session
    REFERENCING NEW TABLE AS new_sessions
    FOR EACH STATEMENT EXECUTE FUNCTION mock_session_slots_count();

DROP TRIGGER IF EXISTS mock_session_slots_on_delete ON mock_session;
CREATE TRIGGER mock_session_slots_on_delete
    AFTER DELETE ON mock_session
    REFERENCING OLD TABLE AS old_sessions
    FOR EACH STATEMENT EXECUTE FUNCTION mock_session_slots_count();

COMMENT ON TABLE mock_session IS
  'One row per X-Mock-Session namespace: sliding expiry, last activity and size totals (#7209, DBP-1.26)';
COMMENT ON COLUMN mock_session.session_token IS
  'Opaque client token from the X-Mock-Session request header';
COMMENT ON COLUMN mock_session.expires_at IS
  'Sliding TTL expiry; the session and its resources are gone past this instant (swept periodically)';
COMMENT ON COLUMN mock_session.last_activity_at IS
  'Last time the expiry was extended; apiome-mock touches it at most about once a minute';
COMMENT ON COLUMN mock_session.resource_count IS
  'Number of mock_session_resource rows, for the per-session resource cap';
COMMENT ON COLUMN mock_session.total_bytes IS
  'Sum of mock_session_resource.byte_size, for the per-session size cap';
COMMENT ON TABLE mock_session_resource IS
  'Session-scoped mock CRUD resources; cascade with their mock_session row (#7209)';
COMMENT ON COLUMN mock_session_resource.collection_path IS
  'OpenAPI collection path template without trailing slash, e.g. /pets';
COMMENT ON COLUMN mock_session_resource.resource_id IS
  'String form of the resource id (path param value)';
COMMENT ON COLUMN mock_session_resource.byte_size IS
  'UTF-8 JSON byte length of resource, used for per-session size caps';
COMMENT ON TABLE mock_session_counter IS
  'Last allocated integer id (or sequence call number) per session collection (#7209)';
COMMENT ON TABLE mock_session_slots IS
  'Single-row count of mock_session rows, kept by trigger; enforces the global session cap (#7209)';
