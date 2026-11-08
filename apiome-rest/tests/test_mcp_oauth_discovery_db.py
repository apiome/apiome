"""OAuth 2.1 discovery against a migrated database and a live stub server — MCAT-6.3 (#3679).

A loopback stub plays a compliant protected MCP server: ``POST /mcp`` answers ``401`` with a
``Bearer`` challenge naming its RFC 9728 Protected Resource Metadata, which lists an authorization
server whose RFC 8414 metadata the stub also serves. A real discovery job (no runner seam, real
transport) is driven against it and the acceptance criterion is checked: the authorization-server
metadata is resolved and stored in ``mcp_endpoint_credentials.oauth_metadata``. The redacted
``GET …/credentials`` route then reports it, and a later ``PUT`` of a token keeps it.

Everything runs inside one transaction on a dedicated connection that is always rolled back, so the
database is left exactly as it was found. Skipped without a reachable migrated database.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, Optional

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_catalog_routes, mcp_credentials, mcp_discovery_engine
from app.auth import validate_authentication
from app.config import settings
from app.database import Database
from app.main import app

pytestmark = pytest.mark.requires_db


class _ProtectedMcpHandler(BaseHTTPRequestHandler):
    """A protected MCP server: 401 on the MCP path, PRM and AS metadata on the well-known paths."""

    def log_message(self, *args: Any) -> None:  # noqa: N802 - stdlib signature
        return

    def _base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def _json(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        challenge = (
            f'Bearer realm="stub", resource_metadata="{self._base()}/.well-known/oauth-protected-resource/mcp", '
            'scope="tools:read"'
        )
        self.send_response(401)
        self.send_header("WWW-Authenticate", challenge)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        base = self._base()
        if self.path == "/.well-known/oauth-protected-resource/mcp":
            self._json(
                {
                    "resource": f"{base}/mcp",
                    "authorization_servers": [f"{base}/as"],
                    "scopes_supported": ["tools:read", "tools:call"],
                }
            )
        elif self.path == "/.well-known/oauth-authorization-server/as":
            self._json(
                {
                    "issuer": f"{base}/as",
                    "authorization_endpoint": f"{base}/as/authorize",
                    "token_endpoint": f"{base}/as/token",
                    "registration_endpoint": f"{base}/as/register",
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                }
            )
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
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


class Harness:
    """One tenant, one endpoint pointing at the stub, and helpers to drive discovery."""

    def __init__(self, db: Database, conn: Any, base_url: str) -> None:
        self.db = db
        self.conn = conn
        self.base_url = base_url
        self.client = TestClient(app)
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES ('acme', 'acme-oauth-db') RETURNING id::text AS id"
            )
            self.tenant_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', 'oauth-db@acme.example', 'x') "
                "RETURNING id::text AS id"
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoint = db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name="Protected",
            base_slug="protected",
            endpoint_url=f"{base_url}/mcp",
            transport="streamable_http",
        )
        self.endpoint_id = str(self.endpoint["id"])
        auth = {"tenant_id": self.tenant_id, "user_id": self.user_id, "auth_method": "jwt"}
        app.dependency_overrides[validate_authentication] = lambda: auth

    async def discover(self) -> Dict[str, Any]:
        """Run one real discovery job for the endpoint and return the finished job row."""
        job = self.db.enqueue_mcp_discovery_job(self.endpoint_id, self.tenant_id)["job"]
        await mcp_discovery_engine._drive_discovery_job(str(job["id"]), dict(self.endpoint))
        return self.db.get_mcp_discovery_job(self.tenant_id, str(job["id"]))

    def credential(self) -> Optional[Dict[str, Any]]:
        return self.db.get_mcp_endpoint_credentials(self.endpoint_id)

    def credentials_path(self) -> str:
        return f"/v1/mcp/acme/endpoints/{self.endpoint_id}/credentials"


@pytest.fixture
def stub_base_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProtectedMcpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, stub_base_url: str) -> Iterator[Harness]:
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.mcp_endpoint_credentials') IS NOT NULL AS ok")
        ready = probe.fetchone()["ok"]
    if not ready:
        conn.close()
        pytest.skip("the MCP catalog migrations are not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    for module in (mcp_catalog_routes, mcp_credentials, mcp_discovery_engine):
        monkeypatch.setattr(module, "db", db)
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    try:
        yield Harness(db, conn, stub_base_url)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        conn.rollback()
        conn.close()


async def test_a_401_resolves_and_stores_the_authorization_server_metadata(harness: Harness) -> None:
    base = harness.base_url
    job = await harness.discover()

    assert job["state"] == "failed"
    assert job["result"]["error"]["code"] == "auth_required"
    assert job["result"]["oauth_discovery"] == {
        "status": "resolved",
        "issuer": f"{base}/as",
        "resource": f"{base}/mcp",
        "authorization_endpoint": f"{base}/as/authorize",
        "token_endpoint": f"{base}/as/token",
    }

    row = harness.credential()
    assert row is not None
    # Stored with no secret: the endpoint still runs anonymously until a token is set.
    assert (row["auth_type"], row["encrypted_payload"], row["key_version"]) == ("none", None, None)
    metadata = row["oauth_metadata"]
    assert metadata["source"] == "oauth_discovery"
    assert metadata["resource"] == f"{base}/mcp"
    assert metadata["resource_metadata_url"] == f"{base}/.well-known/oauth-protected-resource/mcp"
    assert metadata["issuer"] == f"{base}/as"
    assert metadata["authorization_server_metadata_url"] == f"{base}/.well-known/oauth-authorization-server/as"
    assert metadata["registration_endpoint"] == f"{base}/as/register"
    assert metadata["scopes_supported"] == ["tools:read", "tools:call"]
    assert metadata["challenge_scopes"] == ["tools:read"]
    assert metadata["pkce_s256_supported"] is True


async def test_the_credentials_route_reports_the_discovered_metadata(harness: Harness) -> None:
    await harness.discover()

    response = harness.client.get(harness.credentials_path())

    assert response.status_code == 200, response.text
    credential = response.json()["credential"]
    assert credential["auth_type"] == "none"
    assert credential["configured"] is False
    assert credential["oauth_metadata"]["token_endpoint"] == f"{harness.base_url}/as/token"


async def test_rediscovery_merges_over_existing_metadata(harness: Harness) -> None:
    harness.db.merge_mcp_endpoint_oauth_metadata(harness.endpoint_id, {"client_id": "apiome-client", "issuer": "old"})

    await harness.discover()

    metadata = harness.credential()["oauth_metadata"]
    assert metadata["client_id"] == "apiome-client"
    assert metadata["issuer"] == f"{harness.base_url}/as"


async def test_setting_a_token_keeps_the_metadata_unless_replaced(harness: Harness) -> None:
    await harness.discover()

    kept = harness.client.put(
        harness.credentials_path(), json={"auth_type": "oauth2", "payload": {"access_token": "at-123"}}
    )
    assert kept.status_code == 200, kept.text
    row = harness.credential()
    assert row["auth_type"] == "oauth2" and row["encrypted_payload"] is not None
    assert row["oauth_metadata"]["issuer"] == f"{harness.base_url}/as"

    replaced = harness.client.put(
        harness.credentials_path(),
        json={"auth_type": "oauth2", "payload": {"access_token": "at-456"}, "oauth_metadata": {"note": "manual"}},
    )
    assert replaced.status_code == 200, replaced.text
    assert harness.credential()["oauth_metadata"] == {"note": "manual"}


async def test_merging_never_touches_a_stored_secret(harness: Harness) -> None:
    harness.client.put(harness.credentials_path(), json={"auth_type": "bearer", "payload": {"token": "sk-1"}})
    before = harness.credential()

    harness.db.merge_mcp_endpoint_oauth_metadata(harness.endpoint_id, {"issuer": "https://as.example"})

    after = harness.credential()
    assert (after["auth_type"], bytes(after["encrypted_payload"]), after["key_version"]) == (
        before["auth_type"],
        bytes(before["encrypted_payload"]),
        before["key_version"],
    )
    assert after["oauth_metadata"] == {"issuer": "https://as.example"}
