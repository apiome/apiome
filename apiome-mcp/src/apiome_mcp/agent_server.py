"""AGX-2.1 agent runtime — the Apiome-hosted MCP endpoint agents call tenant APIs through (#4533).

``apiome-mcp serve --transport http`` serves two MCP apps from one process:

* ``/mcp`` — the catalog server (:mod:`apiome_mcp.server`, MTG): discover and read published specs;
* ``/agent/mcp`` — this agent runtime (AGX): an agent key's toolset as callable MCP tools.

The two never share a ``tools/list`` (``docs/AGX_COORDINATION.md``). This app carries, in run order,

1. :class:`~apiome_mcp.http_credential_middleware.StashHttpBearerInToolContextMiddleware`;
2. :class:`~apiome_mcp.agent_access.AgentAccessMiddleware` (AGX-3.1) — verifies the agent key and
   narrows ``tools/list`` / ``tools/call`` to the permitted tools;
3. :class:`~apiome_mcp.agent_quotas.AgentQuotaMiddleware` (AGX-3.2) — RPS and daily caps;
4. :class:`AgentToolsetProvider` — serves the key's toolset, compiled per toolset
   (:mod:`apiome_mcp.agent_toolset_source`), each tool an :class:`AgentTool` whose ``run`` is the
   AGX-2.1 invocation proxy (:class:`~apiome_mcp.agent_invocation_proxy.InvocationProxy`).

The tools are **per request**: one process serves every tenant's toolsets, and which tools exist
depends on the key presented. So the MCP SDK's process-wide tool cache is switched off for this app
(:func:`_disable_sdk_tool_cache`): it would mix tenants' definitions, and a cache miss re-runs
``tools/list`` (key verification included) inside every call. Argument validation is the proxy's own,
against the key's toolset.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

import httpx
import mcp.types as mt
import structlog
from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.server.lifespan import lifespan
from fastmcp.server.providers import Provider
from fastmcp.tools.base import Tool, ToolResult
from fastmcp.utilities.versions import VersionSpec
from pydantic import PrivateAttr
from structlog.contextvars import bound_contextvars

from apiome_mcp.agent_access import (
    AgentAccessDeniedError,
    AgentAccessMiddleware,
    AgentAccessReason,
    current_agent_access,
)
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
from apiome_mcp.agent_safety_rails import build_upstream_client, described_with_idempotency, tool_annotations
from apiome_mcp.agent_toolset_source import (
    ServedTool,
    ServedToolset,
    ServedToolsetCache,
    ToolsetSourceUnavailableError,
    load_served_toolset,
)
from apiome_mcp.database_pool import MCP_DB_POOL_KEY, create_async_pool, get_db_pool, ping_pool
from apiome_mcp.http_credential_middleware import StashHttpBearerInToolContextMiddleware
from apiome_mcp.logging_config import configure_logging
from apiome_mcp.settings import Settings, get_settings

_log = structlog.get_logger(__name__)

__all__ = [
    "AGENT_HTTP_CLIENT_KEY",
    "AGENT_MCP_MOUNT",
    "AgentTool",
    "AgentToolsetProvider",
    "agent_lifespan",
    "build_agent_server",
    "get_agent_http_client",
]

#: Lifespan-context key of the shared upstream HTTP client.
AGENT_HTTP_CLIENT_KEY = "agent_http_client"

#: Where the agent app is mounted on the HTTP server; its MCP endpoint is ``{mount}/mcp``.
AGENT_MCP_MOUNT = "/agent"


def _http_client(settings: Settings) -> httpx.AsyncClient:
    """The upstream client: SSRF-guarded except for the mock root, no redirects, pooled (AGX-2.3)."""
    return build_upstream_client(
        mock_base_url=InvocationConfig.from_settings(settings).mock_base_url,
        timeout_seconds=settings.agent_upstream_timeout_seconds,
        allow_private=settings.agent_upstream_allow_private,
    )


@lifespan
async def agent_lifespan(server: Any) -> Any:
    """Open the agent runtime's Postgres pool and upstream HTTP client; close both on shutdown.

    The catalog server's lifespan runs the AGX-3.3 usage sweep; this one does not, so a process
    serving both runs one sweep.
    """
    settings = get_settings()
    configure_logging(settings)
    with bound_contextvars(request_id=str(uuid.uuid4()), tool_name="lifespan.agent"):
        pool = create_async_pool(settings, open=False)
        await pool.open()
        try:
            try:
                await ping_pool(pool)
            except Exception as exc:
                _log.warning("agent_database_pool_probe_failed_at_startup", error=str(exc))
            async with _http_client(settings) as client:
                yield {MCP_DB_POOL_KEY: pool, AGENT_HTTP_CLIENT_KEY: client}
        finally:
            await pool.close()


def get_agent_http_client(ctx: Context) -> httpx.AsyncClient:
    """The shared upstream HTTP client from the agent lifespan."""
    raw = ctx.lifespan_context.get(AGENT_HTTP_CLIENT_KEY)
    if raw is None:
        raise RuntimeError("Agent HTTP client is not available (lifespan not initialized?)")
    return cast(httpx.AsyncClient, raw)


class AgentTool(Tool):
    """One served tool of an agent key's toolset; calling it runs the invocation proxy."""

    _toolset: ServedToolset = PrivateAttr()
    _served: ServedTool = PrivateAttr()
    _proxy: InvocationProxy = PrivateAttr()

    @classmethod
    def for_served(cls, toolset: ServedToolset, served: ServedTool, proxy: InvocationProxy) -> AgentTool:
        """The MCP tool for ``served``: its compiled name, description and ``inputSchema``.

        No ``outputSchema`` is declared (AGX-1.1): a declared one would oblige every result,
        including errors, to conform. The MCP annotations and, for a write tool, the idempotency
        note come from the AGX-1.2 ``write_op`` flag (AGX-2.3).
        """
        definition = served.definition
        write_op = definition.operation in toolset.manifest.write_ops
        method = served.binding.method if served.binding is not None else None
        tool = cls(
            name=definition.name,
            description=described_with_idempotency(definition.description, write_op=write_op, method=method),
            parameters=definition.input_schema,
            annotations=tool_annotations(write_op=write_op, method=method),
        )
        tool._toolset = toolset
        tool._served = served
        tool._proxy = proxy
        return tool

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Invoke the tool for the request's verified agent key."""
        access = current_agent_access()
        if access is None:
            raise AgentAccessDeniedError(AgentAccessReason.KEY_MISSING)
        ctx = get_context()
        return await self._proxy.invoke(
            pool=get_db_pool(ctx),
            client=get_agent_http_client(ctx),
            key=access.key,
            toolset=self._toolset,
            tool=self._served,
            arguments=arguments,
        )


