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
| **`APIOME_MCP_MOCK_PUBLIC_BASE_URL`** | No | `http://localhost:8775` | Public root of the hosted SIM mock runtime. AGX-2.4 toolsets with `target: mock` route `tools/call` to `{root}/{tenant}/{project}/{version}`. Must be absolute `http`/`https` with a host (validated at startup); trailing slashes are stripped. Mirrors apiome-rest's `APIOME_MOCK_PUBLIC_BASE_URL`. See [`MOCK_TARGET.md`](MOCK_TARGET.md). |
| **`APIOME_MCP_ANONYMOUS_POLICY_TENANT_ID`** | No | — | Optional UUID of the **host tenant** whose MCP policy gates anonymous `tools/call` (MTG-2.3). When unset, anonymous callers are not gated. See [`ANONYMOUS_CALL_POLICY.md`](ANONYMOUS_CALL_POLICY.md). |
| **`APIOME_MCP_AGENT_USAGE_SWEEP_INTERVAL_SECONDS`** | No | `3600` | AGX-3.3: seconds between in-process agent usage sweeps (daily rollups + per-tier retention), **0–86400**. `0` disables the in-process sweep; run `apiome-mcp agent-usage sweep` from cron instead. See [`AGENT_INVOCATIONS.md`](AGENT_INVOCATIONS.md). |
| **`APIOME_MCP_AGENT_USAGE_SWEEP_BATCH_SIZE`** | No | `10000` | AGX-3.3: most rows each retention purge deletes per tick (**1–1000000**). |
| **`APIOME_MCP_AGENT_USAGE_FINALIZE_GRACE_HOURS`** | No | `6` | AGX-3.3: hours after a UTC day ends before its rollup is final and its raw rows may be pruned (**1–72**). Must exceed the longest agent call. |
| **`APIOME_MCP_AGENT_UPSTREAM_USE_RETENTION_DAYS`** | No | `90` | AGX-2.2 upstream credential-use ledger retention applied by the AGX-3.3 sweep (**1–3650**). |
| **`APIOME_MCP_AGENT_QUOTA_LIMITS_CACHE_SECONDS`** | No | `60` | AGX-3.2: seconds a tenant's agent key caps (license tier) are cached (**0–3600**). A tier change applies within this time. See [`AGENT_QUOTAS.md`](AGENT_QUOTAS.md). |
| **`APIOME_MCP_AGENT_QUOTA_USAGE_CACHE_SECONDS`** | No | `5` | AGX-3.2: seconds between re-reads of an agent key's daily call count from `agent_invocations` (**0–300**). Across instances a key can overshoot its daily cap by about (instances − 1) × rps × this. |
| **`APIOME_MCP_MOCK_INVOCATION_BASE_URL`** | No | — | AGX-2.1: root of the SIM mock as this process reaches it, when that differs from `APIOME_MCP_MOCK_PUBLIC_BASE_URL` (e.g. `http://mock:8775` inside docker compose). Same validation as the public root; blank = unset. See [`AGENT_INVOCATION_PROXY.md`](AGENT_INVOCATION_PROXY.md). |
| **`APIOME_MCP_AGENT_UPSTREAM_TIMEOUT_SECONDS`** | No | `30` | AGX-2.1: most seconds one upstream attempt of an agent `tools/call` may take, body read included (**> 0**, **≤ 300**). |
| **`APIOME_MCP_AGENT_UPSTREAM_CONNECT_TIMEOUT_SECONDS`** | No | `5` | AGX-2.1: most seconds opening the upstream connection may take (**> 0**, **≤ 60**). |
| **`APIOME_MCP_AGENT_UPSTREAM_MAX_RETRIES`** | No | `2` | AGX-2.1: retries after the first attempt (**0–5**). Idempotent methods retry on timeouts, dropped connections and 502/503/504; other methods only when the connection never opened. |
| **`APIOME_MCP_AGENT_UPSTREAM_BUDGET_SECONDS`** | No | `45` | AGX-2.1: most seconds all attempts and back-off pauses of one call may take together (**> 0**, **≤ 600**). |
| **`APIOME_MCP_AGENT_UPSTREAM_BACKOFF_SECONDS`** | No | `0.2` | AGX-2.1: pause before the first retry; doubles each retry (**0–30**). |
| **`APIOME_MCP_AGENT_RESPONSE_MAX_BYTES`** | No | `65536` | AGX-2.1: most upstream body bytes returned to the agent; longer bodies are cut and marked `[truncated: …]` (**1024–10000000**). |
| **`APIOME_MCP_AGENT_TOOLSET_CACHE_SIZE`** | No | `256` | AGX-2.1: compiled agent toolsets kept in memory per process (**1–100000**). |
| **`APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS`** | For `prod` toolsets with credentials | — | AGX-2.2 vault key map (no `APIOME_MCP_` prefix: it is read by the shared apiome-rest vault code). Must equal apiome-rest's value; without it, a call whose URL has a bound credential fails closed with `upstream_credential_unavailable`. |

## Related files

- **[`../.env.example`](../.env.example)** — copy/paste template for local development.
- **Repository root [`docker-compose.env.example`](../../docker-compose.env.example)** — overrides for **`docker compose`** (Postgres + MCP port + secret).
- **[`LIST_ALWAYS.md`](LIST_ALWAYS.md)** — MTG-2.1 ADR: `tools/list` is never filtered by enable-set (contrast AGX-3.1).
- **[`MOCK_TARGET.md`](MOCK_TARGET.md)** — AGX-2.4: `target: mock` routes agent invocations to the SIM mock (sandbox; no upstream credentials).
- **[`AGX_COORDINATION.md`](AGX_COORDINATION.md)** — MTG-5.5: catalog MCP vs AGX agent tools; shared code must not merge list contracts.
- **[`AGENT_INVOCATION_PROXY.md`](AGENT_INVOCATION_PROXY.md)** — AGX-2.1: the `/agent/mcp` endpoint, request construction, auth injection, timeout/retry budget, error mapping.
- **[`AGENT_INVOCATIONS.md`](AGENT_INVOCATIONS.md)** — AGX-3.3: per-call invocation audit, daily rollups, per-tier retention sweep.
- **[`EFFECTIVE_POLICY.md`](EFFECTIVE_POLICY.md)** — MTG-1.4 effective resolver used by the `tools/call` gate (MTG-2.2).
- **[`ANONYMOUS_CALL_POLICY.md`](ANONYMOUS_CALL_POLICY.md)** — MTG-2.3 ADR: host-tenant anonymous enable-set + matrix.
- **[`POLICY_FRESHNESS.md`](POLICY_FRESHNESS.md)** — MTG-2.5 ADR: per-call DB policy resolve; lag budget `0` (no restart).
