"""HTTP contract tests for API plans — APX-1.2 (#6099).

``/v1/tenants/{tenant_slug}/products/{product_slug}/plans``. The store is replaced by a small
stand-in (its SQL is covered by ``test_api_plan_store_db``), so what is asserted here is the
endpoint's own contract:

* each route is gated on the ``projects`` RBAC resource — ``view`` to read, ``edit`` to write — by
  the *real* ``enforce_permission``, so a Viewer can read plans but not change them;
* limits validate before the store: a non-positive count or an unknown window is a 422;
* a declared-only plan is saved (201), not refused, and carries its notice;
* a refusal becomes the status that matches its kind (404 unknown product or plan, 409 slug taken,
  422 unknown environment, 400 otherwise);
* the routes are part of the published OpenAPI document.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

import pytest
from fastapi.testclient import TestClient

from app import api_plan_routes
from app.api_plans import (
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_INVALID,
    CODE_NOT_FOUND,
    CODE_SLUG_TAKEN,
    NOTICE_DECLARED_ONLY,
    ApiPlanRecord,
    ApiPlanValidationError,
    PlanAuthConfig,
    PlanEnvironment,
    PlanNotice,
)
from app.api_products import CODE_NOT_FOUND as PRODUCT_NOT_FOUND
from app.api_products import ApiProductValidationError
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_BASE = "/v1/tenants/acme/products/payments/plans"

#: The built-in grids for the ``projects`` resource.
_GRIDS: Dict[str, Set[str]] = {
    "owner": {"view", "create", "edit", "delete", "publish"},
    "viewer": {"view"},
}


def _record(slug: str = "standard") -> ApiPlanRecord:
    env = PlanEnvironment(id="g-1", slug="kong-prod-cp", connector_kind="kong-admin", can_provision=False)
    return ApiPlanRecord(
        id="pl-1", product="payments", slug=slug, name="Standard", auth_strategy="key_auth",
        auth_config=PlanAuthConfig(), approval="manual", environments=[env], declared_only=True,
        state="draft", notices=[PlanNotice(code=NOTICE_DECLARED_ONLY, message="Declared only: kong-prod-cp …")],
    )


@pytest.fixture
def calls(monkeypatch) -> List[tuple]:
    """Replace the store with recorders."""
    seen: List[tuple] = []
    monkeypatch.setattr(api_plan_routes, "list_plans", lambda t, p: seen.append(("list", p)) or [_record()])
    monkeypatch.setattr(api_plan_routes, "get_plan", lambda t, p, s: seen.append(("get", p, s)) or _record(s))
    monkeypatch.setattr(api_plan_routes, "create_plan",
                        lambda t, p, body, actor: seen.append(("create", p, body.model_dump(exclude_unset=True),
                                                               actor.user_id)) or _record())
    monkeypatch.setattr(api_plan_routes, "update_plan",
                        lambda t, p, s, patch, actor: seen.append(("update", s, patch.model_dump(exclude_unset=True)))
                        or _record(s))
    monkeypatch.setattr(api_plan_routes, "delete_plan", lambda t, p, s, actor: seen.append(("delete", s)) or s)
    return seen


@pytest.fixture
def role(monkeypatch):
    """Authenticate as a user holding one built-in role."""
    state: Dict[str, Any] = {"role": "owner", "checked": []}

    def _has(tenant_id: str, user_id: str, resource: str, action: str) -> bool:
        state["checked"].append((resource, action))
        return action in _GRIDS[state["role"]]

    monkeypatch.setattr(api_plan_routes.db, "user_has_permission", _has)
    monkeypatch.setattr(api_plan_routes.db, "write_access_audit", lambda **kw: None)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield state
    app.dependency_overrides.clear()


def test_crud_round_trip(calls: List[tuple], role: Dict[str, Any]) -> None:
    body = {
        "name": "Standard",
        "auth_strategy": "key_auth",
        "auth_config": {"header_name": "X-API-Key"},
        "limits": [{"window": "minute", "requests": 100}, {"window": "day", "requests": 50000}],
        "approval": "manual",
        "environments": ["kong-prod-cp"],
    }
    created = client.post(_BASE, json=body)
    assert created.status_code == 201
    assert created.json()["declared_only"] is True
    assert created.json()["notices"][0]["code"] == NOTICE_DECLARED_ONLY

    listed = client.get(_BASE).json()
    assert listed["count"] == 1 and listed["plans"][0]["environments"][0]["slug"] == "kong-prod-cp"
    assert client.get(f"{_BASE}/standard").json()["slug"] == "standard"
    assert client.patch(f"{_BASE}/standard", json={"approval": "auto", "terms_url": None}).status_code == 200
    assert client.delete(f"{_BASE}/standard").json() == {"slug": "standard"}

    assert [c[0] for c in calls] == ["create", "list", "get", "update", "delete"]
    assert calls[0][1] == "payments" and calls[0][3] == _USER
    assert calls[0][2]["limits"] == body["limits"]
    assert calls[3][2] == {"approval": "auto", "terms_url": None}
    assert role["checked"] == [
        ("projects", "edit"), ("projects", "view"), ("projects", "view"), ("projects", "edit"), ("projects", "edit"),
    ]


def test_a_viewer_can_read_but_not_change_plans(calls: List[tuple], role: Dict[str, Any]) -> None:
    role["role"] = "viewer"
    assert client.get(_BASE).status_code == 200
    assert client.get(f"{_BASE}/standard").status_code == 200
    assert client.post(_BASE, json={"name": "Standard"}).status_code == 403
    assert client.patch(f"{_BASE}/standard", json={"name": "X"}).status_code == 403
    assert client.delete(f"{_BASE}/standard").status_code == 403
    assert [c[0] for c in calls] == ["list", "get"]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Standard", "limits": [{"window": "minute", "requests": 0}]},
        {"name": "Standard", "limits": [{"window": "minute", "requests": -1}]},
        {"name": "Standard", "limits": [{"window": "week", "requests": 10}]},
        {"name": "Standard", "auth_strategy": "basic"},
        {"name": "Standard", "approval": "sometimes"},
        {"name": "Standard", "concurrency": 0},
        {"name": "Standard", "auth_config": {"password": "hunter2"}},
    ],
)
def test_malformed_bodies_are_rejected_before_the_store(
    calls: List[tuple], role: Dict[str, Any], body: Dict[str, Any]
) -> None:
    assert client.post(_BASE, json=body).status_code == 422
    assert calls == []


def test_the_slug_cannot_be_patched(calls: List[tuple], role: Dict[str, Any]) -> None:
    assert client.patch(f"{_BASE}/standard", json={"slug": "renamed"}).status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ApiPlanValidationError(CODE_NOT_FOUND, "refused"), 404),
        (ApiProductValidationError(PRODUCT_NOT_FOUND, "refused"), 404),
        (ApiPlanValidationError(CODE_SLUG_TAKEN, "refused"), 409),
        (ApiPlanValidationError(CODE_ENVIRONMENT_NOT_FOUND, "refused"), 422),
        (ApiPlanValidationError(CODE_INVALID, "the minute window is limited twice"), 400),
    ],
)
def test_a_refusal_maps_to_its_status_with_its_code(
    monkeypatch, role: Dict[str, Any], error: ValueError, status: int
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(api_plan_routes, "create_plan", refuse)
    response = client.post(_BASE, json={"name": "Standard"})
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == error.code and detail["message"] == str(error)


def test_the_routes_are_in_the_openapi_document() -> None:
    paths = app.openapi()["paths"]
    assert set(paths["/v1/tenants/{tenant_slug}/products/{product_slug}/plans"]) == {"get", "post"}
    assert set(paths["/v1/tenants/{tenant_slug}/products/{product_slug}/plans/{plan_slug}"]) == {
        "get", "patch", "delete",
    }
