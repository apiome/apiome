"""Integration test for the MCP initialize handshake (V2-MCP-16.2, #3658).

Unlike ``test_mcp_handshake.py`` (which mocks httpx), this drives
:func:`initialize_session` against **real** stub MCP servers over loopback TCP
sockets, exercising the full HTTP path for the two protocol revisions the client
must negotiate (2025-06-18 and 2025-03-26) and confirming an unsupported server
is refused. It also asserts the negotiated version is pinned as the
``MCP-Protocol-Version`` header on the post-handshake request.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.mcp_client.handshake import McpVersionNegotiationError, initialize_session
from app.mcp_client.transport_http import (
    PROTOCOL_VERSION_HEADER,
    SESSION_ID_HEADER,
    StreamableHttpTransport,
)

SESSION_ID = "handshake-session-0001"


def _make_handler(server_protocol_version: str):
    """Build a stub MCP handler that initializes at ``server_protocol_version``."""

    class _StubMcpHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: N802 - stdlib signature
            return

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length else {}

        def do_POST(self):  # noqa: N802 - stdlib signature
            if self.path != "/mcp":
                self.send_response(404)
                self.end_headers()
                return

            body = self._read_body()
            self.server.received.append((dict(self.headers), body))  # type: ignore[attr-defined]

            if "id" not in body:  # notification
                self.send_response(202)
                self.end_headers()
                return

            if body.get("method") == "initialize":
                result = {
                    "protocolVersion": server_protocol_version,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "stub", "version": "0.1.0"},
                    "instructions": "stub instructions",
                }
                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header(SESSION_ID_HEADER, SESSION_ID)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            # Any post-handshake request: echo a trivial OK result.
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_DELETE(self):  # noqa: N802 - stdlib signature
            self.send_response(200)
            self.end_headers()

    return _StubMcpHandler


def _run_server(server_protocol_version: str):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(server_protocol_version))
    server.received = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}/mcp"


@pytest.fixture
def stub_server(request):
    """Run a stub MCP server initializing at the (parametrized) protocol version."""
    server, thread, url = _run_server(request.param)
    try:
        yield server, url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("stub_server", ["2025-06-18", "2025-03-26"], indirect=True)
async def test_negotiates_against_supported_servers(stub_server):
    server, url = stub_server

    async with StreamableHttpTransport(url) as transport:
        result = await initialize_session(transport)

        # The negotiated version matches whatever the stub initialized at.
        assert result.protocol_version in ("2025-06-18", "2025-03-26")
        assert transport.protocol_version == result.protocol_version
        assert result.server_info.name == "stub"
        assert result.capabilities == {"tools": {"listChanged": True}}
        assert result.instructions == "stub instructions"

        # A post-handshake request pins the negotiated version header.
        await transport.request("tools/list", {})

    methods = [body.get("method") for _, body in server.received]
    assert "initialize" in methods
    assert "notifications/initialized" in methods

    # The follow-up request carried the negotiated protocol-version header; the
    # initialize request did not.
    init_headers = next(h for h, b in server.received if b.get("method") == "initialize")
    follow_headers = next(h for h, b in server.received if b.get("method") == "tools/list")
    assert PROTOCOL_VERSION_HEADER.lower() not in {k.lower() for k in init_headers}
    assert follow_headers.get(PROTOCOL_VERSION_HEADER) == result.protocol_version


@pytest.mark.parametrize("stub_server", ["1999-01-01"], indirect=True)
async def test_refuses_unsupported_server(stub_server):
    server, url = stub_server

    async with StreamableHttpTransport(url) as transport:
        with pytest.raises(McpVersionNegotiationError):
            await initialize_session(transport)

    # The client never completed the handshake against the unsupported server.
    methods = [body.get("method") for _, body in server.received]
    assert "notifications/initialized" not in methods
