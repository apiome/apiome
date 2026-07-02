"""End-to-end auth integration: discovery against a bearer-protected stub (MCAT-6.1, #3677).

The acceptance criterion for MCAT-6.1 is: *discovery/test succeed against a bearer-protected
stub; tokens only ever sent in headers*. This drives the real ``initialize`` → ``*/list`` flow
over a loopback socket against a stub that **rejects every request lacking the right
``Authorization: Bearer`` header with 401**. The auth headers come from the production auth-type
model (:func:`app.mcp_auth.build_auth_headers`), exactly as the credential loader would feed them
once decryption (MCAT-6.2) is wired in.

Two things are asserted:
1. With the correct bearer header the full discovery succeeds (tools/resources gathered).
2. The secret token appears only in request **headers** — never in any request **path/URL** —
   upholding the MCP rule that tokens never travel in a URL.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.mcp_auth import build_auth_headers
from app.mcp_client.discovery import discover_listings
from app.mcp_client.handshake import initialize_session
from app.mcp_client.transport_http import (
    SESSION_ID_HEADER,
    McpAuthRequiredError,
    StreamableHttpTransport,
)

SECRET_TOKEN = "tok-MCAT-6-1-secret"
SESSION_ID = "auth-session-0001"


def _build_handler():
    """Build a stub MCP handler that requires ``Authorization: Bearer <SECRET_TOKEN>``."""

    class _ProtectedMcpHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: N802 - stdlib signature
            return

        def _authorized(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {SECRET_TOKEN}"

        def _reject_unauthorized(self):
            body = json.dumps({"error": "unauthorized"}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("WWW-Authenticate", 'Bearer realm="mcp"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "protected-stub", "version": "1.0.0"},
                }
            if method == "tools/list":
                return {"tools": [{"name": "secure_tool"}]}
            if method == "resources/list":
                return {"resources": [{"uri": "file:///secret"}]}
            if method == "resources/templates/list":
                return {"resourceTemplates": []}
            return {}

        def do_POST(self):  # noqa: N802 - stdlib signature
            self.server.request_paths.append(self.path)  # type: ignore[attr-defined]
            self.server.auth_headers.append(  # type: ignore[attr-defined]
                self.headers.get("Authorization")
            )
            if not self._authorized():
                self._reject_unauthorized()
                return
            body = self._read_body()
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

    return _ProtectedMcpHandler


@pytest.fixture
def protected_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _build_handler())
    server.request_paths = []  # type: ignore[attr-defined]
    server.auth_headers = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, f"http://{host}:{port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_bearer_auth_discovery_succeeds(protected_server):
    server, url = protected_server
    headers = build_auth_headers("bearer", {"token": SECRET_TOKEN})

    async with StreamableHttpTransport(url, headers=headers) as transport:
        init = await initialize_session(transport)
        listings = await discover_listings(transport, init.capabilities)

    # Discovery completed against the protected server.
    assert init.server_info.name == "protected-stub"
    assert [t["name"] for t in listings.tools] == ["secure_tool"]
    assert listings.resources == [{"uri": "file:///secret"}]

    # Every request carried the bearer header (the server would have 401'd otherwise).
    assert server.auth_headers  # at least one request was made
    assert all(h == f"Bearer {SECRET_TOKEN}" for h in server.auth_headers)

    # The token must NEVER appear in any request path/URL — only in headers.
    assert all(SECRET_TOKEN not in path for path in server.request_paths)
    assert all(path == "/mcp" for path in server.request_paths)


async def test_missing_bearer_is_rejected(protected_server):
    # Sanity: without the credential the same stub rejects discovery with a 401 that the
    # transport surfaces as McpAuthRequiredError — proving the stub genuinely enforces auth.
    _server, url = protected_server
    async with StreamableHttpTransport(url) as transport:
        with pytest.raises(McpAuthRequiredError):
            await initialize_session(transport)
