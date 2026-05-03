# Objectified 06-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## MCP

- **`objectified-mcp/README.md`** local quickstart: **`uv sync`**, **`.env`** (**`OBJECTIFIED_MCP_DATABASE_URL`**, **`OBJECTIFIED_MCP_INTERNAL_SECRET`**), **`uv run objectified-mcp serve --transport stdio`** or **`--transport http`**; optional Postgres+migrate via **`docker compose`** without the MCP image (#3026).
- **`objectified-mcp/docs/CONFIGURATION.md`** documents every **`OBJECTIFIED_MCP_*`** variable (required vs optional, defaults, bounds); **`objectified-mcp/.env.example`** lists the same surface for copy/paste (#3025).
- Root **`docker-compose.yml`** spins up **Postgres 16** (named volume **`objectified_postgres_data`**), a one-shot **`migrate`** image (**`objectified-db`** / schema-evolution-manager), and **`mcp`** (HTTP on **`8765`** by default); use **`docker compose up --build --wait`** from the repo root. Env overrides: **`docker-compose.env.example`** (#3024).
- Multi-stage **`objectified-mcp/Dockerfile`** (uv builder + slim runtime, non-root user, **`GET /health`** liveness + **`HEALTHCHECK`**) — build from repo root: **`docker build -f objectified-mcp/Dockerfile .`** (#3023).
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
- MCP tool **`spec.search`** keyword-searches public specs (**ILIKE** over title, description, and tag names); **`q`** must be non-empty after trimming; results include **`rank_score`** and use the same **`limit`** / **`next_cursor`** pagination pattern as **`spec.list`** (#3007).
- MCP tool **`spec.list_tags`** returns distinct public-spec tag names with usage counts as **`[{tag, count}, …]`**, sorted by count descending (then tag name ascending); results are cached in-process for **60 seconds** (#3008).
- MCP **`authorize_spec`** combines API key **scope** with revision **visibility** (public rows need scope only; private rows also require the spec tenant to match the key); **`build_authorized_spec_sql_predicate`** emits the same rules as a parameterized SQL **`WHERE`** fragment (#3010).
- MCP **`spec.list`** with a valid API key merges **in-scope public** rows with **in-scope private** published revisions for the key's tenant (same **`items`** / **`has_more`** / **`next_cursor`** shape as anonymous listing); **`resolve_optional_mcp_auth`** resolves credentials from headers, **`tools/call`** meta, or the HTTP Bearer stash (#3011).
- MCP **`spec.describe`** uses the same optional auth path: anonymous callers resolve **public** revisions only; with a valid API key, **in-scope private** published revisions for that tenant return the same metadata shape (**`id`**, **`title`**, **`version`**, **`description`**, **`owner`**, **`tags`**, **`updated_at`**); missing or inaccessible revisions stay **not-found** (#3012).
- Database table **`odb.mcp_access_audit`** records MCP API key **`key_id`**, tool name, **`spec_id`** (revision UUID), timestamp **`at`**, **`success`**, and optional **`error`** for traceability; **`spec.list`** and **`spec.describe`** enqueue **non-blocking** inserts after each **private** revision returned to an authenticated caller (#3013).
- MCP tool **`spec.list_my_specs`** lists specs readable by the **current API key only** (same merged public/private semantics and pagination as authenticated **`spec.list`**); calls **without** a key are rejected (**`Depends(require_mcp_auth)`**); private rows are audited under tool name **`spec.list_my_specs`** (#3014).
- MCP tool **`spec.get_openapi`** returns the generated **OpenAPI 3.1** document as JSON for a published revision UUID (same shape as REST **`GET /v1/schema/{tenant}/{project}/{version}`**): anonymous callers get **public** revisions only; with an MCP API key, **in-scope private** revisions are included; responses larger than **`OBJECTIFIED_MCP_OPENAPI_MAX_JSON_BYTES`** (default **2 MiB**) are rejected with an error described as **HTTP 413** (#3016).
- MCP tool **`spec.export_yaml`** returns the same generated document as **`openapi_yaml`** YAML text (REST-aligned **`yaml.dump`** settings); visibility, auth, private access audit, and UTF-8 size cap match **`spec.get_openapi`** (#3017).
- MCP tool **`spec.list_operations`** returns a compact **`[{path, method, operation_id, summary, tags}, …]`** index for a revision UUID (sorted by path then method), with the same visibility and auth rules as **`spec.get_openapi`**, without returning the full OpenAPI document; private reads are audited as **`spec.list_operations`** (#3018).
- MCP tool **`spec.list_components`** returns OpenAPI **`components`** keys grouped by kind (**`schemas`**, **`parameters`**, **`responses`**, **`securitySchemes`**): each kind maps to a sorted list of names, and empty kinds are omitted; visibility, auth, and private audit match **`spec.get_openapi`** (#3020).
- MCP tool **`spec.describe_component`** returns the resolved definition for one **`components.[kind].[name]`** (same **`kind`** values as **`spec.list_components`**); internal **`#/…`** **`$ref`** values are expanded; unknown **`kind`**, unknown **`name`**, or inaccessible revisions are **not-found**; visibility, auth, and private audit match **`spec.get_openapi`** (#3021).
- MCP tool **`spec.describe_operation`** returns **`parameters`** (merged path + operation), **`requestBody`**, **`responses`**, and **`security`** for a revision UUID and **`path`** / **`method`**; internal **`#/…`** **`$ref`** values are expanded; unknown paths or methods are **not-found**; visibility, auth, and private audit match **`spec.get_openapi`** (#3019).

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

