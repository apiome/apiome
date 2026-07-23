"""Multi-tenant switcher + permission-divergence coverage (OLO-6.4, #4221).

The REST twin of the seeded multi-tenant fixture (``apiome-db/seed/dev/007_multitenant.sql``):
**one user (Grace) in three tenants with diverging roles and license tiers.**

  Aurora Labs        (aurora-labs)        -> Owner  · Free      license
  Borealis Studio    (borealis-studio)    -> Editor · Paid      license
  Cascade Foundation (cascade-foundation) -> Viewer · Sponsor   license

Two contracts are asserted against an in-memory fake ``db`` (no live database, exactly like the
sibling route/guard suites):

  1. **Switcher data contract** (OLO-6.2): ``GET /v1/tenants/me`` lists all three memberships in
     one round-trip, each carrying its distinct role, status, and license tier — the shape the
     header tenant switcher (and its per-tenant license chip) renders from.
  2. **Permission divergence** (RBAC guard, #3611): the *same* user is authorized differently in
     each tenant. ``enforce_permission`` allows everything for the owner, content CRUD but not
     member management for the editor, and only reads for the viewer.

The fake resolves permissions through the canonical built-in role grids (a faithful twin of
``apiome.seed_builtin_roles``, V118), so the guard's real allow/deny control flow is exercised.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.main import app
from app.permissions import Action, Resource, enforce_permission, has_permission

client = TestClient(app)

# ── Fixture shape (mirrors seed/dev/007_multitenant.sql) ───────────────────────

_GRACE_ID = "00000000-0000-4000-8000-000000000010"

# slug -> (tenant_id, name, role, license_name, license_type), in slug order.
_FIXTURE: Dict[str, Tuple[str, str, str, str, str]] = {
    "aurora-labs": ("00000000-0000-4000-8000-000000000011", "Aurora Labs", "owner", "Free", "free"),
    "borealis-studio": (
        "00000000-0000-4000-8000-000000000012",
        "Borealis Studio",
        "editor",
        "Paid",
        "paid",
    ),
    "cascade-foundation": (
        "00000000-0000-4000-8000-000000000013",
        "Cascade Foundation",
        "viewer",
        "Sponsor",
        "sponsor",
    ),
}

_TENANT_BY_ROLE = {row[2]: row[0] for row in _FIXTURE.values()}


# ── Canonical built-in role grids (twin of apiome.seed_builtin_roles, V118) ────

_ALL_RESOURCES = [
    Resource.PROJECTS,
    Resource.VERSIONS,
    Resource.CLASSES,
    Resource.PROPERTIES,
    Resource.PATHS,
    Resource.TYPES,
    Resource.IMPORTS,
    Resource.MEMBERS,
    Resource.API_KEYS,
    Resource.BILLING,
]
# Resources an Editor may fully manage (content); the rest are view-only for them.
_EDITOR_CONTENT = [
    Resource.PROJECTS,
    Resource.VERSIONS,
    Resource.CLASSES,
    Resource.PROPERTIES,
    Resource.PATHS,
    Resource.IMPORTS,
    Resource.API_KEYS,
]
_CRUD = [Action.VIEW, Action.CREATE, Action.EDIT, Action.DELETE]


def _editor_grid() -> Set[str]:
    grid = {f"{r}:{a}" for r in _EDITOR_CONTENT for a in _CRUD}
    grid |= {f"{r}:{Action.VIEW}" for r in (Resource.TYPES, Resource.MEMBERS, Resource.BILLING)}
    return grid


def _viewer_grid() -> Set[str]:
    return {f"{r}:{Action.VIEW}" for r in _ALL_RESOURCES}


_ROLE_GRIDS: Dict[str, Set[str]] = {
    "editor": _editor_grid(),
    "viewer": _viewer_grid(),
    # Owner is the full-access (administrator) plane; the guard short-circuits before any grid.
}


class FakeMultiTenantDb:
    """In-memory ``db`` for the multi-tenant fixture: switcher listing + RBAC resolution."""

    def __init__(self) -> None:
        self.audit_rows: List[Dict[str, Any]] = []

    # -- switcher listing (tenants_session_routes) -------------------------

    def count_tenants_for_user(self, user_id: str) -> int:
        return len(_FIXTURE) if user_id == _GRACE_ID else 0

    def list_tenants_for_user_page(
        self, user_id: str, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        if user_id != _GRACE_ID:
            return []
        rows = [
            {
                "id": tenant_id,
                "slug": slug,
                "name": name,
                "role": role,
                "status": "active",
                "license_name": lic_name,
                "license_type": lic_type,
            }
            for slug, (tenant_id, name, role, lic_name, lic_type) in _FIXTURE.items()
        ]
        rows.sort(key=lambda r: r["slug"])
        return rows[offset : offset + limit]

    # -- RBAC resolution (permissions guard) -------------------------------

    def _role_for_tenant(self, tenant_id: Any) -> Optional[str]:
        for _, (tid, _name, role, _ln, _lt) in _FIXTURE.items():
            if str(tid) == str(tenant_id):
                return role
        return None

    def user_has_permission(
        self, tenant_id: Any, user_id: Any, resource: Any, action: Any
    ) -> bool:
        if str(user_id) != _GRACE_ID:
            return False
        role = self._role_for_tenant(tenant_id)
        if role == "owner":  # full-access (administrator) plane — allowed everything
            return True
        grid = _ROLE_GRIDS.get(role or "", set())
        return f"{resource}:{action}" in grid

    def is_platform_admin(self, user_id: Any) -> bool:
        return False

    def get_fallback_creator_user_id_for_tenant(self, tenant_id: Any) -> Optional[str]:
        return None

    def write_access_audit(self, **kwargs: Any) -> None:
        self.audit_rows.append(kwargs)


_db = FakeMultiTenantDb()


@pytest.fixture(autouse=True)
def _patch_db():
    with patch("app.tenants_session_routes.db", _db):
        yield


def _as_grace() -> None:
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "auth_method": "jwt",
        "user_id": _GRACE_ID,
        "user_email": "grace@example.com",
        "user_name": "Grace Hopper",
    }


def _auth_in(tenant_id: str) -> Dict[str, Any]:
    return {
        "auth_method": "jwt",
        "tenant_id": tenant_id,
        "user_id": _GRACE_ID,
        "user_email": "grace@example.com",
    }


# ── 1. Switcher data contract ─────────────────────────────────────────────────


def test_switcher_lists_all_three_memberships_with_diverging_roles_and_licenses():
    _as_grace()
    try:
        r = client.get("/v1/tenants/me")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3

    by_slug = {item["slug"]: item for item in body["items"]}
    assert set(by_slug) == {"aurora-labs", "borealis-studio", "cascade-foundation"}

    # Each membership carries its own role AND its own license tier — the divergence the
    # switcher renders (role badge + license chip) without any follow-up call.
    for slug, (_id, name, role, lic_name, lic_type) in _FIXTURE.items():
        item = by_slug[slug]
        assert item["name"] == name
        assert item["role"] == role
        assert item["status"] == "active"
        assert item["license_name"] == lic_name
        assert item["license_type"] == lic_type

    # The three license tiers are genuinely distinct (Free / Paid / Sponsor).
    assert {i["license_type"] for i in body["items"]} == {"free", "paid", "sponsor"}
    # And the three roles are genuinely distinct (owner / editor / viewer).
    assert {i["role"] for i in body["items"]} == {"owner", "editor", "viewer"}


def test_switcher_is_a_single_round_trip_and_paginates():
    _as_grace()
    try:
        r = client.get("/v1/tenants/me", params={"limit": 2, "offset": 0})
        r2 = client.get("/v1/tenants/me", params={"limit": 2, "offset": 2})
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200 and r2.status_code == 200
    # total reflects the full membership count regardless of the page window.
    assert r.json()["total"] == 3 and r2.json()["total"] == 3
    assert [i["slug"] for i in r.json()["items"]] == ["aurora-labs", "borealis-studio"]
    assert [i["slug"] for i in r2.json()["items"]] == ["cascade-foundation"]


# ── 2. Permission divergence (same user, different tenant) ────────────────────


def test_owner_tenant_allows_everything_including_member_management():
    aurora = _TENANT_BY_ROLE["owner"]
    # Owner passes the guard for a governance action a viewer/editor cannot perform.
    uid = enforce_permission(_db, _auth_in(aurora), Resource.MEMBERS, Action.CREATE)
    assert uid == _GRACE_ID
    assert enforce_permission(_db, _auth_in(aurora), Resource.VERSIONS, Action.PUBLISH) == _GRACE_ID


def test_editor_tenant_allows_content_but_denies_member_management():
    borealis = _TENANT_BY_ROLE["editor"]
    # Editor may create content...
    assert enforce_permission(_db, _auth_in(borealis), Resource.PROJECTS, Action.CREATE) == _GRACE_ID
    # ...but not manage members, and not publish.
    for resource, action in (
        (Resource.MEMBERS, Action.CREATE),
        (Resource.VERSIONS, Action.PUBLISH),
    ):
        with pytest.raises(Exception) as exc:  # HTTPException(403)
            enforce_permission(_db, _auth_in(borealis), resource, action)
        assert getattr(exc.value, "status_code", None) == 403


def test_viewer_tenant_allows_reads_but_denies_writes():
    cascade = _TENANT_BY_ROLE["viewer"]
    assert has_permission(_db, _auth_in(cascade), Resource.PROJECTS, Action.VIEW) is True
    with pytest.raises(Exception) as exc:  # HTTPException(403)
        enforce_permission(_db, _auth_in(cascade), Resource.PROJECTS, Action.CREATE)
    assert getattr(exc.value, "status_code", None) == 403


def test_same_action_diverges_across_the_three_tenants():
    """The one user, one action (projects:create), three different outcomes."""
    results = {}
    for role, tenant_id in _TENANT_BY_ROLE.items():
        results[role] = has_permission(_db, _auth_in(tenant_id), Resource.PROJECTS, Action.CREATE)
    assert results == {"owner": True, "editor": True, "viewer": False}

    # And a governance action (members:create) that only the owner holds.
    gov = {
        role: has_permission(_db, _auth_in(tid), Resource.MEMBERS, Action.CREATE)
        for role, tid in _TENANT_BY_ROLE.items()
    }
    assert gov == {"owner": True, "editor": False, "viewer": False}
