-- Tool selection & curation model — AGX-1.2 (#4530).
--
-- Switching on Agent Access for a published version must not hand an agent every operation the
-- spec contains: a `DELETE /users/{id}` would become callable the moment access is enabled. This
-- migration is the per-tenant curation layer that decides which operations an agent toolset
-- exposes:
--
--   agent_toolsets       — one toolset per published version that has Agent Access.
--   agent_toolset_tools  — one row per callable operation of that version: exposed or not.
--
-- Five rules shape the schema:
--
--   1. **One toolset per version.** `version_id` is unique, so "the toolset of version X" is never
--      ambiguous. The application only creates a toolset for a *published*, undeleted version of a
--      project in the caller's tenant (published versions are immutable, V083, so the operation
--      set seeded below cannot drift). `tenant_id` is denormalized from version → project so every
--      read is tenant-scoped without a join, and so the AGX-2.2 / AGX-3.1 foreign keys below can
--      bind (tenant, toolset) together.
--
--   2. **`target` is `prod` or `mock`.** Where AGX-2.1 sends tool calls; AGX-2.4 (mock-target mode,
--      `apiome_mcp.mock_target.InvocationTarget`) consumes it. Default `prod`.
--
--   3. **Tool rows reference operations by canonical key.** `operation_key` is the AGX-1.1
--      compiler's operation reference (`GET /pets/{id}`, `Query.user`), the value
--      `app.mcp_tool_mapping.compile_mcp_tools(exposed=…)` takes. `tool_name` is the compiled MCP
--      tool name, recorded at seed time so the MCP agent runtime can read a toolset's enabled
--      tools without recompiling the spec. Names are derived over every callable operation, so
--      curation never renames a tool (AGX-1.1's collision-stable guarantee).
--
--   4. **Safe by default: reads on, writes opt-in.** `write_op` marks a mutating operation
--      (anything but GET/HEAD, or a GraphQL query, as classified by the application). Seeding
--      enables reads and leaves writes off. A write op may only be enabled with an explicit
--      confirmation, which is recorded on the row (`write_confirmed_by` / `write_confirmed_at`):
--      `agent_toolset_tools_write_confirmed_ck` makes an enabled-but-unconfirmed write op
--      unrepresentable, so even a direct SQL write cannot skip the confirmation. Disabling a write
--      op clears the confirmation, so re-enabling it needs a fresh one.
--
--   5. **Changes are audited by the application** in `apiome.access_audit`
--      (`agent.toolset.create|update|delete`, `agent.toolset.tool.update`), beside every other
--      governance change, not here.
--
-- **Handoffs closed.** V268 (`upstream_credentials.toolset_id`, AGX-2.2) and V269
-- (`api_keys.toolset_id`, AGX-3.1) were shipped before this table existed and carry no foreign key.
-- No row in either can reference a toolset that exists yet, so this migration deletes those
-- orphans, then adds composite `(tenant_id, toolset_id)` foreign keys with `ON DELETE CASCADE`:
-- a credential or agent key can only bind to a toolset of its own tenant, and deleting a toolset
-- removes its credentials and agent keys (an agent key without its toolset could never
-- authenticate anyway). `upstream_credential_uses` keeps its history: it has no foreign key.
--
-- **No new RBAC resource.** The toolset API is guarded by the existing `api_keys` resource, as the
-- AGX-2.2 credential and AGX-3.1 agent-key APIs are: the three together are one agent's access.
--
-- Rollback notes (reverse carefully in shared environments):
--   ALTER TABLE apiome.api_keys DROP CONSTRAINT IF EXISTS api_keys_agent_toolset_fk;
--   ALTER TABLE apiome.upstream_credentials
--     DROP CONSTRAINT IF EXISTS upstream_credentials_toolset_fk;
--   DROP TABLE IF EXISTS apiome.agent_toolset_tools;
--   DROP TABLE IF EXISTS apiome.agent_toolsets;
-- (Deleted orphan credentials and agent keys are not restored.)

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- agent_toolsets — Agent Access for one published version.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_toolsets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 1: one toolset per version.
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- Whether the toolset serves agents at all. A disabled toolset exposes nothing.
    enabled BOOLEAN NOT NULL DEFAULT true,

    -- Rule 2: where tool calls go.
    target VARCHAR(8) NOT NULL DEFAULT 'prod'
        CONSTRAINT agent_toolsets_target_ck CHECK (target IN ('prod', 'mock')),

    -- Provenance. ON DELETE SET NULL: a departing user must not take a toolset with them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT agent_toolsets_version_uq UNIQUE (version_id),
    -- The target of the composite foreign keys below.
    CONSTRAINT agent_toolsets_tenant_id_uq UNIQUE (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS idx_agent_toolsets_tenant
    ON agent_toolsets (tenant_id, created_at DESC);

COMMENT ON TABLE agent_toolsets IS
    'AGX-1.2 (#4530): Agent Access for one published version — which of its operations an agent '
    'may call is in agent_toolset_tools. One toolset per version.';

COMMENT ON COLUMN agent_toolsets.version_id IS
    'The published version (versions.id) whose operations this toolset exposes. Unique.';

COMMENT ON COLUMN agent_toolsets.enabled IS
    'Whether the toolset serves agents at all; a disabled toolset exposes no tools.';

COMMENT ON COLUMN agent_toolsets.target IS
    'Where tool calls are sent: prod (the real upstream) or mock (apiome-mock). Consumed by '
    'AGX-2.4 mock-target mode.';

-- ---------------------------------------------------------------------------------------------------
-- agent_toolset_tools — per-operation exposure decisions.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_toolset_tools (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    toolset_id UUID NOT NULL REFERENCES agent_toolsets(id) ON DELETE CASCADE,

    -- Rule 3: the AGX-1.1 operation reference and its compiled tool name.
    operation_key TEXT NOT NULL
        CONSTRAINT agent_toolset_tools_operation_key_ck
            CHECK (char_length(operation_key) BETWEEN 1 AND 2048),
    tool_name VARCHAR(64) NOT NULL
        CONSTRAINT agent_toolset_tools_tool_name_ck
            CHECK (tool_name ~ '^[A-Za-z0-9_-]{1,64}$'),

    -- Rule 4: safe by default.
    write_op BOOLEAN NOT NULL,
    enabled BOOLEAN NOT NULL,
    write_confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    write_confirmed_at TIMESTAMPTZ,
    CONSTRAINT agent_toolset_tools_write_confirmed_ck CHECK (
        (write_op AND enabled AND write_confirmed_at IS NOT NULL)
        OR (NOT (write_op AND enabled) AND write_confirmed_at IS NULL)
    ),

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT agent_toolset_tools_operation_uq UNIQUE (toolset_id, operation_key),
    CONSTRAINT agent_toolset_tools_name_uq UNIQUE (toolset_id, tool_name)
);

-- The MCP agent runtime reads a toolset's enabled tool names on every request.
CREATE INDEX IF NOT EXISTS idx_agent_toolset_tools_enabled
    ON agent_toolset_tools (toolset_id)
    WHERE enabled;

COMMENT ON TABLE agent_toolset_tools IS
    'AGX-1.2 (#4530): one row per callable operation of a toolset''s version — whether it is '
    'exposed to agents. Reads are enabled by default; write ops are opt-in with a confirmation.';

COMMENT ON COLUMN agent_toolset_tools.operation_key IS
    'Canonical operation key (GET /pets/{id}) — the reference app.mcp_tool_mapping resolves.';

COMMENT ON COLUMN agent_toolset_tools.tool_name IS
    'The MCP tool name compile_mcp_tools gives this operation, recorded when the toolset was seeded.';

COMMENT ON COLUMN agent_toolset_tools.write_op IS
    'True for a mutating operation (not GET/HEAD, not a GraphQL query). Opt-in only.';

COMMENT ON COLUMN agent_toolset_tools.write_confirmed_at IS
    'When the enabling of this write op was explicitly confirmed (and by write_confirmed_by). '
    'Required while a write op is enabled; cleared when it is disabled.';

-- ---------------------------------------------------------------------------------------------------
-- AGX-2.2 / AGX-3.1 handoff: remove orphans, then bind toolset_id to agent_toolsets.
-- ---------------------------------------------------------------------------------------------------
DELETE FROM upstream_credentials c
WHERE NOT EXISTS (
    SELECT 1 FROM agent_toolsets t WHERE t.id = c.toolset_id AND t.tenant_id = c.tenant_id
);

DELETE FROM api_keys k
WHERE k.kind = 'agent'
  AND NOT EXISTS (
    SELECT 1 FROM agent_toolsets t WHERE t.id = k.toolset_id AND t.tenant_id = k.tenant_id
  );

ALTER TABLE upstream_credentials
  DROP CONSTRAINT IF EXISTS upstream_credentials_toolset_fk;
ALTER TABLE upstream_credentials
  ADD CONSTRAINT upstream_credentials_toolset_fk
  FOREIGN KEY (tenant_id, toolset_id) REFERENCES agent_toolsets (tenant_id, id) ON DELETE CASCADE;

-- Workspace keys have a NULL toolset_id, which a (default MATCH SIMPLE) foreign key skips.
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_agent_toolset_fk;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_agent_toolset_fk
  FOREIGN KEY (tenant_id, toolset_id) REFERENCES agent_toolsets (tenant_id, id) ON DELETE CASCADE;

COMMENT ON COLUMN upstream_credentials.toolset_id IS
    'The agent toolset (agent_toolsets.id, same tenant) this credential serves. Deleting the '
    'toolset deletes the credential (AGX-1.2, #4530).';

COMMENT ON COLUMN api_keys.toolset_id IS
    'AGX-3.1 (#4537): the agent toolset (agent_toolsets.id, same tenant) an agent key is bound to; '
    'NULL for workspace keys. Deleting the toolset deletes its agent keys (AGX-1.2, #4530).';
