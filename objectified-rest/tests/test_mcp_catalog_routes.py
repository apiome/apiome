"""API + DB tests for MCP Catalog endpoint CRUD (V2-MCP-17.1 / MCAT-3.1, #3663).

Covers the tenant-scoped ``/v1/mcp/{tenant_slug}/endpoints`` routes — list, get,
create, patch — plus the slug auto-derivation/uniqueness and partial-update
helpers in the DB layer, and the request/response model validation.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app.auth import validate_authentication
from app.database import Database
from app.main import app
from app.models import (
    MCP_DISCOVERY_CADENCE_MAX_SECONDS,
    MCP_DISCOVERY_CADENCE_MIN_SECONDS,
    McpEndpointCreate,
    McpEndpointUpdate,
    mcp_endpoint_out_from_row,
    redact_url_credentials,
    validate_mcp_endpoint_url,
)

client = TestClient(app)

# Auth payloads as produced by ``validate_authentication`` (token tenant, not URL slug).
_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_APIKEY_NO_USER = {"tenant_id": "t1", "auth_method": "api_key"}

_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)

_ENDPOINT_ROW = {
    "id": "ep-1",
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/sse",
    "transport": "streamable_http",
    "description": "Weather tools",
    "category": "weather",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "discovery_cadence_seconds": 3600,
    "last_discovered_at": _NOW,
    "last_discovery_status": "ok",
    "current_version_id": None,
    "created_at": _NOW,
    "updated_at": _NOW,
}


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# LIST
# ===========================================================================


def test_list_endpoints_ok():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints.return_value = [_ENDPOINT_ROW]
        r = client.get("/v1/mcp/acme/endpoints")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["endpoints"]) == 1
    ep = body["endpoints"][0]
    assert ep["slug"] == "acme-weather"
    assert ep["transport"] == "streamable_http"
    assert ep["discovery_cadence_seconds"] == 3600
    assert ep["last_discovered_at"].startswith("2026-06-26")


def test_list_endpoints_scoped_to_token_tenant():
    """DB is queried with the token's tenant_id, never the URL slug."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints.return_value = []
        client.get("/v1/mcp/some-other-slug/endpoints")
        mdb.list_mcp_endpoints.assert_called_once_with("t1")


def test_list_endpoints_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get("/v1/mcp/acme/endpoints")
    assert r.status_code == 401


# ===========================================================================
# GET
# ===========================================================================


def test_get_endpoint_ok():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.get(f"/v1/mcp/acme/endpoints/{'a' * 8}-0000-0000-0000-000000000000")
    assert r.status_code == 200
    assert r.json()["endpoint"]["id"] == "ep-1"


def test_get_endpoint_cross_tenant_404():
    """A row owned by another tenant is scoped out by the DB layer → 404."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get("/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 404


def test_get_endpoint_rejects_non_uuid():
    """Path is typed ``uuid.UUID`` so a non-UUID id is a 422, not a DB hit."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.get("/v1/mcp/acme/endpoints/not-a-uuid")
    assert r.status_code == 422
    mdb.get_mcp_endpoint.assert_not_called()


# ===========================================================================
# CREATE
# ===========================================================================


def test_create_endpoint_ok_derives_slug():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.insert_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={
                "name": "Acme Weather!",
                "endpointUrl": "https://mcp.acme.example/sse",
                "transport": "streamable_http",
            },
        )
    assert r.status_code == 201
    kwargs = mdb.insert_mcp_endpoint.call_args.kwargs
    assert kwargs["tenant_id"] == "t1"
    assert kwargs["creator_id"] == "user-1"
    # Punctuation collapses to a single hyphen and is trimmed.
    assert kwargs["base_slug"] == "acme-weather"
    assert kwargs["endpoint_url"] == "https://mcp.acme.example/sse"


