-- Upstream auth vault — AGX-2.2 (#4534).
--
-- Agents must never hold real API credentials. When an agent calls a tenant's API through a
-- managed MCP toolset (AGX-2.1, #4533), the platform injects the tenant's upstream credential
-- server-side; the agent only ever holds a scoped Apiome agent key. This migration is the vault
-- that credential lives in, plus the ledger that records every time one is used.
--
--   upstream_credentials     — one sealed credential per (tenant, toolset, upstream server URL).
--   upstream_credential_uses — append-only, metadata-only record of each use.
--
-- Five rules shape the schema:
--
--   1. **The secret is ciphertext, and only ciphertext.** `encrypted_secret` is an
--      envelope-encrypted blob (AES-256-GCM data key wrapped by a versioned master key held in
--      the environment; see app.envelope_crypto, the same scheme as the V129 MCP vault and the
--      V256 registry vault, sealed under its own vault magic `OUCV`). `key_version` records which
--      master key sealed it. For `basic` the username is sealed too: it is half of the
--      credential. There is no column a plaintext secret could be written to, and the database —
--      or a backup of it — cannot reconstruct one.
--
--   2. **A credential is bound to a toolset and a server URL.** It is only ever injected into a
--      request whose URL sits under `server_url` (same https origin, path on a segment boundary);
--      the application checks that on every use. `server_url` is https-only and carries no
--      userinfo, query or fragment, enforced here as well as in the application. One credential
--      per (tenant, toolset, server URL), so resolving one is never ambiguous.
--
--      `toolset_id` has **no foreign key yet.** `apiome.agent_toolsets` is AGX-1.2 (#4530), which
--      was still open when this vault shipped; the vault was built in parallel, as the roadmap
--      planned. AGX-1.2's migration must first delete rows whose toolset does not exist, then
--      add `REFERENCES agent_toolsets(id) ON DELETE CASCADE`. Until then every read and write is
--      scoped by `tenant_id`, so a credential is never visible across tenants, and nothing
--      reads a credential until the AGX-2.1 proxy exists.
--
--   3. **Only the placement is described in the clear.** `kind` (`apiKey` | `bearer` | `basic`,
--      OpenAPI's vocabulary) and, for `apiKey`, where it goes (`header` | `query`) and under
--      what name. Those are shapes, not secrets. The name is held to the RFC 9110 token grammar,
--      so a stored name can never split a request. There is deliberately no fingerprint of the
--      secret: a digest of a low-entropy basic-auth password can be brute-forced offline.
--
--   4. **Rotation replaces the secret in place.** A rotate is one UPDATE of `encrypted_secret` /
--      `key_version` on the same row, so a concurrent reader sees either the old secret or the
--      new one, never neither. The row id, the binding and the placement survive a rotation.
--
--   5. **Use is audited, and only as metadata.** `upstream_credential_uses` records which
--      credential, which toolset, when, and whether it could be opened. It holds no secret and
--      no request data. `credential_id` has no foreign key, so the history outlives a deleted
--      credential. Rows are write-once (the V128 `mcp_forbid_row_mutation()` guard); DELETE
--      stays open to the tenant cascade and to the retention purge below.
--
-- Mutations (create / rotate / delete) are recorded in `apiome.access_audit` by the application,
-- beside every other governance change, not here. This ledger is the high-volume use record.
--
-- **No new RBAC resource.** The API is guarded by the existing `api_keys` resource: an upstream
-- credential is the other half of an agent's access, and AGX-3.1's agent keys are `api_keys`
-- too. The same argument V254, V255 and V256 made.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP FUNCTION IF EXISTS apiome.purge_upstream_credential_uses(INTEGER);
--   DROP TABLE IF EXISTS apiome.upstream_credential_uses;
--   DROP TABLE IF EXISTS apiome.upstream_credentials;
-- (The V128 guard function apiome.mcp_forbid_row_mutation() is shared — do not drop it here.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- upstream_credentials — the sealed credential a toolset presents to one upstream server.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS upstream_credentials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 2: the toolset this credential serves. No FK until AGX-1.2 creates agent_toolsets.
    toolset_id UUID NOT NULL,

    -- Rule 2: the only server this credential is ever sent to. Normalized by the application
    -- (lower-case host, no default port, no trailing slash); the CHECK is the backstop.
    server_url TEXT NOT NULL
        CONSTRAINT upstream_credentials_server_url_check
            CHECK (server_url ~ '^https://[^/?#@[:space:]]+(/[^?#[:space:]]*)?$'),
    CONSTRAINT upstream_credentials_server_url_length_check
        CHECK (char_length(server_url) <= 2048),

    -- Rule 3: how the secret is presented, in OpenAPI's security-scheme vocabulary.
    kind VARCHAR(16) NOT NULL
        CONSTRAINT upstream_credentials_kind_check
            CHECK (kind IN ('apiKey', 'bearer', 'basic')),
    api_key_in VARCHAR(8),
    api_key_name VARCHAR(128),
    CONSTRAINT upstream_credentials_placement_check CHECK (
        (
            kind = 'apiKey'
            AND api_key_in IN ('header', 'query')
            AND api_key_name ~ '^[!#$%&''*+.^_`|~0-9A-Za-z-]+$'
        )
        OR (kind <> 'apiKey' AND api_key_in IS NULL AND api_key_name IS NULL)
    ),

    -- Rule 1: ciphertext only, plus the master-key version that sealed it.
    encrypted_secret BYTEA NOT NULL,
    key_version INTEGER NOT NULL
        CONSTRAINT upstream_credentials_key_version_check CHECK (key_version >= 1),

    -- Provenance. ON DELETE SET NULL: a departing user must not take a toolset's access with them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rotated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Rule 4: NULL until the first rotation.
    rotated_at TIMESTAMPTZ
);

-- Rule 2, enforced: one credential per (tenant, toolset, server). Also the index a use resolves
-- through (tenant_id, toolset_id prefix).
CREATE UNIQUE INDEX IF NOT EXISTS idx_upstream_credentials_binding
    ON upstream_credentials (tenant_id, toolset_id, server_url);

COMMENT ON TABLE upstream_credentials IS
    'AGX-2.2 (#4534): a tenant''s upstream API credential for one agent toolset and one server '
    'URL, stored as ciphertext only. Write-only through the API: no route returns the secret.';

COMMENT ON COLUMN upstream_credentials.toolset_id IS
    'The agent toolset (AGX-1.2 agent_toolsets.id) this credential serves. No FK until that table '
    'exists; AGX-1.2 adds it after deleting orphans.';

COMMENT ON COLUMN upstream_credentials.server_url IS
    'The only upstream the credential is injected toward: https origin plus optional base path. '
    'A request URL must share the origin and sit under the path on a segment boundary.';

COMMENT ON COLUMN upstream_credentials.encrypted_secret IS
    'Envelope-encrypted secret payload (app.envelope_crypto, vault magic OUCV): {"value"} for '
    'apiKey, {"token"} for bearer, {"username","password"} for basic. Never plaintext.';

COMMENT ON COLUMN upstream_credentials.key_version IS
    'Which configured master key sealed this row. Bound into the GCM AAD, so a row cannot be '
    're-tagged to another version.';

COMMENT ON COLUMN upstream_credentials.rotated_at IS
    'When the secret was last replaced in place (NULL until the first rotation).';

-- ---------------------------------------------------------------------------------------------------
-- upstream_credential_uses — which credential was opened for which toolset, and when.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS upstream_credential_uses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 5: no FK, so the history survives the credential's deletion.
    credential_id UUID NOT NULL,
    toolset_id UUID NOT NULL,

    -- injected: the secret was opened and handed to the proxy for a bound request.
    -- unavailable: the bound credential could not be opened (its master key is not configured,
    -- or the blob fails authentication), so the call failed closed instead of going out bare.
    outcome VARCHAR(16) NOT NULL
        CONSTRAINT upstream_credential_uses_outcome_check
            CHECK (outcome IN ('injected', 'unavailable')),

    used_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- "When was this credential last used" (the list read) and one credential's history.
CREATE INDEX IF NOT EXISTS idx_upstream_credential_uses_credential
    ON upstream_credential_uses (credential_id, used_at DESC);

-- A tenant's use history, newest first, and the retention purge.
CREATE INDEX IF NOT EXISTS idx_upstream_credential_uses_tenant
    ON upstream_credential_uses (tenant_id, used_at DESC);

COMMENT ON TABLE upstream_credential_uses IS
    'AGX-2.2 (#4534): append-only, metadata-only record of each upstream credential use — which '
    'credential, which toolset, when, and whether it could be opened. Never a secret.';

COMMENT ON COLUMN upstream_credential_uses.credential_id IS
    'The credential used. No FK: the history outlives the credential.';

COMMENT ON COLUMN upstream_credential_uses.outcome IS
    'injected | unavailable (the credential could not be opened and the call failed closed)';

-- Rule 5: write-once. DELETE stays available to the tenant cascade and the purge below.
DROP TRIGGER IF EXISTS trigger_upstream_credential_uses_immutable ON upstream_credential_uses;
CREATE TRIGGER trigger_upstream_credential_uses_immutable
    BEFORE UPDATE ON upstream_credential_uses
    FOR EACH ROW
    EXECUTE FUNCTION mcp_forbid_row_mutation();

-- ---------------------------------------------------------------------------------------------------
-- Retention: one row per agent call adds up, so the ledger is bounded by age. Nothing schedules
-- this yet; AGX-3.3 (#4539) owns per-tier retention for agent traffic.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION purge_upstream_credential_uses(p_retention_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    v_purged INTEGER;
    v_cutoff TIMESTAMPTZ := CURRENT_TIMESTAMP - (GREATEST(p_retention_days, 0) * INTERVAL '1 day');
BEGIN
    DELETE FROM apiome.upstream_credential_uses WHERE used_at < v_cutoff;
    GET DIAGNOSTICS v_purged = ROW_COUNT;
    RETURN v_purged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION purge_upstream_credential_uses(INTEGER) IS
    'Hard-delete upstream credential use records older than p_retention_days (default 90). '
    'Returns the number of purged rows (AGX-2.2, #4534).';
