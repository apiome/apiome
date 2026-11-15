-- Project presence & element soft locks — COL-4.1 (#4525).
--
-- Two designers editing one project could silently clobber each other and never see each other.
-- Full CRDT co-editing is deliberately deferred; this is the pragmatic step before it, and it is
-- advisory: a lock informs and asks, it never denies.
--
--   project_presence — one row per open tab ("session") viewing a project: who, where
--                      (``view``), and when it last heartbeated.
--   element_locks    — at most one advisory lock per element of a project, held by one session,
--                      with an optional pending takeover request.
--
-- Rules:
--
--   1. **Liveness is a lease, not a flag.** A row is alive while ``last_seen_at`` / ``expires_at``
--      is in the future; clients heartbeat to renew it. A crashed browser or a dropped socket
--      therefore frees its lock on its own — there is no state a disconnect can leave stuck. A
--      clean disconnect deletes the rows at once; the lease is the backstop. Readers always filter
--      on the lease, so a stale row that has not been swept yet is invisible.
--   2. **One holder per element.** ``UNIQUE (project_id, element_key)``; taking a lock another
--      session still holds is a takeover (request, then steal), never a second row.
--   3. **Ephemeral.** Nothing here is history; rows go with their tenant, project, or user.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.element_locks;
--   DROP TABLE IF EXISTS apiome.project_presence;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS project_presence (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id VARCHAR(64) NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    view VARCHAR(64) NOT NULL DEFAULT 'project',
    connected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, session_id),
    CHECK (length(btrim(session_id)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_project_presence_seen ON project_presence (project_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS element_locks (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    element_key VARCHAR(200) NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    holder_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    holder_session_id VARCHAR(64) NOT NULL,
    acquired_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    takeover_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    takeover_session_id VARCHAR(64),
    takeover_requested_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (project_id, element_key),
    CHECK (length(btrim(element_key)) > 0),
    CHECK ((takeover_session_id IS NULL) = (takeover_requested_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_element_locks_expiry ON element_locks (expires_at);
CREATE INDEX IF NOT EXISTS idx_element_locks_holder ON element_locks (project_id, holder_session_id);
