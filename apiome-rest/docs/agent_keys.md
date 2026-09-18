# Agent keys — AGX-3.1 (#4537)

An agent that calls a tenant's API through a managed MCP toolset holds an **agent key**. It is an
`apiome.api_keys` row, like a workspace key, but it has limits a workspace key doesn't have:

- **Bound to one toolset** (`toolset_id`, an AGX-1.2 `agent_toolsets` id).
- **Restricted to an explicit tool allowlist** (`tool_allowlist`, MCP tool names). The agent may
  list and call only the tools that are **enabled in the toolset _and_ on the allowlist**.
- **Expirable** (`expires_at`) and **revocable** (soft delete). The MCP runtime reads the key on
  every request, so revocation, expiry and allowlist edits apply to the agent's next request.

Per-agent identity is also where quotas (AGX-3.2) and usage analytics (AGX-3.3 / 3.4) attach.

## Where the pieces live

| Piece | What it owns |
| --- | --- |
| `apiome-db/scripts/V269__agent_keys_agx_3_1.sql` | `api_keys.kind` (`workspace` \| `agent`), `toolset_id`, `tool_allowlist`, their CHECKs, the `agent:invoke` scope, two partial indexes |
| `app.agent_keys` | Validation, secret minting (`ak_…`, bcrypt), status, and create / list / get / allowlist edit / revoke |
| `app.agent_key_routes` | The REST surface (below) and its access-audit rows |
| `app.database` | The five `*agent_key*` accessors, and `validate_api_key`, which only accepts workspace keys |
| `apiome_mcp.agent_access` (apiome-mcp) | The MCP middleware that authenticates agent keys and narrows `tools/list` / `tools/call` ([AGENT_ACCESS.md](../../apiome-mcp/docs/AGENT_ACCESS.md)) |

## REST surface

| Method | Path | Permission | Audit action |
| --- | --- | --- | --- |
| `GET` | `/v1/tenants/{t}/agent-keys` (`?toolsetId=…`, `?includeRevoked=true`) | `api_keys:view` | — |
| `POST` | `/v1/tenants/{t}/agent-keys` | `api_keys:create` | `agent.key.create` |
| `GET` | `/v1/tenants/{t}/agent-keys/{id}` | `api_keys:view` | — |
| `PUT` | `/v1/tenants/{t}/agent-keys/{id}/allowlist` | `api_keys:edit` | `agent.key.allowlist_update` |
| `DELETE` | `/v1/tenants/{t}/agent-keys/{id}` | `api_keys:delete` | `agent.key.revoke` (first revoke only) |

There is **no new RBAC resource**. An agent key is an API key, so the existing `api_keys`
permissions guard it, as they guard the AGX-2.2 upstream credentials. Every read and write is
scoped by the caller's authenticated tenant.

```bash
# Create: the secret is in this response only.
curl -sX POST "$APIOME/v1/tenants/acme/agent-keys" \
     -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
     -d '{"name": "claude-desktop", "toolsetId": "'"$TOOLSET"'",
          "toolAllowlist": ["listPets", "getPetById"], "expiresAt": "2026-12-31T00:00:00Z"}'

# Replace the allowlist (the whole list).
curl -sX PUT "$APIOME/v1/tenants/acme/agent-keys/$KEY_ID/allowlist" \
     -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
     -d '{"toolAllowlist": ["listPets"]}'

# Revoke.
curl -sX DELETE "$APIOME/v1/tenants/acme/agent-keys/$KEY_ID" -H "Authorization: Bearer $JWT"
```

### Request rules

- `name` must be 1–255 characters and not blank. It must be unique in the tenant across workspace
  **and** agent keys, revoked keys included (`409 agent-key-exists`).
- `toolsetId` must be a UUID. It is **not** checked against `agent_toolsets` yet (see below).
- Each `toolAllowlist` entry must be an AGX-1.1 tool name, `^[A-Za-z0-9_-]{1,64}$`, and there can
  be at most 1024 entries. The list is stored deduplicated and sorted. There is no wildcard, and an
  empty list permits nothing.
- `expiresAt` is optional and must be in the future. A value without a timezone is read as UTC.
- A refusal is `{"detail": {"code", "errors": [...]}}` with one message per problem:
  `agent-key-invalid` → 422, `agent-key-exists` → 409, `agent-key-not-found` → 404,
  `agent-key-revoked` → 409 (a revoked key's allowlist cannot change).

### Responses

Every response describes the key (`schemaVersion: "agx.agent-key.v1"`): `id`, `kind: "agent"`,
`name`, `description`, `keyPrefix`, `toolsetId`, `toolAllowlist`, `status`, `enabled`,
`expiresAt`, `revokedAt`, `lastUsedAt`, `createdAt`, `updatedAt`, `createdBy`.

- **`secret` appears only in the create response.** The secret is `ak_` followed by 64 hex
  characters. The row stores a bcrypt hash plus the usual `first 12 characters + '...'` prefix, and
  no route ever returns the hash.
- `status` is `revoked`, then `disabled`, then `expired`, else `active`. That is the order the MCP
  middleware checks them in.

### Audit

Each lifecycle action appends one row to `apiome.access_audit` (target = key id, source `api`)
holding metadata only: `name`, `keyPrefix`, `toolsetId`, plus

- `agent.key.create`: `toolAllowlist` and `expiresAt`;
- `agent.key.allowlist_update`: `before` and `after`;
- `agent.key.revoke`: nothing more. Repeating a revoke is a no-op `204` and is not audited again.

An audit failure is logged and never fails the action.

## An agent key is not a REST credential

Agent keys sit in the same table as workspace keys, so every existing reader of `api_keys` had to
be told apart. Two independent defences stop an agent key from becoming a tenant-wide key:

1. `db.validate_api_key` selects `kind = 'workspace'` rows only. On a database older than V269
   there is no `kind` column, and so no agent keys, and it falls back to the older queries. The
   apiome-mock private-mock check and the Control Panel's workspace-key list and expiry nudges
   also select workspace keys only.
2. V269 requires every agent key to carry exactly the scope `agent:invoke`, and forbids that scope
   on workspace keys. No entry in the REST scope allowlist (`app.auth`) accepts it, so even a
   reader that skipped the kind filter would get a `403` on every route.

## Handoffs

- **AGX-1.2 (#4530)** — `toolset_id` has no foreign key: `agent_toolsets` did not exist when this
  shipped, the same situation as V268's upstream credentials. AGX-1.2 must revoke or delete
  agent keys whose toolset does not exist, add `REFERENCES agent_toolsets(id)`, and add a
  route-level toolset check to `POST /agent-keys`. It must also give the MCP middleware its
  enabled-tools source ([AGENT_ACCESS.md](../../apiome-mcp/docs/AGENT_ACCESS.md)). Until then the
  middleware fails closed and every agent request gets `agent_toolset_unavailable`.
- **AGX-2.1 (#4533)** — mount `AgentAccessMiddleware` on the agent runtime's FastMCP app (never on
  the catalog server), and read the verified key with `current_agent_access()`.
- **Latency** — the middleware verifies a bcrypt hash (cost 10, as for workspace keys) on every
  agent request. If that becomes too slow for the AGX-2.1 overhead budget, add a short-lived
  verified-key cache and keep revocation immediate, for example by keying the cache on
  `updated_at`.
