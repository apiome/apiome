"""The MCP query & test harness against a migrated database and a live stub server — V2-MCP-EPIC-22 (#3645).

The epic's children built the pieces: the invocation service (#3687), the ``POST …/test`` route
(#3688), the redacted invocation log and safety guards (#3689) and the CLI / UI that call it
(#3690). Their route tests mock both the database and :mod:`app.mcp_invoke`, and the invocation
integration test calls the service directly, so the whole chain — a tool read from a snapshot
stored by discovery, a real ``tools/call`` round trip, and the audit row written to
``mcp_test_invocations`` — never ran together. This module drives the real route over HTTP
(``TestClient``) against a database migrated from empty by apiome-db, on snapshots persisted by
the real :meth:`Database.record_mcp_discovery_version`, calling a stub MCP server on a loopback
socket, and checks the epic's acceptance criteria:

* **End to end.** A stored tool is invoked with stored-schema-valid arguments; the response
  carries the tool's content, a measured latency and the id of the audit row, and that row
  records the version, tool, outcome, latency and acting user.
* **Three outcomes.** A tool-level error (``isError``) and a JSON-RPC failure are reported in-band
  with HTTP 200, told apart by ``completed``, and both are logged as errors. An unreachable server
  is a failed call too, not a 5xx.
* **Safety.** A destructive tool is refused with 428 until ``confirm`` is sent; arguments that fail
  the stored ``inputSchema`` are refused with 422; neither reaches the server or the log. Secret
  arguments are masked in the log; an ephemeral auth override reaches the server but is never
  stored or logged. The per-endpoint rate limit refuses the call over budget with 429.
* **Errors and isolation.** An undiscovered endpoint is 409; another tenant gets 404; an unknown
  tool is 404; none of them calls out or writes a row.

Everything runs inside one transaction on a dedicated connection that is always rolled back, so the
database is left exactly as it was found. Skipped without a reachable migrated database.
"""

from __future__ import annotations

import json
import socket
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Optional

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_catalog_routes, mcp_credentials
from app.auth import validate_authentication
from app.config import settings
from app.database import Database
from app.main import app
from app.mcp_client import DiscoveryListings, DiscoverySurface, InitializeResult, ServerInfo
from app.mcp_client.transport_http import SESSION_ID_HEADER
from app.models import MCP_INVOCATION_REDACTION_MASK
from app.rate_limit import FixedWindowRateLimiter

pytestmark = pytest.mark.requires_db

DISCOVERED_AT = datetime(2026, 11, 8, 14, 3, 0, tzinfo=timezone.utc)

#: Echoes its ``message`` argument back as text; ``message`` is required by the stored schema.
ECHO_TOOL = {
    "name": "echo",
    "description": "Echo a message back.",
    "inputSchema": {
        "type": "object",
        "properties": {"message": {"type": "string"}, "api_key": {"type": "string"}},
        "required": ["message"],
    },
    "annotations": {"readOnlyHint": True},
}
#: Answers with a tool-level error (``isError: true``).
BOOM_TOOL = {"name": "boom", "description": "Always fails.", "inputSchema": {"type": "object"}}
#: Listed at discovery time, but the server now answers it with a JSON-RPC error.
GONE_TOOL = {"name": "gone", "description": "Removed upstream.", "inputSchema": {"type": "object"}}
#: Flagged destructive, so the harness must refuse it without an explicit confirm.
WIPE_TOOL = {
    "name": "wipe",
    "description": "Delete every record.",
    "inputSchema": {"type": "object"},
    "annotations": {"destructiveHint": True},
}
ALL_TOOLS = (ECHO_TOOL, BOOM_TOOL, GONE_TOOL, WIPE_TOOL)

BEARER_SECRET = "sk-override-secret-1234"


