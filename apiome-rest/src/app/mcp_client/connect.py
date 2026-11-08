"""Open an initialized MCP session over the right transport (V2-MCP-16.5, #3661).

An endpoint's ``transport`` column says how to reach it, but many servers registered as
``streamable_http`` — the default — actually speak the legacy 2024-11-05 HTTP+SSE
transport. :func:`open_session` hides that choice from its callers (discovery and the
capability test harness):

* **``transport='sse'``** — the legacy transport is used directly.
* **Anything else** — Streamable HTTP is tried first. If the ``initialize`` POST is
  answered with the legacy transport's *signature* — one of the statuses in
  :data:`FALLBACK_STATUS_CODES`, which a server without a POST handler on that URL
  returns — the client falls back to the legacy transport on the same URL, as the MCP
  spec's
  `backwards-compatibility guidance <https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#backwards-compatibility>`_
  describes: ``GET`` the URL and expect an SSE stream that opens with an ``endpoint``
  event.

An authentication challenge (``401``), a refusal (``403``) or rate limiting (``429``)
is *not* a transport signature: those mean the right transport answered and said no, so
they surface unchanged rather than triggering a second attempt.

When the fallback cannot even open a legacy stream (the ``GET`` errors, or the reply is
not an SSE stream with an ``endpoint`` event), the server speaks neither transport and
the **original** Streamable HTTP error is raised — it says more about what went wrong
than the failed probe does. Once the legacy stream is open, any later failure is the
legacy server's own and is raised as is.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Tuple

import httpx

from .handshake import InitializeResult, initialize_session
from .transport_http import McpHttpStatusError, McpTransportError, StreamableHttpTransport
from .transport_sse import LegacySseTransport

logger = logging.getLogger(__name__)

#: The ``mcp_endpoints.transport`` value that selects the legacy transport directly.
TRANSPORT_SSE = "sse"

#: Statuses on the Streamable HTTP ``initialize`` POST that mean "this URL does not take
#: Streamable HTTP POSTs": bad request, not found, method not allowed, not acceptable,
#: unsupported media type. Any of them triggers the fallback to the legacy transport.
FALLBACK_STATUS_CODES = frozenset({400, 404, 405, 406, 415})


async def open_session(
    url: str,
    *,
    transport: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = 30.0,
    allow_insecure_http: bool = False,
    allow_private_network: bool = False,
    transcript: Optional[Any] = None,
) -> Tuple[StreamableHttpTransport, InitializeResult]:
    """Connect to ``url``, run the ``initialize`` handshake, and return the live session.

    The caller owns the returned transport and must ``aclose`` it (it is an async context
    manager). On failure, everything this function opened is closed before it raises.

    Args:
        url: The endpoint URL: the single Streamable HTTP endpoint, or the legacy SSE
            endpoint.
        transport: The endpoint's stored transport. ``"sse"`` selects the legacy
            transport; any other value (or ``None``) tries Streamable HTTP with fallback.
        headers: Extra headers (typically auth) sent on every request.
        client: An httpx client to use (tests); when omitted each transport owns one.
        timeout: Per-request timeout in seconds (ignored when ``client`` is given).
        allow_insecure_http: Permit plaintext ``http://`` to non-loopback hosts.
        allow_private_network: Permit an endpoint host that is a private IP literal.
        transcript: Optional protocol-transcript recorder attached to the transport.

    Returns:
        ``(transport, initialize_result)``. ``isinstance(transport, LegacySseTransport)``
        tells the caller which transport the server spoke.

    Raises:
        McpTransportError: Construction refused the URL (scheme, SSRF guard), the
            server failed at the transport level, or the handshake failed; see
            :func:`app.mcp_client.errors.classify_exception` for the taxonomy.
    """
    options = {
        "headers": dict(headers) if headers else {},
        "client": client,
        "timeout": timeout,
        "allow_insecure_http": allow_insecure_http,
        "allow_private_network": allow_private_network,
        "transcript": transcript,
    }
    if transport == TRANSPORT_SSE:
        return await _initialize(LegacySseTransport(url, **options))

    try:
        return await _initialize(StreamableHttpTransport(url, **options))
    except McpHttpStatusError as streamable_error:
        if not is_fallback_signature(streamable_error):
            raise
        logger.info(
            "MCP endpoint answered Streamable HTTP with HTTP %s; trying the legacy HTTP+SSE transport",
            streamable_error.status_code,
        )
        legacy = LegacySseTransport(url, **options)
        try:
            await legacy.connect()
        except McpTransportError:
            await legacy.aclose()
            # The server speaks neither transport; the first answer is the informative one.
            raise streamable_error from None
        return await _initialize(legacy)


def is_fallback_signature(error: McpHttpStatusError) -> bool:
    """True when a Streamable HTTP failure looks like a legacy HTTP+SSE server.

    Args:
        error: The status error the Streamable HTTP ``initialize`` raised.

    Returns:
        True for a status in :data:`FALLBACK_STATUS_CODES` that is not a session expiry.
    """
    return type(error) is McpHttpStatusError and error.status_code in FALLBACK_STATUS_CODES


async def _initialize(
    transport: StreamableHttpTransport,
) -> Tuple[StreamableHttpTransport, InitializeResult]:
    """Run the handshake over ``transport``, closing it if the handshake fails."""
    try:
        return transport, await initialize_session(transport)
    except BaseException:
        await transport.aclose()
        raise
