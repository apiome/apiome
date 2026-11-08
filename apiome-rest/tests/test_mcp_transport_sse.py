"""Unit tests for the legacy HTTP+SSE transport and the fallback (V2-MCP-16.5, #3661).

The legacy (2024-11-05) transport opens a ``GET`` event stream, waits for the server's
``endpoint`` event, POSTs every message to that endpoint, and reads the responses off the
stream. These tests drive :class:`LegacySseTransport` and :func:`open_session` against an
in-memory legacy server (:class:`LegacyStub`, an ``httpx.MockTransport`` handler whose
stream is fed by its POST handler) — no sockets — so every branch is deterministic:
endpoint resolution and the same-origin rule, request/response matching, server-initiated
messages, every failure shape, the protocol versions the handshake accepts, and when the
automatic fallback from Streamable HTTP does and does not happen.

``test_mcp_transport_sse_integration.py`` drives the same code against a real legacy
server over loopback TCP.
"""

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app.mcp_client import (
    LEGACY_SSE_PROTOCOL_VERSIONS,
    SUPPORTED_PROTOCOL_VERSIONS,
    DiscoveryErrorCode,
    classify_exception,
    initialize_session,
    open_session,
)
from app.mcp_client.connect import FALLBACK_STATUS_CODES, is_fallback_signature
from app.mcp_client.handshake import McpVersionNegotiationError, default_protocol_versions
from app.mcp_client.transport_http import (
    PROTOCOL_VERSION_HEADER,
    SESSION_ID_HEADER,
    McpAuthRequiredError,
    McpHttpStatusError,
    McpRateLimitedError,
    McpSsrfError,
    McpTransportError,
    StreamableHttpTransport,
    _iter_sse_data,
    iter_sse_events,
)
from app.mcp_client.transport_sse import (
    ENDPOINT_EVENT,
    LEGACY_PROTOCOL_VERSION,
    LegacySseTransport,
    McpLegacySseError,
)

SSE_URL = "https://mcp.example.com/sse"
MESSAGES_PATH = "/messages?session_id=abc123"
MESSAGES_URL = f"https://mcp.example.com{MESSAGES_PATH}"
AUTH = {"Authorization": "Bearer t0ken"}


# ===========================================================================
# The in-memory legacy server
# ===========================================================================


def initialize_result(version: str = LEGACY_PROTOCOL_VERSION) -> Dict[str, Any]:
    """An ``initialize`` result as a legacy server sends it."""
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "legacy-stub", "version": "0.9.0"},
    }