class _StubMcpHandler(BaseHTTPRequestHandler):
    """A loopback MCP server that initializes and answers ``tools/call`` by tool name.

    Every ``tools/call`` it receives is appended to ``server.calls`` with the tool name, the
    arguments and the ``Authorization`` header, so a test can tell what actually left the harness.
    """

    def log_message(self, *args: Any) -> None:  # noqa: N802 - stdlib signature
        return

    def _send_json(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
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
            self._send_json(
                {"jsonrpc": "2.0", "id": body["id"], "result": result},
                {SESSION_ID_HEADER: "harness-db-session"},
            )
            return
        if method != "tools/call":
            self._send_json({"jsonrpc": "2.0", "id": body["id"], "result": {}})
            return

        params = body.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        self.server.calls.append(  # type: ignore[attr-defined]
            {"name": name, "arguments": arguments, "authorization": self.headers.get("Authorization")}
        )
        if name == "echo":
            result = {"content": [{"type": "text", "text": arguments.get("message", "")}], "isError": False}
        elif name in ("boom", "wipe"):
            result = {"content": [{"type": "text", "text": f"{name} failed"}], "isError": name == "boom"}
        else:
            self._send_json(
                {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
            )
            return
        self._send_json({"jsonrpc": "2.0", "id": body["id"], "result": result})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib signature
        self.send_response(200)
        self.end_headers()


class _NoCommitConnection:
    """A real connection whose commits and rollbacks are swallowed, so one test is one transaction."""

    closed = False

    class _Info:
        transaction_status = TRANSACTION_STATUS_IDLE

    info = _Info()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return False

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


def _surface(*tools: Dict[str, Any]) -> DiscoverySurface:
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="stub", title="Stub", version="0.1.0"),
        capabilities={"tools": {}},
        instructions=None,
        raw={},
    )
    return DiscoverySurface.from_discovery(init, DiscoveryListings(tools=list(tools)))


def _closed_port_url() -> str:
    """A loopback MCP URL nothing is listening on (the port is bound, then released)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/mcp"


class Harness:
    """Two tenants, an endpoint pointed at the stub server, and an HTTP client acting as a tenant."""

    def __init__(self, db: Database, conn: Any, server: ThreadingHTTPServer) -> None:
        self.db = db
        self.conn = conn
        self.server = server
        self.client = TestClient(app)
        host, port = server.server_address[:2]
        self.stub_url = f"http://{host}:{port}/mcp"
        suffix = uuid.uuid4().hex[:8]
        with conn.cursor() as cursor:
            self.tenant_id = self._tenant(cursor, f"harness-{suffix}")
            self.other_tenant_id = self._tenant(cursor, f"harness-other-{suffix}")
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', %s, 'x') RETURNING id::text AS id",
                (f"ada-{suffix}@example.com",),
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoint_id = self.endpoint("stub")
        self.version_id = self.snapshot(_surface(*ALL_TOOLS))
        self.act_as(self.tenant_id)

    @staticmethod
    def _tenant(cursor: Any, slug: str) -> str:
        cursor.execute(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (slug, slug),
        )
        return cursor.fetchone()["id"]

    @property
    def calls(self) -> List[Dict[str, Any]]:
        """The ``tools/call`` requests the stub server has received so far."""
        return self.server.calls  # type: ignore[attr-defined]

    def endpoint(self, slug: str, url: str = "") -> str:
        """Catalog an endpoint for the main tenant (the stub server by default); return its id."""
        row = self.db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name=slug,
            base_slug=slug,
            endpoint_url=url or self.stub_url,
            transport="streamable_http",
        )
        return str(row["id"])

    def snapshot(self, surface: DiscoverySurface, endpoint_id: str = "") -> str:
        """Persist a version snapshot of ``surface`` the way discovery does; return its id."""
        persisted = self.db.record_mcp_discovery_version(
            endpoint_id or self.endpoint_id,
            version_row=surface.to_version_row(),
            capability_rows=surface.to_capability_rows(None),
            change_rows=[],
            discovered_at=DISCOVERED_AT,
        )
        return persisted["version_id"]

    def act_as(self, tenant_id: str) -> None:
        """Authenticate following requests as ``tenant_id``."""
        auth = {"tenant_id": tenant_id, "user_id": self.user_id, "auth_method": "jwt"}
        app.dependency_overrides[validate_authentication] = lambda: auth

    def test(
        self, tool: str, arguments: Optional[Dict[str, Any]] = None, *, endpoint_id: str = "", **extra: Any
    ) -> Any:
        """``POST …/test`` for ``tool`` on an endpoint (the stub endpoint by default)."""
        body = {"item_type": "tool", "item_name": tool, "arguments": arguments or {}, **extra}
        return self.client.post(f"/v1/mcp/acme/endpoints/{endpoint_id or self.endpoint_id}/test", json=body)

    def invocations(self, endpoint_id: str = "") -> List[Dict[str, Any]]:
        """The audit rows logged for an endpoint, oldest first."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT id::text AS id, version_id::text AS version_id, item_type, item_name, "
                "arguments, response, is_error, latency_ms, invoked_by::text AS invoked_by "
                "FROM apiome.mcp_test_invocations WHERE endpoint_id = %s::uuid ORDER BY created_at, id",
                (endpoint_id or self.endpoint_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def credential_rows(self) -> int:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS n FROM apiome.mcp_endpoint_credentials WHERE endpoint_id = %s::uuid",
                (self.endpoint_id,),
            )
            return int(cursor.fetchone()["n"])