def test_create_endpoint_honors_explicit_slug():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.insert_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={
                "name": "Acme Weather",
                "endpoint_url": "https://mcp.acme.example/sse",
                "slug": "My Custom Slug",
            },
        )
    assert r.status_code == 201
    assert mdb.insert_mcp_endpoint.call_args.kwargs["base_slug"] == "my-custom-slug"


def test_create_endpoint_defaults_transport_and_visibility():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.insert_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "Acme", "endpoint_url": "https://x.example"},
        )
    assert r.status_code == 201
    kwargs = mdb.insert_mcp_endpoint.call_args.kwargs
    assert kwargs["transport"] == "streamable_http"
    assert kwargs["visibility"] == "private"


def test_create_endpoint_invalid_transport_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "X", "endpoint_url": "https://x", "transport": "carrier-pigeon"},
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_invalid_visibility_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "X", "endpoint_url": "https://x", "visibility": "secret"},
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_missing_name_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post("/v1/mcp/acme/endpoints", json={"endpoint_url": "https://x"})
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_nonpositive_cadence_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "X", "endpoint_url": "https://x", "discoveryCadenceSeconds": 0},
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_slug_conflict_409():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.insert_mcp_endpoint.side_effect = pg_errors.UniqueViolation("dup")
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "Acme", "endpoint_url": "https://x"},
        )
    assert r.status_code == 409


def test_create_endpoint_requires_resolvable_actor_403():
    """An API-key caller with no resolvable user cannot be attributed → 403."""
    app.dependency_overrides[validate_authentication] = lambda: _APIKEY_NO_USER
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "Acme", "endpoint_url": "https://x"},
        )
    assert r.status_code == 403
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post("/v1/mcp/acme/endpoints", json={"name": "X", "endpoint_url": "https://x"})
    assert r.status_code == 401


# ===========================================================================
# PATCH
# ===========================================================================


