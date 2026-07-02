"""HTTP credential extraction for streamable MCP (#3000).

Parses ``Authorization: Bearer …`` at the ASGI boundary and exposes the secret to
tools via FastMCP ``Context`` request-scoped state (never session-persisted).

- Missing or non-Bearer ``Authorization`` → tools see ``None`` (anonymous).
- Bearer present → tools read the credential string with ``get_http_bearer_from_context``.
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from typing import Any, cast

import mcp.types as mt
from fastmcp import Context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

_MCP_HTTP_BEARER_TOKEN_KEY = "apiome_mcp_http_bearer_token"

_AUTH_BEARER_PREFIX = re.compile(r"(?i)^Bearer\s+")

_current_http_bearer_token: ContextVar[str | None] = ContextVar(
    "apiome_mcp_http_bearer_token",
    default=None,
)


def http_bearer_token_state_key() -> str:
    """State key tools pass to ``ctx.get_state`` for the stashed Bearer secret."""
    return _MCP_HTTP_BEARER_TOKEN_KEY


def bearer_secret_from_authorization_header(value: str | None) -> str | None:
    """Return Bearer credential from an ``Authorization`` header value, else ``None``.

    Non-Bearer schemes and empty tokens yield ``None`` so callers treat the request
    as anonymous at this layer.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if not _AUTH_BEARER_PREFIX.match(stripped):
        return None
    parts = stripped.split(None, 1)
    if len(parts) < 2:
        return None
    secret = parts[1].strip()
    return secret or None


def _authorization_from_scope(scope: dict[str, Any]) -> str | None:
    raw_headers = scope.get("headers") or []
    for name_b, value_b in raw_headers:
        try:
            name = name_b.decode("latin-1").lower()
        except (AttributeError, UnicodeDecodeError):
            continue
        if name == "authorization":
            try:
                return cast(str, value_b.decode("latin-1"))
            except (AttributeError, UnicodeDecodeError):
                return None
    return None


class HttpCredentialExtractionMiddleware:
    """ASGI middleware: bind per-request Bearer token to a ``ContextVar``."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        bearer = bearer_secret_from_authorization_header(_authorization_from_scope(scope))
        token: Token[str | None] = _current_http_bearer_token.set(bearer)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_http_bearer_token.reset(token)


class StashHttpBearerInToolContextMiddleware(Middleware):
    """FastMCP middleware: copy ASGI-extracted Bearer into tool ``Context`` (request-scoped)."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        fc = context.fastmcp_context
        if fc is not None:
            await fc.set_state(
                _MCP_HTTP_BEARER_TOKEN_KEY,
                _current_http_bearer_token.get(),
                serializable=False,
            )
        return await call_next(context)


async def get_http_bearer_from_context(ctx: Context) -> str | None:
    """Return the Bearer secret stashed for this HTTP tool call, or ``None`` if anonymous."""
    value = await ctx.get_state(_MCP_HTTP_BEARER_TOKEN_KEY)
    return cast(str | None, value)
