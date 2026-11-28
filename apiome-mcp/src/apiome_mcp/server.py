"""FastMCP application instance (stdio and streamable HTTP via ``apiome-mcp serve``)."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastmcp import Context, FastMCP
from fastmcp.dependencies import Depends
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse
from structlog.contextvars import bound_contextvars

from apiome_mcp.agent_usage_sweep import start_agent_usage_sweep, stop_agent_usage_sweep
from apiome_mcp.audit_writer import running_audit_writer
from apiome_mcp.capability_middleware import CapabilityCallGateMiddleware
from apiome_mcp.catalog_key_gate import McpKeyRequiredMiddleware
from apiome_mcp.database_pool import MCP_DB_POOL_KEY, create_async_pool, get_db_pool, ping_pool
from apiome_mcp.export_tools import build_export_targets_response, build_version_export_response
from apiome_mcp.http_credential_middleware import StashHttpBearerInToolContextMiddleware
from apiome_mcp.logging_config import configure_logging
from apiome_mcp.mcp_auth import McpAuthContext, require_mcp_auth
from apiome_mcp.pact_tools import (
    build_pact_can_i_deploy_response,
    build_pact_list_response,
    build_pact_matrix_response,
    build_pact_record_deployment_response,
)
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
from apiome_mcp.spec_semantic_search_tool import (
    EMBEDDING_HTTP_CLIENT_KEY,
    build_spec_semantic_search_response,
    embedding_http_client,
)

_log = structlog.get_logger(__name__)


@lifespan
async def database_lifespan(server: Any) -> Any:
    """Open the shared async pool at MCP startup; close it on shutdown (including cancellation).

    Also runs the AGX-3.3 agent usage sweep (rollups + retention) in the background while the pool
    is open, unless ``agent_usage_sweep_interval_seconds`` is 0, the batched audit writer
    (DBP-1.21; flushed before the pool closes) and the shared embeddings HTTP client.
    """
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
            sweep = start_agent_usage_sweep(pool, settings)
            try:
                # DBP-1.21: one batched writer for audit rows, one HTTP client for embeddings.
                async with running_audit_writer(pool, settings):
                    async with embedding_http_client(settings) as client:
                        yield {MCP_DB_POOL_KEY: pool, EMBEDDING_HTTP_CLIENT_KEY: client}
            finally:
                await stop_agent_usage_sweep(sweep)
        finally:
            _log.info("database_pool_closing")
            await pool.close()


mcp = FastMCP("Apiome", lifespan=database_lifespan)
# Middleware run order is reversed on the way in (last added runs first).
# Inbound: Stash Bearer → key gate → registry fail-closed → capability gate → tool.
# The key gate refuses every request but initialize/ping without a valid MCP API key.
# MTG-2.1 (#4770): never strip tools from tools/list by enable-set (contrast AGX-3.1).
# MTG-5.5 (#4789): do not merge AGX list-filtering into catalog middleware — AGX_COORDINATION.md.
# MTG-2.2 (#4771): call-time enable-set gate after auth resolve.
mcp.add_middleware(CapabilityCallGateMiddleware())
mcp.add_middleware(RegistryFailClosedMiddleware())
mcp.add_middleware(McpKeyRequiredMiddleware())
mcp.add_middleware(StashHttpBearerInToolContextMiddleware())


@mcp.custom_route("/health", methods=["GET"])
async def _http_health(_request: Request) -> JSONResponse:
    """Liveness probe for load balancers and Docker HEALTHCHECK (HTTP 200; does not query Postgres)."""
    return JSONResponse({"status": "ok"})


@mcp.tool
async def ping(ctx: Context) -> dict[str, Any]:
    """Smoke-test: service name, package version, Postgres reachability, UTC timestamp. Requires an MCP API key."""
    pool = get_db_pool(ctx)
    return await build_ping_response(pool)


@mcp.tool(
    name="spec.list",
    description=(
        "List published OpenAPI specs with cursor pagination. Requires an MCP API key: results merge "
        "in-scope public rows (apiome.mcp_v_public_specs) plus in-scope private revisions for the key's "
        "tenant (#3011). "
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
    )


@mcp.tool(
    name="project.list",
    description=(
        "List distinct projects (tenant + project) that have at least one published spec revision the "
        "caller can see. Requires an MCP API key: merges in-scope public rows (apiome.mcp_v_public_specs) "
        "plus in-scope private published revisions for the key's tenant (same scope rules as spec.list). "
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
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_project_list_response(
        pool,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        auth_ctx=auth,
    )


@mcp.tool(
    name="export.targets",
    description=(
        "List every registered export target for an artifact version (MFX-40.1): each target's descriptor "
        "(key, format, label), its fidelity tier and preserved share for this source, its options schema and "
        "defaults. Requires an API key; exports within the key's tenant and scope. Pass a target key to "
        "version.export. artifact: the artifact / project id; version: a revision id or label (latest when omitted)."
    ),
)
async def export_targets(
    ctx: Context,
    artifact: str,
    version: str | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    return await build_export_targets_response(auth_ctx=auth, artifact=artifact, version=version)


@mcp.tool(
    name="version.export",
    description=(
        "Export an artifact version to any registered target (MFX-40.1) — the same pipeline as the Export "
        "dialog and `apiome export`. Returns the job's state, the structured fidelity report (fidelity.summary "
        "tier/preserved share, fidelity.report: the per-construct LossinessReport, fidelity.advisory), the "
        "transcoding guard, and the files: inline `content` when small (contentInline), otherwise a REST "
        "downloadPath. `advisory` is the canonical fidelity advisory — the same words the UI and CLI show. A "
        "conversion that loses fidelity (tier other than lossless) emits nothing unless allow_lossy=true: it answers "
        "state=blocked with the report and the advisory, so read them first (MFX-40.2). A severe conversion also "
        "fails unless confirm=true. When the job outlives the wait it answers state=running with jobId: call again "
        "with job_id to collect it. Requires an API key."
    ),
)
async def version_export(
    ctx: Context,
    artifact: str | None = None,
    target: str | None = None,
    version: str | None = None,
    options: dict[str, Any] | None = None,
    confirm: bool = False,
    allow_lossy: bool = False,
    job_id: str | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    return await build_version_export_response(
        auth_ctx=auth,
        artifact=artifact,
        target=target,
        version=version,
        options=options,
        confirm=confirm,
        allow_lossy=allow_lossy,
        job_id=job_id,
    )


@mcp.tool(
    name="spec.list_my_specs",
    description=(
        "List OpenAPI spec revisions this MCP API key can read: in-scope public catalog rows "
        "(apiome.mcp_v_public_specs) plus in-scope private published revisions for the key's tenant "
        "(same rules as spec.list). Requires an MCP API key. "
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
        "Requires an MCP API key: in-scope public revisions (apiome.mcp_v_public_specs) and in-scope "
        "private published revisions for the key's tenant (#3012). "
        "Raises not-found when the revision is missing, out of scope, or not accessible."
    ),
)
async def spec_describe(
    ctx: Context,
    spec_id: str,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_describe_response(pool, spec_id=spec_id, auth_ctx=auth)


@mcp.tool(
    name="spec.get_openapi",
    description=(
        "Return the generated OpenAPI 3.1 document (JSON object) for a published spec revision by id (UUID). "
        "Matches the REST schema export shape (paths, components.schemas, servers, securitySchemes). "
        "Requires an MCP API key: in-scope public and private published revisions for the key's tenant (#3016). "
        "Raises not-found when inaccessible. If the serialized document exceeds the configured byte cap "
        "(APIOME_MCP_OPENAPI_MAX_JSON_BYTES), returns an error analogous to HTTP 413."
    ),
)
async def spec_get_openapi(
    ctx: Context,
    spec_id: str,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_get_openapi_response(pool, spec_id=spec_id, auth_ctx=auth)


@mcp.tool(
    name="spec.export_yaml",
    description=(
        "Return the generated OpenAPI 3.1 document as YAML text for a published spec revision by id (UUID). "
        "Same semantics as spec.get_openapi: requires an MCP API key; in-scope public and private published "
        "revisions are included (#3017). "
        "Response field openapi_yaml round-trips with YAML loaders to the same structure as the JSON tool. "
        "If UTF-8 YAML exceeds APIOME_MCP_OPENAPI_MAX_JSON_BYTES (default 2 MiB), returns an error "
        "analogous to HTTP 413."
    ),
)
async def spec_export_yaml(
    ctx: Context,
    spec_id: str,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, str]:
    pool = get_db_pool(ctx)
    return await build_spec_export_yaml_response(pool, spec_id=spec_id, auth_ctx=auth)


@mcp.tool(
    name="spec.list_operations",
    description=(
        "Return a compact index of HTTP operations for a published spec revision by id (UUID): "
        "each item has path, method, operation_id, summary, and tags. Sorted by path then method. "
        "Same visibility and auth rules as spec.get_openapi: requires an MCP API key; in-scope public and "
        "private published revisions are included (#3018). "
        "Does not return the full OpenAPI document."
    ),
)
async def spec_list_operations(
    ctx: Context,
    spec_id: str,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> list[dict[str, Any]]:
    pool = get_db_pool(ctx)
    return await build_spec_list_operations_response(pool, spec_id=spec_id, auth_ctx=auth)


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
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, list[str]]:
    pool = get_db_pool(ctx)
    return await build_spec_list_components_response(pool, spec_id=spec_id, auth_ctx=auth)


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
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> Any:
    pool = get_db_pool(ctx)
    return await build_spec_describe_component_response(
        pool,
        spec_id=spec_id,
        kind=kind,
        name=name,
        auth_ctx=auth,
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
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_describe_operation_response(
        pool,
        spec_id=spec_id,
        path=path,
        method=method,
        auth_ctx=auth,
    )


@mcp.tool(
    name="spec.search",
    description=(
        "Search published public OpenAPI specs with Postgres full-text search (english config) over "
        "project title, revision description, version label, and tag names (maintained in "
        "apiome.versions.mcp_public_doc_tsv). Required q must be non-empty after trimming and is passed "
        "to plainto_tsquery. Results use ts_rank_cd with cursor pagination: limit defaults to 50, "
        "capped at 100; pass next_cursor from the previous response for the next page. "
        "Requires an MCP API key."
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
        "next_cursor). Returns the 200 nearest specs at most: has_more is false on the page that reaches "
        "them. Rows without embeddings are omitted until backfilled. Requires an MCP API key."
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
        http_client=ctx.lifespan_context.get(EMBEDDING_HTTP_CLIENT_KEY),
    )


@mcp.tool(
    name="spec.list_tags",
    description=(
        "Distinct version-tag names across published public OpenAPI specs with counts of specs "
        "that expose each tag. Sorted by count descending, then tag name ascending. Counts are "
        "refreshed about every 45 seconds. Cursor pagination: limit defaults to 50, capped at 100; "
        "pass next_cursor from the previous response for the next page. Requires an MCP API key."
    ),
)
async def spec_list_tags(
    ctx: Context,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    pool = get_db_pool(ctx)
    return await build_spec_list_tags_response(pool, limit=limit, cursor=cursor)


# PFX-4.5 (#6942): the workspace's Pact Broker. Reads need the key owner's pacts:view; recording a
# deployment needs pacts:create. Pacts are workspace-wide: a project-limited key is refused.
_PACT_READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


@mcp.tool(
    name="pact.list",
    description=(
        "List the latest pact of every consumer -> provider integration in the key's workspace (PFX-4.5): consumer, "
        "provider, consumerVersion, sha, specificationVersion, interactionCount, publishedAt and the pact's "
        "latestVerification (success, verifiedAt, providerVersion, kind) or null. No pact content. Optional "
        "provider / consumer filters (handle, id or name). limit 1-100 (default 50); pass nextCursor as cursor for "
        "the next page. Requires an MCP API key without a project limit, whose owner has pacts:view."
        " Refused (mcp-pact-agent-action-off) when the workspace has switched agent reads off "
        "(Contracts → Settings → Agents)."
    ),
    annotations=_PACT_READ,
)
async def pact_list(
    provider: str | None = None,
    consumer: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    return await build_pact_list_response(
        auth_ctx=auth, provider=provider, consumer=consumer, limit=limit, cursor=cursor
    )


@mcp.tool(
    name="pact.matrix",
    description=(
        "Pact Broker matrix query (PFX-4.5; what pact-broker can-i-deploy asks). selectors: [{pacticipant, version?, "
        "latest?, tag?, branch?, environment?, main_branch?}] - one selector with a destination asks 'can I deploy "
        "this?', two or more ask 'do these work together?'. Destination: to_environment, to_tag (with latest=true), "
        "latest, or main_branch. latestby: cvp | cvpv | cp. ignore: ['Name' or {pacticipant, version?}]. Answers "
        "summary.deployable (true / false / null = a verification result is missing; retryAfterSeconds says when to "
        "ask again), summary.reason, notices [{type, code, text}] and at most max_rows (1-100, default 50) compact "
        "rows with rowsTotal / rowsTruncated; the verdict always reads every row. Unknown selector keys are "
        "refused. Requires pacts:view."
        " Refused (mcp-pact-agent-action-off) when the workspace has switched agent reads off "
        "(Contracts → Settings → Agents)."
    ),
    annotations=_PACT_READ,
)
async def pact_matrix(
    selectors: list[dict[str, Any]],
    latestby: str | None = None,
    to_environment: str | None = None,
    to_tag: str | None = None,
    latest: bool | None = None,
    main_branch: bool | None = None,
    ignore: list[Any] | None = None,
    limit: int | None = None,
    max_rows: int | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    return await build_pact_matrix_response(
        auth_ctx=auth,
        selectors=selectors,
        latestby=latestby,
        to_environment=to_environment,
        to_tag=to_tag,
        latest=latest,
        main_branch=main_branch,
        ignore=ignore,
        limit=limit,
        max_rows=max_rows,
    )


@mcp.tool(
    name="pact.can_i_deploy",
    description=(
        "Can this pacticipant version be deployed? (PFX-4.5; pact-broker can-i-deploy). pacticipant and version name "
        "what is deployed; give exactly one of to_environment (checked against everything currently deployed to or "
        "released in it) or to_tag (the latest version of each other pacticipant with that tag). ignore leaves "
        "pacticipants out of the verdict. Same answer as pact.matrix: read summary.deployable (true / false / null "
        "while a result is missing - retry after retryAfterSeconds), summary.reason and notices; at most max_rows "
        "rows. Requires pacts:view."
        " Refused (mcp-pact-agent-action-off) when the workspace has switched agent reads off "
        "(Contracts → Settings → Agents)."
    ),
    annotations=_PACT_READ,
)
async def pact_can_i_deploy(
    pacticipant: str,
    version: str,
    to_environment: str | None = None,
    to_tag: str | None = None,
    ignore: list[Any] | None = None,
    max_rows: int | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    return await build_pact_can_i_deploy_response(
        auth_ctx=auth,
        pacticipant=pacticipant,
        version=version,
        to_environment=to_environment,
        to_tag=to_tag,
        ignore=ignore,
        max_rows=max_rows,
    )


@mcp.tool(
    name="pact.record_deployment",
    description=(
        "WRITE: record that a pacticipant version is now deployed to an environment (PFX-4.5; pact-broker "
        "record-deployment). environment is the environment's name; application_instance names the instance "
        "(region, customer) when the environment has several. The pacticipant's previous deployment there is "
        "marked undeployed. Answers {created, deployment}; created=false when it already was the current "
        "deployment. The version must already be recorded (published a pact or verified one). Requires an MCP API "
        "key whose owner has pacts:create. The workspace must allow agents to record deployments (Contracts → "
        "Settings → Agents; off by default), and an agent never records to an environment marked production "
        "(mcp-pact-agent-production); every refusal is audited."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def pact_record_deployment(
    pacticipant: str,
    version: str,
    environment: str,
    application_instance: str | None = None,
    auth: McpAuthContext = Depends(require_mcp_auth),
) -> dict[str, Any]:
    return await build_pact_record_deployment_response(
        auth_ctx=auth,
        pacticipant=pacticipant,
        version=version,
        environment=environment,
        application_instance=application_instance,
    )
