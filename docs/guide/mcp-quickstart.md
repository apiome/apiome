# MCP setup quick-start

The Apiome **MCP server** exposes your **published OpenAPI specs** to MCP hosts (Claude Desktop,
IDEs, automation). It is **read-only**: it lists, searches, and returns published documents and
fragments. Anonymous callers see **public** specs; a valid **MCP API key** additionally unlocks
**in-scope private** specs for its tenant.

Full reference: [`apiome-mcp/README.md`](../../apiome-mcp/README.md) and
[`apiome-mcp/docs/CONFIGURATION.md`](../../apiome-mcp/docs/CONFIGURATION.md).

---

## 1. Get an MCP API key (optional, for private specs)

Create an MCP-type key in the UI under **Dashboard → API keys** (`/ade/dashboard/api-keys`). Keys are
stored hashed and can be scoped to specific tenants/projects. You can skip this if you only need
public specs.

Tenant admins also govern **which tools that key may call** (ceiling, defaults, and per-key
capabilities). Listing the catalog is never filtered by those settings — see
[Governed keys: list vs call](#governed-keys-list-vs-call).

## 2. Connect a host

The server speaks two transports. For connecting to an already-running Apiome, **streamable
HTTP** is the simplest.

### Streamable HTTP (recommended)

The server's MCP endpoint is `http://<host>:8765/mcp` (default port **8765**). Point your host at
that URL and pass the key as a bearer token:

```
URL:     http://localhost:8765/mcp
Header:  Authorization: Bearer <your-mcp-api-key>
```

Liveness check (no auth, no DB): `GET http://localhost:8765/health`.

### stdio (local / self-hosted)

For hosts that launch the server as a subprocess. The server connects **directly to Postgres**, so
it needs the database URL and an internal secret:

```jsonc
// Claude Desktop — claude_desktop_config.json
{
  "mcpServers": {
    "apiome": {
      "command": "uv",
      "args": ["run", "apiome-mcp", "serve", "--transport", "stdio"],
      "env": {
        "APIOME_MCP_DATABASE_URL": "postgresql://user:pass@localhost:5432/apiome",
        "APIOME_MCP_INTERNAL_SECRET": "<16+ character secret>"
      }
    }
  }
}
```

With stdio, the API key (if any) is passed per call in the JSON-RPC `_meta` (e.g. `api_key`), not as
an HTTP header.

## 3. Run the server yourself (for HTTP transport)

```bash
cd apiome-mcp
uv sync
uv run apiome-mcp serve --transport http --host 0.0.0.0 --port 8765
```

Required env (see `apiome-mcp/.env.example`): `APIOME_MCP_DATABASE_URL`,
`APIOME_MCP_INTERNAL_SECRET` (≥16 chars). Host/port default to `127.0.0.1:8765` and can be set
with `APIOME_MCP_HTTP_HOST` / `APIOME_MCP_HTTP_PORT`. The local `docker compose up` already
brings the MCP server up on `:8765`.

## Tools available to the host

| Tool | What it returns |
|---|---|
| `ping` | Service name, version, DB reachability, timestamp |
| `spec.list` | Published specs (public; + in-scope private with a key) |
| `project.list` | Distinct projects visible to the caller |
| `spec.list_my_specs` | Specs for the authenticated key only |
| `spec.describe` | Metadata for one spec revision |
| `spec.get_openapi` | Full OpenAPI 3.1 JSON for a revision |
| `spec.export_yaml` | The same document as YAML |
| `spec.list_operations` / `spec.describe_operation` | Operation index / one operation's fragments |
| `spec.list_components` / `spec.describe_component` | Component index / one component definition |
| `spec.search` | Full-text search over public specs |
| `spec.search_semantic` | Semantic search (needs `APIOME_MCP_OPENAI_API_KEY`) |
| `spec.list_tags` | Distinct public tags with counts |

## Governed keys: list vs call

Catalog MCP separates **discovery** from **invocation**:

| Operation | Behavior |
|---|---|
| `tools/list` | **Always** returns the full live registry. Tenant ceiling, defaults, anonymous flags, and per-key enable-sets **never** hide tools from the list. |
| `tools/call` | Allowed only when the tool is enabled for the caller. For an authenticated MCP key that means: tool ∈ tenant ceiling **and** (key inherits tenant defaults **or** tool ∈ the key’s explicit enable-set). |

Seeing a tool in the host’s tool picker does **not** mean the key can invoke it. A denied call returns a
stable `capability_disabled` error (for example: *Tool 'spec.search' is disabled for this API key.
A tenant admin must enable it before it can be called.*) — never secret key material.

### How to request enablement

1. Ask a **tenant administrator** for the tenant that owns the MCP key.
2. The admin opens **Dashboard → Tenants** (`/ade/dashboard/tenants`) and expands **MCP Settings**.
3. There they can raise the tenant **ceiling / defaults** (toolset or per-tool toggles) and, when
   needed, set the key’s capabilities to **inherit** those defaults or an **explicit** enable-set.

Non-admins can browse the same panel read-only; only tenant admins can save changes. For scripted
break-glass flows, use `apiome mcp policy` / `apiome mcp key capabilities` (see
[`apiome-cli/README.md`](../../apiome-cli/README.md)).

Operator-depth ADRs: [`LIST_ALWAYS.md`](../../apiome-mcp/docs/LIST_ALWAYS.md),
[`EFFECTIVE_POLICY.md`](../../apiome-mcp/docs/EFFECTIVE_POLICY.md).

## Verify

Call `ping` from your host — it returns the service version and confirms Postgres reachability. Then
`spec.list` should return the published specs (including the seeded `petstore-sample` if you loaded
the dev seed). This is the same query the [Golden Path](../GOLDEN_PATH.md) runs as its final step.

If a later tool call fails with `capability_disabled`, use
[Governed keys: list vs call](#governed-keys-list-vs-call) and **Tenants → MCP Settings** to enable it.

## Related

- [publish-a-version.md](publish-a-version.md) — only published specs are visible over MCP
- [browse-published-specs.md](browse-published-specs.md) — the same catalog, in the UI
- **Tenants → MCP Settings** (`/ade/dashboard/tenants`) — tenant ceiling, defaults, and per-key call grants
