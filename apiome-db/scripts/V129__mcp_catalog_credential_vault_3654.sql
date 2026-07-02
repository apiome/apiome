-- External MCP Catalog (#3654, V2-MCP-15.4 / MCAT-1.4): the encrypted credential vault.
--
-- Connecting to a protected MCP server means holding a secret (a bearer token, a custom header
-- value, an OAuth2 token set, or an environment-variable bundle). `mcp_endpoint_credentials` is
-- where that secret lives — and it lives there as ciphertext only. There is deliberately NO
-- plaintext secret column on this table: the secret material is sealed by the application layer
-- (envelope encryption, MCAT-6.2 / #3678) and only the resulting `encrypted_payload` (BYTEA) is
-- ever persisted. The database stores opaque bytes; it never sees, and cannot reconstruct, a token.
--
-- `auth_type` records which authorization scheme the endpoint uses, per the MCP authorization spec
-- (https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization):
--   * none   — no credential (public server). `encrypted_payload` is NULL for this type.
--   * bearer — a bearer token sent as `Authorization: Bearer <token>` (MCAT-6.1).
--   * header — an arbitrary header (name + value) the client must send.
--   * oauth2 — an OAuth2 token set; the non-secret discovery/registration metadata (authorize,
--              token, registration endpoints, scopes, resource indicator) lives in `oauth_metadata`
--              as cleartext JSONB, while the tokens themselves are sealed in `encrypted_payload`.
--   * env    — an environment-variable bundle (for future stdio transports, MCAT-6.1).
--
-- `key_version` tags which key-generation sealed `encrypted_payload`, so the app can rotate the
-- master/data key and still decrypt older rows (envelope-encryption key rotation, MCAT-6.2). It is
-- NULL exactly when there is no ciphertext (i.e. `auth_type = 'none'`).
--
-- `last_refreshed_at` is when the secret was last (re)sealed/rotated — distinct from `updated_at`,
-- which moves on any row change (e.g. editing `oauth_metadata`).
--
-- One credential row per endpoint (acceptance criterion): `endpoint_id` is UNIQUE and the row is
-- cascade-deleted with its endpoint (and thus its tenant) — purging credentials on endpoint
-- teardown (MCAT-6.4). Unlike the immutable version/change tables (V128), credentials are mutable:
-- they get rotated and re-sealed, so this table carries `updated_at` and the usual touch trigger.
--
-- Rollback notes: this migration is additive (one new table, its index, an updated_at trigger
-- function + trigger, and comments). To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_endpoint_credentials CASCADE;   -- also drops its index + trigger
--   DROP FUNCTION IF EXISTS apiome.update_mcp_endpoint_credentials_updated_at();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- mcp_endpoint_credentials — one encrypted credential per MCP endpoint. Ciphertext only.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcp_endpoint_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Owning endpoint; exactly one credential row per endpoint, reaped on endpoint/tenant teardown.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- Which authorization scheme this endpoint uses (per the MCP authorization spec).
    auth_type VARCHAR(32) NOT NULL DEFAULT 'none',

    -- The sealed secret material (envelope-encrypted by the app layer). NULL only for auth_type 'none'.
    encrypted_payload BYTEA,

    -- Key-generation that sealed encrypted_payload, enabling key rotation. NULL iff no ciphertext.
    key_version INTEGER,

    -- Non-secret OAuth2 discovery/registration metadata: authorize/token/registration endpoints,
    -- scopes, resource indicator, etc. Cleartext by design — it contains no secret material.
    oauth_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- When the secret was last (re)sealed/rotated; distinct from updated_at (any-change touch).
    last_refreshed_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Exactly one credential row per endpoint. The btree backing this constraint also serves the
    -- by-endpoint lookup the loader uses, so no separate index is created.
    CONSTRAINT mcp_endpoint_credentials_endpoint_unique UNIQUE (endpoint_id),

    -- auth_type must be one of the five supported schemes.
    CONSTRAINT mcp_endpoint_credentials_auth_type_check
        CHECK (auth_type IN ('none', 'bearer', 'header', 'oauth2', 'env')),

    -- Ciphertext and its key version travel together: either both present, or both absent. The
    -- 'none' scheme carries no secret (both NULL); every other scheme must carry sealed bytes.
    CONSTRAINT mcp_endpoint_credentials_payload_key_consistent
        CHECK (
            (encrypted_payload IS NULL AND key_version IS NULL)
            OR (encrypted_payload IS NOT NULL AND key_version IS NOT NULL)
        ),

    -- The 'none' scheme means no credential at all; every other scheme must carry ciphertext.
    CONSTRAINT mcp_endpoint_credentials_auth_payload_check
        CHECK (
            (auth_type = 'none' AND encrypted_payload IS NULL)
            OR (auth_type <> 'none' AND encrypted_payload IS NOT NULL)
        )
);

COMMENT ON TABLE mcp_endpoint_credentials IS 'Encrypted, one-per-endpoint credential vault for protected MCP servers; stores ciphertext only (#3654, V2-MCP-15.4)';
COMMENT ON COLUMN mcp_endpoint_credentials.id IS 'Unique identifier for the credential row';
COMMENT ON COLUMN mcp_endpoint_credentials.endpoint_id IS 'Owning mcp_endpoints row (UNIQUE: one credential per endpoint); cascade-deleted with the endpoint/tenant';
COMMENT ON COLUMN mcp_endpoint_credentials.auth_type IS 'Authorization scheme: none, bearer, header, oauth2, or env (per the MCP authorization spec)';
COMMENT ON COLUMN mcp_endpoint_credentials.encrypted_payload IS 'App-layer envelope-encrypted secret material (ciphertext only); NULL for auth_type none';
COMMENT ON COLUMN mcp_endpoint_credentials.key_version IS 'Key-generation that sealed encrypted_payload, enabling key rotation; NULL iff no ciphertext';
COMMENT ON COLUMN mcp_endpoint_credentials.oauth_metadata IS 'Non-secret OAuth2 metadata (authorize/token/registration endpoints, scopes, resource indicator); cleartext by design';
COMMENT ON COLUMN mcp_endpoint_credentials.last_refreshed_at IS 'When the secret was last (re)sealed/rotated; distinct from updated_at';
COMMENT ON COLUMN mcp_endpoint_credentials.created_at IS 'Timestamp when the credential row was created';
COMMENT ON COLUMN mcp_endpoint_credentials.updated_at IS 'Timestamp when the credential row was last updated (maintained by trigger)';

-- ---------------------------------------------------------------------------------------------------
-- updated_at maintenance: credentials are mutable (rotated/re-sealed), so a BEFORE UPDATE trigger
-- keeps updated_at current on every change — the established convention (cf. V010).
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_mcp_endpoint_credentials_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_mcp_endpoint_credentials_updated_at ON mcp_endpoint_credentials;
CREATE TRIGGER trigger_update_mcp_endpoint_credentials_updated_at
    BEFORE UPDATE ON mcp_endpoint_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_mcp_endpoint_credentials_updated_at();

COMMENT ON FUNCTION update_mcp_endpoint_credentials_updated_at() IS 'Trigger function that refreshes updated_at on any change to an mcp_endpoint_credentials row (#3654)';
