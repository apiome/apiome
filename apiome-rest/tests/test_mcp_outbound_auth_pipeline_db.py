"""Outbound MCP authentication end to end on a migrated database — V2-MCP-EPIC-20 (#3643).

The epic's five children each have their own tests, but most of them mock the store or the HTTP
peer: the auth-type model (#3677) and encryption (#3678) are unit-tested, the credential routes
(#3681) mock the database, and the OAuth flow (#3680) runs against an in-memory credential table.
This suite runs the whole chain from the epic's diagram at once —
``mcp_endpoint_credentials`` → app-layer decrypt → headers on the MCP client, and
OAuth 2.1 auth code + PKCE + refresh → back into the sealed credential — over HTTP, against a
database migrated from empty and a real loopback server.

:class:`_ProtectedServer` is both sides of a protected deployment on one socket:

* ``POST /mcp`` — an MCP server that answers ``401`` with a ``Bearer`` challenge unless the request
  carries an access token it issued (or the static bearer / header secret), and otherwise serves
  ``initialize`` and ``tools/list``.
* ``/.well-known/…`` — its RFC 9728 Protected Resource Metadata and RFC 8414 AS metadata.
* ``/as/register``, ``/as/authorize``, ``/as/token`` — an authorization server that registers
  clients (RFC 7591), redirects with a code bound to the PKCE challenge, requires the RFC 8707
  ``resource`` on every token request, issues JWT access tokens whose ``aud`` is the resource and
  rotates refresh tokens.

Every test runs in one transaction on a dedicated connection that is rolled back, so the database
is left as it was found. Skipped without a reachable migrated database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

import httpx
import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_catalog_routes, mcp_credentials, mcp_discovery_engine, mcp_oauth_service
from app.auth import validate_authentication
from app.config import settings
from app.database import Database
from app.main import app
from app.mcp_client.transport_http import SESSION_ID_HEADER
from app.mcp_credential_crypto import unseal_credential_payload

pytestmark = pytest.mark.requires_db

#: The UI callback the authorization server sends the browser back to.
REDIRECT_URI = "http://localhost:3000/ade/dashboard/mcp/oauth/callback"
#: A static bearer secret the server also accepts (auth type ``bearer``).
STATIC_BEARER = "sk-static-bearer-0001"
#: A static custom-header secret the server also accepts (auth type ``header``).
STATIC_HEADER = ("X-Api-Key", "hk-static-header-0002")
#: The one tool the server lists once a request is authorized.
TOOL = {"name": "search", "description": "Search records.", "inputSchema": {"type": "object"}}


def _jwt(claims: Dict[str, Any]) -> str:
    """An access token shaped like a JWT (Apiome reads ``aud`` but never verifies a signature)."""

    def seg(obj: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'RS256', 'typ': 'at+jwt'})}.{seg(claims)}.c2ln"


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class _ProtectedServer(ThreadingHTTPServer):
    """The stub's shared state: issued tokens and every request worth asserting on."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.base = f"http://127.0.0.1:{self.server_address[1]}"
        self.resource = f"{self.base}/mcp"
        self.expires_in = 3600
        self.clients: Dict[str, List[str]] = {}
        self.codes: Dict[str, Dict[str, Any]] = {}
        self.access_tokens: set = set()
        self.refresh_tokens: Dict[str, str] = {}
        #: ``(path, Authorization header, custom header)`` of every MCP request.
        self.mcp_requests: List[Dict[str, Optional[str]]] = []
        #: The form of every token request.
        self.token_requests: List[Dict[str, str]] = []
        self.issued = 0

    def issue(self, client_id: str) -> Dict[str, Any]:
        """Mint an access + refresh token pair for ``client_id``."""
        self.issued += 1
        access = _jwt({"aud": self.resource, "n": self.issued})
        refresh = f"rt-{self.issued}-{secrets.token_hex(4)}"
        self.access_tokens.add(access)
        self.refresh_tokens[refresh] = client_id
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "refresh_token": refresh,
            "scope": "tools:read",
        }

    def authorized(self, headers: Any) -> bool:
        """True when a request to ``/mcp`` carries a credential this server accepts."""
        auth = headers.get("Authorization") or ""
        if auth == f"Bearer {STATIC_BEARER}" or headers.get(STATIC_HEADER[0]) == STATIC_HEADER[1]:
            return True
        return auth.startswith("Bearer ") and auth[len("Bearer ") :] in self.access_tokens


