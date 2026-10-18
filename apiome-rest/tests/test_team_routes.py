"""HTTP contract tests for teams — CDG-2.1 (#5960).

``/v1/tenants/{tenant_slug}/teams`` and its sub-paths. The store is replaced by an in-memory
fake with the same refusal behaviour (its SQL is covered by ``test_team_store``), so what is
asserted here is the endpoint's own contract:

* CRUD and membership round-trip through the HTTP surface;
* every route is gated on the ``teams`` RBAC resource — the guard is the *real*
  ``enforce_permission``, fed the built-in grids V284 seeds, so an Editor can read teams but not
  change them and a denial is a 403;
* a refusal becomes the status that matches its kind (404 unknown, 409 slug taken or team owns
  entities with ``owned_count``, 422 member not in tenant, 400 otherwise), always with its code.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from fastapi.testclient import TestClient

from app import team_routes
from app.auth import validate_authentication
from app.main import app
from app.teams import (
    CODE_MEMBER_NOT_IN_TENANT,
    CODE_NOT_FOUND,
    CODE_OWNS_ENTITIES,
    CODE_REASSIGN_INVALID,
    CODE_SLUG_TAKEN,
    TeamMember,
    TeamRecord,
    TeamValidationError,
    normalize_contact_email,
    normalize_link,
    normalize_name,
    resolve_slug,
    validate_members,
)

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_PEER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_OUTSIDER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_BASE = "/v1/tenants/acme/teams"

#: The built-in grids V284 seeds for the ``teams`` resource.
_GRIDS: Dict[str, Set[str]] = {
    "owner": {"view", "create", "edit", "delete"},
    "admin": {"view", "create", "edit", "delete"},
    "editor": {"view"},
    "viewer": {"view"},
}


class _FakeStore:
    """An in-memory stand-in for :mod:`app.team_store` with the same refusals."""

    def __init__(self) -> None:
        self.teams: Dict[str, Dict[str, Any]] = {}
        self.members: Dict[str, List[Tuple[str, str]]] = {}
        self.owned: Dict[str, int] = {}
        self.tenant_members = {_USER, _PEER}
        self.audit: List[str] = []

    def _record(self, slug: str, with_members: bool = True) -> TeamRecord:
        members = [TeamMember(user_id=u, role=r) for u, r in self.members.get(slug, [])]
        return TeamRecord(
            **self.teams[slug],
            member_count=len(members),
            members=members if with_members else None,
        )

    def _live(self, slug: str) -> str:
        key = (slug or "").strip().lower()
        if key not in self.teams:
            raise TeamValidationError(CODE_NOT_FOUND, f"no team '{slug}' in this tenant")
        return key

    def list_teams(self, tenant_id: str) -> List[TeamRecord]:
        return [self._record(s, with_members=False) for s in sorted(self.teams)]

    def get_team(self, tenant_id: str, slug: str) -> TeamRecord:
        return self._record(self._live(slug))

    def create_team(self, tenant_id: str, body: Any, *, actor: Any) -> TeamRecord:
        name = normalize_name(body.name)
        slug = resolve_slug(body.slug, name)
        if slug in self.teams:
            raise TeamValidationError(CODE_SLUG_TAKEN, "taken")
        self.teams[slug] = {
            "id": f"id-{slug}",
            "slug": slug,
            "name": name,
            "description": body.description,
            "contact_email": normalize_contact_email(body.contact_email),
            "chat_url": normalize_link("chat_url", body.chat_url),
            "oncall_url": normalize_link("oncall_url", body.oncall_url),
            "docs_url": normalize_link("docs_url", body.docs_url),
            "created_by": actor.user_id,
        }
        self.audit.append("team.create")
        return self._record(slug)

    def update_team(self, tenant_id: str, slug: str, patch: Any, *, actor: Any) -> TeamRecord:
        key = self._live(slug)
        for field in patch.model_fields_set:
            value = getattr(patch, field)
            if field.endswith("_url"):
                value = normalize_link(field, value)
            self.teams[key][field] = value
        self.audit.append("team.update")
        return self._record(key)

    def delete_team(
        self, tenant_id: str, slug: str, *, actor: Any, reassign_to: Optional[str] = None
    ) -> Dict[str, Any]:
        key = self._live(slug)
        owned = self.owned.get(key, 0)
        if reassign_to is not None and (reassign_to == key or reassign_to not in self.teams):
            raise TeamValidationError(CODE_REASSIGN_INVALID, "bad target")
        if owned and reassign_to is None:
            raise TeamValidationError(CODE_OWNS_ENTITIES, "owns", owned_count=owned)
        if owned:
            self.owned[reassign_to] = self.owned.get(reassign_to, 0) + owned
        del self.teams[key]
        self.members.pop(key, None)
        self.audit.append("team.delete")
        return {"slug": key, "owned_count": owned, "reassigned_to": reassign_to if owned else None}

    def replace_team_members(
        self, tenant_id: str, slug: str, members: List[Any], *, actor: Any
    ) -> TeamRecord:
        key = self._live(slug)
        wanted = validate_members(members)
        outsiders = [m.user_id for m in wanted if m.user_id not in self.tenant_members]
        if outsiders:
            raise TeamValidationError(CODE_MEMBER_NOT_IN_TENANT, ", ".join(outsiders))
        self.members[key] = [(m.user_id, m.role) for m in wanted]
        self.audit.append("team.members.replace")
        return self._record(key)


@pytest.fixture
def store(monkeypatch) -> _FakeStore:
    """Route every store call to a fresh fake."""
    fake = _FakeStore()
    for name in (
        "list_teams",
        "get_team",
        "create_team",
        "update_team",
        "delete_team",
        "replace_team_members",
    ):
        monkeypatch.setattr(team_routes, name, getattr(fake, name))
    return fake


@pytest.fixture
def role(monkeypatch):
    """Authenticate as a user holding one built-in role; returns a setter and the denials."""
    state: Dict[str, Any] = {"role": "owner", "denied": []}

    def _has(tenant_id: str, user_id: str, resource: str, action: str) -> bool:
        assert resource == "teams"
        return action in _GRIDS[state["role"]]

    monkeypatch.setattr(team_routes.db, "user_has_permission", _has)
    monkeypatch.setattr(
        team_routes.db, "write_access_audit", lambda **kw: state["denied"].append(kw["target"])
    )
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "jwt",
    }
    yield state
    app.dependency_overrides.clear()


# ===========================================================================
# Round trip
# ===========================================================================


def test_crud_and_membership_round_trip(store: _FakeStore, role: Dict[str, Any]) -> None:
    created = client.post(
        _BASE,
        json={
            "name": "Payments",
            "contact_email": "pay@example.com",
            "chat_url": "https://chat.example/c/payments",
            "oncall_url": "https://oncall.example/payments",
            "docs_url": "https://docs.example/payments",
        },
    )
    assert created.status_code == 201
    assert created.json()["slug"] == "payments"
    assert created.json()["chat_url"] == "https://chat.example/c/payments"

    listed = client.get(_BASE).json()
    assert listed["count"] == 1 and listed["teams"][0]["members"] is None

    patched = client.patch(f"{_BASE}/payments", json={"description": "Card rails", "docs_url": None})
    assert patched.status_code == 200
    assert patched.json()["description"] == "Card rails" and patched.json()["docs_url"] is None

    members = client.put(
        f"{_BASE}/payments/members",
        json={"members": [{"user_id": _USER, "role": "lead"}, {"user_id": _PEER}]},
    )
    assert members.status_code == 200
    assert [(m["user_id"], m["role"]) for m in members.json()["members"]] == [
        (_USER, "lead"),
        (_PEER, "member"),
    ]

    read = client.get(f"{_BASE}/payments").json()
    assert read["member_count"] == 2 and read["description"] == "Card rails"

    deleted = client.delete(f"{_BASE}/payments")
    assert deleted.status_code == 200
    assert deleted.json() == {"slug": "payments", "owned_count": 0, "reassigned_to": None}
    assert client.get(f"{_BASE}/payments").status_code == 404
    assert store.audit == [
        "team.create",
        "team.update",
        "team.members.replace",
        "team.delete",
    ]


# ===========================================================================
# RBAC
# ===========================================================================


@pytest.mark.parametrize("grid", ["editor", "viewer"])
def test_editor_and_viewer_can_read_but_not_change_teams(
    store: _FakeStore, role: Dict[str, Any], grid: str
) -> None:
    client.post(_BASE, json={"name": "Payments"})
    role["role"] = grid
    assert client.get(_BASE).status_code == 200
    assert client.get(f"{_BASE}/payments").status_code == 200
    attempts = [
        client.post(_BASE, json={"name": "Platform"}),
        client.patch(f"{_BASE}/payments", json={"name": "Pay"}),
        client.put(f"{_BASE}/payments/members", json={"members": []}),
        client.delete(f"{_BASE}/payments"),
    ]
    assert [a.status_code for a in attempts] == [403, 403, 403, 403]
    assert "teams:create" in attempts[0].text and "teams:delete" in attempts[3].text
    assert store.audit == ["team.create"]
    assert role["denied"] == ["Platform", "payments", "payments", "payments"]


@pytest.mark.parametrize("grid", ["owner", "admin"])
def test_owner_and_admin_manage_teams(store: _FakeStore, role: Dict[str, Any], grid: str) -> None:
    role["role"] = grid
    assert client.post(_BASE, json={"name": "Payments"}).status_code == 201
    assert client.patch(f"{_BASE}/payments", json={"name": "Pay"}).status_code == 200
    assert client.put(f"{_BASE}/payments/members", json={"members": []}).status_code == 200
    assert client.delete(f"{_BASE}/payments").status_code == 200


def test_a_caller_without_a_role_that_grants_view_cannot_list(
    store: _FakeStore, role: Dict[str, Any], monkeypatch
) -> None:
    monkeypatch.setattr(team_routes.db, "user_has_permission", lambda *a, **k: False)
    response = client.get(_BASE)
    assert response.status_code == 403
    assert "teams:view" in response.text


# ===========================================================================
# Refusals
# ===========================================================================


def test_a_taken_slug_is_409(store: _FakeStore, role: Dict[str, Any]) -> None:
    client.post(_BASE, json={"name": "Payments"})
    response = client.post(_BASE, json={"name": "Other", "slug": "payments"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_SLUG_TAKEN


def test_a_malformed_link_is_400(store: _FakeStore, role: Dict[str, Any]) -> None:
    response = client.post(_BASE, json={"name": "Payments", "chat_url": "ftp://x.example"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "team-invalid"


def test_an_unknown_field_is_rejected(store: _FakeStore, role: Dict[str, Any]) -> None:
    client.post(_BASE, json={"name": "Payments"})
    response = client.patch(f"{_BASE}/payments", json={"slug": "renamed"})
    assert response.status_code == 422


def test_an_unknown_team_is_404(store: _FakeStore, role: Dict[str, Any]) -> None:
    for response in (
        client.get(f"{_BASE}/ghost"),
        client.patch(f"{_BASE}/ghost", json={"name": "X"}),
        client.delete(f"{_BASE}/ghost"),
        client.put(f"{_BASE}/ghost/members", json={"members": []}),
    ):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == CODE_NOT_FOUND


def test_a_member_outside_the_tenant_is_422_and_changes_nothing(
    store: _FakeStore, role: Dict[str, Any]
) -> None:
    client.post(_BASE, json={"name": "Payments"})
    response = client.put(
        f"{_BASE}/payments/members",
        json={"members": [{"user_id": _USER}, {"user_id": _OUTSIDER}]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == CODE_MEMBER_NOT_IN_TENANT
    assert _OUTSIDER in response.json()["detail"]["message"]
    assert store.members.get("payments") is None


def test_deleting_an_owning_team_is_409_with_the_count(
    store: _FakeStore, role: Dict[str, Any]
) -> None:
    client.post(_BASE, json={"name": "Payments"})
    store.owned["payments"] = 4
    response = client.delete(f"{_BASE}/payments")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == CODE_OWNS_ENTITIES and detail["owned_count"] == 4
    assert "payments" in store.teams


def test_reassign_to_moves_the_entities_and_deletes(store: _FakeStore, role: Dict[str, Any]) -> None:
    client.post(_BASE, json={"name": "Payments"})
    client.post(_BASE, json={"name": "Platform"})
    store.owned["payments"] = 4
    response = client.delete(f"{_BASE}/payments", params={"reassign_to": "platform"})
    assert response.status_code == 200
    assert response.json() == {"slug": "payments", "owned_count": 4, "reassigned_to": "platform"}
    assert store.owned["platform"] == 4


def test_reassigning_to_an_unknown_team_is_400(store: _FakeStore, role: Dict[str, Any]) -> None:
    client.post(_BASE, json={"name": "Payments"})
    response = client.delete(f"{_BASE}/payments", params={"reassign_to": "ghost"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == CODE_REASSIGN_INVALID
