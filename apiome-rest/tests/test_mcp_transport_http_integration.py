"""Integration test for the MCP Streamable HTTP transport (V2-MCP-16.1, #3657).

Unlike ``test_mcp_transport_http.py`` (which mocks httpx), this drives the
transport against a **real** stub MCP server over a loopback TCP socket, so the
full HTTP path is exercised: actual sockets, an ``initialize`` request answered
with JSON + an ``Mcp-Session-Id`` header, a ``tools/list`` answered as a genuine
``text/event-stream`` SSE response, a notification answered ``202``, and a
``DELETE`` that ends the session. The stub asserts that the client echoes the
session id and protocol-version header on post-initialization requests.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.mcp_client.transport_http import (
    DEFAULT_PROTOCOL_VERSION,
    PROTOCOL_VERSION_HEADER,
    SESSION_ID_HEADER,
    StreamableHttpTransport,
)

SESSION_ID = "stub-session-0001"


class _StubMcpHandler(BaseHTTPRequestHandler):
    """A minimal Streamable HTTP MCP endpoint for one ``…/mcp`` path.

    Records what the client sent (so the test can assert the session/protocol
    headers round-trip) on the owning server instance.
    """

    # Silence the default stderr request logging during tests.
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
        self.server.received.append((self.headers, body))  # type: ignore[attr-defined]

        # Notification (no id): acknowledge with 202 and no body.
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return

        method = body.get("method")
        if method == "initialize":
            payload = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": DEFAULT_PROTOCOL_VERSION, "capabilities": {}},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header(SESSION_ID_HEADER, SESSION_ID)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # Everything else streams its response back as SSE.
        message = json.dumps(
            {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "echo"}]}}
        )
        chunk = f"event: message\ndata: {message}\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(chunk)

    def do_DELETE(self):  # noqa: N802 - stdlib signature
        self.server.deleted.append(self.headers.get(SESSION_ID_HEADER))  # type: ignore[attr-defined]
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def stub_server():
    """Run the stub MCP server on an ephemeral loopback port for one test."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubMcpHandler)
    server.received = []  # type: ignore[attr-defined]
    server.deleted = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield server, f"http://{host}:{port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_full_session_against_stub_server(stub_server):
    server, url = stub_server

    async with StreamableHttpTransport(url) as transport:
        # 1. initialize -> JSON response, session id captured from the header.
        init = await transport.request("initialize", {"capabilities": {}})
        assert not init.is_error
        assert init.result["protocolVersion"] == DEFAULT_PROTOCOL_VERSION
        assert transport.session_id == SESSION_ID
        assert transport.initialized is True

        # 2. tools/list -> a genuine SSE-streamed response.
        tools = await transport.request("tools/list", {})
        assert tools.result["tools"] == [{"name": "echo"}]

        # 3. notification -> 202 Accepted.
        assert await transport.notify("notifications/initialized") is None

    # 4. leaving the context issued a DELETE carrying the session id.
    assert server.deleted == [SESSION_ID]
    assert transport.session_id is None

    # The post-init requests echoed the session id and pinned the protocol version;
    # the initialize request did neither.
    init_headers, _ = server.received[0]
    follow_headers, _ = server.received[1]
    assert SESSION_ID_HEADER not in init_headers
    assert PROTOCOL_VERSION_HEADER not in init_headers
    assert follow_headers.get(SESSION_ID_HEADER) == SESSION_ID
    assert follow_headers.get(PROTOCOL_VERSION_HEADER) == DEFAULT_PROTOCOL_VERSION
    # Origin is always sent so a server can enforce DNS-rebinding protection.
    assert init_headers.get("Origin", "").startswith("http://127.0.0.1:")
