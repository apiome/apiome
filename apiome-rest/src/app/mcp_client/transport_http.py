"""MCP transport client over Streamable HTTP (V2-MCP-16.1, #3657).

This is the network foundation of the MCP discovery client: it speaks
`JSON-RPC 2.0 <https://www.jsonrpc.org/specification>`_ to a single external MCP
endpoint using the **Streamable HTTP** transport defined by the MCP spec,
`2025-06-18 <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>`_.

What the spec requires of a client, and how this module satisfies it:

* **Single endpoint, POST per message.** Every JSON-RPC request/notification is
  ``POST``ed to one ``…/mcp`` URL with
  ``Accept: application/json, text/event-stream`` so the server may answer either
  with a single JSON object or with a Server-Sent-Events (SSE) stream.
* **Two response shapes.** A ``200`` with ``application/json`` carries one
  JSON-RPC message; a ``200`` with ``text/event-stream`` carries a sequence of
  SSE ``message`` events, each whose ``data`` is one JSON-RPC message. We read
  the stream until the response that matches our request id arrives, then stop.
* **202 Accepted.** When the POST body contains only notifications/responses
  (no request needing an answer), the server returns ``202`` with no body.
* **Session handshake.** The server MAY assign a session by returning an
  ``Mcp-Session-Id`` header (typically on the ``initialize`` response). Once
  seen, the client echoes it on every subsequent request and ``DELETE``\\ s it to
  end the session.
* **Protocol version pinning.** After initialization the client sends an
  ``MCP-Protocol-Version`` header on every request so a server that supports
  multiple revisions knows which one is in play.
* **Status codes.** ``400``/``405`` surface as :class:`McpHttpStatusError`; a
  ``404`` *after* a session was established means the session expired and surfaces
  as :class:`McpSessionExpiredError` (the local session is cleared).
* **Transport security.** Plain ``http://`` is only allowed to loopback hosts
  (local reference servers); any other host must use ``https://`` unless the
  caller explicitly opts out. An ``Origin`` header is always sent so servers can
  enforce their own DNS-rebinding protection.

The transport is asynchronous (httpx ``AsyncClient``) because SSE responses are
naturally streamed; it is usable as an async context manager. It owns the
JSON-RPC envelope and id bookkeeping but is deliberately ignorant of MCP method
semantics (``initialize``, ``tools/list``, …) — those belong to the discovery
layer built on top of it (2.2/2.3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from ipaddress import ip_address
from itertools import count
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Union

import httpx

from .resilience import private_address_reason

logger = logging.getLogger(__name__)

# MCP protocol revision this client targets. Sent as the ``MCP-Protocol-Version``
# header on every post-initialization request.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# Headers / media types defined by the Streamable HTTP transport.
SESSION_ID_HEADER = "Mcp-Session-Id"
PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
_JSON_MEDIA_TYPE = "application/json"
_SSE_MEDIA_TYPE = "text/event-stream"
_ACCEPT_VALUE = f"{_JSON_MEDIA_TYPE}, {_SSE_MEDIA_TYPE}"

# A server-initiated request or notification received over an SSE stream while we
# were waiting for our own response. The handler is optional; see ``request``.
ServerMessageHandler = Callable[[Dict[str, Any]], Union[None, Awaitable[None]]]


# ===========================================================================
# Errors
# ===========================================================================


class McpTransportError(Exception):
    """Base class for every error raised by the Streamable HTTP transport."""


class McpProtocolError(McpTransportError):
    """The server's reply was not a well-formed Streamable HTTP / JSON-RPC message.

    Examples: a ``200`` whose ``Content-Type`` is neither JSON nor SSE, a body
    that does not parse as JSON, or a JSON-RPC envelope missing ``jsonrpc``.
    """


class McpSsrfError(McpTransportError):
    """The endpoint URL points at a non-public network address (SSRF guard).

    Raised during transport construction when the host is an IP literal in a
    blocked range (RFC 1918 private, link-local, reserved, multicast, …). A
    tenant-supplied discovery URL must not be able to make the worker reach
    internal infrastructure; per the MCP
    `security best practices <https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices>`_
    such targets are refused unless the caller explicitly opts in
    (``allow_private_network=True``) for a trusted local/lab endpoint.

    Attributes:
        host: The offending host component of the URL.
        reason: The stable range classification that triggered the block (e.g.
            ``"private"``, ``"link-local"``); see
            :func:`app.mcp_client.resilience.private_address_reason`.
    """

    def __init__(self, host: str, reason: str) -> None:
        self.host = host
        self.reason = reason
        super().__init__(
            f"refusing MCP endpoint host {host!r}: {reason} address ranges are "
            "blocked (SSRF guard); pass allow_private_network=True for a trusted endpoint"
        )


class McpHttpStatusError(McpTransportError):
    """The server returned an HTTP status the transport treats as a failure.

    Attributes:
        status_code: The HTTP status code returned (e.g. ``400``, ``405``).
        body: The (possibly empty) response body, useful for diagnostics.
    """

    def __init__(self, status_code: int, body: str = "", message: Optional[str] = None) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(message or f"MCP server returned HTTP {status_code}")


class McpSessionExpiredError(McpHttpStatusError):
    """The server returned ``404`` for a request carrying a session id.

    Per spec this means the session has been terminated server-side; the client
    must discard the session id and re-initialize. The transport clears its local
    session id before raising so a subsequent ``initialize`` starts cleanly.
    """

    def __init__(self, session_id: str, body: str = "") -> None:
        self.session_id = session_id
        super().__init__(
            404,
            body,
            message=f"MCP session '{session_id}' has expired; re-initialization required",
        )


class McpRateLimitedError(McpHttpStatusError):
    """The server returned ``429 Too Many Requests``, asking the client to slow down.

    Surfaced as a dedicated error — separate from a generic :class:`McpHttpStatusError`
    — so the discovery taxonomy can record a stable "rate limited" outcome and the
    periodic sweep's backoff can *respect* the server's pacing: when the response carries
    a ``Retry-After`` header expressed as a delay in seconds, it is parsed into
    :attr:`retry_after` so the backoff never retries sooner than the server permits
    (MCAT-5.3). An ``HTTP-date`` form of ``Retry-After`` is not converted (left ``None``),
    so the client falls back to its own exponential backoff in that case.

    Attributes:
        retry_after: The ``Retry-After`` delay in seconds when the header was present and
            given as a non-negative integer, else ``None``.
    """

    def __init__(self, body: str = "", retry_after: Optional[int] = None) -> None:
        self.retry_after = retry_after
        hint = f" (Retry-After: {retry_after}s)" if retry_after is not None else ""
        super().__init__(
            429, body, message=f"MCP server rate limited the request (HTTP 429){hint}"
        )


def parse_retry_after_seconds(value: Optional[str]) -> Optional[int]:
    """Parse a ``Retry-After`` header value expressed as a delay in seconds.

    Only the ``delta-seconds`` form (RFC 9110 §10.2.3) is recognized; the alternative
    ``HTTP-date`` form returns ``None`` (the caller falls back to its own backoff). A
    negative or non-integer value also returns ``None`` so a malformed header can never
    shorten — or invert — the backoff delay.

    Args:
        value: The raw ``Retry-After`` header value, or ``None`` when absent.

    Returns:
        The non-negative integer delay in seconds, or ``None`` when the header is
        absent, an HTTP-date, or otherwise unparseable.
    """
    if value is None:
        return None
    text = value.strip()
    if not text.isdigit():
        return None
    seconds = int(text)
    return seconds if seconds >= 0 else None


class McpAuthRequiredError(McpHttpStatusError):
    """The server returned ``401 Unauthorized``, requesting authentication.

    The MCP authorization flow advertises *how* to authenticate via the
    ``WWW-Authenticate`` response header (e.g. an OAuth resource-metadata URL).
    The transport surfaces ``401`` as this dedicated error — separate from a
    generic :class:`McpHttpStatusError` — so the discovery taxonomy can record a
    stable "auth required" outcome and preserve the challenge for the operator.

    Attributes:
        www_authenticate: The verbatim ``WWW-Authenticate`` header value, or
            ``None`` if the server omitted it.
    """

    def __init__(self, body: str = "", www_authenticate: Optional[str] = None) -> None:
        self.www_authenticate = www_authenticate
        challenge = f" ({www_authenticate})" if www_authenticate else ""
        super().__init__(
            401, body, message=f"MCP server requires authentication (HTTP 401){challenge}"
        )


# ===========================================================================
# JSON-RPC value objects
# ===========================================================================


@dataclass(frozen=True)
class JsonRpcError:
    """The ``error`` member of a JSON-RPC 2.0 response."""

    code: int
    message: str
    data: Any = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "JsonRpcError":
        return cls(
            code=int(payload.get("code", 0)),
            message=str(payload.get("message", "")),
            data=payload.get("data"),
        )


@dataclass(frozen=True)
class JsonRpcResponse:
    """A JSON-RPC 2.0 response: exactly one of ``result`` or ``error`` is set.

    Attributes:
        id: The request id this response answers.
        result: The success payload (``None`` when ``error`` is set).
        error: The :class:`JsonRpcError` (``None`` on success).
    """

    id: Union[str, int, None]
    result: Any = None
    error: Optional[JsonRpcError] = None

    @property
    def is_error(self) -> bool:
        """True when the server returned a JSON-RPC error rather than a result."""
        return self.error is not None

    def raise_for_error(self) -> "JsonRpcResponse":
        """Return ``self`` on success; raise :class:`McpProtocolError` on a JSON-RPC error.

        A convenience for callers that treat a JSON-RPC error as fatal::

            resp = (await transport.request("tools/list", {})).raise_for_error()
        """
        if self.error is not None:
            raise McpProtocolError(
                f"JSON-RPC error {self.error.code}: {self.error.message}"
            )
        return self

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "JsonRpcResponse":
        error = payload.get("error")
        return cls(
            id=payload.get("id"),
            result=payload.get("result"),
            error=JsonRpcError.from_dict(error) if isinstance(error, dict) else None,
        )


# ===========================================================================
# Transport
# ===========================================================================


@dataclass
class StreamableHttpTransport:
    """A JSON-RPC client over the MCP Streamable HTTP transport.

    Typical use::

        async with StreamableHttpTransport("https://example.com/mcp") as t:
            init = await t.request("initialize", {...})   # session id captured here
            tools = await t.request("tools/list", {})
            await t.notify("notifications/initialized")
        # leaving the context DELETEs the session and closes the HTTP client

    Args:
        url: The single MCP endpoint (``…/mcp``).
        protocol_version: Value sent as ``MCP-Protocol-Version`` once initialized.
        origin: ``Origin`` header value. Defaults to the endpoint's
            scheme://authority so servers can enforce DNS-rebinding protection.
        client: An existing httpx ``AsyncClient`` to use (e.g. a mocked transport
            in tests). When omitted, the transport creates and owns one.
        timeout: Per-request timeout in seconds (ignored when ``client`` is given).
        allow_insecure_http: Permit ``http://`` to non-loopback hosts. Defaults to
            ``False``; loopback ``http://`` (local reference servers) is always
            allowed regardless of this flag.
        allow_private_network: Permit endpoints whose host is an IP literal in a
            non-public range (RFC 1918 private, link-local, reserved, …). Defaults
            to ``False`` (the SSRF guard blocks them); loopback is always allowed
            regardless of this flag for local reference servers.
        headers: Extra static headers merged into every request.
    """

    url: str
    protocol_version: str = DEFAULT_PROTOCOL_VERSION
    origin: Optional[str] = None
    client: Optional[httpx.AsyncClient] = None
    timeout: float = 30.0
    allow_insecure_http: bool = False
    allow_private_network: bool = False
    headers: Dict[str, str] = field(default_factory=dict)

    # --- internal state (not constructor arguments) ------------------------
    _session_id: Optional[str] = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)
    _owns_client: bool = field(default=False, init=False)
    _id_counter: "count[int]" = field(default_factory=lambda: count(1), init=False)

    def __post_init__(self) -> None:
        parsed = httpx.URL(self.url)
        self._enforce_transport_security(parsed)
        self._guard_ssrf(parsed)
        if self.origin is None:
            # scheme://host[:port] — no path/query, matching browser Origin semantics.
            self.origin = _origin_of(parsed)
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def session_id(self) -> Optional[str]:
        """The server-assigned session id, or ``None`` before/after a session."""
        return self._session_id

    @property
    def initialized(self) -> bool:
        """True once a successful ``initialize`` response has been seen."""
        return self._initialized

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------
    async def __aenter__(self) -> "StreamableHttpTransport":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """End the session (best-effort ``DELETE``) and close an owned HTTP client."""
        try:
            await self.end_session()
        finally:
            if self._owns_client and self.client is not None:
                await self.client.aclose()

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
        """Send a JSON-RPC request and return the matching response.

        Handles both response shapes transparently: a single JSON object or an
        SSE stream that is drained until the message whose ``id`` equals this
        request's id is found.

        Args:
            method: The JSON-RPC method (e.g. ``"initialize"``, ``"tools/list"``).
            params: The method parameters; omitted from the envelope when ``None``.
            request_id: Override the auto-generated request id (mostly for tests).
            on_server_message: Optional handler invoked for any server-initiated
                request/notification received on the SSE stream *before* our
                response. Without it such messages are logged and dropped.

        Returns:
            The :class:`JsonRpcResponse` answering this request.

        Raises:
            McpHttpStatusError: on ``400``/``405``/other unexpected statuses.
            McpSessionExpiredError: on ``404`` while a session was active.
            McpProtocolError: on a malformed body, unexpected ``202``, or a
                stream that closed without delivering our response.
        """
        rpc_id: Union[str, int] = request_id if request_id is not None else next(self._id_counter)
        payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            payload["params"] = params

        response = await self._post(payload, is_request=True)
        try:
            self._capture_session(response)
            if response.status_code == 202:
                # 202 is for bodies with no request; a request must get a response.
                raise McpProtocolError(
                    f"server returned 202 Accepted to request '{method}'; expected a response"
                )
            await self._raise_for_status(response)
            result = await self._read_response(response, rpc_id, on_server_message)
        finally:
            await response.aclose()

        # A successful initialize unlocks protocol-version pinning for later calls.
        if method == "initialize" and not result.is_error:
            self._initialized = True
        return result

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send a JSON-RPC notification (a request with no ``id``, no response).

        The server is expected to answer ``202 Accepted`` (or ``200`` with an
        empty/ignored body). Any error status is raised.

        Args:
            method: The notification method (e.g. ``"notifications/initialized"``).
            params: Optional parameters; omitted from the envelope when ``None``.
        """
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params

        response = await self._post(payload, is_request=False)
        try:
            self._capture_session(response)
            if response.status_code in (200, 202):
                return
            await self._raise_for_status(response)
            # A 2xx other than 200/202 is unexpected for a notification.
            raise McpProtocolError(
                f"unexpected status {response.status_code} for notification '{method}'"
            )
        finally:
            await response.aclose()

    async def end_session(self) -> None:
        """Terminate the session with an HTTP ``DELETE``, then clear local state.

        A no-op when no session is active. A ``405`` is tolerated — the spec lets
        a server refuse client-initiated termination — but we still drop our local
        session id since the transport is done with it. Other error statuses raise.
        """
        if self._session_id is None or self.client is None:
            return
        try:
            response = await self.client.request(
                "DELETE", self.url, headers=self._build_headers(is_request=True)
            )
            await response.aclose()
            if response.status_code == 405:
                logger.info("MCP server refused client session termination (405); clearing locally")
            elif response.status_code >= 400 and response.status_code != 404:
                raise McpHttpStatusError(
                    response.status_code, message=f"DELETE session failed: HTTP {response.status_code}"
                )
        finally:
            # We are done with the session regardless of how the server replied.
            self._session_id = None
            self._initialized = False

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    async def _post(self, payload: Dict[str, Any], *, is_request: bool) -> httpx.Response:
        """POST a JSON-RPC envelope and return the (streaming) response object.

        The response is returned *open* (via ``client.send(stream=True)``) so SSE
        bodies are not buffered into memory; callers must ``aclose`` it.
        """
        assert self.client is not None  # set in __post_init__
        http_request = self.client.build_request(
            "POST",
            self.url,
            headers=self._build_headers(is_request=is_request),
            content=json.dumps(payload).encode("utf-8"),
        )
        return await self.client.send(http_request, stream=True)

    def _build_headers(self, *, is_request: bool) -> Dict[str, str]:
        """Assemble the header set for one outbound message.

        ``MCP-Protocol-Version`` is added only after initialization; the
        ``initialize`` request itself negotiates the version and must omit it.
        ``Mcp-Session-Id`` is echoed once the server has assigned one.
        """
        headers: Dict[str, str] = {
            "Accept": _ACCEPT_VALUE,
            "Content-Type": _JSON_MEDIA_TYPE,
        }
        if self.origin:
            headers["Origin"] = self.origin
        if self._session_id is not None:
            headers[SESSION_ID_HEADER] = self._session_id
        # Pin the protocol version on everything after initialize negotiated it.
        if is_request and self._initialized:
            headers[PROTOCOL_VERSION_HEADER] = self.protocol_version
        headers.update(self.headers)
        return headers

    def _capture_session(self, response: httpx.Response) -> None:
        """Record an ``Mcp-Session-Id`` the server returned (idempotent)."""
        assigned = response.headers.get(SESSION_ID_HEADER)
        if assigned and assigned != self._session_id:
            logger.debug("MCP session established: %s", assigned)
            self._session_id = assigned

    async def _raise_for_status(self, response: httpx.Response) -> None:
        """Translate spec-relevant error statuses into transport exceptions.

        ``401`` raises :class:`McpAuthRequiredError`, preserving the
        ``WWW-Authenticate`` challenge; ``404`` with an active session means the
        session expired (clears it and raises :class:`McpSessionExpiredError`);
        ``400``/``405`` and any other ``>= 400`` status raise
        :class:`McpHttpStatusError`. ``2xx`` is a no-op.
        """
        status = response.status_code
        if status < 400:
            return
        body = await self._safe_body(response)
        if status == 401:
            raise McpAuthRequiredError(body, response.headers.get("WWW-Authenticate"))
        if status == 429:
            raise McpRateLimitedError(
                body, parse_retry_after_seconds(response.headers.get("Retry-After"))
            )
        if status == 404 and self._session_id is not None:
            expired = self._session_id
            self._session_id = None
            self._initialized = False
            raise McpSessionExpiredError(expired, body)
        raise McpHttpStatusError(status, body)

    @staticmethod
    async def _safe_body(response: httpx.Response) -> str:
        """Read an error response body without letting a read failure mask the status."""
        try:
            return (await response.aread()).decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - diagnostics only
            return ""

    async def _read_response(
        self,
        response: httpx.Response,
        rpc_id: Union[str, int],
        on_server_message: Optional[ServerMessageHandler],
    ) -> JsonRpcResponse:
        """Parse a ``200`` body (JSON or SSE) and return the response for ``rpc_id``."""
        content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()

        if media_type == _JSON_MEDIA_TYPE:
            raw = (await response.aread()).decode("utf-8")
            message = self._parse_json_rpc(raw)
            return self._coerce_response(message, rpc_id)

        if media_type == _SSE_MEDIA_TYPE:
            return await self._read_sse_response(response, rpc_id, on_server_message)

        raise McpProtocolError(
            f"unexpected Content-Type '{content_type or '(none)'}' on 200 response; "
            f"expected {_JSON_MEDIA_TYPE} or {_SSE_MEDIA_TYPE}"
        )

    async def _read_sse_response(
        self,
        response: httpx.Response,
        rpc_id: Union[str, int],
        on_server_message: Optional[ServerMessageHandler],
    ) -> JsonRpcResponse:
        """Drain an SSE stream until the message answering ``rpc_id`` arrives.

        Each SSE ``message`` event carries one JSON-RPC message. Responses whose
        id matches ours are returned; server-initiated requests/notifications seen
        beforehand are dispatched to ``on_server_message`` (or logged and dropped).
        """
        async for event_data in _iter_sse_data(response):
            message = self._parse_json_rpc(event_data)
            if self._is_response_for(message, rpc_id):
                return JsonRpcResponse.from_dict(message)
            # Not our answer: a server-initiated request/notification or a
            # response to a different id. Hand it off if the caller wants it.
            await self._dispatch_server_message(message, on_server_message)
        raise McpProtocolError(
            f"SSE stream closed before a response for id {rpc_id!r} was received"
        )

    @staticmethod
    async def _dispatch_server_message(
        message: Dict[str, Any], handler: Optional[ServerMessageHandler]
    ) -> None:
        """Deliver a non-matching SSE message to the caller's handler, if any."""
        if handler is None:
            logger.debug("dropping unsolicited MCP message: %s", message.get("method") or message.get("id"))
            return
        outcome = handler(message)
        if hasattr(outcome, "__await__"):
            await outcome  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json_rpc(raw: str) -> Dict[str, Any]:
        """Parse one JSON-RPC message, validating the envelope minimally."""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpProtocolError(f"response body is not valid JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise McpProtocolError("JSON-RPC message must be an object")
        if message.get("jsonrpc") != "2.0":
            raise McpProtocolError("JSON-RPC message is missing or has a bad 'jsonrpc' version")
        return message

    @staticmethod
    def _is_response_for(message: Dict[str, Any], rpc_id: Union[str, int]) -> bool:
        """True when ``message`` is the response/error for ``rpc_id``.

        A response has an ``id`` and either ``result`` or ``error``; requests and
        notifications from the server carry a ``method`` instead.
        """
        if "method" in message:
            return False
        return message.get("id") == rpc_id

    @staticmethod
    def _coerce_response(message: Dict[str, Any], rpc_id: Union[str, int]) -> JsonRpcResponse:
        """Validate a single-object response and build a :class:`JsonRpcResponse`."""
        if "method" in message:
            raise McpProtocolError(
                f"expected a response to id {rpc_id!r} but got a server '{message['method']}' message"
            )
        if "result" not in message and "error" not in message:
            raise McpProtocolError("JSON-RPC response has neither 'result' nor 'error'")
        return JsonRpcResponse.from_dict(message)

    # ------------------------------------------------------------------
    # Transport security
    # ------------------------------------------------------------------
    def _enforce_transport_security(self, parsed: httpx.URL) -> None:
        """Reject plaintext ``http://`` to non-loopback hosts.

        Local reference MCP servers run on loopback over plain HTTP, so those are
        always permitted; any other host must use HTTPS unless the caller set
        ``allow_insecure_http=True`` (e.g. a trusted private network).
        """
        scheme = (parsed.scheme or "").lower()
        if scheme == "https":
            return
        if scheme != "http":
            raise McpTransportError(f"unsupported URL scheme '{scheme or '(none)'}'; use http or https")
        if self.allow_insecure_http or _is_loopback_host(parsed.host):
            return
        raise McpTransportError(
            f"refusing plaintext http:// to non-loopback host '{parsed.host}'; "
            "use https:// or pass allow_insecure_http=True"
        )

    def _guard_ssrf(self, parsed: httpx.URL) -> None:
        """Reject an endpoint whose host is an IP literal in a non-public range.

        The SSRF guard stops a tenant-supplied URL from steering the discovery
        worker at internal infrastructure (cloud metadata, private services).
        Loopback is exempt — it is the local reference-server case the transport
        already permits over plain HTTP — and any other private/link-local/
        reserved/multicast literal is refused unless ``allow_private_network`` is
        set for a trusted endpoint. Hostnames are not resolved here (no DNS in the
        constructor); a caller guarding against DNS rebinding resolves first and
        passes IP literals through :func:`app.mcp_client.resilience.private_address_reason`.
        """
        host = parsed.host
        if _is_loopback_host(host) or self.allow_private_network:
            return
        reason = private_address_reason(host)
        if reason is not None:
            raise McpSsrfError(host, reason)


# ===========================================================================
# Module-level helpers
# ===========================================================================


def _origin_of(url: httpx.URL) -> str:
    """Derive an ``Origin`` value (``scheme://host[:port]``) from an endpoint URL."""
    origin = f"{url.scheme}://{url.host}"
    if url.port is not None:
        origin = f"{origin}:{url.port}"
    return origin


def _is_loopback_host(host: str) -> bool:
    """True for ``localhost`` and any IP literal in a loopback range (127/8, ::1)."""
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the ``data`` payload of each SSE ``message`` event in ``response``.

    A minimal Server-Sent-Events parser sufficient for MCP: events are separated
    by a blank line; ``data:`` lines within an event are concatenated with ``\\n``
    (per the SSE spec); ``event:``/``id:``/``retry:`` and comment (``:``) lines are
    recognized but, for MCP, only the default ``message`` event type carries
    JSON-RPC, so we yield whenever a non-empty data buffer is flushed. A trailing
    event without a final blank line is flushed at end-of-stream.
    """
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        # ``aiter_lines`` strips the newline; an SSE event ends on an empty line.
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive
        field_name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]  # one optional leading space after the colon
        if field_name == "data":
            data_lines.append(value)
        # Other fields (event/id/retry) are not needed to extract MCP payloads.
    if data_lines:
        yield "\n".join(data_lines)
