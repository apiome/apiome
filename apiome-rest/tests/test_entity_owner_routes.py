"""HTTP contract tests for entity owners — CDG-2.2 (#5961).

``/v1/tenants/{tenant_slug}/owners/{kind}/{entity_id}`` (+ ``/confirm``) and ``…/owners:assign``.
The store is faked (its rules are ``test_entity_owner_store``); asserted here:

* each kind is gated by the permission that edits it, through the *real* ``enforce_permission`` —
  ``projects`` for projects, catalog items and MCP endpoints, ``consumer_contracts`` for consumers,
  ``imports`` for connectors — ``view`` to read, ``edit`` to change;
* a bulk assignment needs ``edit`` on every kind it lists;
* refusals map to 400 / 404 with their code.
"""

from __future__ import annotations

from typing import Any, List, Set, Tuple

import pytest
from fastapi.testclient import TestClient

from app import entity_owner_routes as routes
from app.auth import validate_authentication
from app.entity_owners import (
    CODE_ENTITY_NOT_FOUND,
    CODE_NO_SUGGESTION,
    CODE_TEAM_NOT_FOUND,
    OwnerRecord,
    OwnersResponse,
    OwnerTeamRef,
    OwnerValidationError,
)
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_ID = "22222222-2222-4222-8222-222222222222"
_BASE = "/v1/tenants/acme/owners"


def _owned(kind: str, entity_id: str, slug: str = "payments", status: str = "confirmed") -> OwnersResponse:
    record = OwnerRecord(
        team=OwnerTeamRef(id="t-1", slug=slug, name=slug.title()),
        status=status,
        source="manual" if status == "confirmed" else "gateway_tag",
    )
    if status == "confirmed":
        return OwnersResponse(kind=kind, entity_id=entity_id, owner=record)
    return OwnersResponse(kind=kind, entity_id=entity_id, suggestions=[record])


class _FakeStore:
    """Records calls; ``refuse`` makes the next call raise."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Any]] = []
        self.refuse: OwnerValidationError | None = None

    def _maybe_refuse(self) -> None:
        if self.refuse is not None:
            raise self.refuse

    def read_owners(self, tenant_id, kind, entity_id):
        self._maybe_refuse()
        self.calls.append(("read", kind))
        return _owned(kind, entity_id, status="suggested")

    def assign_owner(self, tenant_id, kind, entity_id, team, *, actor):
        self._maybe_refuse()
        self.calls.append(("assign", (kind, team, actor.user_id)))
        return _owned(kind, entity_id, team)

    def remove_owner(self, tenant_id, kind, entity_id, *, actor):
        self._maybe_refuse()
        self.calls.append(("remove", kind))
        return OwnersResponse(kind=kind, entity_id=entity_id)

    def confirm_owner(self, tenant_id, kind, entity_id, team, *, actor):
        self._maybe_refuse()
        self.calls.append(("confirm", (kind, team)))
        return _owned(kind, entity_id, team or "payments")

    def bulk_assign_owner(self, tenant_id, team, entities, *, actor):
        self._maybe_refuse()
        self.calls.append(("bulk", [(e.kind, e.id) for e in entities]))
        return [_owned(e.kind, e.id, team) for e in entities]


@pytest.fixture
def store(monkeypatch) -> _FakeStore:
    fake = _FakeStore()
    for name in ("read_owners", "assign_owner", "remove_owner", "confirm_owner", "bulk_assign_owner"):
        monkeypatch.setattr(routes, name, getattr(fake, name))
    return fake


@pytest.fixture
def grants(monkeypatch):
    """Authenticate, and grant exactly the ``resource:action`` keys in the returned set."""
    granted: Set[str] = set()
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return f"{resource}:{action}" in granted

    monkeypatch.setattr(routes.db, "user_has_permission", _has)
    monkeypatch.setattr(routes.db, "write_access_audit", lambda **kw: None)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield granted, asked
    app.dependency_overrides.clear()


_KIND_RESOURCE = {
    "project": "projects",
    "catalog_item": "projects",
    "mcp_endpoint": "projects",
    "consumer": "consumer_contracts",
    "connector": "imports",
}


@pytest.mark.parametrize("kind,resource", sorted(_KIND_RESOURCE.items()))
def test_each_kind_reads_with_view_and_changes_with_edit(store, grants, kind, resource) -> None:
    granted, asked = grants
    url = f"{_BASE}/{kind}/{_ID}"

    assert client.get(url).status_code == 403
    assert asked[-1] == f"{resource}:view"
    granted.add(f"{resource}:view")
    assert client.get(url).status_code == 200

    for call in (
        lambda: client.put(url, json={"team": "payments"}),
        lambda: client.post(f"{url}/confirm", json={}),
        lambda: client.delete(url),
    ):
        response = call()
        assert response.status_code == 403
        assert f"{resource}:edit" in response.text

    granted.add(f"{resource}:edit")
    assert client.put(url, json={"team": "payments"}).status_code == 200
    assert client.post(f"{url}/confirm", json={"team": "payments"}).status_code == 200
    assert client.delete(url).status_code == 200
    assert [c[0] for c in store.calls] == ["read", "assign", "confirm", "remove"]


def test_confirm_returns_the_confirmed_owner(store, grants) -> None:
    grants[0].update({"projects:edit"})
    body = client.post(f"{_BASE}/catalog_item/{_ID}/confirm", json={}).json()
    assert body["owner"]["team"]["slug"] == "payments" and body["owner"]["status"] == "confirmed"
    assert store.calls == [("confirm", ("catalog_item", None))]


def test_an_unknown_kind_is_400(store, grants) -> None:
    response = client.get(f"{_BASE}/widget/{_ID}")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "owner-invalid"


@pytest.mark.parametrize("code", [CODE_ENTITY_NOT_FOUND, CODE_TEAM_NOT_FOUND, CODE_NO_SUGGESTION])
def test_unknown_things_are_404(store, grants, code) -> None:
    grants[0].update({"projects:edit"})
    store.refuse = OwnerValidationError(code, "nope")
    response = client.put(f"{_BASE}/project/{_ID}", json={"team": "payments"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == code


def test_bulk_assign_needs_edit_on_every_kind_listed(store, grants) -> None:
    granted, asked = grants
    body = {
        "team": "platform",
        "entities": [
            {"kind": "catalog_item", "id": _ID},
            {"kind": "consumer", "id": _ID},
        ],
    }
    granted.add("projects:edit")
    response = client.post(f"{_BASE}:assign", json=body)
    assert response.status_code == 403
    assert "consumer_contracts:edit" in response.text
    assert store.calls == []

    granted.add("consumer_contracts:edit")
    response = client.post(f"{_BASE}:assign", json=body)
    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert store.calls == [("bulk", [("catalog_item", _ID), ("consumer", _ID)])]


def test_bulk_assign_rejects_an_unknown_kind_and_an_empty_list(store, grants) -> None:
    grants[0].add("projects:edit")
    assert client.post(f"{_BASE}:assign", json={"team": "x", "entities": []}).status_code == 422
    response = client.post(
        f"{_BASE}:assign", json={"team": "x", "entities": [{"kind": "widget", "id": _ID}]}
    )
    assert response.status_code == 422


def test_assign_needs_a_team(store, grants) -> None:
    grants[0].add("projects:edit")
    assert client.put(f"{_BASE}/project/{_ID}", json={}).status_code == 422

