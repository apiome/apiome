-- Stateful mock CRUD session store (#4453, SIM-4.1).
--
-- Ephemeral per-session resources keyed by tenant/project/version + X-Mock-Session token.
-- Sliding TTL via expires_at; byte_size supports per-session size caps in apiome-mock.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_session_state (
    tenant_slug VARCHAR(255) NOT NULL,
    project_slug VARCHAR(255) NOT NULL,
    version_label VARCHAR(255) NOT NULL,
    session_token VARCHAR(255) NOT NULL,
    collection_path TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource JSONB NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (
        tenant_slug,
        project_slug,
        version_label,
        session_token,
        collection_path,
        resource_id
    )
);

CREATE INDEX IF NOT EXISTS idx_mock_session_state_expires
    ON mock_session_state (expires_at);

CREATE INDEX IF NOT EXISTS idx_mock_session_state_session
    ON mock_session_state (tenant_slug, project_slug, version_label, session_token);

COMMENT ON TABLE mock_session_state IS
  'Session-scoped mock CRUD resources for X-Mock-Session stateful memory (#4453, SIM-4.1)';
COMMENT ON COLUMN mock_session_state.session_token IS
  'Opaque client token from the X-Mock-Session request header';
COMMENT ON COLUMN mock_session_state.collection_path IS
  'OpenAPI collection path template without trailing slash, e.g. /pets';
COMMENT ON COLUMN mock_session_state.resource_id IS
  'String form of the resource id (path param value)';
COMMENT ON COLUMN mock_session_state.byte_size IS
  'UTF-8 JSON byte length of resource, used for per-session size caps';
COMMENT ON COLUMN mock_session_state.expires_at IS
  'Sliding TTL expiry; rows past this instant are treated as gone';
