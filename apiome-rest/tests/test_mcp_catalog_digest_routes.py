"""API tests for the scheduled catalog digest config + preview routes (MCAT-19.5, #4654).

Covers the tenant-scoped ``/v1/mcp/{tenant_slug}/digest/config`` (GET/PUT) and ``/digest/preview``
routes with a mocked DB and an overridden auth dependency (token tenant, not URL slug).
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# --- GET config ------------------------------------------------------------------------------------


def test_get_config_defaults_when_absent():
    with patch("app.mcp_catalog_digest_routes.db") as mdb:
        mdb.get_mcp_catalog_digest_config.return_value = None
        r = client.get("/v1/mcp/acme/digest/config")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["cadenceSeconds"] is None
    assert body["effectiveCadenceSeconds"] == 604800  # global default
    assert body["sendEmpty"] is False
    assert body["lastDigestAt"] is None
    mdb.get_mcp_catalog_digest_config.assert_called_once_with("t1")


def test_get_config_returns_stored_row():
    with patch("app.mcp_catalog_digest_routes.db") as mdb:
        mdb.get_mcp_catalog_digest_config.return_value = {
            "tenant_id": "t1",
            "enabled": True,
            "cadence_seconds": 86400,
            "send_empty": True,
            "last_digest_at": _NOW,
        }
        r = client.get("/v1/mcp/acme/digest/config")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["cadenceSeconds"] == 86400
    assert body["effectiveCadenceSeconds"] == 86400  # override wins
    assert body["sendEmpty"] is True


# --- PUT config ------------------------------------------------------------------------------------


def test_put_config_upserts():
    with patch("app.mcp_catalog_digest_routes.db") as mdb:
        mdb.upsert_mcp_catalog_digest_config.return_value = {
            "tenant_id": "t1",
            "enabled": True,
            "cadence_seconds": 86400,
            "send_empty": False,
            "last_digest_at": None,
        }
        r = client.put(
            "/v1/mcp/acme/digest/config",
            json={"enabled": True, "cadenceSeconds": 86400, "sendEmpty": False},
        )
    assert r.status_code == 200
    kwargs = mdb.upsert_mcp_catalog_digest_config.call_args.kwargs
    assert mdb.upsert_mcp_catalog_digest_config.call_args.args[0] == "t1"
    assert kwargs == {"enabled": True, "cadence_seconds": 86400, "send_empty": False}
    assert r.json()["enabled"] is True


def test_put_config_null_cadence_ok():
    with patch("app.mcp_catalog_digest_routes.db") as mdb:
        mdb.upsert_mcp_catalog_digest_config.return_value = {
            "tenant_id": "t1",
            "enabled": True,
            "cadence_seconds": None,
            "send_empty": False,
            "last_digest_at": None,
        }
        r = client.put("/v1/mcp/acme/digest/config", json={"enabled": True})
    assert r.status_code == 200
    assert mdb.upsert_mcp_catalog_digest_config.call_args.kwargs["cadence_seconds"] is None


def test_put_config_rejects_subfloor_cadence():
    r = client.put(
        "/v1/mcp/acme/digest/config",
        json={"enabled": True, "cadenceSeconds": 60},  # below 300 floor
    )
    assert r.status_code == 422


def test_put_config_rejects_unknown_field():
    r = client.put(
        "/v1/mcp/acme/digest/config",
        json={"enabled": True, "bogus": 1},
    )
    assert r.status_code == 422


def test_put_config_requires_enabled():
    r = client.put("/v1/mcp/acme/digest/config", json={"cadenceSeconds": 86400})
    assert r.status_code == 422


# --- preview ---------------------------------------------------------------------------------------


def test_preview_compiles_from_real_data():
    removed = {
        "endpoint_id": "ep-weather",
        "endpoint_name": "Weather",
        "endpoint_slug": "weather",
        "version_id": "v1",
        "change_type": "removed",
        "item_type": "tool",
        "item_name": "getForecast",
        "detail": {},
        "version_seq": 2,
        "version_tag": "t",
        "discovered_at": _NOW,
    }
    with patch("app.mcp_catalog_digest_routes.db") as mdb:
        mdb.get_mcp_catalog_digest_config.return_value = None
        mdb.list_mcp_new_endpoints_in_window.return_value = [
            {"id": "ep-maps", "name": "Maps", "slug": "maps", "visibility": "public"}
        ]
        mdb.list_mcp_catalog_changes_in_window.return_value = [removed]
        mdb.list_mcp_grade_movements_in_window.return_value = []
        mdb.list_mcp_health_problems_in_window.return_value = []
        r = client.post("/v1/mcp/acme/digest/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["event"] == "mcp.catalog.digest"
    assert body["tenantSlug"] == "acme"
    assert body["totals"]["newEndpoints"] == 1
    assert body["totals"]["breakingChanges"] == 1
    # Every window read is tenant-scoped by the token tenant, not the URL slug.
    assert mdb.list_mcp_catalog_changes_in_window.call_args.args[0] == "t1"