def test_patch_endpoint_ok_applies_only_present_fields():
    updated = {**_ENDPOINT_ROW, "enabled": False, "name": "Renamed"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.update_mcp_endpoint.return_value = updated
        r = client.patch(
            "/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111",
            json={"enabled": False, "name": "Renamed"},
        )
    assert r.status_code == 200
    args = mdb.update_mcp_endpoint.call_args.args
    assert args[0] == "t1"  # tenant from token
    assert args[1] == "11111111-1111-1111-1111-111111111111"
    fields = args[2]
    assert fields == {"enabled": False, "name": "Renamed"}


def test_patch_endpoint_blank_description_becomes_null():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.update_mcp_endpoint.return_value = _ENDPOINT_ROW
        client.patch(
            "/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111",
            json={"description": "   "},
        )
    assert mdb.update_mcp_endpoint.call_args.args[2] == {"description": None}


def test_patch_endpoint_cross_tenant_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.update_mcp_endpoint.return_value = None
        r = client.patch(
            "/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111",
            json={"enabled": True},
        )
    assert r.status_code == 404


def test_patch_endpoint_invalid_transport_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.patch(
            "/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111",
            json={"transport": "telepathy"},
        )
    assert r.status_code == 422
    mdb.update_mcp_endpoint.assert_not_called()


def test_patch_endpoint_empty_body_is_noop():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.update_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.patch(
            "/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111",
            json={},
        )
    assert r.status_code == 200
    assert mdb.update_mcp_endpoint.call_args.args[2] == {}


# ===========================================================================
# DELETE (lifecycle — soft delete + child purge, V2-MCP-17.5 / MCAT-3.5)
# ===========================================================================


def test_delete_endpoint_ok_returns_teardown_summary():
    summary = {
        "endpoint_id": "11111111-1111-1111-1111-111111111111",
        "credentials_purged": True,
        "versions_deleted": 2,
        "jobs_deleted": 3,
    }
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.soft_delete_mcp_endpoint.return_value = summary
        r = client.delete("/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["endpoint_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["credentials_purged"] is True
    assert body["versions_deleted"] == 2
    assert body["jobs_deleted"] == 3
    args = mdb.soft_delete_mcp_endpoint.call_args.args
    assert args[0] == "t1"  # tenant from token, not URL slug
    assert args[1] == "11111111-1111-1111-1111-111111111111"


def test_delete_endpoint_scoped_to_token_tenant():
    """The delete is scoped by the token tenant, never the URL slug."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.soft_delete_mcp_endpoint.return_value = {
            "endpoint_id": "11111111-1111-1111-1111-111111111111",
            "credentials_purged": False,
            "versions_deleted": 0,
            "jobs_deleted": 0,
        }
        client.delete("/v1/mcp/some-other-slug/endpoints/11111111-1111-1111-1111-111111111111")
        assert mdb.soft_delete_mcp_endpoint.call_args.args[0] == "t1"


def test_delete_endpoint_cross_tenant_or_missing_404():
    """A row owned by another tenant (or already deleted) matches nothing → 404."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.soft_delete_mcp_endpoint.return_value = None
        r = client.delete("/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 404


def test_delete_endpoint_rejects_non_uuid():
    """Path is typed ``uuid.UUID`` so a non-UUID id is a 422, not a DB hit."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.delete("/v1/mcp/acme/endpoints/not-a-uuid")
    assert r.status_code == 422
    mdb.soft_delete_mcp_endpoint.assert_not_called()


def test_delete_endpoint_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.delete("/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 401


# ===========================================================================
# Model validation
# ===========================================================================


def test_model_create_camelcase_and_snake_case():
    m1 = McpEndpointCreate(name="A", endpointUrl="https://x", discoveryCadenceSeconds=600)
    m2 = McpEndpointCreate(name="A", endpoint_url="https://x", discovery_cadence_seconds=600)
    assert m1.endpoint_url == m2.endpoint_url == "https://x"
    assert m1.discovery_cadence_seconds == 600


def test_model_update_has_any_field():
    assert McpEndpointUpdate().has_any_field() is False
    assert McpEndpointUpdate(enabled=False).has_any_field() is True


def test_mcp_endpoint_out_from_row_normalizes_types():
    out = mcp_endpoint_out_from_row(_ENDPOINT_ROW)
    assert out.id == "ep-1"
    assert out.last_discovered_at.startswith("2026-06-26")
    assert out.current_version_id is None
    assert out.published is False


# ===========================================================================
# Endpoint Pydantic models & validation (V2-MCP-17.3 / MCAT-3.3, #3665)
# ===========================================================================


def test_create_endpoint_plaintext_http_remote_422():
    """Plaintext http to a non-loopback host is rejected at the API boundary."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "X", "endpoint_url": "http://mcp.acme.example/sse"},
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_non_http_scheme_for_http_transport_422():
    """An HTTP-family transport requires an http(s) URL — ftp:// is rejected."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "X", "endpoint_url": "ftp://mcp.acme.example", "transport": "sse"},
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_localhost_http_allowed_in_dev():
    """http is tolerated for loopback hosts when not in production (the default test env)."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.insert_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={"name": "Local", "endpoint_url": "http://localhost:8080/mcp"},
        )
    assert r.status_code == 201
    assert mdb.insert_mcp_endpoint.call_args.kwargs["endpoint_url"] == "http://localhost:8080/mcp"


def test_create_endpoint_stdio_command_target_allowed():
    """``stdio`` endpoints carry a command target, not a URL, so scheme rules don't apply."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.insert_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={
                "name": "Local stdio",
                "endpoint_url": "npx -y @modelcontextprotocol/server-everything",
                "transport": "stdio",
            },
        )
    assert r.status_code == 201


def test_create_endpoint_cadence_below_min_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={
                "name": "X",
                "endpoint_url": "https://x",
                "discoveryCadenceSeconds": MCP_DISCOVERY_CADENCE_MIN_SECONDS - 1,
            },
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_create_endpoint_cadence_above_max_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints",
            json={
                "name": "X",
                "endpoint_url": "https://x",
                "discoveryCadenceSeconds": MCP_DISCOVERY_CADENCE_MAX_SECONDS + 1,
            },
        )
    assert r.status_code == 422
    mdb.insert_mcp_endpoint.assert_not_called()


def test_patch_endpoint_plaintext_http_remote_422():
    """A URL-only PATCH cannot smuggle in plaintext http to a remote host."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.patch(
            "/v1/mcp/acme/endpoints/11111111-1111-1111-1111-111111111111",
            json={"endpoint_url": "http://evil.example/mcp"},
        )
    assert r.status_code == 422
    mdb.update_mcp_endpoint.assert_not_called()


def test_validate_mcp_endpoint_url_production_rejects_localhost_http():
    """In production even loopback http is rejected — only https is acceptable."""
    fake_settings = type("S", (), {"is_production": True})()
    with patch("app.models.settings", fake_settings):
        with pytest.raises(ValueError):
            validate_mcp_endpoint_url("http://localhost:8080/mcp", "streamable_http")
        # https stays valid in production
        validate_mcp_endpoint_url("https://mcp.acme.example/sse", "streamable_http")


def test_validate_mcp_endpoint_url_blank_rejected():
    with pytest.raises(ValueError):
        validate_mcp_endpoint_url("   ", "streamable_http")


def test_redact_url_credentials_masks_userinfo():
    assert (
        redact_url_credentials("https://user:secret@mcp.acme.example/sse")
        == "https://***@mcp.acme.example/sse"
    )
    # token-as-username (no password) is masked too
    assert (
        redact_url_credentials("https://tok123@mcp.acme.example/sse")
        == "https://***@mcp.acme.example/sse"
    )


def test_redact_url_credentials_preserves_port_and_query():
    assert (
        redact_url_credentials("https://u:p@host.example:8443/mcp?x=1")
        == "https://***@host.example:8443/mcp?x=1"
    )


def test_redact_url_credentials_passes_through_clean_urls():
    assert (
        redact_url_credentials("https://mcp.acme.example/sse")
        == "https://mcp.acme.example/sse"
    )
    # stdio command target (no authority) is untouched, even with an @ in the path
    assert (
        redact_url_credentials("npx -y @modelcontextprotocol/server-everything")
        == "npx -y @modelcontextprotocol/server-everything"
    )
    assert redact_url_credentials(None) is None


def test_out_from_row_redacts_endpoint_url_credentials():
    row = {**_ENDPOINT_ROW, "endpoint_url": "https://user:secret@mcp.acme.example/sse"}
    out = mcp_endpoint_out_from_row(row)
    assert out.endpoint_url == "https://***@mcp.acme.example/sse"
    assert "secret" not in out.endpoint_url


# ===========================================================================
# DB layer: slug uniqueness + partial update
# ===========================================================================


class _FakeCursor:
    """Minimal cursor double: records statements and serves canned fetch results."""

    def __init__(self, fetchall_rows=None, fetchone_row=None):
        self._fetchall_rows = fetchall_rows or []
        self._fetchone_row = fetchone_row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._fetchall_rows

    def fetchone(self):
        return self._fetchone_row


def test_next_available_slug_free():
    db = Database()
    cur = _FakeCursor(fetchall_rows=[])
    assert db._next_available_mcp_slug(cur, "t1", "acme") == "acme"


def test_next_available_slug_increments_past_collisions():
    db = Database()
    cur = _FakeCursor(fetchall_rows=[{"slug": "acme"}, {"slug": "acme-2"}])
    assert db._next_available_mcp_slug(cur, "t1", "acme") == "acme-3"


def test_next_available_slug_queries_all_rows_including_deleted():
    """Collision detection must not filter deleted_at (unique constraint counts them)."""
    db = Database()
    cur = _FakeCursor(fetchall_rows=[])
    db._next_available_mcp_slug(cur, "t1", "acme")
    sql, params = cur.executed[0]
    assert "deleted_at" not in sql
    assert params == ("t1", "acme", "acme-%")


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_update_mcp_endpoint_filters_unknown_fields(monkeypatch):
    cur = _FakeCursor(fetchone_row=dict(_ENDPOINT_ROW))
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)
    db.update_mcp_endpoint("t1", "ep-1", {"enabled": False, "bogus": "x"})
    sql, params = cur.executed[0]
    assert "enabled = %s" in sql
    assert "bogus" not in sql
    # params: [enabled, endpoint_id, tenant_id]
    assert params == (False, "ep-1", "t1")
    assert conn.committed is True