class LegacyStub:
    """An ``httpx.MockTransport`` handler that behaves like a 2024-11-05 MCP server.

    ``GET`` on the SSE URL opens a stream that starts with ``first_event`` carrying
    ``endpoint``; a ``POST`` to the message endpoint is acknowledged with
    ``post_status`` and its response is pushed onto the stream. A ``POST`` to the SSE
    URL itself — what a Streamable HTTP client sends first — gets ``sse_post_status``.

    Args:
        endpoint: The ``endpoint`` event's data.
        first_event: The type of the stream's first event.
        get_status: The status the ``GET`` is answered with.
        content_type: The ``GET`` response's Content-Type.
        post_status: The status a message POST is acknowledged with.
        sse_post_status: The status a POST to the SSE URL is answered with.
        version: The protocol version ``initialize`` answers with.
        before_response: Extra raw SSE chunks pushed before each response.
        silent: Push no responses at all, then close the stream.
    """

    def __init__(
        self,
        *,
        endpoint: str = MESSAGES_PATH,
        first_event: str = ENDPOINT_EVENT,
        get_status: int = 200,
        content_type: str = "text/event-stream",
        post_status: int = 202,
        sse_post_status: int = 405,
        version: str = LEGACY_PROTOCOL_VERSION,
        before_response: Optional[List[str]] = None,
        silent: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.first_event = first_event
        self.get_status = get_status
        self.content_type = content_type
        self.post_status = post_status
        self.sse_post_status = sse_post_status
        self.version = version
        self.before_response = before_response or []
        self.silent = silent
        self.queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        self.requests: List[httpx.Request] = []
        self.posts: List[Dict[str, Any]] = []
        self.stream_response: Optional[httpx.Response] = None

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET":
            return self._open_stream()
        if request.method == "POST" and request.url.path == "/sse":
            return httpx.Response(self.sse_post_status, text="use the SSE transport")
        if request.method == "POST":
            return await self._message(request)
        return httpx.Response(405)

    def _open_stream(self) -> httpx.Response:
        if self.get_status != 200:
            return httpx.Response(self.get_status, text="no stream here")
        self.queue.put_nowait(f"event: {self.first_event}\ndata: {self.endpoint}\n\n")
        if self.silent:
            self.queue.put_nowait(None)
        self.stream_response = httpx.Response(
            200, headers={"Content-Type": self.content_type}, content=self._stream()
        )
        return self.stream_response

    async def _message(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.posts.append(body)
        if self.post_status >= 400:
            return httpx.Response(self.post_status, text="rejected")
        if "id" in body and not self.silent:
            for chunk in self.before_response:
                self.queue.put_nowait(chunk)
            self.push({"jsonrpc": "2.0", "id": body["id"], "result": self._result(body)})
        return httpx.Response(self.post_status, text="Accepted")

    def _result(self, body: Dict[str, Any]) -> Dict[str, Any]:
        method = body.get("method")
        if method == "initialize":
            return initialize_result(self.version)
        if method == "tools/list":
            return {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
        return {"echoed": method}

    def push(self, message: Dict[str, Any], event: str = "message") -> None:
        """Push one JSON-RPC message onto the stream."""
        self.queue.put_nowait(f"event: {event}\ndata: {json.dumps(message)}\n\n")

    async def _stream(self):
        while True:
            chunk = await self.queue.get()
            if chunk is None:
                return
            yield chunk.encode("utf-8")

    @property
    def stream_closed(self) -> bool:
        """True once the client closed the stream response it was given."""
        return self.stream_response is not None and self.stream_response.is_closed

    def methods(self) -> List[str]:
        """The JSON-RPC methods POSTed to the message endpoint, in order."""
        return [body["method"] for body in self.posts]

    def first(self, method: str) -> httpx.Request:
        """The first recorded request with this HTTP method."""
        return next(r for r in self.requests if r.method == method)


def make_transport(stub: LegacyStub, url: str = SSE_URL, **kwargs: Any) -> LegacySseTransport:
    """A legacy transport wired to ``stub``."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(stub))
    return LegacySseTransport(url, client=client, **kwargs)


def client_for(stub: Callable[[httpx.Request], Any]) -> httpx.AsyncClient:
    """An httpx client whose every request is answered by ``stub``."""
    return httpx.AsyncClient(transport=httpx.MockTransport(stub))


# ===========================================================================
# SSE parsing
# ===========================================================================


class _Body:
    """A minimal stand-in for an httpx response, for the SSE parser."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def aiter_lines(self):
        for line in self._text.split("\n"):
            yield line


async def test_sse_events_report_their_type_and_default_to_message() -> None:
    text = "event: endpoint\ndata: /messages\n\ndata: {\"a\": 1}\n\n: keep-alive\nevent: message\ndata: x\ndata: y\n"
    events = [event async for event in iter_sse_events(_Body(text))]
    assert events == [("endpoint", "/messages"), ("message", '{"a": 1}'), ("message", "x\ny")]


async def test_streamable_http_data_parsing_is_unchanged() -> None:
    text = "event: message\ndata: one\n\nevent: other\ndata: two\n\n"
    assert [data async for data in _iter_sse_data(_Body(text))] == ["one", "two"]


# ===========================================================================
# Opening the stream
# ===========================================================================


async def test_connect_resolves_the_endpoint_against_the_sse_url() -> None:
    stub = LegacyStub()
    async with make_transport(stub, headers=AUTH) as transport:
        assert transport.connected is False
        assert await transport.connect() == MESSAGES_URL
        assert transport.connected is True
        assert transport.message_url == MESSAGES_URL

    get = stub.first("GET")
    assert str(get.url) == SSE_URL
    assert get.headers["Accept"] == "text/event-stream"
    assert get.headers["Origin"] == "https://mcp.example.com"
    assert get.headers["Authorization"] == AUTH["Authorization"]


async def test_connect_is_idempotent() -> None:
    stub = LegacyStub()
    async with make_transport(stub) as transport:
        await transport.connect()
        await transport.connect()
    assert [r.method for r in stub.requests] == ["GET"]


async def test_an_absolute_same_origin_endpoint_is_accepted() -> None:
    stub = LegacyStub(endpoint=MESSAGES_URL)
    async with make_transport(stub) as transport:
        assert await transport.connect() == MESSAGES_URL


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example.net/messages",
        "http://mcp.example.com/messages",
        "https://mcp.example.com:8443/messages",
        "//evil.example.net/messages",
    ],
)
async def test_a_cross_origin_endpoint_is_refused_before_anything_is_posted(endpoint: str) -> None:
    stub = LegacyStub(endpoint=endpoint)
    async with make_transport(stub, headers=AUTH) as transport:
        with pytest.raises(McpLegacySseError, match="cross-origin"):
            await transport.request("initialize", {})
    assert stub.posts == []
    assert stub.stream_closed is True


async def test_an_empty_endpoint_is_refused() -> None:
    stub = LegacyStub(endpoint="   ")
    async with make_transport(stub) as transport:
        with pytest.raises(McpLegacySseError, match="no URI"):
            await transport.connect()


async def test_a_stream_that_does_not_open_with_endpoint_is_refused() -> None:
    stub = LegacyStub(first_event="message")
    async with make_transport(stub) as transport:
        with pytest.raises(McpLegacySseError, match="'message' event"):
            await transport.connect()
    assert stub.stream_closed is True


async def test_a_non_sse_answer_is_refused() -> None:
    stub = LegacyStub(content_type="application/json")
    async with make_transport(stub) as transport:
        with pytest.raises(McpLegacySseError, match="application/json"):
            await transport.connect()


async def test_a_stream_that_closes_before_the_endpoint_event_is_refused() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=b": hi\n\n")

    async with LegacySseTransport(SSE_URL, client=client_for(handler)) as transport:
        with pytest.raises(McpLegacySseError, match="closed"):
            await transport.connect()


