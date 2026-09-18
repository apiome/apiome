-- Agent key kind + scopes — AGX-3.1 (#4537).
--
-- An agent that calls a tenant's API through a managed MCP toolset holds an Apiome *agent key*.
-- It is an `api_keys` row, but not a general-purpose one: it is bound to one toolset, it may only
-- call the tools on an explicit allowlist, and it can expire. Per-agent identity is also what
-- quotas (AGX-3.2) and usage analytics (AGX-3.3 / AGX-3.4) will hang off. This migration extends
-- `api_keys` instead of adding a table, so agent keys share the existing hashing, prefix lookup,
-- `enabled` toggle, soft-delete revocation and `expires_at`:
--
--   kind            'workspace' (every existing row, via the default) | 'agent'
--   toolset_id      the agent toolset the key is bound to (agent keys only)
--   tool_allowlist  JSON array of MCP tool names the key may see and call (agent keys only)
--   expires_at      already present since V006; agent keys use it unchanged
--
-- Five rules shape the schema:
--
--   1. **The two kinds are exclusive.** An agent key has a toolset and an allowlist; a workspace
--      key has neither. `api_keys_agent_binding_ck` enforces both directions, so a workspace key
--      can never be half-converted into an agent key, or the reverse.
--
--   2. **An agent key is not a REST credential.** apiome-rest's `validate_api_key` (and the
--      apiome-mock private-mock check) only accept `kind = 'workspace'`. As defence in depth an
--      agent key also carries exactly the scope `agent:invoke`, which no REST route allowlists
--      (see apiome-rest `app.auth`), so even a validator that forgot the kind filter would refuse
--      it on every route. A workspace key may never hold that scope.
--
--   3. **The allowlist is explicit.** A JSON array of MCP tool names in the AGX-1.1 grammar
--      (`^[A-Za-z0-9_-]{1,64}$`, `app.tool_projection.TOOL_NAME_PATTERN`), at most 1024 of them.
--      There is no wildcard: an empty array permits nothing. The tools a key may use are the
--      toolset's enabled tools (AGX-1.2) intersected with this list, computed per request by the
--      MCP agent-access middleware in apiome-mcp.
--
--   4. **`toolset_id` has no foreign key yet.** `apiome.agent_toolsets` is AGX-1.2 (#4530), which
--      was still open when agent keys shipped (the same situation as V268's
--      `upstream_credentials.toolset_id`). AGX-1.2's migration must revoke or delete agent keys
--      whose toolset does not exist, then add `REFERENCES agent_toolsets(id)`. Until then the MCP
--      middleware fails closed: a key whose toolset cannot be resolved lists and calls nothing.
--
--   5. **Revocation is the existing soft delete.** Revoking sets `deleted_at` (and clears
--      `enabled`); the MCP middleware reads the key on every request, so a revoked or expired key
--      is refused on its next request. Lifecycle actions (create / allowlist edit / revoke) are
--      written to `apiome.access_audit` by apiome-rest, beside every other governance change.
--
-- **No new RBAC resource.** The key-management API is guarded by the existing `api_keys`
-- resource, as V268's upstream-credential API is: an agent key is an API key.
--
-- Rollback notes (reverse carefully in shared environments — revoke agent keys first):
--   DELETE FROM apiome.api_keys WHERE kind = 'agent';
--   DROP INDEX IF EXISTS apiome.idx_api_keys_agent_toolset;
--   DROP INDEX IF EXISTS apiome.idx_api_keys_agent_prefix;
--   ALTER TABLE apiome.api_keys
--     DROP CONSTRAINT IF EXISTS api_keys_kind_scopes_ck,
--     DROP CONSTRAINT IF EXISTS api_keys_agent_allowlist_ck,
--     DROP CONSTRAINT IF EXISTS api_keys_agent_binding_ck,
--     DROP CONSTRAINT IF EXISTS api_keys_kind_ck,
--     DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
--   ALTER TABLE apiome.api_keys
--     ADD CONSTRAINT api_keys_scopes_vocab_ck
--     CHECK (scopes <@ ARRAY['*', 'diff:read', 'lint:read']::text[]);
--   ALTER TABLE apiome.api_keys
--     DROP COLUMN IF EXISTS tool_allowlist,
--     DROP COLUMN IF EXISTS toolset_id,
--     DROP COLUMN IF EXISTS kind;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Columns. Existing rows become workspace keys through the default; no row is rewritten.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE api_keys
  ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS toolset_id UUID,
  ADD COLUMN IF NOT EXISTS tool_allowlist JSONB;

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_kind_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_kind_ck
  CHECK (kind IN ('workspace', 'agent'));

-- Rule 1: an agent key has a toolset and an allowlist; a workspace key has neither.
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_agent_binding_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_agent_binding_ck
  CHECK (
    (kind = 'agent' AND toolset_id IS NOT NULL AND tool_allowlist IS NOT NULL)
    OR (kind = 'workspace' AND toolset_id IS NULL AND tool_allowlist IS NULL)
  );

-- Rule 3: a JSON array of at most 1024 MCP tool names. `strict` stops nested arrays from being
-- unwrapped into their elements, so `[["x"]]` is refused rather than read as `["x"]`.
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_agent_allowlist_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_agent_allowlist_ck
  CHECK (
    tool_allowlist IS NULL
    OR (
      jsonb_typeof(tool_allowlist) = 'array'
      AND jsonb_array_length(tool_allowlist) <= 1024
      AND NOT jsonb_path_exists(
        tool_allowlist,
        'strict $[*] ? (@.type() != "string" || !(@ like_regex "^[A-Za-z0-9_-]{1,64}$"))'
      )
    )
  );

-- Rule 2: widen the V177 scope vocabulary by `agent:invoke`, then tie it to the agent kind.
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_vocab_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_vocab_ck
  CHECK (
    scopes <@ ARRAY['*', 'diff:read', 'lint:read', 'agent:invoke']::text[]
  );

ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_kind_scopes_ck;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_kind_scopes_ck
  CHECK (
    (kind = 'agent' AND scopes = ARRAY['agent:invoke']::text[])
    OR (kind = 'workspace' AND NOT ('agent:invoke' = ANY (scopes)))
  );

-- ---------------------------------------------------------------------------------------------------
-- Indexes. The MCP middleware looks an agent key up by prefix on every request, and must find a
-- revoked one too (to say so), which the V006 prefix index excludes (`WHERE deleted_at IS NULL`).
-- ---------------------------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_api_keys_agent_prefix
  ON api_keys (key_prefix)
  WHERE kind = 'agent';

-- Listing a toolset's keys, and AGX-1.2's orphan sweep before it adds the foreign key.
CREATE INDEX IF NOT EXISTS idx_api_keys_agent_toolset
  ON api_keys (tenant_id, toolset_id)
  WHERE kind = 'agent';

-- ---------------------------------------------------------------------------------------------------
-- Documentation.
-- ---------------------------------------------------------------------------------------------------
COMMENT ON COLUMN api_keys.kind IS
  'AGX-3.1 (#4537): workspace = general REST/API key (default); agent = MCP agent key bound to '
  'one toolset and a tool allowlist. apiome-rest only accepts workspace keys as REST credentials.';

COMMENT ON COLUMN api_keys.toolset_id IS
  'AGX-3.1 (#4537): the agent toolset (AGX-1.2 agent_toolsets.id) an agent key is bound to; NULL '
  'for workspace keys. No FK until that table exists; AGX-1.2 adds it after removing orphans.';

COMMENT ON COLUMN api_keys.tool_allowlist IS
  'AGX-3.1 (#4537): JSON array of MCP tool names an agent key may list and call; NULL for '
  'workspace keys. Permitted tools = the toolset''s enabled tools intersected with this list. '
  'No wildcard: an empty array permits nothing.';

COMMENT ON COLUMN api_keys.scopes IS
  'Machine-key capability scopes (#4473, CTG-2.3; AGX-3.1 #4537). ''*'' = full access (default). '
  'CI tokens use diff:read and/or lint:read only — no write access. Agent keys carry exactly '
  'agent:invoke, which no REST route accepts. Enforced in apiome-rest auth allowlist.';
