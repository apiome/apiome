"""REST-side end-to-end journey for the OAuth Login & Onboarding MVP (OLO-7.4, #4226).

The Playwright suite (``apiome-ui/e2e/journey``) drives the browser half of the
journey; this module walks the same story through the REST contracts alone, as one
continuous progression over a shared in-memory database fake:

  1. First-tenant provisioning (OLO-4.3): atomic creation, owner membership, Free
     license attached.
  2. Tenant-cap guard (OLO-5.3): a second provision for the same user is refused with
     the structured ``tenant-cap-reached`` 403.
  3. Slug uniqueness: a taken slug is refused with the structured ``tenant-slug-taken``
     409.
  4. License surface (OLO-5.4): plan/seats reflect the provisioned Free license.
  5. Seat enforcement (OLO-5.3): member invites succeed to the Free seat limit, then
     the structured ``license-seats-exhausted`` 403 — and the license surface agrees.
  6. Enriched session (OLO-6.2): ``GET /v1/tenants/me`` lists every membership with
     role, lifecycle status, and license plan — the switcher's data contract.

Route modules import the ``db`` singleton directly, so the fake is patched into each
consuming module; auth is stubbed via FastAPI dependency overrides exactly like the
sibling suites. No live database is touched.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication, validate_session_credentials
from app.database import (
    DEFAULT_FREE_MAX_TENANTS,
    DEFAULT_FREE_MAX_USERS_PER_TENANT,
    TenantCapReachedError,
    TenantSlugConflictError,
)
from app.main import app

client = TestClient(app)

_ADA_ID = "660e8400-e29b-41d4-a716-446655440001"
_BEA_ID = "660e8400-e29b-41d4-a716-446655440002"
_CAL_ID = "660e8400-e29b-41d4-a716-446655440003"

# Pre-existing accounts available as invite targets (invites require an account).
_MEMBER_POOL = {
    f"member{n}@example.test": f"770e8400-e29b-41d4-a716-44665544{n:04d}" for n in range(1, 7)
}


class FakeJourneyDb:
    """In-memory stand-in for the ``db`` singleton, coherent across the journey.

    Implements exactly the methods the journeyed routes call, with Free-tier
    defaults mirroring the real schema: ``max_tenants`` per user and
    ``max_users_per_tenant`` seats per tenant.
    """

    def __init__(self) -> None:
        self.tenants: Dict[str, Dict[str, Any]] = {}
        # (tenant_id, user_id) -> {"role": ..., "status": ...}
        self.memberships: Dict[tuple, Dict[str, str]] = {}
        self.users: Dict[str, Dict[str, str]] = {
            email: {"id": user_id, "email": email, "name": email.split("@")[0]}
            for email, user_id in _MEMBER_POOL.items()
        }
        self.audit_rows: List[Dict[str, Any]] = []

    # -- provisioning (onboarding_routes) ----------------------------------

    def provision_first_tenant(self, user_id: str, name: str, slug: str) -> Dict[str, Any]:
        owned = [
            t for (t, u), m in self.memberships.items() if u == user_id and m["role"] == "owner"
        ]
        if len(owned) >= DEFAULT_FREE_MAX_TENANTS:
            raise TenantCapReachedError(
                f"You already have {len(owned)} tenant(s); the Free plan allows "
                f"{DEFAULT_FREE_MAX_TENANTS}."
            )
        if any(t["slug"] == slug for t in self.tenants.values()):
            raise TenantSlugConflictError(f"Slug '{slug}' is already in use.")
        tenant_id = f"550e8400-e29b-41d4-a716-4466554400{len(self.tenants):02d}"
        self.tenants[tenant_id] = {
            "id": tenant_id,
            "name": name,
            "slug": slug,
            "created_at": datetime(2026, 7, 18, 12, 0, 0),
            # Auto-issued Free license (OLO-5.2) with the default seat shape.
            "license": {
                "name": "Free",
                "license_type": "free",
                "seats": {"max_users_per_tenant": DEFAULT_FREE_MAX_USERS_PER_TENANT},
            },
        }
        self.memberships[(tenant_id, user_id)] = {"role": "owner", "status": "active"}
        return dict(self.tenants[tenant_id])

    # -- license read surface (license_routes, tenants_session_routes) -----

    def get_tenant_license_info(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return None
        return {k: tenant["license"][k] for k in ("name", "license_type")}

    def list_tenant_effective_features(self, tenant_id: str) -> List[Dict[str, Any]]:
        return []

    # -- seat accounting (license_capacity, license_routes) ----------------

    def get_tenant_license_seats(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        tenant = self.tenants.get(tenant_id)
        return dict(tenant["license"]["seats"]) if tenant else None

    def count_member_seats_in_use(self, tenant_id: str) -> int:
        return sum(
            1
            for (t, _), m in self.memberships.items()
            if t == tenant_id and m["status"] in ("active", "pending")
        )

    # -- membership (access_routes) ----------------------------------------

    def get_user_by_email(self, email: str) -> Optional[Dict[str, str]]:
        return self.users.get(email.strip().lower())

    def add_member(self, tenant_id: str, user_id: str, status: str = "active") -> None:
        self.memberships.setdefault((tenant_id, user_id), {"role": "editor", "status": status})

    def ensure_builtin_roles(self, tenant_id: str) -> None:  # pragma: no cover - no-op
        return None

    def list_members(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [
            {"user_id": u, "role_slug": m["role"], "status": m["status"]}
            for (t, u), m in self.memberships.items()
            if t == tenant_id
        ]

    def write_access_audit(self, **kwargs: Any) -> None:
        self.audit_rows.append(kwargs)

    # -- permission guard (permissions.enforce_permission) -----------------

    def user_has_permission(
        self, tenant_id: Any, user_id: Any, resource: Any, action: Any
    ) -> bool:
        """Authorization is out of scope here (covered by test_permission_guard)."""
        return True

    # -- enriched session (tenants_session_routes) -------------------------

    def count_tenants_for_user(self, user_id: str) -> int:
        return sum(1 for (_, u) in self.memberships if u == user_id)

    def list_tenants_for_user_page(
        self, user_id: str, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        rows = []
        for (tenant_id, member_id), membership in self.memberships.items():
            if member_id != user_id:
                continue
            tenant = self.tenants[tenant_id]
            rows.append(
                {
                    "id": tenant_id,
                    "slug": tenant["slug"],
                    "name": tenant["name"],
                    "role": membership["role"],
                    "status": membership["status"],
                    "license_name": tenant["license"]["name"],
                    "license_type": tenant["license"]["license_type"],
                }
            )
        rows.sort(key=lambda r: r["slug"])
        return rows[offset : offset + limit]


# One shared fake: the whole module is a single continuous journey.
_db = FakeJourneyDb()

# Every module that resolved ``db`` at import time gets the same fake.
_DB_CONSUMERS = [
    "app.onboarding_routes.db",
    "app.license_routes.db",
    "app.license_capacity.db",
    "app.access_routes.db",
    "app.tenants_session_routes.db",
]


@pytest.fixture(autouse=True)
def _fake_db():
    patches = [patch(target, _db) for target in _DB_CONSUMERS]
    for p in patches:
        p.start()
    yield _db
    for p in patches:
        p.stop()


def _as_session(user_id: str, email: str) -> None:
    """Authenticate subsequent requests as a JWT user session (no tenant context)."""
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "auth_method": "jwt",
        "user_id": user_id,
        "user_email": email,
        "user_name": email.split("@")[0],
    }


def _as_tenant_member(user_id: str, tenant_id: str) -> None:
    """Authenticate subsequent requests as a member acting inside a tenant."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "auth_method": "jwt",
        "user_id": user_id,
        "tenant_id": tenant_id,
    }