class _Handler(BaseHTTPRequestHandler):
    server: _ProtectedServer

    def log_message(self, *args: Any) -> None:  # noqa: N802 - stdlib signature
        return

    def _send(self, status: int, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    # -- MCP -----------------------------------------------------------------
    def _mcp(self) -> None:
        raw = self._body()
        server = self.server
        server.mcp_requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "custom": self.headers.get(STATIC_HEADER[0]),
            }
        )
        if not server.authorized(self.headers):
            challenge = (
                f'Bearer realm="stub", resource_metadata="{server.base}/.well-known/oauth-protected-resource/mcp", '
                'scope="tools:read"'
            )
            self._send(401, headers={"WWW-Authenticate": challenge})
            return
        body = json.loads(raw) if raw else {}
        if "id" not in body:
            self._send(202)
            return
        method = body.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "protected-stub", "version": "1.0.0"},
            }
            self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": result}, {SESSION_ID_HEADER: "s-1"})
        elif method == "tools/list":
            self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [TOOL]}})
        else:
            self._send(200, {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "nope"}})

    # -- authorization server ---------------------------------------------------
    def _register(self) -> None:
        body = json.loads(self._body())
        client_id = f"client-{len(self.server.clients) + 1}"
        self.server.clients[client_id] = body["redirect_uris"]
        self._send(201, {"client_id": client_id, "token_endpoint_auth_method": "none"})

    def _authorize(self) -> None:
        """The user consenting: check the request, then redirect back with a code."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        server = self.server
        valid = (
            q.get("response_type") == "code"
            and q.get("code_challenge_method") == "S256"
            and q.get("resource") == server.resource
            and q.get("redirect_uri") in server.clients.get(q.get("client_id", ""), [])
        )
        if not valid:
            self._send(400, {"error": "invalid_request"})
            return
        code = secrets.token_urlsafe(12)
        server.codes[code] = {
            "challenge": q["code_challenge"],
            "client_id": q["client_id"],
            "redirect": q["redirect_uri"],
        }
        location = q["redirect_uri"] + "?" + urlencode({"code": code, "state": q["state"], "iss": f"{server.base}/as"})
        self._send(302, headers={"Location": location})

    def _token(self) -> None:
        form = dict(parse_qsl(self._body().decode()))
        server = self.server
        server.token_requests.append(form)
        if form.get("resource") != server.resource:
            self._send(400, {"error": "invalid_target"})
            return
        if form.get("grant_type") == "authorization_code":
            grant = server.codes.pop(form.get("code", ""), None)
            if (
                grant is None
                or _challenge(form.get("code_verifier", "")) != grant["challenge"]
                or form.get("client_id") != grant["client_id"]
                or form.get("redirect_uri") != grant["redirect"]
            ):
                self._send(400, {"error": "invalid_grant"})
                return
            self._send(200, server.issue(grant["client_id"]))
            return
        if form.get("grant_type") == "refresh_token":
            client_id = server.refresh_tokens.pop(form.get("refresh_token", ""), None)
            if client_id is None or client_id != form.get("client_id"):
                self._send(400, {"error": "invalid_grant"})
                return
            self._send(200, server.issue(client_id))
            return
        self._send(400, {"error": "unsupported_grant_type"})

    # -- routing ---------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = urlsplit(self.path).path
        if path == "/mcp":
            self._mcp()
        elif path == "/as/register":
            self._register()
        elif path == "/as/token":
            self._token()
        else:
            self._send(404)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        base = self.server.base
        path = urlsplit(self.path).path
        if path == "/.well-known/oauth-protected-resource/mcp":
            self._send(
                200,
                {
                    "resource": f"{base}/mcp",
                    "authorization_servers": [f"{base}/as"],
                    "scopes_supported": ["tools:read"],
                },
            )
        elif path == "/.well-known/oauth-authorization-server/as":
            self._send(
                200,
                {
                    "issuer": f"{base}/as",
                    "authorization_endpoint": f"{base}/as/authorize",
                    "token_endpoint": f"{base}/as/token",
                    "registration_endpoint": f"{base}/as/register",
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                },
            )
        elif path == "/as/authorize":
            self._authorize()
        else:
            self._send(404)

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib signature
        self._send(200)


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
    """One tenant and user, one endpoint pointing at the stub, and helpers for each step."""

    def __init__(self, db: Database, conn: Any, server: _ProtectedServer) -> None:
        self.db = db
        self.server = server
        self.client = TestClient(app)
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES ('acme', 'acme-auth-epic') RETURNING id::text AS id"
            )
            self.tenant_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', 'auth-epic@acme.example', 'x') "
                "RETURNING id::text AS id"
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoint = db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name="Protected",
            base_slug="protected",
            endpoint_url=server.resource,
            transport="streamable_http",
        )
        self.endpoint_id = str(self.endpoint["id"])
        self.auth = {"tenant_id": self.tenant_id, "user_id": self.user_id, "auth_method": "jwt"}
        app.dependency_overrides[validate_authentication] = lambda: self.auth

    @property
    def credentials_path(self) -> str:
        return f"/v1/mcp/acme/endpoints/{self.endpoint_id}/credentials"

    async def discover(self) -> Dict[str, Any]:
        """Run one real discovery job and return the finished job row."""
        job = self.db.enqueue_mcp_discovery_job(self.endpoint_id, self.tenant_id)["job"]
        await mcp_discovery_engine._drive_discovery_job(str(job["id"]), dict(self.endpoint))
        return self.db.get_mcp_discovery_job(self.tenant_id, str(job["id"]))

    def credential(self) -> Optional[Dict[str, Any]]:
        return self.db.get_mcp_endpoint_credentials(self.endpoint_id)

    def payload(self) -> Dict[str, Any]:
        """The stored credential, unsealed (the test plays the app layer)."""
        row = self.credential()
        return unseal_credential_payload(row["encrypted_payload"], row["key_version"])

    def authorize(self) -> Dict[str, str]:
        """Start an OAuth connection and consent at the stub; return the redirect's parameters."""
        started = self.client.post(
            f"/v1/mcp/acme/endpoints/{self.endpoint_id}/oauth/authorize", json={"redirect_uri": REDIRECT_URI}
        )
        assert started.status_code == 200, started.text
        consent = httpx.get(started.json()["authorization_url"], follow_redirects=False)
        assert consent.status_code == 302, consent.text
        location = urlsplit(consent.headers["location"])
        assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT_URI
        return {k: v[0] for k, v in parse_qs(location.query).items()}

    def complete(self, redirect: Dict[str, str]) -> httpx.Response:
        return self.client.post("/v1/mcp/acme/oauth/callback", json=redirect)

    async def connect(self) -> None:
        """Discover (401 → metadata), then the whole OAuth round trip."""
        job = await self.discover()
        assert job["result"]["oauth_discovery"]["status"] == "resolved"
        finished = self.complete(self.authorize())
        assert finished.status_code == 200, finished.text


