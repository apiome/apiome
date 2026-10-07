# Agent access (AGX-3.1)

**Ticket:** AGX-3.1 ([#4537](https://github.com/apiome/apiome/issues/4537)).
Module: [`apiome_mcp.agent_access`](../src/apiome_mcp/agent_access.py).
Keys are minted by apiome-rest's `/v1/tenants/{t}/agent-keys`
([agent_keys.md](../../apiome-rest/docs/agent_keys.md)).

An agent calling a tenant's API through a managed MCP toolset presents an **agent key**: an
`apiome.api_keys` row with `kind = 'agent'` (V269), bound to one toolset and carrying an explicit
tool allowlist. `AgentAccessMiddleware` is the FastMCP middleware that enforces it on the **agent
surface**. What an agent may use is

```
permitted = toolset's enabled tools (AGX-1.2)  ∩  key's tool_allowlist
```

and an agent cannot even *see* a tool outside that set.

```mermaid
flowchart LR
  A[Agent request<br/>MCP + agent key] --> MW[AgentAccessMiddleware.on_request]
  MW --> K[(api_keys<br/>kind=agent, toolset_id,<br/>tool_allowlist, expires_at)]
  K -->|missing / invalid / revoked /<br/>disabled / expired| E[✗ -32010 + data.reason]
  K --> TS[enabled_tools source<br/>AGX-1.2]
  TS -->|None| U[✗ -32011 agent_toolset_unavailable]
  TS --> INT[permitted = enabled ∩ allowlist]
  INT --> L[tools/list → permitted only]
  INT --> C[tools/call → permitted only,<br/>else 'Unknown tool: …']
```

## Per request

Every request except the `initialize` handshake goes through the same steps:

1. **Read the key.** It comes from `Authorization: Bearer <key>` over HTTP. Transports without
   headers can send it in `params._meta` (`authorization`, `apiome_authorization`,
   `apiome_api_key` or `api_key`), the same keys the catalog server reads.
2. **Resolve it.** `resolve_agent_key(pool, secret)` looks the key up by its 12-character prefix,
   `kind = 'agent'` only, and verifies the bcrypt hash in a worker thread. **After** the hash
   matches, it refuses the key in this order: revoked, disabled, expired. A caller without the real
   secret only ever gets `agent_key_invalid`. The row is read on every request, so a revoke, an
   expiry or an allowlist edit applies to the very next request, even within the same MCP session.
   Nothing is cached.
3. **Ask the toolset.** `enabled_tools(ctx, key)` returns the toolset's enabled tool names, or
   `None` when the toolset is missing or disabled.
4. **Narrow.** `tools/list` is filtered to the permitted set. `tools/call` on anything else raises
   FastMCP's own `Unknown tool: '<name>'`. A tool the key may not use therefore looks exactly like
   a tool that does not exist, so an agent cannot probe for tools.

The decided `AgentAccess` (key plus permitted set) is available to the rest of the request through
`current_agent_access()`. The AGX-2.1 invocation path uses that value instead of resolving the key
a second time.

## Errors

A refusal is an `AgentAccessDeniedError`, which is an `mcp.McpError`:

| `data.reason` | JSON-RPC code | When |
|---|---|---|
| `agent_key_missing` | `-32010` | No key presented |
| `agent_key_invalid` | `-32010` | Unknown key, wrong secret, workspace/catalog key, or disabled tenant |
| `agent_key_revoked` | `-32010` | Key revoked (`DELETE /agent-keys/{id}`) |
| `agent_key_disabled` | `-32010` | Key's `enabled` flag is off |
| `agent_key_expired` | `-32010` | `expires_at` has passed |
| `agent_toolset_unavailable` | `-32011` | The key is fine, but its toolset is missing, disabled, or not curated yet |
| `agent_access_unavailable` | `-32603` | Access could not be decided (e.g. database down). Fails closed and the cause is not echoed |

`-32010` and `-32011` sit in JSON-RPC's implementation-defined server-error range, clear of the
codes the MCP SDKs use (`-32000`, `-32001`, `-32002`, `-32042`).

- **`tools/list`** returns the error as a JSON-RPC error with that code and `data`.
- **`tools/call`**: the MCP Python SDK turns any error raised while handling a call into an
  `isError: true` tool result. The result text is the error message, which always starts with the
  reason (`agent_key_revoked: This agent key has been revoked.`).

No message contains the key, its hash or its prefix.

## Mounting it (AGX-2.1)

The agent runtime ([`apiome_mcp.agent_server.build_agent_server`](../src/apiome_mcp/agent_server.py),
served at `/agent/mcp`) mounts it, after the bearer stash and before the AGX-3.2 quota middleware:

```python
agent_mcp = FastMCP("Apiome agent runtime", lifespan=agent_lifespan, providers=[AgentToolsetProvider(proxy)])
agent_mcp.add_middleware(StashHttpBearerInToolContextMiddleware())
agent_mcp.add_middleware(AgentAccessMiddleware())  # enabled tools read from AGX-1.2 curation
agent_mcp.add_middleware(AgentQuotaMiddleware(guard=AgentQuotaGuard.from_settings(settings)))
```

FastMCP runs middleware in the order it was added. The invocation proxy reads the verified key from
`current_agent_access()`; see [AGENT_INVOCATION_PROXY.md](AGENT_INVOCATION_PROXY.md).

- **Never mount it on the catalog server** (`apiome_mcp.server`). The catalog's `tools/list`
  always returns the full registry (MTG-2.1, [LIST_ALWAYS.md](LIST_ALWAYS.md); rules in
  [AGX_COORDINATION.md](AGX_COORDINATION.md)). A test fails the build if the catalog app ever
  carries `AgentAccessMiddleware`.
- **The default `enabled_tools` is the AGX-1.2 curation (#4530).** `toolset_enabled_tools` reads
  the enabled `tool_name`s of the key's toolset from `agent_toolset_tools` (V270). apiome-rest
  recorded those names with `compile_mcp_tools` when it seeded the toolset, so they are the names
  an allowlist holds. It returns `None`, and the request fails closed with
  `agent_toolset_unavailable`, when the toolset is not in the key's tenant, is switched off, or its
  version is no longer published. An enabled toolset with no enabled tools lists nothing.
- `key_resolver` can be replaced too (tests pass a fake). The default resolves against `api_keys`
  through the lifespan pool.

## Tests

- `tests/test_agent_access.py` covers the intersection, the error mapping, the resolver against an
  in-memory `api_keys` (`tests/agent_access_fakes.py`), and the middleware driven through
  FastMCP's dispatch.
- `tests/test_agent_access_http.py` checks the acceptance criteria over real streamable HTTP
  (Uvicorn plus a FastMCP client):
  - `tools/list` returns exactly the intersection;
  - a non-permitted `tools/call` is indistinguishable from an unknown tool;
  - expired keys are rejected;
  - revocation and allowlist edits take effect on the same session's next request.
