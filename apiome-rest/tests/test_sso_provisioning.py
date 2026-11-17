"""Just-in-time provisioning for enterprise SSO — EID-1.3 (#5013).

The pure rules of :mod:`app.sso_provisioning` and the route contract of
``POST /v1/tenants/{t}/sso/providers/{id}/provision`` (:mod:`app.tenant_sso_routes`), with the
store replaced by the in-memory fake of ``test_sso_provider_routes`` and the membership write by a
small in-memory workspace that follows the same rules. What the real schema must prove is in
``test_sso_provisioning_db.py``.

* service token only — no session, no API key, no anonymous call;
* the acceptance path: a first sign-in is provisioned with the default role; a repeat changes
  nothing; a member keeps their role (never demoted);
* a full workspace blocks provisioning and says so; switching seat enforcement off lifts it;
* a provider of workspace A cannot provision into workspace B, by id or by slug;
* only someone who signed in through the provider, from one of its verified domains, is
  provisioned; a disabled provider provisions nobody;
* ``owner`` is never the role a sign-in grants.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import sso_provisioning as provisioning
from app import tenant_sso_routes as routes
from app.config import settings
from app.main import app
from app.notifications import MAX_RECIPIENTS, NOTIFICATION_TYPES, TYPE_SEAT_CAP_BLOCKED_SSO
from tests.test_sso_provider_routes import FakeSsoStore

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
USER = "55555555-5555-4555-8555-555555555555"
OWNER = "33333333-3333-4333-8333-333333333333"
SERVICE_TOKEN = "internal-service-token-for-tests"
HEADERS = {"X-Internal-Service-Token": SERVICE_TOKEN}

ROLES = [
    {"id": "r-owner", "slug": "owner", "name": "Owner"},
    {"id": "r-admin", "slug": "admin", "name": "Admin"},
    {"id": "r-editor", "slug": "editor", "name": "Editor"},
    {"id": "r-viewer", "slug": "viewer", "name": "Viewer"},
]


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


class TestChooseRole:
    def test_the_providers_default_role_is_used(self) -> None:
        assert provisioning.choose_role(ROLES, "editor")["slug"] == "editor"

    @pytest.mark.parametrize("default", [None, "", "  ", "gone-role"])
    def test_no_default_or_a_removed_one_falls_back_to_viewer(self, default) -> None:
        assert provisioning.choose_role(ROLES, default)["slug"] == "viewer"

    def test_owner_is_never_granted_by_signing_in(self) -> None:
        assert provisioning.choose_role(ROLES, "owner")["slug"] == "viewer"

    def test_a_workspace_without_a_viewer_role_grants_no_role(self) -> None:
        assert provisioning.choose_role([ROLES[0]], "owner") is None


class TestBlockedNotification:
    PROVIDER = {"slug": "acme-okta", "display_name": "Acme Okta"}

    def _drafts(self, owners: List[str]):
        return provisioning.blocked_notification_drafts(
            owners, user_id=USER, user_email="new@acme.com", provider=self.PROVIDER, seat_limit=5
        )

    def test_every_owner_is_told_once(self) -> None:
        drafts = self._drafts([OWNER, "other-owner", OWNER])
        assert [draft.user_id for draft in drafts] == [OWNER, "other-owner"]
        assert {draft.type for draft in drafts} == {TYPE_SEAT_CAP_BLOCKED_SSO}

    def test_the_row_says_who_which_provider_and_where_to_go(self) -> None:
        (draft,) = self._drafts([OWNER])
        assert draft.payload["summary"] == (
            "new@acme.com signed in through Acme Okta but was not added: all 5 member seats are in use."
        )
        assert draft.payload["link"] == "/ade/dashboard/members"
        assert draft.payload["user_id"] == USER
        assert draft.payload["provider_slug"] == "acme-okta"
        assert draft.actor_id == USER

    def test_the_blocked_person_is_not_told_about_themselves(self) -> None:
        assert self._drafts([USER]) == []

    def test_the_recipient_set_is_bounded(self) -> None:
        assert len(self._drafts([f"owner-{n}" for n in range(MAX_RECIPIENTS + 50)])) == MAX_RECIPIENTS

    def test_the_type_is_part_of_the_inbox_vocabulary(self) -> None:
        assert TYPE_SEAT_CAP_BLOCKED_SSO in NOTIFICATION_TYPES


def test_provenance_is_the_identity_kind() -> None:
    assert provisioning.provisioned_by("acme-okta") == "sso:acme-okta"


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


class Installation:
    """Two workspaces, their members, and who holds which SSO identity."""

    def __init__(self) -> None:
        self.http = TestClient(app)
        self.store = FakeSsoStore()
        self.tenants = {
            TENANT: {"id": TENANT, "slug": "acme", "name": "Acme"},
            OTHER_TENANT: {"id": OTHER_TENANT, "slug": "globex", "name": "Globex"},
        }
        self.users: Dict[str, Dict[str, Any]] = {USER: {"id": USER, "email": "new@acme.com", "name": "New Person"}}
        self.identities: set = set()
        #: (tenant, user) -> {"status", "role", "provisioned_by"}
        self.members: Dict[tuple, Dict[str, Any]] = {}
        self.blocked: List[Dict[str, Any]] = []
        self.seat_limits: Dict[str, int] = {TENANT: 5, OTHER_TENANT: 5}

    def provider(self, tenant_id: str = TENANT, *, slug: str = "acme-okta", domain: str = "acme.com", **extra):
        """An enabled provider of ``tenant_id`` with one verified domain."""
        row = self.store.create_provider(
            None,
            {
                "slug": slug,
                "protocol": "oidc",
                "display_name": "Acme Okta",
                "issuer": "https://idp.example.com",
                "tenant_id": tenant_id,
                "enabled": True,
                **extra,
            },
            actor="test",
        )
        self.store.add_domain(None, row["id"], domain, token="t")
        self.store.verify_domain(None, row["id"], domain, actor="test")
        return row

    def signed_in_through(self, slug: str, user_id: str = USER) -> None:
        self.identities.add((user_id, slug))

    def provision(self, provider_id: str, *, tenant: str = "acme", user_id: str = USER, headers=HEADERS):
        return self.http.post(
            f"/v1/tenants/{tenant}/sso/providers/{provider_id}/provision", json={"user_id": user_id}, headers=headers
        )

    # The in-memory twin of app.sso_provisioning.provision_member — same table as its docstring.
    def provision_member(self, _db, *, provider, user, seat_limit: Optional[int]):
        key = (provider["tenant_id"], user["id"])
        member = self.members.get(key)
        if member is not None:
            outcome = {"pending": "activated", "suspended": "suspended"}.get(member["status"], "existing")
            if member["status"] == "pending":
                member["status"] = "active"
            role = member["role"]
        else:
            in_use = sum(1 for (t, _), m in self.members.items() if t == key[0] and m["status"] != "suspended")
            if seat_limit is not None and in_use >= seat_limit:
                self.blocked.append({"tenant_id": key[0], "user_id": user["id"]})
                return {"outcome": "seat-cap-blocked", "role_slug": None, "role_name": None, "seat_limit": seat_limit}
            role = provisioning.choose_role(ROLES, provider.get("default_role_slug"))
            self.members[key] = {"status": "active", "role": role, "provisioned_by": f"sso:{provider['slug']}"}
            outcome = "provisioned"
        return {
            "outcome": outcome,
            "role_slug": role["slug"] if role else None,
            "role_name": role["name"] if role else None,
            "seat_limit": seat_limit,
        }


@pytest.fixture
def inst(monkeypatch):
    installation = Installation()
    monkeypatch.setattr(settings, "internal_service_token", SERVICE_TOKEN)
    monkeypatch.setattr(settings, "license_enforcement_enabled", True)
    monkeypatch.setattr(routes, "store", installation.store)
    monkeypatch.setattr(routes.provisioning, "get_tenant", lambda _db, tenant_id: installation.tenants.get(tenant_id))
    monkeypatch.setattr(routes.provisioning, "get_sso_user", lambda _db, user_id: installation.users.get(user_id))
    monkeypatch.setattr(
        routes.provisioning,
        "user_has_identity",
        lambda _db, user_id, slug: (user_id, slug) in installation.identities,
    )
    monkeypatch.setattr(routes.provisioning, "provision_member", installation.provision_member)
    monkeypatch.setattr(routes, "member_seat_limit", lambda tenant_id: installation.seat_limits[tenant_id])
    yield installation
    app.dependency_overrides.clear()


class TestGate:
    def test_without_the_service_token_nobody_is_provisioned(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        assert inst.provision(provider["id"], headers={}).status_code == 401
        assert inst.provision(provider["id"], headers={"X-Internal-Service-Token": "wrong"}).status_code == 403
        assert inst.provision(provider["id"], headers={"Authorization": "Bearer a.session.jwt"}).status_code == 401
        assert inst.members == {}

    def test_the_route_is_off_when_no_service_token_is_configured(self, inst, monkeypatch) -> None:
        provider = inst.provider()
        monkeypatch.setattr(settings, "internal_service_token", None)
        assert inst.provision(provider["id"]).status_code == 503

    def test_an_unknown_field_is_refused(self, inst) -> None:
        provider = inst.provider()
        response = inst.http.post(
            f"/v1/tenants/acme/sso/providers/{provider['id']}/provision",
            json={"user_id": USER, "role_slug": "owner"},
            headers=HEADERS,
        )
        assert response.status_code == 422
        assert inst.members == {}


class TestFirstSignIn:
    def test_a_first_time_user_becomes_a_member_with_the_default_role(self, inst) -> None:
        provider = inst.provider(default_role_slug="editor")
        inst.signed_in_through("acme-okta")

        response = inst.provision(provider["id"])

        assert response.status_code == 200, response.text
        assert response.json() == {
            "outcome": "provisioned",
            "tenant_id": TENANT,
            "tenant_slug": "acme",
            "tenant_name": "Acme",
            "role_slug": "editor",
            "role_name": "Editor",
            "seat_limit": 5,
        }
        assert inst.members[(TENANT, USER)]["provisioned_by"] == "sso:acme-okta"

    def test_the_workspace_may_be_named_by_id(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        assert inst.provision(provider["id"], tenant=TENANT).json()["outcome"] == "provisioned"

    def test_no_default_role_means_viewer_and_owner_is_never_granted(self, inst) -> None:
        plain = inst.provider()
        inst.signed_in_through("acme-okta")
        assert inst.provision(plain["id"]).json()["role_slug"] == "viewer"

        owner = inst.provider(OTHER_TENANT, slug="globex-okta", domain="acme.com.example", default_role_slug="owner")
        inst.users[OWNER] = {"id": OWNER, "email": "boss@acme.com.example", "name": "Boss"}
        inst.signed_in_through("globex-okta", OWNER)
        assert inst.provision(owner["id"], tenant="globex", user_id=OWNER).json()["role_slug"] == "viewer"

    def test_a_repeat_sign_in_changes_nothing(self, inst) -> None:
        provider = inst.provider(default_role_slug="editor")
        inst.signed_in_through("acme-okta")
        inst.provision(provider["id"])
        before = dict(inst.members[(TENANT, USER)])

        again = inst.provision(provider["id"])

        assert again.json()["outcome"] == "existing"
        assert inst.members == {(TENANT, USER): before}

    def test_an_existing_member_keeps_their_role(self, inst) -> None:
        provider = inst.provider(default_role_slug="viewer")
        inst.signed_in_through("acme-okta")
        inst.members[(TENANT, USER)] = {"status": "active", "role": ROLES[1], "provisioned_by": None}

        response = inst.provision(provider["id"])

        assert response.json()["outcome"] == "existing"
        assert response.json()["role_slug"] == "admin"  # never demoted to the provider's default
        assert inst.members[(TENANT, USER)]["provisioned_by"] is None

    def test_signing_in_accepts_a_pending_invitation_and_keeps_its_role(self, inst) -> None:
        provider = inst.provider(default_role_slug="viewer")
        inst.signed_in_through("acme-okta")
        inst.members[(TENANT, USER)] = {"status": "pending", "role": ROLES[2], "provisioned_by": None}

        response = inst.provision(provider["id"])

        assert response.json()["outcome"] == "activated"
        assert response.json()["role_slug"] == "editor"
        assert inst.members[(TENANT, USER)]["status"] == "active"

    def test_a_suspended_member_is_not_reinstated_by_signing_in(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        inst.members[(TENANT, USER)] = {"status": "suspended", "role": ROLES[3], "provisioned_by": None}

        assert inst.provision(provider["id"]).json()["outcome"] == "suspended"
        assert inst.members[(TENANT, USER)]["status"] == "suspended"


class TestSeatCap:
    def _fill(self, inst, tenant_id: str = TENANT) -> None:
        for n in range(inst.seat_limits[tenant_id]):
            inst.members[(tenant_id, f"member-{n}")] = {"status": "active", "role": ROLES[3], "provisioned_by": None}

    def test_a_full_workspace_blocks_provisioning_and_says_so(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        self._fill(inst)

        response = inst.provision(provider["id"])

        assert response.status_code == 200, response.text  # the sign-in itself completes
        assert response.json()["outcome"] == "seat-cap-blocked"
        assert response.json()["role_slug"] is None
        assert response.json()["seat_limit"] == 5
        assert (TENANT, USER) not in inst.members
        assert inst.blocked == [{"tenant_id": TENANT, "user_id": USER}]

    def test_an_existing_member_of_a_full_workspace_still_signs_in(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        self._fill(inst)
        inst.members[(TENANT, USER)] = {"status": "active", "role": ROLES[3], "provisioned_by": None}

        assert inst.provision(provider["id"]).json()["outcome"] == "existing"
        assert inst.blocked == []

    def test_suspended_members_do_not_hold_a_seat(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        self._fill(inst)
        inst.members[(TENANT, "member-0")]["status"] = "suspended"

        assert inst.provision(provider["id"]).json()["outcome"] == "provisioned"

    def test_switching_seat_enforcement_off_lifts_the_cap(self, inst, monkeypatch) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        self._fill(inst)
        monkeypatch.setattr(settings, "license_enforcement_enabled", False)

        response = inst.provision(provider["id"])

        assert response.json()["outcome"] == "provisioned"
        assert response.json()["seat_limit"] is None


class TestNoCrossWorkspaceLeak:
    def test_a_provider_of_one_workspace_cannot_provision_into_another(self, inst) -> None:
        provider = inst.provider(TENANT)
        inst.signed_in_through("acme-okta")

        for other in ("globex", OTHER_TENANT):
            response = inst.provision(provider["id"], tenant=other)
            assert response.status_code == 404
            assert response.json()["detail"]["error"] == "sso-provider-not-found"
        assert inst.members == {}

    def test_one_person_may_be_provisioned_into_several_workspaces_through_their_own_providers(self, inst) -> None:
        acme = inst.provider(TENANT)
        globex = inst.provider(OTHER_TENANT, slug="globex-okta", domain="acme.com.example")
        inst.signed_in_through("acme-okta")

        assert inst.provision(acme["id"]).json()["tenant_id"] == TENANT
        # Holding Acme's identity opens nothing at Globex.
        response = inst.provision(globex["id"], tenant="globex")
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "sso-identity-missing"
        assert set(inst.members) == {(TENANT, USER)}

    def test_an_unknown_or_malformed_provider_is_not_found(self, inst) -> None:
        inst.provider()
        for provider_id in ("00000000-0000-4000-8000-000000000000", "not-a-uuid"):
            assert inst.provision(provider_id).status_code == 404

    def test_a_provider_without_a_workspace_provisions_nobody(self, inst) -> None:
        provider = inst.provider()
        inst.store.providers[provider["id"]]["tenant_id"] = None  # registered before EID-1.3
        inst.signed_in_through("acme-okta")
        assert inst.provision(provider["id"]).status_code == 404
        assert inst.members == {}


class TestWhoIsProvisioned:
    def test_someone_who_never_signed_in_through_the_provider_is_refused(self, inst) -> None:
        provider = inst.provider()
        response = inst.provision(provider["id"])
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "sso-identity-missing"
        assert inst.members == {}

    def test_an_email_outside_the_verified_domains_is_refused(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        inst.users[USER]["email"] = "new@elsewhere.example"
        response = inst.provision(provider["id"])
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "sso-email-domain-mismatch"

    def test_an_unverified_domain_does_not_count(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        inst.store.add_domain(None, provider["id"], "pending.example", token="t")
        inst.users[USER]["email"] = "new@pending.example"
        assert inst.provision(provider["id"]).status_code == 403

    def test_an_unknown_deleted_or_malformed_account_is_not_found(self, inst) -> None:
        provider = inst.provider()
        for user_id in ("66666666-6666-4666-8666-666666666666", "not-a-uuid"):
            response = inst.provision(provider["id"], user_id=user_id)
            assert response.status_code == 404
            assert response.json()["detail"]["error"] == "sso-user-not-found"

    def test_a_disabled_provider_provisions_nobody(self, inst) -> None:
        provider = inst.provider()
        inst.signed_in_through("acme-okta")
        inst.store.providers[provider["id"]]["enabled"] = False
        response = inst.provision(provider["id"])
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "sso-provider-disabled"
        assert inst.members == {}
