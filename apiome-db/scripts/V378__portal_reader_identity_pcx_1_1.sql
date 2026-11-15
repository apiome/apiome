-- Portal reader identity, magic-link sign-in and reader sessions — PCX-1.1 (#5889).
--
-- Browse has served public versions only: an external consumer of a private API could reach it
-- only through a *workspace* API key, so every consumer cost a workspace credential and a human
-- hand-off. This migration adds a **reader** principal without a second identity system:
--
--   portal_memberships     — a user's standing as a reader of one tenant's portal.
--   portal_magic_links     — one-time sign-in tokens mailed to a reader (15-minute expiry).
--   portal_reader_sessions — the opaque, tenant-bound session Browse holds in a cookie.
--
-- Four rules shape the schema:
--
--   1. **A reader is a user.** The person is a row in the existing ``users`` table; what is new is
--      the membership that makes them a reader of a tenant, unique per tenant and user. A reader
--      membership is **not** a ``tenant_users`` row: it grants no workspace access of any kind.
--
--   2. **Secrets are never stored.** A magic link stores a bcrypt hash and a short lookup prefix
--      (the API-key scheme); a session stores the SHA-256 of a 256-bit random token, which is
--      enough for a secret that is never chosen by a person and lets every Browse request find its
--      session through one unique index instead of a bcrypt comparison.
--
--   3. **A token is burned once.** ``consumed_at`` is set in the exchange transaction; a second
--      exchange of the same token is refused, as is one after ``expires_at``.
--
--   4. **Revocation is a stamp, never a delete.** A revoked membership or session keeps its row
--      (``revoked_at``) so the access audit and the readers admin page (PCX-1.6) can still explain
--      it. Membership state and its timestamps are kept consistent by CHECK constraints.
--
-- Sessions keep the **user-agent family only** (``Chrome``, ``Firefox``, …) — never the full
-- User-Agent string and never an IP address.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.portal_reader_sessions;
--   DROP TABLE IF EXISTS apiome.portal_magic_links;
--   DROP TABLE IF EXISTS apiome.portal_memberships;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- portal_memberships — a user's standing as a reader of one tenant's portal.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portal_memberships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    status VARCHAR(16) NOT NULL DEFAULT 'invited'
        CONSTRAINT portal_memberships_status_check
            CHECK (status IN ('invited', 'active', 'revoked')),

    -- How the membership came to be. PCX-1.1 writes ``magic_link``; ``invite`` (PCX-1.6),
    -- ``domain`` (PCX-1.2) and ``sso`` (PCX-1.5) are reserved for the tickets that add them.
    source VARCHAR(16) NOT NULL
        CONSTRAINT portal_memberships_source_check
            CHECK (source IN ('invite', 'magic_link', 'domain', 'sso')),

    invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
    activated_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 1: one membership per tenant and user.
    CONSTRAINT portal_memberships_tenant_user_unique UNIQUE (tenant_id, user_id),

    -- Rule 4: an active membership says when it was activated; a revoked one says when it was
    -- revoked; an invited one carries neither revocation stamp.
    CONSTRAINT portal_memberships_activation_check
        CHECK (status <> 'active' OR activated_at IS NOT NULL),
    CONSTRAINT portal_memberships_revocation_check
        CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);

-- A user's reader memberships across tenants.
CREATE INDEX IF NOT EXISTS idx_portal_memberships_user
    ON portal_memberships (user_id);

-- A tenant's readers by status (the PCX-1.6 admin page's read).
CREATE INDEX IF NOT EXISTS idx_portal_memberships_tenant_status
    ON portal_memberships (tenant_id, status);

COMMENT ON TABLE portal_memberships IS
    'A user''s standing as a reader of one tenant''s Browse portal (PCX-1.1, #5889); grants no workspace access';
COMMENT ON COLUMN portal_memberships.status IS 'invited | active | revoked';
COMMENT ON COLUMN portal_memberships.source IS 'invite | magic_link | domain | sso — how the membership was created';
COMMENT ON COLUMN portal_memberships.invited_by IS 'The member who invited the reader, for an invite membership';
COMMENT ON COLUMN portal_memberships.activated_at IS 'When the reader first signed in; set whenever status is active';
COMMENT ON COLUMN portal_memberships.revoked_at IS 'When the membership was revoked; set exactly while status is revoked';

-- ---------------------------------------------------------------------------------------------------
-- portal_magic_links — one-time sign-in tokens.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portal_magic_links (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    membership_id UUID NOT NULL REFERENCES portal_memberships(id) ON DELETE CASCADE,

    -- Rule 2: a short public prefix finds the row; the bcrypt hash proves the secret.
    lookup_prefix VARCHAR(32) NOT NULL
        CONSTRAINT portal_magic_links_lookup_prefix_unique UNIQUE,
    token_hash VARCHAR(255) NOT NULL,

    -- A relative Browse path the reader returns to after signing in; validated by apiome-rest.
    return_to VARCHAR(1024),

    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    -- Rule 3: set once, in the exchange transaction.
    consumed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portal_magic_links_membership
    ON portal_magic_links (membership_id, created_at DESC);

COMMENT ON TABLE portal_magic_links IS 'One-time Browse sign-in tokens mailed to a reader (PCX-1.1, #5889)';
COMMENT ON COLUMN portal_magic_links.lookup_prefix IS 'Public lookup prefix of the token; never the secret';
COMMENT ON COLUMN portal_magic_links.token_hash IS 'bcrypt hash of the token secret';
COMMENT ON COLUMN portal_magic_links.return_to IS 'Relative Browse path to return to after sign-in';
COMMENT ON COLUMN portal_magic_links.expires_at IS 'The token is refused after this instant (15 minutes after issue)';
COMMENT ON COLUMN portal_magic_links.consumed_at IS 'When the token was exchanged for a session; a used token is refused';

-- ---------------------------------------------------------------------------------------------------
-- portal_reader_sessions — the opaque, tenant-bound reader session.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portal_reader_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    membership_id UUID NOT NULL REFERENCES portal_memberships(id) ON DELETE CASCADE,

    -- Rule 2: SHA-256 hex of the 256-bit session token.
    token_hash CHAR(64) NOT NULL
        CONSTRAINT portal_reader_sessions_token_hash_unique UNIQUE,

    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,

    -- Browser family only (``Chrome``, ``Firefox``, ``Safari``, ``Edge``, ``Other``).
    user_agent_family VARCHAR(32),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portal_reader_sessions_membership
    ON portal_reader_sessions (membership_id, created_at DESC);

COMMENT ON TABLE portal_reader_sessions IS
    'Opaque tenant-bound reader sessions Browse forwards as Authorization: Reader <token> (PCX-1.1, #5889)';
COMMENT ON COLUMN portal_reader_sessions.token_hash IS 'SHA-256 hex of the session token; the token itself is never stored';
COMMENT ON COLUMN portal_reader_sessions.expires_at IS 'Absolute expiry; the session is refused after it';
COMMENT ON COLUMN portal_reader_sessions.last_seen_at IS 'The latest request the session authenticated';
COMMENT ON COLUMN portal_reader_sessions.revoked_at IS 'When the session was signed out or revoked; refused from the next request';
COMMENT ON COLUMN portal_reader_sessions.user_agent_family IS 'Browser family only, never the full User-Agent';