async def test_an_auth_challenge_on_the_stream_surfaces_as_auth_required() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"WWW-Authenticate": 'Bearer realm="mcp"'})

    async with LegacySseTransport(SSE_URL, client=client_for(handler)) as transport:
        with pytest.raises(McpAuthRequiredError) as exc:
            await transport.connect()
    assert exc.value.www_authenticate == 'Bearer realm="mcp"'


def test_the_streamable_http_security_rules_apply() -> None:
    with pytest.raises(McpTransportError, match="plaintext"):
        LegacySseTransport("http://mcp.example.com/sse")
    with pytest.raises(McpSsrfError):
        LegacySseTransport("https://10.0.0.5/sse")
    LegacySseTransport("http://127.0.0.1:9000/sse")  # loopback stays allowed


# ===========================================================================
# Requests and notifications
# ===========================================================================


async def test_a_request_is_posted_and_its_response_read_from_the_stream() -> None:
    stub = LegacyStub()
    async with make_transport(stub, headers=AUTH) as transport:
        response = await transport.request("tools/list", {"cursor": "c1"})

    assert response.result == {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    post = stub.first("POST")
    assert str(post.url) == MESSAGES_URL
    assert post.headers["Content-Type"] == "application/json"
    assert post.headers["Authorization"] == AUTH["Authorization"]
    assert stub.posts == [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"cursor": "c1"}}]


async def test_streamable_http_only_headers_are_never_sent() -> None:
    stub = LegacyStub()
    async with make_transport(stub) as transport:
        await initialize_session(transport)
        await transport.request("tools/list", {})
    for request in stub.requests:
        assert PROTOCOL_VERSION_HEADER not in request.headers
        assert SESSION_ID_HEADER not in request.headers


