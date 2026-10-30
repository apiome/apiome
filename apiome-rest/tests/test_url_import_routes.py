"""URL import refresh API (RAR-6.1, #3538).

The store and the capture service are replaced with fakes; the tests pin each route's permission,
the camelCase shape (with the effective cadence and ``refreshable``), capture's project / version /
URL checks, and the settings patch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import url_import_routes, url_import_store
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.permissions import Action, Resource
from app.url_import_refresh import UrlImportError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_OTHER_PROJECT = "88888888-8888-4888-8888-888888888888"
_VERSION = "55555555-5555-4555-8555-555555555555"
_SPEC = "66666666-6666-4666-8666-666666666666"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_URL = "/v1/tenants/acme/url-imports"
_WHEN = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)


def _row(**overrides: Any) -> Dict[str, Any]:
    return {
        "id": _SPEC,
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        "project_name": "Orders",
        "project_slug": "orders",
        "url": "https://specs.example.com/orders.json",
        "source_kind": "openapi",
        "authenticated": False,
        "auto_refresh_enabled": True,
        "refresh_interval_seconds": None,
        "etag": '"v1"',
        "last_modified": "Wed, 21 Oct 2026 07:28:00 GMT",
        "last_version_id": _VERSION,
        "last_checked_at": _WHEN,
        "last_refreshed_at": None,
        "last_status": "up-to-date",
        "last_reason": "not-modified",
        "last_error": None,
        "consecutive_failures": 0,
        "backoff_until": None,
        "created_at": _WHEN,
        "updated_at": _WHEN,
        **overrides,
    }


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(
        db,
        "get_project_by_id",
        lambda project_id, tenant_id, **kw: (
            {"id": project_id} if tenant_id == _TENANT and project_id in (_PROJECT, _OTHER_PROJECT) else None
        ),
    )
    monkeypatch.setattr(
        db,
        "get_version_by_id",
        lambda version_id, tenant_id: {"id": version_id, "project_id": _PROJECT} if version_id == _VERSION else None,
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def stored(monkeypatch) -> Dict[str, Any]:
    """The fake store: one row; records captures and patches."""
    state: Dict[str, Any] = {"row": _row(), "captured": [], "patched": []}

    def capture(db_, **kw):
        state["captured"].append(kw)
        return {"id": _SPEC}

    def update(db_, tenant_id, spec_id, **kw):
        state["patched"].append(kw)
        if tenant_id != _TENANT or spec_id != _SPEC:
            return None
        if kw["auto_refresh_enabled"] is not None:
            state["row"]["auto_refresh_enabled"] = kw["auto_refresh_enabled"]
        if kw["clear_interval"]:
            state["row"]["refresh_interval_seconds"] = None
        elif kw["refresh_interval_seconds"] is not None:
            state["row"]["refresh_interval_seconds"] = kw["refresh_interval_seconds"]
        return state["row"]

    monkeypatch.setattr(url_import_routes, "record_url_import", capture)
    monkeypatch.setattr(url_import_store, "update_settings", update)
    monkeypatch.setattr(
        url_import_store, "get_spec", lambda db_, tenant_id, spec_id: state["row"] if spec_id == _SPEC else None
    )
    monkeypatch.setattr(
        url_import_store,
        "list_specs",
        lambda db_, tenant_id, project_id=None: [state["row"]] if project_id in (None, _PROJECT) else [],
    )
    return state


_RECORD = {"projectId": _PROJECT, "url": "https://specs.example.com/orders.json", "versionId": _VERSION}


@pytest.mark.parametrize(
    ("method", "url", "body", "action"),
    [
        ("POST", _URL, _RECORD, Action.CREATE),
        ("GET", _URL, None, Action.VIEW),
        ("PATCH", f"{_URL}/{_SPEC}", {"autoRefreshEnabled": False}, Action.EDIT),
    ],
)
def test_each_route_enforces_its_permission(stored, method, url, body, action):
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method, url, json=body)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:4] == (Resource.IMPORTS, action)


def test_record_captures_the_import_and_returns_the_lineage(stored):
    body = {
        **_RECORD,
        "sourceKind": "openapi",
        "contentType": "application/json",
        "options": {"classPrefix": "Ord"},
        "authenticated": False,
    }
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_URL, json=body)
    assert response.status_code == 201, response.text
    [captured] = stored["captured"]
    assert captured["tenant_id"] == _TENANT and captured["user_id"] == _ACTOR
    target = (captured["project_id"], captured["version_id"], captured["options"])
    assert target == (_PROJECT, _VERSION, {"classPrefix": "Ord"})
    out = response.json()
    assert out["projectId"] == _PROJECT and out["refreshable"] is True
    assert out["effectiveIntervalSeconds"] == 300 and out["refreshIntervalSeconds"] is None
    assert out["lastStatus"] == "up-to-date" and out["lastCheckedAt"].startswith("2026-10-30T14:00")


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({**_RECORD, "projectId": "77777777-7777-4777-8777-777777777777"}, 404),
        ({**_RECORD, "projectId": "not-a-uuid"}, 404),
        ({**_RECORD, "versionId": "99999999-9999-4999-8999-999999999999"}, 422),
        ({**_RECORD, "projectId": _OTHER_PROJECT}, 422),  # the version is not this project's
        ({**_RECORD, "unknown": 1}, 422),
    ],
)
def test_record_refuses_a_bad_target(stored, body, status):
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_URL, json=body)
    assert response.status_code == status, response.text
    assert stored["captured"] == []


def test_record_refuses_an_unrefreshable_url(stored, monkeypatch):
    def refuse(db_, **kw):
        raise UrlImportError("Only http and https URLs can be refreshed.")

    monkeypatch.setattr(url_import_routes, "record_url_import", refuse)
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_URL, json={**_RECORD, "url": "ftp://example.com/a.json"})
    assert response.status_code == 422 and "http and https" in response.text


def test_list_returns_the_lineages_and_filters_by_project(stored):
    stored["row"].update(authenticated=True)
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR):
        everything = client.get(_URL).json()["urlImports"]
        mine = client.get(_URL, params={"projectId": _PROJECT}).json()["urlImports"]
        other = client.get(_URL, params={"projectId": _OTHER_PROJECT}).json()["urlImports"]
        junk = client.get(_URL, params={"projectId": "x"}).json()["urlImports"]
    assert len(everything) == 1 and everything[0]["authenticated"] is True and everything[0]["refreshable"] is False
    assert len(mine) == 1 and other == [] and junk == []


def test_patch_turns_refresh_off_and_sets_the_cadence(stored):
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR):
        off = client.patch(f"{_URL}/{_SPEC}", json={"autoRefreshEnabled": False, "refreshIntervalSeconds": 3600})
        floor = client.patch(f"{_URL}/{_SPEC}", json={"refreshIntervalSeconds": 5})
        default = client.patch(f"{_URL}/{_SPEC}", json={"useDefaultInterval": True})
    assert off.json()["autoRefreshEnabled"] is False and off.json()["effectiveIntervalSeconds"] == 3600
    assert off.json()["refreshable"] is False
    assert floor.json()["effectiveIntervalSeconds"] == 60  # raised to the floor
    assert default.json()["refreshIntervalSeconds"] is None and default.json()["effectiveIntervalSeconds"] == 300


def test_patch_an_unknown_lineage_is_404(stored):
    with patch("app.url_import_routes.enforce_permission", return_value=_ACTOR):
        assert client.patch(f"{_URL}/77777777-7777-4777-8777-777777777777", json={}).status_code == 404
        assert client.patch(f"{_URL}/nope", json={}).status_code == 404
        assert client.patch(f"{_URL}/{_SPEC}", json={"refreshIntervalSeconds": 0}).status_code == 422
