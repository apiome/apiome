"""MCP transport client over the legacy HTTP+SSE transport (V2-MCP-16.5, #3661).

Some MCP servers still speak the transport of the
`2024-11-05 revision <https://modelcontextprotocol.io/specification/2024-11-05/basic/transports>`_,
which the Streamable HTTP transport (:mod:`app.mcp_client.transport_http`) replaced. It
uses **two endpoints** instead of one:

1. **The SSE endpoint.** The client opens a long-lived ``GET`` with
   ``Accept: text/event-stream``. The server's first event is an ``endpoint`` event
   whose ``data`` is the URI the client must ``POST`` its messages to (typically
   ``/messages?session_id=…``).
2. **The message endpoint.** Every JSON-RPC request and notification is ``POST``\\ ed
   there. The server acknowledges the POST (usually ``202 Accepted``) and delivers the
   *response* as a ``message`` event on the SSE stream opened in step 1.

:class:`LegacySseTransport` presents the same interface as
:class:`~app.mcp_client.transport_http.StreamableHttpTransport` — ``request``,
``notify``, ``aclose``, ``protocol_version``, ``transcript``, ``observed_transport`` —
so the handshake and discovery layers drive it unchanged. It subclasses the Streamable
HTTP transport to reuse its transport-security rules (no plaintext ``http://`` to a
non-loopback host, the SSRF guard), its HTTP status taxonomy, its JSON-RPC parsing and
its protocol-transcript recording.

What it adds, and the safeguards around it:

* **Same-origin message endpoint.** The ``endpoint`` URI is resolved against the SSE
  URL and must share its scheme, host and port. A server cannot steer the client's
  POSTs — which carry the endpoint's auth headers — to another host.
* **The first event must be ``endpoint``.** A stream that opens with anything else,
  or closes before announcing one, is not the legacy transport
  (:class:`McpLegacySseError`).
* **One request at a time.** Responses arrive on a single shared stream; a lock keeps
  requests sequential, which is how discovery and invocation already run.
* **No sessions to end.** The legacy transport has no ``Mcp-Session-Id`` and no
  ``DELETE``; closing the transport closes the stream.

Choosing between the two transports — and the automatic fallback from Streamable HTTP
when a server answers with the legacy transport's signature — lives in
:mod:`app.mcp_client.connect`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional, Tuple, Union

import httpx

from .transport_http import (
    PROTOCOL_VERSION_HEADER,
    SESSION_ID_HEADER,
    SSE_DEFAULT_EVENT,
    JsonRpcResponse,
    McpProtocolError,
    ServerMessageHandler,
    StreamableHttpTransport,
    _origin_of,
    iter_sse_events,
)

logger = logging.getLogger(__name__)

#: The MCP revision whose transport this module speaks.
LEGACY_PROTOCOL_VERSION = "2024-11-05"

#: The SSE event type a legacy server opens its stream with; its data is the POST URI.
ENDPOINT_EVENT = "endpoint"

_SSE_MEDIA_TYPE = "text/event-stream"
_JSON_MEDIA_TYPE = "application/json"


class McpLegacySseError(McpProtocolError):
    """The server did not behave like the legacy HTTP+SSE transport.

    Raised when the ``GET`` is not answered with an event stream, the stream's first
    event is not ``endpoint``, the announced endpoint is cross-origin or empty, or the
    stream closes before delivering a response. A subclass of
    :class:`~app.mcp_client.transport_http.McpProtocolError`, so the discovery error
    taxonomy classifies it as a protocol failure without special handling.
    """


@dataclass
class LegacySseTransport(StreamableHttpTransport):
    """A JSON-RPC client over the MCP 2024-11-05 HTTP+SSE transport.

    Typical use::

        async with LegacySseTransport("https://example.com/sse") as t:
            init = await t.request("initialize", {...})  # opens the stream first
            tools = await t.request("tools/list", {})
        # leaving the context closes the stream and the owned HTTP client

    Args:
        url: The SSE endpoint the client ``GET``\\ s (``…/sse``). Every constructor
            argument of :class:`StreamableHttpTransport` applies, with the same
            security defaults.
        protocol_version: Defaults to :data:`LEGACY_PROTOCOL_VERSION`; the handshake
            overwrites it with the negotiated version.
    """

    protocol_version: str = LEGACY_PROTOCOL_VERSION

    # --- internal state (not constructor arguments) ------------------------
    _post_url: Optional[str] = field(default=None, init=False)
    _stream: Optional[httpx.Response] = field(default=None, init=False)
    _events: Optional[AsyncIterator[Tuple[str, str]]] = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def message_url(self) -> Optional[str]:
        """The absolute URL messages are POSTed to, once the server announced it."""
        return self._post_url

    @property
    def connected(self) -> bool:
        """True once the SSE stream is open and its ``endpoint`` event was received."""
        return self._post_url is not None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def __aenter__(self) -> "LegacySseTransport":
        return self

    async def connect(self) -> str:
        """Open the SSE stream and wait for the server's ``endpoint`` event (idempotent).

        Called automatically by the first :meth:`request` or :meth:`notify`.

        Returns:
            The absolute, same-origin URL messages will be POSTed to.

        Raises:
            McpHttpStatusError: The ``GET`` was answered with an error status (``401``
                as :class:`~app.mcp_client.transport_http.McpAuthRequiredError`, and so on).
            McpLegacySseError: The answer was not an event stream, or did not open with
                a usable ``endpoint`` event.
        """
        if self._post_url is not None:
            return self._post_url
        assert self.client is not None  # set in __post_init__

        started = time.monotonic()
        http_request = self.client.build_request("GET", self.url, headers=self._stream_headers())
        response = await self.client.send(http_request, stream=True)
        self._stream = response
        try:
            self._maybe_capture_transport(response, time.monotonic() - started)
            await self._raise_for_status(response)
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media_type != _SSE_MEDIA_TYPE:
                raise McpLegacySseError(
                    f"expected {_SSE_MEDIA_TYPE} from the SSE endpoint, got "
                    f"'{media_type or '(none)'}'"
                )
            self._events = iter_sse_events(response).__aiter__()
            event_type, data = await self._next_event()
            if event_type != ENDPOINT_EVENT:
                raise McpLegacySseError(
                    f"the SSE stream opened with a '{event_type}' event; expected '{ENDPOINT_EVENT}'"
                )
            self._post_url = self._resolve_endpoint(data)
        except BaseException:
            await self._close_stream()
            raise
        logger.debug("legacy MCP SSE stream open; messages go to %s", self._post_url)
        return self._post_url

    async def aclose(self) -> None:
        """Close the SSE stream, then the owned HTTP client. There is no session to end."""
        try:
            await self._close_stream()
        finally:
            await super().aclose()

    # ------------------------------------------------------------------
    # JSON-RPC operations
    # ------------------------------------------------------------------
    async def request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        request_id: Optional[Union[str, int]] = None,
        on_server_message: Optional[ServerMessageHandler] = None,
    ) -> JsonRpcResponse:
        """POST a JSON-RPC request and return the response the server sends on the stream.

        Args:
            method: The JSON-RPC method (e.g. ``"initialize"``, ``"tools/list"``).
            params: The method parameters; omitted from the envelope when ``None``.
            request_id: Override the auto-generated request id (mostly for tests).
            on_server_message: Optional handler for server-initiated requests or
                notifications that arrive on the stream before the response. Without it
                they are logged and dropped.

        Returns:
            The :class:`JsonRpcResponse` answering this request.

        Raises:
            McpHttpStatusError: The POST was answered with an error status.
            McpLegacySseError: The stream misbehaved or closed before the response.
            McpProtocolError: A message on the stream was not valid JSON-RPC.
        """
        async with self._lock:
            await self.connect()
            rpc_id: Union[str, int] = request_id if request_id is not None else next(self._id_counter)
            payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
            if params is not None:
                payload["params"] = params

            status = await self._post_message(payload, is_request=True)
            result = await self._await_response(rpc_id, on_server_message)

        # Same observational recording as Streamable HTTP; the POST's status is what the
        # server answered the request itself with.
        if self.transcript is not None:
            self.transcript.record(
                method,
                request_id=rpc_id,
                params=params,
                http_status=status,
                envelope=result.raw,
            )
        if method == "initialize" and not result.is_error:
            self._initialized = True
        return result

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """POST a JSON-RPC notification. The server acknowledges it; nothing comes back.

        Args:
            method: The notification method (e.g. ``"notifications/initialized"``).
            params: Optional parameters; omitted from the envelope when ``None``.

        Raises:
            McpHttpStatusError: The POST was answered with an error status.
        """
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        async with self._lock:
            await self.connect()
            await self._post_message(payload, is_request=False)

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    async def _post_message(self, payload: Dict[str, Any], *, is_request: bool) -> int:
        """POST one envelope to the message endpoint and return the acknowledging status.

        Any ``2xx`` is an acknowledgement (``202 Accepted`` per spec; some servers answer
        ``200`` with a short text body); its body is ignored because the response travels
        on the stream. An error status raises through the shared status taxonomy.
        """
        assert self.client is not None and self._post_url is not None
        http_request = self.client.build_request(
            "POST",
            self._post_url,
            headers=self._build_headers(is_request=is_request),
            content=_json_bytes(payload),
        )
        response = await self.client.send(http_request, stream=True)
        try:
            await self._raise_for_status(response)
            return response.status_code
        finally:
            await response.aclose()

    async def _await_response(
        self, rpc_id: Union[str, int], on_server_message: Optional[ServerMessageHandler]
    ) -> JsonRpcResponse:
        """Read ``message`` events until the response to ``rpc_id`` arrives."""
        while True:
            event_type, data = await self._next_event()
            if event_type != SSE_DEFAULT_EVENT:
                logger.debug("ignoring legacy MCP SSE '%s' event", event_type)
                continue
            message = self._parse_json_rpc(data)
            if self._is_response_for(message, rpc_id):
                return JsonRpcResponse.from_dict(message)
            await self._dispatch_server_message(message, on_server_message)

    async def _next_event(self) -> Tuple[str, str]:
        """The next event on the stream; :class:`McpLegacySseError` when it has closed."""
        assert self._events is not None
        try:
            return await self._events.__anext__()
        except StopAsyncIteration:
            raise McpLegacySseError("the SSE stream closed before the expected event") from None

    def _resolve_endpoint(self, data: str) -> str:
        """Resolve the ``endpoint`` event's URI against the SSE URL and require same origin.

        Args:
            data: The event's data: an absolute URL or a path relative to the SSE URL.

        Returns:
            The absolute message URL.

        Raises:
            McpLegacySseError: The URI is empty or points at another scheme, host or port.
        """
        announced = data.strip()
        if not announced:
            raise McpLegacySseError("the server's 'endpoint' event carried no URI")
        base = httpx.URL(self.url)
        resolved = base.join(announced)
        if _origin_of(resolved) != _origin_of(base):
            raise McpLegacySseError(
                f"refusing the cross-origin message endpoint '{resolved}'; it must share "
                f"the SSE endpoint's origin '{_origin_of(base)}'"
            )
        return str(resolved)

    def _stream_headers(self) -> Dict[str, str]:
        """Headers for the ``GET`` that opens the stream: SSE accept, Origin, extra headers."""
        headers: Dict[str, str] = {"Accept": _SSE_MEDIA_TYPE}
        if self.origin:
            headers["Origin"] = self.origin
        headers.update(self.headers)
        return headers

    def _build_headers(self, *, is_request: bool) -> Dict[str, str]:
        """Headers for a POST: JSON in, no Streamable-HTTP-only headers.

        ``MCP-Protocol-Version`` and ``Mcp-Session-Id`` belong to the Streamable HTTP
        transport and are never sent here.
        """
        headers = super()._build_headers(is_request=is_request)
        headers["Accept"] = _JSON_MEDIA_TYPE
        headers.pop(PROTOCOL_VERSION_HEADER, None)
        headers.pop(SESSION_ID_HEADER, None)
        headers.update(self.headers)
        return headers

    async def _close_stream(self) -> None:
        """Close the SSE response, if open, and forget the stream state."""
        stream, self._stream, self._events = self._stream, None, None
        if stream is not None:
            await stream.aclose()


def _json_bytes(payload: Dict[str, Any]) -> bytes:
    """Encode a JSON-RPC envelope for the wire."""
    return json.dumps(payload).encode("utf-8")
