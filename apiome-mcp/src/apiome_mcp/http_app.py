"""The streamable-HTTP application ``apiome-mcp serve --transport http`` runs.

One process, one port, two MCP apps that never share a ``tools/list`` (``docs/AGX_COORDINATION.md``):

* ``/mcp`` — the catalog server (:data:`apiome_mcp.server.mcp`), plus ``GET /health``;
* ``/agent/mcp`` — the AGX-2.1 agent runtime (:func:`apiome_mcp.agent_server.build_agent_server`).

Each app keeps its own lifespan (pool, and for the catalog the AGX-3.3 usage sweep); this module only
mounts them side by side and runs both lifespans.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.applications import Starlette
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.routing import Mount

from apiome_mcp.agent_server import AGENT_MCP_MOUNT
from apiome_mcp.http_credential_middleware import HttpCredentialExtractionMiddleware

__all__ = ["MCP_PATH", "build_http_app"]

#: The MCP endpoint path inside each app (catalog at ``/mcp``, agent at ``/agent/mcp``).
MCP_PATH = "/mcp"


def build_http_app(catalog: FastMCP, agent: FastMCP | None) -> Starlette:
    """Mount the catalog app at ``/`` and, when given, the agent app at ``/agent``.

    Args:
        catalog: The catalog FastMCP server.
        agent: The agent runtime, or ``None`` to serve the catalog only.

    Returns:
        The ASGI app to run with Uvicorn (``lifespan="on"``).
    """
    middleware = [StarletteMiddleware(HttpCredentialExtractionMiddleware)]
    catalog_app = catalog.http_app(path=MCP_PATH, transport="streamable-http", middleware=middleware)
    if agent is None:
        return catalog_app
    agent_app = agent.http_app(path=MCP_PATH, transport="streamable-http", middleware=middleware)
    return Starlette(
        routes=[Mount(AGENT_MCP_MOUNT, app=agent_app), Mount("", app=catalog_app)],
        lifespan=combine_lifespans(catalog_app.lifespan, agent_app.lifespan),
    )