class AgentToolsetProvider(Provider):
    """Serves the tools of the request's agent key's toolset.

    Without a verified key (no :func:`current_agent_access`) it serves nothing. A toolset that is
    missing, disabled, unpublished or whose source no longer compiles fails closed with
    ``agent_toolset_unavailable``.
    """

    def __init__(self, proxy: InvocationProxy, *, cache: ServedToolsetCache | None = None) -> None:
        """Serve through ``proxy``; ``cache`` holds compiled toolsets (default: a fresh one)."""
        super().__init__()
        self._proxy = proxy
        self._cache = cache or ServedToolsetCache()

    async def _served(self) -> ServedToolset | None:
        """The request's served toolset, or ``None`` outside an agent request."""
        access = current_agent_access()
        if access is None:
            return None
        key = access.key
        try:
            served = await load_served_toolset(get_db_pool(get_context()), self._cache, key.tenant_id, key.toolset_id)
        except ToolsetSourceUnavailableError as exc:
            _log.warning("agent_toolset_source_unavailable", toolset_id=key.toolset_id, error=str(exc))
            raise AgentAccessDeniedError(AgentAccessReason.TOOLSET_UNAVAILABLE) from None
        if served is None:
            raise AgentAccessDeniedError(AgentAccessReason.TOOLSET_UNAVAILABLE)
        return served

    async def _list_tools(self) -> Sequence[Tool]:
        """Every tool of the served toolset (the access middleware narrows it to the permitted ones)."""
        served = await self._served()
        if served is None:
            return []
        return [AgentTool.for_served(served, tool, self._proxy) for tool in served.tools.values()]

    async def _get_tool(self, name: str, version: VersionSpec | None = None) -> Tool | None:
        """The served tool named ``name``, if the toolset has it."""
        served = await self._served()
        tool = served.tools.get(name) if served is not None else None
        return AgentTool.for_served(served, tool, self._proxy) if served is not None and tool is not None else None


class _DiscardingToolCache(dict[str, mt.Tool]):
    """A dict that never stores anything: the MCP SDK's tool cache, switched off."""

    def __setitem__(self, key: str, value: mt.Tool) -> None:
        """Drop the write."""


def _disable_sdk_tool_cache(app: FastMCP) -> None:
    """Stop the MCP SDK from caching tool definitions process-wide for ``app`` (see module docstring)."""
    low_level = app._mcp_server

    async def no_cached_definition(tool_name: str) -> mt.Tool | None:
        return None

    low_level._tool_cache = _DiscardingToolCache()
    setattr(low_level, "_get_cached_tool_definition", no_cached_definition)


def build_agent_server(
    *,
    settings: Settings | None = None,
    proxy: InvocationProxy | None = None,
    access: AgentAccessMiddleware | None = None,
    quota: AgentQuotaMiddleware | None = None,
    server_lifespan: Any = agent_lifespan,
) -> FastMCP:
    """Build the agent runtime's FastMCP app.

    Args:
        settings: Process settings (default: :func:`get_settings`, read lazily only when needed).
        proxy: The invocation proxy (default: from settings).
        access: The access middleware (default: agent keys from ``api_keys``, toolsets from AGX-1.2).
        quota: The quota middleware (default: a guard from settings).
        server_lifespan: The lifespan (tests pass their own pool and client).

    Returns:
        The app. Mount its HTTP app at :data:`AGENT_MCP_MOUNT`.
    """
    if proxy is None or quota is None:
        settings = settings or get_settings()
    proxy = proxy or InvocationProxy(InvocationConfig.from_settings(cast(Settings, settings)))
    cache_size = settings.agent_toolset_cache_size if settings is not None else None
    provider = AgentToolsetProvider(proxy, cache=ServedToolsetCache(cache_size) if cache_size else None)
    app = FastMCP(
        "Apiome agent runtime",
        lifespan=server_lifespan,
        providers=[provider],
        strict_input_validation=False,
        # Compiled input schemas are already self-contained (AGX-1.1 inlines every ref).
        dereference_schemas=False,
    )
    app.add_middleware(StashHttpBearerInToolContextMiddleware())
    app.add_middleware(access or AgentAccessMiddleware())
    app.add_middleware(quota or AgentQuotaMiddleware(guard=AgentQuotaGuard.from_settings(cast(Settings, settings))))
    _disable_sdk_tool_cache(app)
    return app