def test_update_mcp_endpoint_empty_fields_returns_current(monkeypatch):
    db = Database()
    monkeypatch.setattr(db, "get_mcp_endpoint", lambda t, e: {"sentinel": True})
    assert db.update_mcp_endpoint("t1", "ep-1", {}) == {"sentinel": True}


def test_update_mcp_endpoint_missing_row_returns_none(monkeypatch):
    cur = _FakeCursor(fetchone_row=None)
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)
    assert db.update_mcp_endpoint("t1", "ep-1", {"enabled": True}) is None


# ---------------------------------------------------------------------------
# DB layer: soft delete + child purge (V2-MCP-17.5 / MCAT-3.5)
# ---------------------------------------------------------------------------


class _FakeSeqCursor:
    """Cursor double for the soft-delete transaction.

    Serves the ``RETURNING id`` row via :meth:`fetchone` and advances ``rowcount``
    from a per-DELETE sequence so the teardown summary can be asserted.
    """

    def __init__(self, retire_row, delete_rowcounts=None):
        self._retire_row = retire_row
        self._rowcounts = list(delete_rowcounts or [])
        self.executed = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.strip().upper().startswith("DELETE") and self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)

    def fetchone(self):
        return self._retire_row


def test_soft_delete_mcp_endpoint_retires_row_and_purges_children(monkeypatch):
    # rowcounts: credentials, jobs, versions (in deletion order).
    cur = _FakeSeqCursor(retire_row={"id": "ep-1"}, delete_rowcounts=[1, 3, 2])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    summary = db.soft_delete_mcp_endpoint("t1", "ep-1")
    assert summary == {
        "endpoint_id": "ep-1",
        "credentials_purged": True,
        "versions_deleted": 2,
        "jobs_deleted": 3,
    }
    assert conn.committed is True

    # The retire UPDATE runs first, soft-deleting only a live, tenant-owned row.
    retire_sql, retire_params = cur.executed[0]
    assert "deleted_at = CURRENT_TIMESTAMP" in retire_sql
    assert "deleted_at IS NULL" in retire_sql
    assert retire_params == ("ep-1", "t1")

    # All three child tables are purged.
    joined = " ".join(sql for sql, _ in cur.executed)
    assert "mcp_endpoint_credentials" in joined
    assert "mcp_discovery_jobs" in joined
    assert "mcp_endpoint_versions" in joined


def test_soft_delete_mcp_endpoint_reports_no_credentials_when_none(monkeypatch):
    cur = _FakeSeqCursor(retire_row={"id": "ep-1"}, delete_rowcounts=[0, 0, 0])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)
    summary = db.soft_delete_mcp_endpoint("t1", "ep-1")
    assert summary["credentials_purged"] is False
    assert summary["versions_deleted"] == 0
    assert summary["jobs_deleted"] == 0


def test_soft_delete_mcp_endpoint_missing_row_returns_none_without_purge(monkeypatch):
    cur = _FakeSeqCursor(retire_row=None)
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)
    assert db.soft_delete_mcp_endpoint("t1", "missing") is None
    assert conn.rolled_back is True
    # Only the guarded retire UPDATE ran — no child DELETE statements fired.
    assert len(cur.executed) == 1
    assert cur.executed[0][0].strip().upper().startswith("UPDATE")
