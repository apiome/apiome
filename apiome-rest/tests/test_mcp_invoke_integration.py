"""Integration test for the MCP invocation service (V2-MCP-22.1 / MCAT-8.1, #3687).

Unlike ``test_mcp_invoke.py`` (which mocks httpx), this drives :func:`app.mcp_invoke.invoke_tool`
against a **real** stub MCP server over a loopback TCP socket — the ticket's acceptance
criterion: *"calls a stub tool and returns content + latency; ``isError`` results surfaced
distinctly from transport errors."* The stub answers ``initialize`` and three flavours of
``tools/call`` (a normal result, an ``isError:true`` result, and a JSON-RPC error), so the full
HTTP round trip — handshake, the call, latency timing, and the session ``DELETE`` — is exercised
end to end with no mocking.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from app.mcp_client.errors import DiscoveryErrorCode
from app.mcp_client.transport_http import SESSION_ID_HEADER
from app.mcp_invoke import invoke_tool

SESSION_ID = "invoke-int-session-0001"


class _StubMcpHandler(BaseHTTPRequestHandler):
    """A loopback MCP server that initializes and answers ``tools/call`` by tool name."""

    def log_message(self, *args):  # noqa: N802 - stdlib signature
        return

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - stdlib signature
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            return

        body = self._read_body()
        if "id" not in body:  # notifications/initialized
            self.send_response(202)
            self.end_headers()
            return

        method = body.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "stub", "version": "0.1.0"},
            }
            body_bytes = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header(SESSION_ID_HEADER, SESSION_ID)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return

        if method == "tools/call":
            name = (body.get("params") or {}).get("name")
            if name == "echo":
                args = (body.get("params") or {}).get("arguments") or {}
                self._send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "content": [{"type": "text", "text": args.get("message", "")}],
                            "isError": False,
                        },
                    }
                )
                return
            if name == "boom":
                self._send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "content": [{"type": "text", "text": "tool blew up"}],
                            "isError": True,
                        },
                    }
                )
                return
            # Any other tool: a JSON-RPC protocol error (unknown tool).
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"},
                }
            )
            return

        self._send_json({"jsonrpc": "2.0", "id": body["id"], "result": {}})

    def do_DELETE(self):  # noqa: N802 - stdlib signature
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def stub_server() -> Iterator[str]:
    """Run the stub MCP server on a loopback port; yield its ``…/mcp`` URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubMcpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_invoke_tool_against_real_stub_returns_content_and_latency(stub_server):
    """The acceptance path: a real stub tool returns content + a measured latency."""
    result = await invoke_tool(stub_server, "echo", {"message": "hello stub"})

    assert result.completed is True
    assert result.is_error is False
    assert result.succeeded is True
    assert result.content == ({"type": "text", "text": "hello stub"},)
    assert result.latency_ms > 0.0  # a real round trip takes measurable time


async def test_invoke_tool_iserror_distinct_from_transport_error(stub_server):
    """An ``isError:true`` result completes (with content) — not a transport failure."""
    result = await invoke_tool(stub_server, "boom")

    assert result.completed is True
    assert result.is_error is True
    assert result.error is None
    assert result.content == ({"type": "text", "text": "tool blew up"},)


async def test_invoke_unknown_tool_is_protocol_failure(stub_server):
    """An unknown tool surfaces as a JSON-RPC protocol failure over the real socket."""
    result = await invoke_tool(stub_server, "does-not-exist")

    assert result.completed is False
    assert result.error is not None
    assert result.error.code is DiscoveryErrorCode.JSONRPC_ERROR
    assert result.error.detail["code"] == -32602