def _provision(name: str, slug: Optional[str] = None):
    body: Dict[str, Any] = {"name": name, "provision_sample_project": False}
    if slug is not None:
        body["slug"] = slug
    return client.post("/v1/onboarding/first-tenant", json=body)


def _acme_id() -> str:
    return next(t["id"] for t in _db.tenants.values() if t["slug"] == "acme-corp")


# ---- 1. provisioning ------------------------------------------------------


def test_01_ada_provisions_first_tenant_with_free_license():
    _as_session(_ADA_ID, "ada@example.test")
    r = _provision("Acme Corp")
    assert r.status_code == 201
    tenant = r.json()["tenant"]
    assert tenant["name"] == "Acme Corp"
    assert tenant["slug"] == "acme-corp"
    # The atomic provision attached the Free license and the owner membership.
    assert _db.get_tenant_license_info(tenant["id"]) == {
        "name": "Free",
        "license_type": "free",
    }
    assert _db.memberships[(tenant["id"], _ADA_ID)] == {"role": "owner", "status": "active"}


def test_02_second_tenant_hits_the_cap_guard():
    _as_session(_ADA_ID, "ada@example.test")
    r = _provision("Acme Two")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "tenant-cap-reached"


def test_03_bea_provisions_her_own_tenant():
    _as_session(_BEA_ID, "bea@example.test")
    r = _provision("Beeworks")
    assert r.status_code == 201
    assert r.json()["tenant"]["slug"] == "beeworks"


