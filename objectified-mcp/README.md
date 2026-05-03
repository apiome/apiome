# objectified-mcp

Python **FastMCP** service for exposing Objectified OpenAPI specifications over the Model Context Protocol.

## Local quickstart (uv, no MCP container)

Use **[uv](https://docs.astral.sh/uv/)** with **Python ≥ 3.11**. Environment variables are loaded from **`.env`** in your **current working directory**—run commands from **`objectified-mcp/`** after **`cd`**.

### Database

The server needs PostgreSQL with the Objectified schema applied. Startup fails if the connection pool cannot open; a failed initial `SELECT 1` probe only logs a warning and the server continues.

**Option A — Docker from the repository root** (Postgres + migrations only; does not start the MCP image):

```bash
docker compose up -d postgres && docker compose run --rm migrate
```

With default **`docker-compose.yml`** credentials, set **`OBJECTIFIED_MCP_DATABASE_URL`** to:

`postgresql://postgres:objectified_local_dev@localhost:5432/objectified`

**Option B — Your own cluster** — use any migrated database URI in **`OBJECTIFIED_MCP_DATABASE_URL`**.

### Install, env, and run

After the database is ready:

```bash
cd objectified-mcp
uv sync
cp .env.example .env
```

Edit **`.env`**: set **`OBJECTIFIED_MCP_DATABASE_URL`** and **`OBJECTIFIED_MCP_INTERNAL_SECRET`** (minimum **16** characters). Every **`OBJECTIFIED_MCP_*`** variable is documented in **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

**Stdio** (Claude Desktop, MCP Inspector):

```bash
uv run objectified-mcp serve --transport stdio
```

**HTTP** (streamable MCP at **`http://<host>:<port>/mcp`**; bind **`OBJECTIFIED_MCP_HTTP_HOST`** / **`OBJECTIFIED_MCP_HTTP_PORT`** or **`--host`** / **`--port`**):

```bash
uv run objectified-mcp serve --transport http
```

**`uv run objectified-mcp serve`** without **`--transport`** loads settings and exits—use that to verify **`.env`** after edits. Stop a running server with **Ctrl+C** or **`SIGTERM`** (HTTP uses graceful uvicorn shutdown).

## Configuration

Full reference (defaults, bounds, required flags) is **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**—it mirrors **`objectified_mcp.settings.Settings`**.

### Docker Compose (Postgres + migrations + MCP)

From the **repository root**, **`docker compose up --build --wait`** starts Postgres 16 with a persistent volume, applies **`objectified-db`** migrations once, then runs the MCP image on **`8765`** (override with **`OBJECTIFIED_MCP_HTTP_PORT`**). Optional env overrides are documented in [**`docker-compose.env.example`**](../docker-compose.env.example) at the repo root.

When the MCP runtime starts, it opens a shared **`psycopg_pool.AsyncConnectionPool`**, runs **`SELECT 1`** against it, exposes the pool on FastMCP lifespan context under **`db_pool`**, and **`await pool.close()`** in **`finally`** so shutdown (including EOF on stdio or task cancellation) tears down connections cleanly. Pool sizing is controlled with **`OBJECTIFIED_MCP_DATABASE_POOL_MIN_SIZE`**, **`OBJECTIFIED_MCP_DATABASE_POOL_MAX_SIZE`**, and **`OBJECTIFIED_MCP_DATABASE_POOL_TIMEOUT`** (seconds to wait for a connection).

## API key read scope

`odb.mcp_api_keys.scope_json` stores **`{"tenants": [...], "projects": [...]}`** (UUID strings). The Python type is **`objectified_mcp.scope.Scope`**: empty **`tenants`** means any tenant; empty **`projects`** means any project within the tenant constraint; **`Scope.allows(tenant_id, project_id)`** returns whether a read is permitted. Parse DB payloads with **`parse_scope_json`**.

## Logging

Logs go to **stderr** as **JSON** (via **structlog**), one object per line. Each line includes **`timestamp`** (UTC ISO-8601), **`level`**, **`event`**, **`request_id`**, and **`tool_name`** (use **`structlog.contextvars.bound_contextvars`** around MCP tool handlers so tool calls carry the RPC id and tool name). Root verbosity is set with **`OBJECTIFIED_MCP_LOG_LEVEL`** (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
