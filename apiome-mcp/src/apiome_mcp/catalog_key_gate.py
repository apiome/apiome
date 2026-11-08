"""Catalog key gate — no MCP API key, no access.

Every request to the catalog server (:data:`apiome_mcp.server.mcp`) must present a valid MCP
API key: ``tools/list`` and every ``tools/call``, on HTTP and on stdio alike. Only the
``initialize`` handshake and the protocol ``ping`` pass without one — a host has to connect
before it can send a key, and neither returns catalog data.

A direct in-process call (``await mcp.list_tools()`` from server code or tests) is not a client
request — it has no MCP request context and no HTTP request — and is not gated. An HTTP request is
always gated, session or not.

The key is verified once here and recorded for the request
(:func:`~apiome_mcp.mcp_auth.bind_current_mcp_auth`), so the capability gate and the tools'
:func:`~apiome_mcp.mcp_auth.require_mcp_auth` reuse it instead of checking bcrypt again.

A refusal is a JSON-RPC error with code :data:`MCP_KEY_REJECTED_CODE`. A failure to verify
(database unreachable, anything unexpected) fails closed.
"""

from __future__ import annotations

from typing import Any

import mcp.types as mt
import structlog
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import McpError

from apiome_mcp.database_pool import get_db_pool
from apiome_mcp.mcp_auth import (
    MCP_KEY_REQUIRED_MESSAGE,
    bind_current_mcp_auth,
    current_mcp_auth,
    on_http_request,
    presented_mcp_api_key,
    reset_current_mcp_auth,
    validate_mcp_api_key,
)

_log = structlog.get_logger(__name__)

__all__ = ["MCP_KEY_REJECTED_CODE", "McpKeyRequiredError", "McpKeyRequiredMiddleware"]

#: JSON-RPC error code for a missing or unusable MCP API key (server-defined range).
MCP_KEY_REJECTED_CODE = -32001

#: Methods that need no key: the handshake and the protocol liveness check.
_KEYLESS_METHODS = frozenset({"initialize", "ping"})


def _is_in_process(fc: Any) -> bool:
    """True for a direct server call: no MCP request context and no HTTP request in flight."""
    request_context = fc.request_context if fc is not None else None
    return request_context is None and not on_http_request()


class McpKeyRequiredError(McpError):
    """The request carried no usable MCP API key. FastMCP returns it as a JSON-RPC error."""

    def __init__(self, message: str, *, code: int = MCP_KEY_REJECTED_CODE) -> None:
        super().__init__(mt.ErrorData(code=code, message=message))


class McpKeyRequiredMiddleware(Middleware):
    """Refuse every catalog request but ``initialize`` / ``ping`` without a valid MCP API key."""

    async def on_request(
        self,
        context: MiddlewareContext[mt.Request[Any, Any]],
        call_next: CallNext[mt.Request[Any, Any], Any],
    ) -> Any:
        if context.method in _KEYLESS_METHODS:
            return await call_next(context)

        # A request nested in one already verified — the MCP SDK re-runs tools/list inside
        # tools/call to look the tool up — rides on that verification.
        if current_mcp_auth() is not None:
            return await call_next(context)
        fc = context.fastmcp_context
        if _is_in_process(fc):
            return await call_next(context)
        try:
            secret = await presented_mcp_api_key(fc, headers=get_http_headers(include={"authorization"}))
            if secret is None or fc is None:
                raise McpKeyRequiredError(MCP_KEY_REQUIRED_MESSAGE)
            auth = await validate_mcp_api_key(get_db_pool(fc), secret)
        except McpKeyRequiredError:
            _log.info("mcp_key_missing", method=context.method)
            raise
        except AuthorizationError as rejected:
            _log.info("mcp_key_rejected", method=context.method, reason=str(rejected))
            raise McpKeyRequiredError(str(rejected)) from None
        except Exception:
            _log.warning("mcp_key_verification_unavailable", method=context.method, exc_info=True)
            raise McpKeyRequiredError(
                "The MCP API key could not be verified; try again later.",
                code=mt.INTERNAL_ERROR,
            ) from None

        token = bind_current_mcp_auth(auth)
        try:
            return await call_next(context)
        finally:
            reset_current_mcp_auth(token)