def test_04_taken_slug_is_a_structured_conflict():
    # Cal has no tenants (so the cap guard passes) but wants Ada's slug.
    _as_session(_CAL_ID, "cal@example.test")
    r = _provision("Acme Impostor", slug="acme-corp")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "tenant-slug-taken"


# ---- 2. license surface ---------------------------------------------------


def test_05_license_surface_shows_free_plan_and_one_seat_used():
    _as_tenant_member(_ADA_ID, _acme_id())
    r = client.get("/v1/tenants/acme-corp/license")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == {"name": "Free", "type": "free"}
    assert body["seats"] == {"used": 1, "max": DEFAULT_FREE_MAX_USERS_PER_TENANT}


# ---- 3. seat enforcement --------------------------------------------------


def test_06_invites_fill_the_free_seats_then_are_refused():
    acme = _acme_id()
    _as_tenant_member(_ADA_ID, acme)
    emails = list(_MEMBER_POOL)

    # Seats 2..5: four invites succeed.
    for email in emails[:4]:
        r = client.post("/v1/access/acme-corp/members", json={"email": email})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

    # Seat 6: the structured refusal, before any lookup or write.
    r = client.post("/v1/access/acme-corp/members", json={"email": emails[4]})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "license-seats-exhausted"
    assert str(DEFAULT_FREE_MAX_USERS_PER_TENANT) in detail["message"]

    # Nothing was written for the refused invite.
    assert _db.count_member_seats_in_use(acme) == DEFAULT_FREE_MAX_USERS_PER_TENANT


def test_07_license_surface_agrees_seats_are_exhausted():
    _as_tenant_member(_ADA_ID, _acme_id())
    r = client.get("/v1/tenants/acme-corp/license")
    assert r.status_code == 200
    seats = r.json()["seats"]
    assert seats["used"] == seats["max"] == DEFAULT_FREE_MAX_USERS_PER_TENANT


# ---- 4. enriched session --------------------------------------------------


def test_08_member1_joins_beeworks_and_sees_both_memberships_enriched():
    member1_email = "member1@example.test"
    member1_id = _MEMBER_POOL[member1_email]

    # Bea invites member1 into Beeworks (it has free seats).
    beeworks = next(t["id"] for t in _db.tenants.values() if t["slug"] == "beeworks")
    _as_tenant_member(_BEA_ID, beeworks)
    r = client.post("/v1/access/beeworks/members", json={"email": member1_email})
    assert r.status_code == 200

    # The switcher contract (OLO-6.2): every membership, enriched in one call.
    _as_session(member1_id, member1_email)
    r = client.get("/v1/tenants/me")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    by_slug = {item["slug"]: item for item in body["items"]}
    assert set(by_slug) == {"acme-corp", "beeworks"}
    for item in by_slug.values():
        assert item["role"] == "editor"
        assert item["status"] == "active"
        assert item["license_name"] == "Free"
        assert item["license_type"] == "free"


def test_09_owner_membership_reads_as_owner_in_the_enriched_list():
    _as_session(_ADA_ID, "ada@example.test")
    r = client.get("/v1/tenants/me")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "acme-corp"
    assert body["items"][0]["role"] == "owner"
    assert body["items"][0]["license_name"] == "Free"
