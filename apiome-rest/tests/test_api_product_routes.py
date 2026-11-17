"""HTTP contract tests for API products — APX-1.1 (#6098).

``/v1/tenants/{tenant_slug}/products`` and its members sub-resource. The store is replaced by a
small stand-in (its rules are covered by ``test_api_product_store``), so what is asserted here is
the endpoint's own contract:

* each route is gated on the ``projects`` RBAC resource with the right action — the guard is the
  *real* ``enforce_permission``, so a Viewer can read products but not change them;
* a refusal becomes the status that matches its kind (404 unknown, 409 slug taken or duplicate
  member, 422 unknown team or ref or a portal refusal with ``blockers``, 400 otherwise);
* the routes are part of the published OpenAPI document.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

import pytest
from fastapi.testclient import TestClient

from app import api_product_routes
from app.api_products import (
    CODE_INVALID,
    CODE_MEMBER_DUPLICATE,
    CODE_MEMBER_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_PORTAL_UNPUBLISHED,
    CODE_SLUG_TAKEN,
    CODE_TEAM_NOT_FOUND,
    ApiProductMember,
    ApiProductRecord,
    ApiProductValidationError,
)
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_BASE = "/v1/tenants/acme/products"

#: The built-in grids for the ``projects`` resource.
_GRIDS: Dict[str, Set[str]] = {
    "owner": {"view", "create", "edit", "delete", "publish"},
    "editor": {"view", "create", "edit", "delete", "publish"},
    "viewer": {"view"},
}


def _record(slug: str = "payments", members: List[ApiProductMember] | None = None) -> ApiProductRecord:
    return ApiProductRecord(id="p-1", slug=slug, name="Payments", visibility="private", state="draft",
                            member_count=len(members or []), members=members,
                            portal_ready=None if members is None else True)


_MEMBER = ApiProductMember(id="m-1", kind="project_latest", ref="r-1", name="Payments API", published=True)


@pytest.fixture
def calls(monkeypatch) -> List[tuple]:
    """Replace the store with recorders; ``raise_for`` makes one function refuse."""
    seen: List[tuple] = []
    monkeypatch.setattr(api_product_routes, "list_products", lambda t: seen.append(("list", t)) or [_record()])
    monkeypatch.setattr(api_product_routes, "get_product",
                        lambda t, s: seen.append(("get", s)) or _record(s, [_MEMBER]))
    monkeypatch.setattr(api_product_routes, "create_product",
                        lambda t, body, actor: seen.append(("create", body.name, actor.user_id)) or _record(members=[]))
    monkeypatch.setattr(api_product_routes, "update_product",
                        lambda t, s, patch, actor: seen.append(("update", s, patch.model_dump(exclude_unset=True)))
                        or _record(s, []))
    monkeypatch.setattr(api_product_routes, "delete_product", lambda t, s, actor: seen.append(("delete", s)) or s)
    monkeypatch.setattr(api_product_routes, "list_members", lambda t, s: seen.append(("members", s)) or [_MEMBER])
    monkeypatch.setattr(api_product_routes, "add_member",
                        lambda t, s, body, actor: seen.append(("add", s, body.kind, body.ref)) or _record(s, [_MEMBER]))
    monkeypatch.setattr(api_product_routes, "remove_member",
                        lambda t, s, m, actor: seen.append(("remove", s, m)) or _record(s, []))
    return seen


@pytest.fixture
def role(monkeypatch):
    """Authenticate as a user holding one built-in role."""
    state: Dict[str, Any] = {"role": "owner", "checked": []}

    def _has(tenant_id: str, user_id: str, resource: str, action: str) -> bool:
        state["checked"].append((resource, action))
        return action in _GRIDS[state["role"]]

    monkeypatch.setattr(api_product_routes.db, "user_has_permission", _has)
    monkeypatch.setattr(api_product_routes.db, "write_access_audit", lambda **kw: None)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield state
    app.dependency_overrides.clear()


def test_crud_and_members_round_trip(calls: List[tuple], role: Dict[str, Any]) -> None:
    created = client.post(_BASE, json={"name": "Payments", "members": [{"kind": "project_latest", "ref": "payments"}]})
    assert created.status_code == 201 and created.json()["slug"] == "payments"

    listed = client.get(_BASE).json()
    assert listed["count"] == 1 and listed["products"][0]["members"] is None

    read = client.get(f"{_BASE}/payments").json()
    assert read["members"][0]["name"] == "Payments API" and read["portal_ready"] is True

    assert client.patch(f"{_BASE}/payments", json={"visibility": "workspace", "summary": None}).status_code == 200
    assert client.get(f"{_BASE}/payments/members").json()["count"] == 1
    added = client.post(f"{_BASE}/payments/members", json={"kind": "mcp_server", "ref": "payments-mcp"})
    assert added.status_code == 201
    assert client.delete(f"{_BASE}/payments/members/m-1").status_code == 200
    assert client.delete(f"{_BASE}/payments").json() == {"slug": "payments"}

    assert [c[0] for c in calls] == ["create", "list", "get", "update", "members", "add", "remove", "delete"]
    assert calls[0][2] == _USER
    assert calls[3][2] == {"visibility": "workspace", "summary": None}
    assert role["checked"] == [
        ("projects", "create"), ("projects", "view"), ("projects", "view"), ("projects", "edit"),
        ("projects", "view"), ("projects", "edit"), ("projects", "edit"), ("projects", "delete"),
    ]


def test_a_viewer_can_read_but_not_change_products(calls: List[tuple], role: Dict[str, Any]) -> None:
    role["role"] = "viewer"
    assert client.get(_BASE).status_code == 200
    assert client.get(f"{_BASE}/payments").status_code == 200
    assert client.post(_BASE, json={"name": "Payments"}).status_code == 403
    assert client.patch(f"{_BASE}/payments", json={"name": "X"}).status_code == 403
    assert client.post(f"{_BASE}/payments/members", json={"kind": "project_latest", "ref": "x"}).status_code == 403
    assert client.delete(f"{_BASE}/payments").status_code == 403
    assert [c[0] for c in calls] == ["list", "get"]


def test_malformed_bodies_are_rejected_before_the_store(calls: List[tuple], role: Dict[str, Any]) -> None:
    assert client.post(_BASE, json={"name": "Payments", "visibility": "public"}).status_code == 422
    assert client.post(f"{_BASE}/payments/members", json={"kind": "project", "ref": "x"}).status_code == 422
    assert client.patch(f"{_BASE}/payments", json={"slug": "renamed"}).status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (CODE_NOT_FOUND, 404),
        (CODE_MEMBER_NOT_FOUND, 404),
        (CODE_SLUG_TAKEN, 409),
        (CODE_MEMBER_DUPLICATE, 409),
        (CODE_TEAM_NOT_FOUND, 422),
        (CODE_PORTAL_UNPUBLISHED, 422),
        (CODE_INVALID, 400),
    ],
)
def test_a_refusal_maps_to_its_status_with_its_code(
    monkeypatch, role: Dict[str, Any], code: str, status: int
) -> None:
    blockers = [{"kind": "mcp_server", "ref": "r", "name": "Payments MCP"}] if code == CODE_PORTAL_UNPUBLISHED else None

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ApiProductValidationError(code, "refused", blockers=blockers)

    monkeypatch.setattr(api_product_routes, "add_member", refuse)
    response = client.post(f"{_BASE}/payments/members", json={"kind": "project_latest", "ref": "payments"})
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail.get("blockers") == blockers


def test_the_routes_are_in_the_openapi_document() -> None:
    paths = app.openapi()["paths"]
    assert set(paths["/v1/tenants/{tenant_slug}/products"]) == {"get", "post"}
    assert set(paths["/v1/tenants/{tenant_slug}/products/{product_slug}"]) == {"get", "patch", "delete"}
    assert set(paths["/v1/tenants/{tenant_slug}/products/{product_slug}/members"]) == {"get", "post"}
    assert set(paths["/v1/tenants/{tenant_slug}/products/{product_slug}/members/{member_id}"]) == {"delete"}
