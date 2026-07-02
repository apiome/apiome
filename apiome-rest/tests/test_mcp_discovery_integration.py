"""Integration test for MCP discovery list methods + pagination (V2-MCP-16.3, #3659).

Unlike ``test_mcp_discovery.py`` (which mocks httpx), this drives the full
``initialize`` → ``*/list`` discovery flow against a **real** stub MCP server over
a loopback TCP socket. The stub declares only ``tools`` and ``resources`` (not
``prompts``) and serves a genuinely multi-page ``tools/list`` paged by opaque
cursor, so the test confirms end to end that the client pages to exhaustion,
gathers resources and resource templates, and skips the undeclared ``prompts``
capability without ever calling ``prompts/list``.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.mcp_client.discovery import discover_listings
from app.mcp_client.handshake import initialize_session
from app.mcp_client.transport_http import SESSION_ID_HEADER, StreamableHttpTransport

SESSION_ID = "discovery-session-0001"

# A three-page tools list keyed by the cursor the *previous* page advertised.
# ``None`` is the first (cursor-less) request.
_TOOLS_PAGES = {
    None: {"tools": [{"name": "alpha"}], "nextCursor": "p2"},
    "p2": {"tools": [{"name": "bravo"}], "nextCursor": "p3"},
    "p3": {"tools": [{"name": "charlie"}]},  # final page: no nextCursor
}


def _build_handler():
    """Build a stub MCP handler that declares tools+resources and pages tools/list."""

    class _StubMcpHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: N802 - stdlib signature
            return

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length else {}

        def _send_json(self, payload: dict, *, session: bool = False):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if session:
                self.send_header(SESSION_ID_HEADER, SESSION_ID)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _result_for(self, method: str, params: dict) -> dict:
            if method == "initialize":
                return {
                    "protocolVersion": "2025-06-18",
                    # Note: prompts is intentionally NOT declared.
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "stub", "version": "0.1.0"},
                }
            if method == "tools/list":
                return _TOOLS_PAGES[params.get("cursor")]
            if method == "resources/list":
                return {"resources": [{"uri": "file:///r1"}]}
            if method == "resources/templates/list":
                return {"resourceTemplates": [{"uriTemplate": "file:///{path}"}]}
            if method == "prompts/list":  # must never be reached (undeclared)
                raise AssertionError("prompts/list called for an undeclared capability")
            return {}

        def do_POST(self):  # noqa: N802 - stdlib signature
            if self.path != "/mcp":
                self.send_response(404)
                self.end_headers()
                return

            body = self._read_body()
            self.server.received.append(body)  # type: ignore[attr-defined]

            if "id" not in body:  # notification
                self.send_response(202)
                self.end_headers()
                return

            method = body.get("method")
            result = self._result_for(method, body.get("params") or {})
            self._send_json(
                {"jsonrpc": "2.0", "id": body["id"], "result": result},
                session=(method == "initialize"),
            )

        def do_DELETE(self):  # noqa: N802 - stdlib signature
            self.send_response(200)
            self.end_headers()

    return _StubMcpHandler


@pytest.fixture
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _build_handler())
    server.received = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, f"http://{host}:{port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_discovers_and_pages_declared_capabilities(stub_server):
    server, url = stub_server

    async with StreamableHttpTransport(url) as transport:
        init = await initialize_session(transport)
        listings = await discover_listings(transport, init.capabilities)

    # tools/list paged across three pages to exhaustion, in order.
    assert [t["name"] for t in listings.tools] == ["alpha", "bravo", "charlie"]
    assert listings.resources == [{"uri": "file:///r1"}]
    assert listings.resource_templates == [{"uriTemplate": "file:///{path}"}]

    # prompts was undeclared: empty, recorded as skipped, and never requested.
    assert listings.prompts == []
    assert "prompts/list" in listings.skipped

    methods = [b.get("method") for b in server.received]
    assert methods.count("tools/list") == 3
    assert "resources/list" in methods
    assert "resources/templates/list" in methods
    assert "prompts/list" not in methods