@pytest.fixture
def server() -> Iterator[_ProtectedServer]:
    stub = _ProtectedServer()
    thread = threading.Thread(target=stub.serve_forever, daemon=True)
    thread.start()
    try:
        yield stub
    finally:
        stub.shutdown()
        stub.server_close()
        thread.join(timeout=5)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, server: _ProtectedServer) -> Iterator[Harness]:
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
    for module in (mcp_catalog_routes, mcp_credentials, mcp_discovery_engine, mcp_oauth_service):
        monkeypatch.setattr(module, "db", db)
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    try:
        yield Harness(db, conn, server)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        conn.rollback()
        conn.close()


# ===========================================================================
# Static credentials: none / bearer / header (#3677, #3678, #3681)
# ===========================================================================


async def test_anonymous_discovery_of_a_protected_server_is_auth_required(harness: Harness) -> None:
    job = await harness.discover()

    assert job["state"] == "failed"
    assert job["result"]["error"]["code"] == "auth_required"
    assert harness.server.mcp_requests[0]["authorization"] is None


@pytest.mark.parametrize(
    ("auth_type", "payload", "seen"),
    [
        ("bearer", {"token": STATIC_BEARER}, ("authorization", f"Bearer {STATIC_BEARER}")),
        ("header", {"name": STATIC_HEADER[0], "value": STATIC_HEADER[1]}, ("custom", STATIC_HEADER[1])),
    ],
)
async def test_a_stored_secret_is_sealed_redacted_and_sent_as_a_header(
    harness: Harness, auth_type: str, payload: Dict[str, str], seen: tuple
) -> None:
    secret = next(iter(payload.values())) if auth_type == "bearer" else payload["value"]
    stored = harness.client.put(harness.credentials_path, json={"auth_type": auth_type, "payload": payload})

    assert stored.status_code == 200, stored.text
    assert secret not in stored.text
    row = harness.credential()
    assert row["auth_type"] == auth_type
    assert secret.encode() not in bytes(row["encrypted_payload"])  # ciphertext only (#3678)
    status = harness.client.get(harness.credentials_path).json()["credential"]
    assert status["configured"] is True and status["masked_secret"] and secret not in json.dumps(status)

    job = await harness.discover()

    assert job["state"] == "completed", job["result"]
    field, value = seen
    assert all(request[field] == value for request in harness.server.mcp_requests)
    assert all(secret not in request["path"] for request in harness.server.mcp_requests)


