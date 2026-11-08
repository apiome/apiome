"""Integration test: the legacy HTTP+SSE transport against a real stub (V2-MCP-16.5, #3661).

Unlike ``test_mcp_transport_sse.py`` (which mocks httpx), this runs a **real** 2024-11-05
MCP server over a loopback TCP socket — a ``GET /sse`` event stream that announces
``/messages?session_id=…``, and a message endpoint that acknowledges each POST with
``202`` and answers on the stream — and drives the client against it end to end:

* ``transport='sse'`` connects directly;
* the default transport tries Streamable HTTP, is answered ``405`` by ``POST /sse``,
  and falls back on that signature;
* discovery (handshake + ``tools/list``) and the discovery engine's client path produce a
  surface, and the capability test harness invokes a tool, all over the legacy transport.
"""

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List
from urllib.parse import parse_qs, urlparse

import pytest

from app import mcp_discovery_engine
from app.mcp_client import LEGACY_PROTOCOL_VERSION, LegacySseTransport, discover_listings, open_session
from app.mcp_invoke import invoke_tool

SESSION = "sess-0001"
TOOL = {
    "name": "echo",
    "description": "Echo the input back.",
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
}


class _LegacyServer(ThreadingHTTPServer):
    """A threaded HTTP server holding one SSE session's outbound queue."""

    daemon_threads = True

    def __init__(self, address: Any) -> None:
        super().__init__(address, _LegacyHandler)
        self.outbox: "queue.Queue[str]" = queue.Queue()
        self.posts: List[Dict[str, Any]] = []
        self.stopping = threading.Event()


class _LegacyHandler(BaseHTTPRequestHandler):
    """``GET /sse`` streams events; ``POST /messages`` is acknowledged and answered on it."""

    server: _LegacyServer

    def log_message(self, *args: Any) -> None:  # noqa: D401 - stdlib signature
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if urlparse(self.path).path != "/sse":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self._write(f"event: endpoint\ndata: /messages?session_id={SESSION}\n\n")
        while not self.server.stopping.is_set():
            try:
                chunk = self.server.outbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if not self._write(chunk):
                return

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        if parsed.path == "/sse":
            # What a Streamable HTTP client tries first: this server has no POST handler here.
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.end_headers()
            return
        if parsed.path != "/messages" or parse_qs(parsed.query).get("session_id") != [SESSION]:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        self.server.posts.append(body)
        if "id" in body:
            reply = {"jsonrpc": "2.0", "id": body["id"], "result": _result(body)}
            self.server.outbox.put(f"event: message\ndata: {json.dumps(reply)}\n\n")
        self.send_response(202)
        self.send_header("Content-Length", "8")
        self.end_headers()
        self.wfile.write(b"Accepted")

    def _write(self, chunk: str) -> bool:
        try:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False


def _result(body: Dict[str, Any]) -> Dict[str, Any]:
    """What the legacy server answers each method with."""
    method = body.get("method")
    if method == "initialize":
        return {
            "protocolVersion": LEGACY_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "legacy-weather", "version": "1.2.0"},
        }
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        text = body["params"]["arguments"].get("text", "")
        return {"content": [{"type": "text", "text": text}], "isError": False}
    return {}


@pytest.fixture
def legacy_server() -> Iterator[_LegacyServer]:
    """A running legacy MCP server on an ephemeral loopback port."""
    server = _LegacyServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def _sse_url(server: _LegacyServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/sse"


async def test_transport_sse_connects_and_discovers(legacy_server: _LegacyServer) -> None:
    transport, initialize = await open_session(_sse_url(legacy_server), transport="sse", timeout=5.0)
    try:
        assert isinstance(transport, LegacySseTransport)
        assert initialize.protocol_version == LEGACY_PROTOCOL_VERSION
        assert initialize.server_info.name == "legacy-weather"
        listings = await discover_listings(transport, initialize.capabilities)
    finally:
        await transport.aclose()
    assert [tool["name"] for tool in listings.tools] == ["echo"]
    assert [post["method"] for post in legacy_server.posts] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]


async def test_streamable_http_falls_back_on_the_405_signature(legacy_server: _LegacyServer) -> None:
    transport, initialize = await open_session(_sse_url(legacy_server), timeout=5.0)
    try:
        assert isinstance(transport, LegacySseTransport)
        assert transport.message_url is not None
        assert transport.message_url.endswith(f"/messages?session_id={SESSION}")
        assert initialize.protocol_version == LEGACY_PROTOCOL_VERSION
    finally:
        await transport.aclose()


async def test_the_discovery_engine_reads_a_legacy_server(legacy_server: _LegacyServer) -> None:
    endpoint = {"endpoint_url": _sse_url(legacy_server), "transport": "streamable_http"}
    surface, transport_meta, transcript = await mcp_discovery_engine._run_mcp_client(endpoint, {})

    assert surface.protocol_version == LEGACY_PROTOCOL_VERSION
    assert [tool.name for tool in surface.tools] == ["echo"]
    assert transport_meta is not None
    assert transcript is not None


async def test_the_test_harness_invokes_a_tool_on_a_legacy_server(legacy_server: _LegacyServer) -> None:
    result = await invoke_tool(_sse_url(legacy_server), "echo", {"text": "hello"}, timeout=5.0)
    assert result.completed is True
    assert result.is_error is False
    assert result.content[0]["text"] == "hello"