async def test_server_messages_before_the_response_reach_the_handler() -> None:
    ping = {"jsonrpc": "2.0", "id": "srv-1", "method": "ping"}
    note = {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}}
    stub = LegacyStub(
        before_response=[
            f"event: message\ndata: {json.dumps(ping)}\n\n",
            "event: heartbeat\ndata: tick\n\n",
            f"event: message\ndata: {json.dumps(note)}\n\n",
        ]
    )
    seen: List[Dict[str, Any]] = []
    async with make_transport(stub) as transport:
        response = await transport.request("tools/list", {}, on_server_message=seen.append)
    assert response.result is not None
    assert seen == [ping, note]


async def test_a_stream_that_closes_before_the_response_fails() -> None:
    stub = LegacyStub(silent=True)
    async with make_transport(stub) as transport:
        with pytest.raises(McpLegacySseError, match="closed"):
            await transport.request("tools/list", {})


async def test_a_rejected_post_surfaces_its_status() -> None:
    stub = LegacyStub(post_status=500)
    async with make_transport(stub) as transport:
        with pytest.raises(McpHttpStatusError) as exc:
            await transport.request("tools/list", {})
    assert exc.value.status_code == 500


async def test_a_notification_is_posted_without_waiting() -> None:
    stub = LegacyStub()
    async with make_transport(stub) as transport:
        await transport.notify("notifications/initialized")
    assert stub.posts == [{"jsonrpc": "2.0", "method": "notifications/initialized"}]


async def test_closing_closes_the_stream_and_sends_no_delete() -> None:
    stub = LegacyStub()
    transport = make_transport(stub)
    await transport.request("tools/list", {})
    await transport.aclose()
    assert stub.stream_closed is True
    assert [r.method for r in stub.requests] == ["GET", "POST"]


async def test_the_transcript_records_each_request() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.records: List[Dict[str, Any]] = []
            self.versions: List[Dict[str, Any]] = []

        def record(self, method: str, **kwargs: Any) -> None:
            self.records.append({"method": method, **kwargs})

        def note_versions(self, **kwargs: Any) -> None:
            self.versions.append(kwargs)

    recorder = Recorder()
    stub = LegacyStub()
    async with make_transport(stub, transcript=recorder) as transport:
        await initialize_session(transport)
    assert [r["method"] for r in recorder.records] == ["initialize"]
    assert recorder.records[0]["http_status"] == 202
    assert recorder.records[0]["envelope"]["result"]["protocolVersion"] == LEGACY_PROTOCOL_VERSION


def test_a_legacy_failure_classifies_as_a_protocol_error() -> None:
    error = classify_exception(McpLegacySseError("no endpoint"))
    assert error.code == DiscoveryErrorCode.PROTOCOL_ERROR


# ===========================================================================
# Handshake over the legacy transport
# ===========================================================================