async def test_clearing_the_credential_returns_to_anonymous(harness: Harness) -> None:
    harness.client.put(harness.credentials_path, json={"auth_type": "bearer", "payload": {"token": STATIC_BEARER}})
    assert (await harness.discover())["state"] == "completed"

    cleared = harness.client.delete(harness.credentials_path)

    assert cleared.status_code == 200 and cleared.json()["removed"] is True
    assert harness.client.get(harness.credentials_path).json()["credential"]["auth_type"] == "none"
    assert (await harness.discover())["result"]["error"]["code"] == "auth_required"


# ===========================================================================
# OAuth 2.1: discovery → auth code + PKCE → tokens → refresh (#3679, #3680)
# ===========================================================================


async def test_oauth_connection_end_to_end(harness: Harness) -> None:
    server = harness.server
    first = await harness.discover()
    assert first["result"]["error"]["code"] == "auth_required"
    assert harness.credential()["oauth_metadata"]["pkce_s256_supported"] is True

    redirect = harness.authorize()
    assert list(server.clients) == ["client-1"]  # dynamic registration (RFC 7591)
    finished = harness.complete(redirect)

    assert finished.status_code == 200, finished.text
    payload = harness.payload()
    assert payload["access_token"] not in finished.text and payload["refresh_token"] not in finished.text
    credential = finished.json()["credential"]
    assert credential["auth_type"] == "oauth2" and credential["configured"] is True
    token = credential["oauth_metadata"]["token"]
    assert token["client_id"] == "client-1" and token["refreshable"] is True and token["scope"] == "tools:read"
    row = harness.credential()
    assert "pending_authorization" not in row["oauth_metadata"]
    assert payload["access_token"].encode() not in bytes(row["encrypted_payload"])
    code_request = server.token_requests[0]
    assert code_request["grant_type"] == "authorization_code" and code_request["resource"] == server.resource

    job = await harness.discover()

    assert job["state"] == "completed", job["result"]
    last = server.mcp_requests[-1]
    assert last["authorization"] == f"Bearer {payload['access_token']}"
    assert all(payload["access_token"] not in request["path"] for request in server.mcp_requests)


