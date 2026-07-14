"""FastMCP application instance (stdio and streamable HTTP via ``apiome-mcp serve``)."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastmcp import Context, FastMCP
from fastmcp.dependencies import CurrentHeaders, Depends
from fastmcp.server.lifespan import lifespan
from starlette.requests import Request
from starlette.responses import JSONResponse
from structlog.contextvars import bound_contextvars

from apiome_mcp.database_pool import MCP_DB_POOL_KEY, create_async_pool, get_db_pool, ping_pool
from apiome_mcp.http_credential_middleware import StashHttpBearerInToolContextMiddleware
from apiome_mcp.logging_config import configure_logging
from apiome_mcp.mcp_auth import McpAuthContext, require_mcp_auth, resolve_optional_mcp_auth
from apiome_mcp.ping_tool import build_ping_response
from apiome_mcp.project_list_tool import build_project_list_response
from apiome_mcp.registry_middleware import RegistryFailClosedMiddleware
from apiome_mcp.settings import get_settings
from apiome_mcp.spec_describe_component_tool import build_spec_describe_component_response
from apiome_mcp.spec_describe_operation_tool import build_spec_describe_operation_response
from apiome_mcp.spec_describe_tool import build_spec_describe_response
from apiome_mcp.spec_export_yaml_tool import build_spec_export_yaml_response
from apiome_mcp.spec_get_openapi_tool import build_spec_get_openapi_response
from apiome_mcp.spec_list_components_tool import build_spec_list_components_response
from apiome_mcp.spec_list_operations_tool import build_spec_list_operations_response
from apiome_mcp.spec_list_tags_tool import build_spec_list_tags_response
from apiome_mcp.spec_list_tool import build_spec_list_response
from apiome_mcp.spec_search_tool import build_spec_search_response
from apiome_mcp.spec_semantic_search_tool import build_spec_semantic_search_response

_log = structlog.get_logger(__name__)


@lifespan
async def database_lifespan(server: Any) -> Any:
    """Open the shared async pool at MCP startup; close it on shutdown (including cancellation)."""
    settings = get_settings()
    configure_logging(settings)
    with bound_contextvars(request_id=str(uuid.uuid4()), tool_name="lifespan.database"):
        pool = create_async_pool(settings, open=False)
        try:
            _log.info("database_pool_opening")
            await pool.open()
            try:
                await ping_pool(pool)
                _log.info("database_pool_ready")
            except Exception as exc:
                _log.warning("database_pool_probe_failed_at_startup", error=str(exc))
            yield {MCP_DB_POOL_KEY: pool}
        finally:
            _log.info("database_pool_closing")
            await pool.close()


mcp = FastMCP("Apiome", lifespan=database_lifespan)
# MTG-2.1 (#4770): middleware must never strip tools from tools/list by enable-set
# (contrast AGX-3.1). Registry gate + call-time capability (MTG-2.2) act on tools/call only.
mcp.add_middleware(RegistryFailClosedMiddleware())
mcp.add_middleware(StashHttpBearerInToolContextMiddleware())


@mcp.custom_route("/health", methods=["GET"])
async def _http_health(_request: Request) -> JSONResponse:
    """Liveness probe for load balancers and Docker HEALTHCHECK (HTTP 200; does not query Postgres)."""
    return JSONResponse({"status": "ok"})


@mcp.tool
async def ping(ctx: Context) -> dict[str, Any]:
    """Smoke-test: service name, package version, Postgres reachability, UTC timestamp."""
    pool = get_db_pool(ctx)
    return await build_ping_response(pool)


@mcp.tool(
    name="spec.list",
    description=(
        "List published OpenAPI specs with cursor pagination. Anonymous callers see the public catalog "
        "(apiome.mcp_v_public_specs). With Authorization: Bearer <MCP API key> (or stdio meta credentials), "
        "results merge in-scope public rows plus in-scope private revisions for the key's tenant (#3011). "
        "Optional filters: tenant_id, project_id (UUID strings). "
        "limit defaults to 50, capped at 100. Pass next_cursor from the previous response for the next page."
    ),
)
async def spec_list(
    ctx: Context,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_list_response(
        pool,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        auth_ctx=auth_ctx,
    )


@mcp.tool(
    name="project.list",
    description=(
        "List distinct projects (tenant + project) that have at least one published spec revision the "
        "caller can see. Anonymous: derived from the public catalog (apiome.mcp_v_public_specs). "
        "With Authorization: Bearer <MCP API key>, merges in-scope public rows plus in-scope private "
        "published revisions for the key's tenant (same scope rules as spec.list). "
        "Each item: tenant_id, project_id, title, updated_at (UTC Z; latest revision activity in scope). "
        "Optional filters: tenant_id, project_id (UUID strings). limit defaults to 50, capped at 100. "
        "Pass next_cursor from the previous response for the next page."
    ),
)
async def project_list(
    ctx: Context,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_project_list_response(
        pool,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        auth_ctx=auth_ctx,
    )


@mcp.tool(
    name="spec.list_my_specs",
    description=(
        "List OpenAPI spec revisions this MCP API key can read: in-scope public catalog rows "
        "(apiome.mcp_v_public_specs) plus in-scope private published revisions for the key's tenant "
        "(same rules as spec.list when authenticated). Requires API key — anonymous calls are rejected. "
        "Response shape matches spec.list: items, has_more, next_cursor. "
        "Optional tenant_id / project_id (UUID strings). limit defaults to 50, capped at 100 (#3014)."
    ),
)
async def spec_list_my_specs(
    ctx: Context,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_list_response(
        pool,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        auth_ctx=auth,
        private_access_audit_tool="spec.list_my_specs",
    )


@mcp.tool(
    name="spec.describe",
    description=(
        "Return metadata for a single published OpenAPI spec revision by id (UUID). "
        "Fields: id, title, version, description, owner (tenant slug), tags, updated_at (UTC Z). "
        "Anonymous callers see public revisions only (apiome.mcp_v_public_specs). "
        "With Authorization: Bearer <MCP API key> (or stdio meta credentials), in-scope private "
        "published revisions for the key's tenant are included (#3012). "
        "Raises not-found when the revision is missing, out of scope, or not accessible."
    ),
)
async def spec_describe(
    ctx: Context,
    spec_id: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_describe_response(pool, spec_id=spec_id, auth_ctx=auth_ctx)


@mcp.tool(
    name="spec.get_openapi",
    description=(
        "Return the generated OpenAPI 3.1 document (JSON object) for a published spec revision by id (UUID). "
        "Matches the REST schema export shape (paths, components.schemas, servers, securitySchemes). "
        "Anonymous callers: public revisions only. With Authorization: Bearer <MCP API key>, in-scope private "
        "published revisions for the tenant are included (#3016). "
        "Raises not-found when inaccessible. If the serialized document exceeds the configured byte cap "
        "(APIOME_MCP_OPENAPI_MAX_JSON_BYTES), returns an error analogous to HTTP 413."
    ),
)
async def spec_get_openapi(
    ctx: Context,
    spec_id: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_get_openapi_response(pool, spec_id=spec_id, auth_ctx=auth_ctx)


@mcp.tool(
    name="spec.export_yaml",
    description=(
        "Return the generated OpenAPI 3.1 document as YAML text for a published spec revision by id (UUID). "
        "Same semantics as spec.get_openapi: anonymous callers see public revisions only; with "
        "Authorization: Bearer <MCP API key>, in-scope private published revisions are included (#3017). "
        "Response field openapi_yaml round-trips with YAML loaders to the same structure as the JSON tool. "
        "If UTF-8 YAML exceeds APIOME_MCP_OPENAPI_MAX_JSON_BYTES (default 2 MiB), returns an error "
        "analogous to HTTP 413."
    ),
)
async def spec_export_yaml(
    ctx: Context,
    spec_id: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, str]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_export_yaml_response(pool, spec_id=spec_id, auth_ctx=auth_ctx)


@mcp.tool(
    name="spec.list_operations",
    description=(
        "Return a compact index of HTTP operations for a published spec revision by id (UUID): "
        "each item has path, method, operation_id, summary, and tags. Sorted by path then method. "
        "Same visibility and auth rules as spec.get_openapi: anonymous callers see public revisions only; "
        "with Authorization: Bearer <MCP API key>, in-scope private published revisions are included (#3018). "
        "Does not return the full OpenAPI document."
    ),
)
async def spec_list_operations(
    ctx: Context,
    spec_id: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> list[dict[str, Any]]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_list_operations_response(pool, spec_id=spec_id, auth_ctx=auth_ctx)


@mcp.tool(
    name="spec.list_components",
    description=(
        "Return OpenAPI component names for a published spec revision by id (UUID), grouped by kind: "
        "schemas, parameters, responses, securitySchemes. Each kind maps to a sorted list of "
        "component keys; kinds with no entries are omitted. Same visibility and auth rules as "
        "spec.get_openapi (#3020)."
    ),
)
async def spec_list_components(
    ctx: Context,
    spec_id: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, list[str]]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_list_components_response(pool, spec_id=spec_id, auth_ctx=auth_ctx)


@mcp.tool(
    name="spec.describe_component",
    description=(
        "Return one OpenAPI component definition for a published spec revision by id (UUID): ``kind`` is "
        "schemas, parameters, responses, or securitySchemes (same grouping as spec.list_components); ``name`` "
        "is the component key in that section. Internal ``#/…`` ``$ref`` values are expanded; external refs "
        "are left as-is. Same visibility and auth rules as spec.get_openapi (#3021). Raises not-found for "
        "inaccessible revisions or unknown kind/name."
    ),
)
async def spec_describe_component(
    ctx: Context,
    spec_id: str,
    kind: str,
    name: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> Any:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_describe_component_response(
        pool,
        spec_id=spec_id,
        kind=kind,
        name=name,
        auth_ctx=auth_ctx,
    )


@mcp.tool(
    name="spec.describe_operation",
    description=(
        "Return OpenAPI fragments for one HTTP operation on a published spec revision: ``parameters`` "
        "(path-item + operation merge, operation wins same name/in), ``requestBody``, ``responses``, "
        "and ``security`` (operation override or document default). Internal ``#/…`` ``$ref`` values "
        "are expanded; external refs are left as-is. Same visibility and auth rules as "
        "spec.get_openapi (#3019). Raises not-found for inaccessible revisions or unknown path/method."
    ),
)
async def spec_describe_operation(
    ctx: Context,
    spec_id: str,
    path: str,
    method: str,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    auth_ctx = await resolve_optional_mcp_auth(ctx, pool, headers=headers)
    return await build_spec_describe_operation_response(
        pool,
        spec_id=spec_id,
        path=path,
        method=method,
        auth_ctx=auth_ctx,
    )


@mcp.tool(
    name="spec.search",
    description=(
        "Search published public OpenAPI specs with Postgres full-text search (english config) over "
        "project title, revision description, version label, and tag names (maintained in "
        "apiome.versions.mcp_public_doc_tsv). Required q must be non-empty after trimming and is passed "
        "to plainto_tsquery. Results use ts_rank_cd with cursor pagination: limit defaults to 50, "
        "capped at 100; pass next_cursor from the previous response for the next page."
    ),
)
async def spec_search(
    ctx: Context,
    q: str,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_search_response(pool, q=q, limit=limit, cursor=cursor)


@mcp.tool(
    name="spec.search_semantic",
    description=(
        "Semantic search over published **public** specs that have **mcp_public_embedding** populated "
        "(pgvector cosine distance vs OpenAI-compatible query embeddings). Requires "
        "APIOME_MCP_OPENAI_API_KEY. Uses the same pagination shape as spec.search (items, has_more, "
        "next_cursor). Rows without embeddings are omitted until backfilled."
    ),
)
async def spec_search_semantic(
    ctx: Context,
    q: str,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    settings = get_settings()
    return await build_spec_semantic_search_response(
        pool,
        settings=settings,
        q=q,
        limit=limit,
        cursor=cursor,
    )


@mcp.tool(
    name="spec.list_tags",
    description=(
        "Distinct version-tag names across published public OpenAPI specs with counts of specs "
        "that expose each tag (via apiome.mcp_v_public_specs). Sorted by count descending, "
        "then tag name ascending. Cursor pagination: limit defaults to 50, capped at 100; "
        "pass next_cursor from the previous response for the next page."
    ),
)
async def spec_list_tags(
    ctx: Context,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_list_tags_response(pool, limit=limit, cursor=cursor)
