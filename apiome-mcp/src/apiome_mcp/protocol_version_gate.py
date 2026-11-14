"""Protocol-version acceptance for ``/agent/mcp``: the AAU-4.1 ASGI shim (#5714).

The installed SDK decides versions by its own list (``mcp.shared.version``), which serves
2024-11-05 and knows nothing of 2026-07-28. ``docs/PROTOCOL_VERSIONS.md`` records the decision to
keep that SDK and pin the served table here instead, in two layers:

* :class:`ProtocolVersionGateMiddleware` (ASGI, before any body is read) reads
  ``MCP-Protocol-Version``. A value outside
  :data:`~apiome_mcp.protocol_versions.ACCEPTED_PROTOCOL_VERSIONS` is refused with ``400`` and a
  JSON-RPC ``-32022`` error whose ``data.supported`` lists what is accepted — never served at
  another version. An absent header reads as the legacy default (2025-03-26). A modern
  (2026-07-28) value is accepted and handed to the SDK as
  :data:`~apiome_mcp.protocol_versions.SDK_WIRE_VERSION`; the real value is what middleware and
  audit see.
* :class:`ProtocolVersionNegotiationMiddleware` (FastMCP, ``on_initialize``) rewrites an offer
  the handshake cannot serve to :data:`~apiome_mcp.protocol_versions.LATEST_HANDSHAKE_VERSION`
  before the SDK answers, so ``initialize`` never settles on 2024-11-05 nor claims 2026-07-28.

The gate records the accepted version in the request's ASGI ``state``
(:data:`PROTOCOL_VERSION_STATE_KEY`) — a ContextVar set at the ASGI layer would not reach the SDK's
session task, which runs in the context of the session's *first* request.
:class:`ProtocolVersionNegotiationMiddleware` reads it back per message (``on_message``) and binds it
to :func:`current_protocol_version` and to the structlog context (``protocol_version``), so every
later middleware, log line and audit event of the message carries it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from contextvars import ContextVar
from typing import Any

import mcp.types as mt
import structlog
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from structlog.contextvars import bound_contextvars

from apiome_mcp.protocol_versions import (
    ACCEPTED_PROTOCOL_VERSIONS,
    LEGACY_DEFAULT_PROTOCOL_VERSION,
    MODERN_PROTOCOL_VERSIONS,
    PROTOCOL_VERSION_HEADER,
    SDK_WIRE_VERSION,
    UNSUPPORTED_PROTOCOL_VERSION_CODE,
    is_accepted_header_version,
    negotiate_handshake_version,
)

__all__ = [
    "PROTOCOL_VERSION_STATE_KEY",
    "ProtocolVersionGateMiddleware",
    "ProtocolVersionNegotiationMiddleware",
    "current_protocol_version",
    "unsupported_version_body",
]

_log = structlog.get_logger(__name__)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

#: Longest requested value echoed back in a refusal or a log line; a header is client-controlled.
_MAX_ECHOED_CHARS = 64

_HEADER_NAME = PROTOCOL_VERSION_HEADER.encode("latin-1")

#: Key of the accepted version in the request's ASGI ``state`` (``request.scope["state"]``).
PROTOCOL_VERSION_STATE_KEY = "apiome_mcp_protocol_version"

_current_protocol_version: ContextVar[str | None] = ContextVar("apiome_mcp_protocol_version", default=None)


def current_protocol_version() -> str | None:
    """The MCP protocol version of the request being handled, or ``None`` outside one.

    The header's version (the legacy default when absent); for ``initialize``, the version the
    handshake settles on.
    """
    return _current_protocol_version.get()


def _bounded(value: object) -> str:
    """``value`` as a string, cut to :data:`_MAX_ECHOED_CHARS`."""
    return str(value)[:_MAX_ECHOED_CHARS]


def unsupported_version_body(requested: str) -> dict[str, Any]:
    """The JSON-RPC error a refused request receives (the 2026-07-28 ``-32022`` shape).

    Args:
        requested: The refused header value (echoed back cut to 64 characters).

    Returns:
        A JSON-RPC 2.0 error envelope with ``id: null`` (the body was never parsed), whose
        ``data.supported`` lists every accepted version, newest first.
    """
    shown = _bounded(requested)
    supported = list(ACCEPTED_PROTOCOL_VERSIONS)
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": UNSUPPORTED_PROTOCOL_VERSION_CODE,
            "message": f"Unsupported MCP-Protocol-Version {shown!r}; supported: {', '.join(supported)}",
            "data": {"supported": supported, "requested": shown},
        },
    }


def _header_values(scope: Scope) -> list[str]:
    """Every ``MCP-Protocol-Version`` value on the request, in order."""
    values: list[str] = []
    for name, value in scope.get("headers") or []:
        if bytes(name).lower() == _HEADER_NAME:
            values.append(bytes(value).decode("latin-1"))
    return values


def _forwarded_scope(scope: Scope, version: str) -> Scope:
    """A copy of ``scope`` carrying ``version`` in its ``state``, the header rewritten for the SDK if modern.

    The ``state`` dict is copied, never mutated: Uvicorn shares the lifespan state's values with it.
    """
    forwarded: Scope = {**scope, "state": {**(scope.get("state") or {}), PROTOCOL_VERSION_STATE_KEY: version}}
    if version in MODERN_PROTOCOL_VERSIONS:
        headers = [(n, v) for n, v in scope.get("headers") or [] if bytes(n).lower() != _HEADER_NAME]
        headers.append((_HEADER_NAME, SDK_WIRE_VERSION.encode("latin-1")))
        forwarded["headers"] = headers
    return forwarded


def _request_version() -> str | None:
    """The version the gate recorded for the message's HTTP request, or ``None`` (stdio, no gate)."""
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    value = (request.scope.get("state") or {}).get(PROTOCOL_VERSION_STATE_KEY)
    return value if isinstance(value, str) else None


