# Objectified 06-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## MCP

- New `objectified-mcp` Python package (FastMCP, uv, ruff, mypy) as the foundation for the Model Context Protocol server.
- MCP server loads typed configuration from the environment via pydantic-settings (`objectified-mcp serve`); **`objectified-mcp serve --transport stdio`** runs the FastMCP stdio transport for Claude Desktop and similar hosts; **`objectified-mcp serve --transport http`** exposes streamable HTTP at **`/mcp`** with configurable **`--host`** / **`--port`** (or env defaults); see `objectified-mcp/.env.example`.
- MCP runtime opens a shared async Postgres pool (psycopg 3) at startup, exposes it to tools via lifespan context, runs a health probe (`SELECT 1`), and closes the pool cleanly on shutdown.
- MCP process logs are structured JSON on stderr (structlog): each line includes `timestamp`, `level`, `event`, `request_id`, and `tool_name`; verbosity is controlled with `OBJECTIFIED_MCP_LOG_LEVEL`.
- MCP **`ping`** tool returns service id, package version, UTC timestamp, and **`db_ok`** (Postgres `SELECT 1` via the shared pool); on failure **`db_ok`** is false and **`db_error`** carries the exception message.
- Database migration adds **`odb.mcp_api_keys`** for MCP API key storage (hashed secret, lookup prefix, tenant, JSON scopes, lifecycle timestamps).
- MCP tools can require Postgres-backed API keys via FastMCP **`Depends(require_mcp_auth)`**: accepts **`Authorization: Bearer`** on HTTP or **`tools/call` `_meta`** on stdio, verifies bcrypt(SHA-256(secret)) against **`odb.mcp_api_keys`**, and returns a typed scope payload (clear errors for missing auth, unknown keys, expiry, and revocation).
- Streamable HTTP binds **`Authorization: Bearer`** per request into tool context (**`get_http_bearer_from_context`**) via ASGI middleware plus FastMCP middleware; requests without a Bearer token expose **`None`** (anonymous).
- MCP API key **`scope_json`** uses a typed **`Scope`** model (`tenants` / `projects` string lists, JSONB): empty lists mean no restriction at that level; **`scope.allows(tenant_id, project_id)`** gates reads (#3001).
- Successful MCP API key authentication updates **`last_used_at`** in Postgres asynchronously (non-blocking); **`objectified-mcp keys revoke <prefix>`** (also **`mcp keys revoke …`** via the `mcp` console alias) revokes active keys by stored prefix (#3002).
- Database view **`odb.mcp_v_public_specs`** exposes published, public schema revisions for MCP discovery (project title, semantic version, description, sorted tag names, timestamps); dev checklist data lives in **`objectified-db/fixtures/mcp_public_specs_dev.sql`** (#3004).
- MCP tool **`spec.list`** lists public specs from that view with optional **`tenant_id`** / **`project_id`** filters, **`limit`** (default 50, max 100), and stable base64url **cursor** pagination (**`next_cursor`**) (#3005).
- MCP tool **`spec.describe`** loads one public spec by revision UUID and returns **`id`**, **`title`**, **`version`**, **`description`**, **`owner`** (tenant slug), **`tags`**, and **`updated_at`** (UTC **`Z`**); missing, unpublished, or private revisions surface as not-found (#3006).

## Importing
- Race condition fixed in 3.0.1 specification imports
- Import supports Swagger 2.0 format
- Adds the ability to import multiple versions of the same project 

## Repositories
- Recent imports from repository metrics are now displayed
- Imports tab now shows the previously imported files from the repository
- Files in the imports tab now leads to the original file that was imported

---

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: May 2, 2026*