@pytest.fixture
def stub_server() -> Iterator[ThreadingHTTPServer]:
    """Run the stub MCP server on a loopback port for one test."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubMcpHandler)
    server.calls = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, stub_server: ThreadingHTTPServer) -> Iterator[Harness]:
    """The test-harness route wired to a real, migrated database inside one rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.mcp_test_invocations') IS NOT NULL AS ok")
        ready = probe.fetchone()["ok"]
    if not ready:
        conn.close()
        pytest.skip("the MCP catalog migrations are not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(mcp_catalog_routes, "db", db)
    monkeypatch.setattr(mcp_credentials, "db", db)
    # A fresh per-endpoint limiter with a generous budget; the rate-limit test lowers it.
    monkeypatch.setattr(mcp_catalog_routes, "_test_invocation_limiter", FixedWindowRateLimiter())
    monkeypatch.setattr(mcp_catalog_routes.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(mcp_catalog_routes.settings, "mcp_test_rate_limit_per_minute", 1000)
    monkeypatch.setattr(mcp_catalog_routes.settings, "rate_limit_window_seconds", 60)
    try:
        yield Harness(db, conn, stub_server)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        conn.rollback()
        conn.close()


# ===========================================================================
# End to end
# ===========================================================================


def test_a_stored_tool_is_invoked_live_and_the_call_is_logged(harness: Harness) -> None:
    response = harness.test("echo", {"message": "hello harness"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["method"], body["target"]) == ("tools/call", "echo")
    assert body["completed"] is True and body["isError"] is False
    assert body["content"] == [{"type": "text", "text": "hello harness"}]
    assert body["latencyMs"] > 0
    assert body["authOverrideApplied"] is False

    assert harness.calls == [{"name": "echo", "arguments": {"message": "hello harness"}, "authorization": None}]
    (row,) = harness.invocations()
    assert row["id"] == body["invocationId"]
    assert row["version_id"] == harness.version_id
    assert (row["item_type"], row["item_name"]) == ("tool", "echo")
    assert row["is_error"] is False
    assert row["latency_ms"] == round(body["latencyMs"])
    assert row["invoked_by"] == harness.user_id
    assert row["arguments"] == {"message": "hello harness"}
    assert row["response"]["content"] == [{"type": "text", "text": "hello harness"}]


def test_the_latest_snapshot_is_the_surface_that_is_tested(harness: Harness) -> None:
    # Re-discovery drops ``echo``: the harness follows the endpoint's current version.
    newer = harness.snapshot(_surface(BOOM_TOOL))

    assert harness.test("echo", {"message": "hi"}).status_code == 404
    response = harness.test("boom")

    assert response.status_code == 200, response.text
    assert [row["version_id"] for row in harness.invocations()] == [newer]


# ===========================================================================
# Three outcomes, each reported in-band and logged
# ===========================================================================


def test_a_tool_error_is_reported_in_band_and_logged_as_an_error(harness: Harness) -> None:
    response = harness.test("boom")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completed"] is True and body["isError"] is True
    assert body["content"] == [{"type": "text", "text": "boom failed"}]
    assert body["error"] is None
    (row,) = harness.invocations()
    assert row["is_error"] is True
    assert row["response"]["is_error"] is True


def test_a_json_rpc_failure_is_a_failed_call_not_a_tool_error(harness: Harness) -> None:
    response = harness.test("gone")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completed"] is False
    assert body["error"]["code"] == "jsonrpc_error"
    assert "Unknown tool" in body["error"]["message"]
    (row,) = harness.invocations()
    assert row["is_error"] is True
    assert row["response"]["completed"] is False
    assert row["response"]["error"]["code"] == "jsonrpc_error"


def test_an_unreachable_server_is_a_failed_call_not_a_server_error(harness: Harness) -> None:
    down = harness.endpoint("down", _closed_port_url())
    harness.snapshot(_surface(ECHO_TOOL), down)

    response = harness.test("echo", {"message": "anyone?"}, endpoint_id=down, timeout_seconds=5)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completed"] is False
    assert body["error"]["code"] == "connect_error"
    (row,) = harness.invocations(down)
    assert row["is_error"] is True
    assert row["latency_ms"] is not None


# ===========================================================================
# Safety guards
# ===========================================================================


def test_a_destructive_tool_needs_confirm_before_it_is_called(harness: Harness) -> None:
    refused = harness.test("wipe")

    assert refused.status_code == 428
    assert "confirm" in refused.json()["detail"]
    assert harness.calls == []
    assert harness.invocations() == []

    confirmed = harness.test("wipe", confirm=True)

    assert confirmed.status_code == 200, confirmed.text
    assert [call["name"] for call in harness.calls] == ["wipe"]
    assert [row["item_name"] for row in harness.invocations()] == ["wipe"]


def test_arguments_that_fail_the_stored_schema_never_leave_the_harness(harness: Harness) -> None:
    for arguments in ({}, {"message": 42}):
        assert harness.test("echo", arguments).status_code == 422

    assert harness.calls == []
    assert harness.invocations() == []


def test_secret_arguments_are_sent_to_the_server_but_masked_in_the_log(harness: Harness) -> None:
    response = harness.test("echo", {"message": "hi", "api_key": "sk-live-9999"})

    assert response.status_code == 200, response.text
    assert harness.calls[0]["arguments"]["api_key"] == "sk-live-9999"
    (row,) = harness.invocations()
    assert row["arguments"] == {"message": "hi", "api_key": MCP_INVOCATION_REDACTION_MASK}


def test_an_auth_override_reaches_the_server_but_is_never_stored(harness: Harness) -> None:
    response = harness.test(
        "echo",
        {"message": "with auth"},
        auth_override={"auth_type": "bearer", "payload": {"token": BEARER_SECRET}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["authOverrideApplied"] is True
    assert harness.calls[0]["authorization"] == f"Bearer {BEARER_SECRET}"
    assert BEARER_SECRET not in response.text
    assert harness.credential_rows() == 0
    (row,) = harness.invocations()
    assert BEARER_SECRET not in json.dumps(row, default=str)


def test_calls_over_the_per_endpoint_budget_are_refused_with_429(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_catalog_routes.settings, "mcp_test_rate_limit_per_minute", 2)

    statuses = [harness.test("echo", {"message": str(n)}).status_code for n in range(3)]

    assert statuses == [200, 200, 429]
    assert len(harness.calls) == 2
    assert len(harness.invocations()) == 2


# ===========================================================================
# Errors and tenant isolation
# ===========================================================================


def test_an_undiscovered_endpoint_is_409(harness: Harness) -> None:
    fresh = harness.endpoint("fresh")

    response = harness.test("echo", {"message": "hi"}, endpoint_id=fresh)

    assert response.status_code == 409
    assert harness.calls == []
    assert harness.invocations(fresh) == []


def test_another_tenant_gets_404_and_nothing_is_called_or_logged(harness: Harness) -> None:
    harness.act_as(harness.other_tenant_id)

    assert harness.test("echo", {"message": "hi"}).status_code == 404
    assert harness.calls == []
    assert harness.invocations() == []


def test_a_tool_not_on_the_surface_is_404(harness: Harness) -> None:
    assert harness.test("not_a_tool").status_code == 404
    assert harness.calls == []
    assert harness.invocations() == []