async def _refuse(send: Send, requested: str) -> None:
    """Answer ``400`` with :func:`unsupported_version_body`."""
    body = json.dumps(unsupported_version_body(requested)).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ProtocolVersionGateMiddleware:
    """ASGI middleware: refuse unsupported ``MCP-Protocol-Version`` headers, record the accepted one."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        """Wrap ``app`` (the agent runtime's Starlette app)."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Gate one request; non-HTTP scopes (lifespan) pass through untouched."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        values = _header_values(scope)
        if len(set(values)) > 1:
            # Two different versions on one request: neither can be trusted to be "the" version.
            _log.info("mcp_protocol_version_refused", requested=_bounded(values), reason="conflicting_headers")
            await _refuse(send, ",".join(values))
            return
        version = values[0] if values else LEGACY_DEFAULT_PROTOCOL_VERSION
        if not is_accepted_header_version(version):
            _log.info("mcp_protocol_version_refused", requested=_bounded(version), reason="unsupported")
            await _refuse(send, version)
            return

        token = _current_protocol_version.set(version)
        try:
            await self.app(_forwarded_scope(scope, version), receive, send)
        finally:
            _current_protocol_version.reset(token)


class ProtocolVersionNegotiationMiddleware(Middleware):
    """FastMCP middleware: bind each message's version; keep ``initialize`` inside the served revisions."""

    async def on_message(self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]) -> Any:
        """Bind the version the gate accepted for this message's request, for the message's duration.

        Outside a gated HTTP request (stdio, tests without the gate) nothing is bound.
        """
        version = _request_version()
        if version is None:
            return await call_next(context)
        token = _current_protocol_version.set(version)
        try:
            with bound_contextvars(protocol_version=version):
                return await call_next(context)
        finally:
            _current_protocol_version.reset(token)

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: CallNext[mt.InitializeRequest, mt.InitializeResult | None],
    ) -> mt.InitializeResult | None:
        """Counter-offer the latest handshake revision when the client asked for one not served.

        The SDK echoes the offered version whenever *it* supports it, so the offer itself is
        rewritten before the SDK reads it; the result then carries the served version.
        """
        params = context.message.params
        requested = params.protocolVersion
        negotiated = negotiate_handshake_version(requested)
        if negotiated != requested:
            _log.info("mcp_protocol_version_counter_offered", requested=_bounded(requested), negotiated=negotiated)
            params.protocolVersion = negotiated
        token = _current_protocol_version.set(negotiated)
        try:
            with bound_contextvars(protocol_version=negotiated):
                return await call_next(context)
        finally:
            _current_protocol_version.reset(token)