async def test_the_handshake_negotiates_2024_11_05_over_the_legacy_transport() -> None:
    stub = LegacyStub()
    async with make_transport(stub) as transport:
        result = await initialize_session(transport)
        assert transport.initialized is True
        assert transport.protocol_version == LEGACY_PROTOCOL_VERSION
    assert result.protocol_version == LEGACY_PROTOCOL_VERSION
    assert stub.posts[0]["params"]["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]
    assert stub.methods() == ["initialize", "notifications/initialized"]


async def test_a_current_revision_served_over_sse_is_accepted() -> None:
    stub = LegacyStub(version="2025-03-26")
    async with make_transport(stub) as transport:
        result = await initialize_session(transport)
    assert result.protocol_version == "2025-03-26"


def test_only_the_legacy_transport_accepts_2024_11_05() -> None:
    assert LEGACY_PROTOCOL_VERSION in LEGACY_SSE_PROTOCOL_VERSIONS
    assert LEGACY_PROTOCOL_VERSION not in SUPPORTED_PROTOCOL_VERSIONS
    assert default_protocol_versions(LegacySseTransport(SSE_URL)) == LEGACY_SSE_PROTOCOL_VERSIONS
    assert default_protocol_versions(StreamableHttpTransport(SSE_URL)) == SUPPORTED_PROTOCOL_VERSIONS


async def test_streamable_http_still_refuses_2024_11_05() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": initialize_result()})

    async with StreamableHttpTransport(SSE_URL, client=client_for(handler)) as transport:
        with pytest.raises(McpVersionNegotiationError):
            await initialize_session(transport)


# ===========================================================================
# open_session: choosing the transport and falling back
# ===========================================================================


async def test_transport_sse_uses_the_legacy_transport_directly() -> None:
    stub = LegacyStub()
    transport, result = await open_session(SSE_URL, transport="sse", client=client_for(stub))
    try:
        assert isinstance(transport, LegacySseTransport)
        assert result.protocol_version == LEGACY_PROTOCOL_VERSION
    finally:
        await transport.aclose()
    assert stub.requests[0].method == "GET"
    assert all(r.url.path != "/sse" or r.method == "GET" for r in stub.requests)


@pytest.mark.parametrize("status", sorted(FALLBACK_STATUS_CODES))
async def test_streamable_http_falls_back_on_the_legacy_signature(status: int) -> None:
    stub = LegacyStub(sse_post_status=status)
    transport, result = await open_session(SSE_URL, client=client_for(stub), headers=AUTH)
    try:
        assert isinstance(transport, LegacySseTransport)
        assert result.server_info.name == "legacy-stub"
        assert (await transport.request("tools/list", {})).result["tools"][0]["name"] == "echo"
    finally:
        await transport.aclose()
    assert [(r.method, r.url.path) for r in stub.requests[:2]] == [("POST", "/sse"), ("GET", "/sse")]


@pytest.mark.parametrize(
    "status, expected",
    [(401, McpAuthRequiredError), (429, McpRateLimitedError), (403, McpHttpStatusError), (500, McpHttpStatusError)],
)
async def test_auth_refusal_rate_limits_and_server_errors_do_not_fall_back(
    status: int, expected: type
) -> None:
    stub = LegacyStub(sse_post_status=status)
    with pytest.raises(expected) as exc:
        await open_session(SSE_URL, client=client_for(stub))
    assert exc.value.status_code == status
    assert [r.method for r in stub.requests] == ["POST"]


async def test_a_server_speaking_neither_transport_reports_the_original_error() -> None:
    stub = LegacyStub(sse_post_status=405, get_status=404)
    with pytest.raises(McpHttpStatusError) as exc:
        await open_session(SSE_URL, client=client_for(stub))
    assert exc.value.status_code == 405
    assert [r.method for r in stub.requests] == ["POST", "GET"]


async def test_a_legacy_failure_after_the_stream_opened_is_reported_as_is() -> None:
    stub = LegacyStub(post_status=401)
    with pytest.raises(McpAuthRequiredError):
        await open_session(SSE_URL, client=client_for(stub))


async def test_a_streamable_http_server_never_triggers_the_legacy_probe() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        result = initialize_result("2025-06-18")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    seen: List[str] = []

    async def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return await handler(request)

    transport, result = await open_session(SSE_URL, client=client_for(recording))
    await transport.aclose()
    assert isinstance(transport, StreamableHttpTransport) and not isinstance(transport, LegacySseTransport)
    assert result.protocol_version == "2025-06-18"
    assert "GET" not in seen


async def test_a_failed_handshake_closes_the_legacy_stream() -> None:
    stub = LegacyStub(version="1999-01-01")
    with pytest.raises(McpVersionNegotiationError):
        await open_session(SSE_URL, transport="sse", client=client_for(stub))
    assert stub.stream_closed is True


def test_only_a_plain_status_error_in_the_set_is_a_signature() -> None:
    assert is_fallback_signature(McpHttpStatusError(405))
    assert not is_fallback_signature(McpHttpStatusError(500))
    assert not is_fallback_signature(McpAuthRequiredError())
    assert not is_fallback_signature(McpRateLimitedError())
