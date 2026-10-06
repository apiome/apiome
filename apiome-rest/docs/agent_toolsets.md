# Agent toolsets: tool selection & curation (AGX-1.2, #4530)

Switching on Agent Access for a published version must not hand an agent every operation the
spec contains. A `DELETE /users/{id}` would become callable the moment access is on. An **agent
toolset** is a tenant's curated choice of which operations of **one published version** its agents
may call as MCP tools.

- **One toolset per version.** It can only be created for a published, undeleted version of a
  project in the caller's tenant.
- **Safe by default: reads on, writes opt-in.** When the toolset is created, every callable
  operation gets a tool row. Reads (`GET`, `HEAD`, GraphQL queries) are enabled, except deprecated
  ones. Every other operation is a **write op** and starts disabled. That includes
  `POST`/`PUT`/`PATCH`/`DELETE`, unknown verbs, and RPC methods, which cannot be shown to be reads.
- **Enabling a write op needs an explicit confirmation**: `confirmWriteOp: true`. The confirmation
  is stamped on the tool row (`writeConfirmedBy`, `writeConfirmedAt`) and cleared when the tool is
  disabled, so re-enabling needs a fresh one. A database CHECK makes an enabled but unconfirmed
  write op impossible to store, even through direct SQL.
- **`target`** is `prod` (default) or `mock`: where AGX-2.1 sends tool calls (AGX-2.4 mock-target
  mode, `apiome_mcp.mock_target`).

## Where the pieces live

| Piece | What it owns |
| --- | --- |
| `apiome-db/scripts/V270__agent_toolsets_agx_1_2.sql` | `agent_toolsets`, `agent_toolset_tools`, the write-confirmation CHECK, and the AGX-2.2 / AGX-3.1 foreign keys |
| `app.agent_toolsets` | Read/write classification, safe-by-default seeding, create / list / get / update / delete, tool enable/disable |
| `app.agent_toolset_routes` | The REST surface (below), its access-audit rows, and `require_agent_toolset` (the route-level toolset check) |
| `app.database` | The `*agent_toolset*` accessors |
| `apiome_mcp.agent_access` (apiome-mcp) | `toolset_enabled_tools`, the MCP middleware's default source of a key's enabled tools |

## Tools are the compiler's tools

Tool rows reference operations by **canonical key** (`GET /pets/{id}`, `Query.user`), the reference
`app.mcp_tool_mapping.compile_mcp_tools(exposed=…)` resolves. They also record the compiled **MCP
tool name**. Names are derived over every callable operation (AGX-1.1), so enabling or disabling one
tool never renames another, and the names are the ones an agent key's allowlist holds.

The operations come from the version's captured source (`app.export_source.load_export_source`),
the same model SDK and export generation use. A version without captured source, such as one built
only in Studio, cannot get a toolset: the create is a `422 agent-toolset-source-unavailable`.

## REST surface

| Method | Path | Permission | Audit action |
| --- | --- | --- | --- |
| `GET` | `/v1/tenants/{t}/agent-toolsets` (`?versionId=…`) | `api_keys:view` | — |
| `POST` | `/v1/tenants/{t}/agent-toolsets` | `api_keys:create` | `agent.toolset.create` |
| `GET` | `/v1/tenants/{t}/agent-toolsets/{id}` (with every tool) | `api_keys:view` | — |
| `PATCH` | `/v1/tenants/{t}/agent-toolsets/{id}` (`enabled`, `target`) | `api_keys:edit` | `agent.toolset.update` (before/after) |
| `DELETE` | `/v1/tenants/{t}/agent-toolsets/{id}` | `api_keys:delete` | `agent.toolset.delete` |
| `GET` | `/v1/tenants/{t}/agent-toolsets/{id}/tools` | `api_keys:view` | — |
| `PATCH` | `/v1/tenants/{t}/agent-toolsets/{id}/tools/{toolId}` (`enabled`, `confirmWriteOp`) | `api_keys:edit` | `agent.toolset.tool.update` |

There is **no new RBAC resource**. A toolset, its upstream credentials (AGX-2.2) and its agent keys
(AGX-3.1) are together one agent's access, and all three use the `api_keys` permissions. Every read
and write is scoped by the caller's authenticated tenant. Tool rows are seeded from the version and
are not created or deleted one at a time.

`agent.toolset.tool.update` records the operation, tool name, `writeOp`, enabled before/after and
the confirmation time. With the audit row's actor and timestamp, that answers "who enabled which
write op, when".

| Refusal code | Status |
| --- | --- |
| `agent-toolset-version-not-found` | 404 |
| `agent-toolset-version-unpublished` (unpublished or deleted) | 409 |
| `agent-toolset-exists` (the version already has one) | 409 |
| `agent-toolset-source-unavailable` | 422 |
| `agent-toolset-not-found` / `agent-toolset-tool-not-found` | 404 |
| `agent-toolset-write-op-unconfirmed` | 422 |
| `agent-toolset-invalid` (a `PATCH` that changes nothing) | 422 |

```bash
# Give a published version Agent Access: reads on, writes off.
curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"versionId": "<published versions.id>"}'

# Enabling a DELETE without confirmation is refused (422)...
curl -sX PATCH "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/tools/$TOOL" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"enabled": true}'

# ...and accepted with the explicit confirmation.
curl -sX PATCH "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/tools/$TOOL" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"enabled": true, "confirmWriteOp": true}'
```

## Deleting a toolset

V270 gave `upstream_credentials.toolset_id` and `api_keys.toolset_id` a `(tenant_id, toolset_id)`
foreign key to `agent_toolsets` with `ON DELETE CASCADE`. Deleting a toolset therefore deletes its
tool rows, its upstream credentials and its agent keys. An agent holding one of those keys is
refused on its next request. Credential use history (`upstream_credential_uses`) is kept. The
migration first deleted credentials and agent keys whose toolset did not exist. None could have
existed, because no toolset could be created before V270.

The agent-key create and the upstream-credential list/create routes check the toolset first with
`require_agent_toolset`, so a toolset id from another tenant is a `404`, never a foreign-key error.

## What agents see

`apiome_mcp.agent_access.toolset_enabled_tools`, the agent-access middleware's default source,
returns the toolset's enabled tool names. It returns `None` when the toolset is missing from the
key's tenant, switched off, or its version is no longer published, and the agent request then fails
closed with `agent_toolset_unavailable`. The tools an agent key may use are those names intersected
with its allowlist.

## Tests

| File | Pins |
| --- | --- |
| `tests/test_agent_toolsets.py` | Classification, safe-by-default seeding (compiler names, deprecated reads off), create refusals, the write-op confirmation |
| `tests/test_agent_toolset_routes.py` | Permissions, status mapping, tenant scoping, one audit row per change, both acceptance rules end to end |
| `tests/test_agent_toolsets_migration.py`, `apiome-db/test/agent-toolsets.test.ts` | The V270 schema promises |
| `tests/agent_toolset_fakes.py` | The in-memory store (enforces the write-confirmation CHECK) |
| apiome-mcp `tests/test_agent_access.py` | The enabled-tools source and its fail-closed cases |
