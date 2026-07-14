# apiome-mcp configuration

Runtime configuration is loaded from the environment by [`Settings`](../src/apiome_mcp/settings.py) (pydantic-settings). All variables use the prefix **`APIOME_MCP_`**. An optional **`.env`** file in the current working directory is read when present (`env_file=".env"`).

## Variable reference

| Environment variable | Required | Default | Valid range / notes |
|---------------------|----------|---------|---------------------|
| **`APIOME_MCP_DATABASE_URL`** | Yes | — | PostgreSQL URL (`postgres://` or `postgresql://`). Field: `database_url`. |
| **`APIOME_MCP_INTERNAL_SECRET`** | Yes | — | Minimum **16** characters. Used for internal signing material (e.g. HMAC). Field: `internal_secret` (secret value). |
| **`APIOME_MCP_LOG_LEVEL`** | No | `INFO` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (case-insensitive; normalized to uppercase). |
| **`APIOME_MCP_TRANSPORT`** | No | `stdio` | `stdio` or `http`. Stored on `Settings`; **`apiome-mcp serve` still requires `--transport stdio` or `--transport http` to run a transport**—without those flags the CLI validates configuration and exits. |
| **`APIOME_MCP_HTTP_HOST`** | No | `127.0.0.1` | Non-empty bind address when using HTTP transport (CLI `--host` overrides). |
| **`APIOME_MCP_HTTP_PORT`** | No | `8765` | Integer **1–65535** (CLI `--port` overrides). |
| **`APIOME_MCP_DATABASE_POOL_MIN_SIZE`** | No | `1` | Integer **1–256**. |
| **`APIOME_MCP_DATABASE_POOL_MAX_SIZE`** | No | `10` | Integer **1–256**; must be **≥** `DATABASE_POOL_MIN_SIZE`. |
| **`APIOME_MCP_DATABASE_POOL_TIMEOUT`** | No | `30` | Seconds to wait for a pool connection; **> 0** and **≤ 600**. |
| **`APIOME_MCP_OPENAPI_MAX_JSON_BYTES`** | No | `2097152` | Max UTF-8 size for exported OpenAPI JSON/YAML payloads (**1024–100_000_000**). |
| **`APIOME_MCP_OPENAI_API_KEY`** | No | — | Secret for **`spec.search_semantic`** query embeddings (`Bearer` to **`APIOME_MCP_OPENAI_EMBEDDING_URL`**). When unset, calling **`spec.search_semantic`** fails fast. |
| **`APIOME_MCP_OPENAI_EMBEDDING_URL`** | No | `https://api.openai.com/v1/embeddings` | OpenAI-compatible embeddings endpoint (POST JSON `model`, `input`, `dimensions`). |
| **`APIOME_MCP_OPENAI_EMBEDDING_MODEL`** | No | `text-embedding-3-small` | Passed through to the embeddings API as **`model`**. |
| **`APIOME_MCP_OPENAI_EMBEDDING_DIMENSIONS`** | No | `1536` | Must match **`apiome.versions.mcp_public_embedding`** (`vector(1536)` migration). |
| **`APIOME_MCP_OPENAI_EMBEDDING_TIMEOUT_S`** | No | `60` | HTTP timeout for embedding requests (**> 0**, **≤ 600**). |
| **`APIOME_MCP_ANONYMOUS_POLICY_TENANT_ID`** | No | — | Optional UUID of the **host tenant** whose MCP policy gates anonymous `tools/call` (MTG-2.3). When unset, anonymous callers are not gated. See [`ANONYMOUS_CALL_POLICY.md`](ANONYMOUS_CALL_POLICY.md). |

## Related files

- **[`../.env.example`](../.env.example)** — copy/paste template for local development.
- **Repository root [`docker-compose.env.example`](../../docker-compose.env.example)** — overrides for **`docker compose`** (Postgres + MCP port + secret).
- **[`LIST_ALWAYS.md`](LIST_ALWAYS.md)** — MTG-2.1 ADR: `tools/list` is never filtered by enable-set (contrast AGX-3.1).
- **[`AGX_COORDINATION.md`](AGX_COORDINATION.md)** — MTG-5.5: catalog MCP vs AGX agent tools; shared code must not merge list contracts.
- **[`EFFECTIVE_POLICY.md`](EFFECTIVE_POLICY.md)** — MTG-1.4 effective resolver used by the `tools/call` gate (MTG-2.2).
- **[`ANONYMOUS_CALL_POLICY.md`](ANONYMOUS_CALL_POLICY.md)** — MTG-2.3 ADR: host-tenant anonymous enable-set + matrix.
- **[`POLICY_FRESHNESS.md`](POLICY_FRESHNESS.md)** — MTG-2.5 ADR: per-call DB policy resolve; lag budget `0` (no restart).