async def test_a_callback_is_accepted_once(harness: Harness) -> None:
    await harness.discover()
    redirect = harness.authorize()
    assert harness.complete(redirect).status_code == 200

    replay = harness.complete(redirect)

    assert replay.status_code == 400 and "invalid_state" in replay.json()["detail"]


async def test_a_callback_from_another_user_is_refused(harness: Harness) -> None:
    await harness.discover()
    redirect = harness.authorize()
    harness.auth = {**harness.auth, "user_id": "00000000-0000-0000-0000-000000000000"}
    app.dependency_overrides[validate_authentication] = lambda: harness.auth

    refused = harness.complete(redirect)

    assert refused.status_code == 400 and "invalid_state" in refused.json()["detail"]
    assert harness.credential()["auth_type"] == "none"


async def test_an_expiring_token_is_refreshed_before_the_run(harness: Harness) -> None:
    server = harness.server
    server.expires_in = 30  # inside the 60 s refresh window
    await harness.connect()
    before = harness.payload()

    job = await harness.discover()

    assert job["state"] == "completed", job["result"]
    after = harness.payload()
    assert server.token_requests[-1]["grant_type"] == "refresh_token"
    assert server.token_requests[-1]["resource"] == server.resource
    assert after["access_token"] != before["access_token"]
    assert after["refresh_token"] != before["refresh_token"]  # rotated
    assert server.mcp_requests[-1]["authorization"] == f"Bearer {after['access_token']}"
    assert harness.credential()["oauth_metadata"]["token"]["refreshed_at"]


async def test_a_rejected_token_is_refreshed_and_the_run_retried(harness: Harness) -> None:
    server = harness.server
    await harness.connect()
    old = harness.payload()["access_token"]
    server.access_tokens.discard(old)  # the server revoked it before it expired

    job = await harness.discover()

    assert job["state"] == "completed", job["result"]
    new = harness.payload()["access_token"]
    assert new != old
    sent = [request["authorization"] for request in server.mcp_requests]
    assert f"Bearer {old}" in sent and sent[-1] == f"Bearer {new}"


async def test_a_failed_refresh_keeps_the_token_and_records_why(harness: Harness) -> None:
    server = harness.server
    server.expires_in = 30
    await harness.connect()
    token = harness.payload()["access_token"]
    server.refresh_tokens.clear()  # the authorization server forgot the refresh token

    job = await harness.discover()

    assert job["state"] == "completed", job["result"]  # the old token is still accepted
    assert server.mcp_requests[-1]["authorization"] == f"Bearer {token}"
    error = harness.credential()["oauth_metadata"]["token"]["last_refresh_error"]
    assert error["code"] == "token_error" and "invalid_grant" in error["message"]


async def test_token_store_compare_and_set_on_the_database(harness: Harness) -> None:
    await harness.connect()
    row = harness.credential()
    sealed = bytes(row["encrypted_payload"])

    won = harness.db.store_mcp_endpoint_oauth_tokens(
        endpoint_id=harness.endpoint_id,
        encrypted_payload=sealed,
        key_version=row["key_version"],
        metadata_patch={"token": {"refreshed_at": "now"}},
        expected_last_refreshed_at=row["last_refreshed_at"],
        compare=True,
    )
    lost = harness.db.store_mcp_endpoint_oauth_tokens(
        endpoint_id=harness.endpoint_id,
        encrypted_payload=sealed,
        key_version=row["key_version"],
        metadata_patch={"token": {"refreshed_at": "later"}},
        expected_last_refreshed_at=row["last_refreshed_at"],
        compare=True,
    )

    assert won is not None and won["last_refreshed_at"] != row["last_refreshed_at"]
    assert lost is None
    assert harness.credential()["oauth_metadata"]["token"] == {"refreshed_at": "now"}
