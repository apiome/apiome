"""Single sign-on run by a workspace's owners — EID-1.2 (#5012).

Route contract of :mod:`app.tenant_sso_routes`, with the store replaced by the in-memory fake of
``test_sso_provider_routes``, the IdP fetches and the DNS lookup replaced by canned answers (no
network), and the OLO-8.3 crypto running for real against a test key.

* owners and tenant admins only, by session — every route, reads included; API keys refused;
* a workspace sees and changes only its own providers; a new provider always belongs to it;
* the acceptance path: register, add ``acme.com``, publish the TXT record, verify, enable — and
  only then is the provider routable;
* a second workspace is refused ``sso-domain-claimed``; public mailbox domains are refused;
* a failed DNS lookup is ``could-not-check`` with the observed answer and verifies nothing;
* three checks an hour per domain; an already verified domain costs none;
* disabling stops routing; removing reports how many members used the provider;
* every change lands in the workspace's access audit, with no secret in it; no response carries
  a secret.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import sso_domain_verification as verification
from app import sso_provider_routes as admin_routes
from app import tenant_sso_routes as routes
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.sso_metadata import SsoConfigError
from tests.test_sso_provider_routes import CLIENT_SECRET, ISSUER, SAML_METADATA, SP_PRIVATE_KEY, FakeSsoStore

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
OWNER = "33333333-3333-4333-8333-333333333333"
OTHER_OWNER = "44444444-4444-4444-8444-444444444444"
MEMBER = "55555555-5555-4555-8555-555555555555"

BASE = "/v1/tenants/acme/sso/providers"
SERVICE_TOKEN = "internal-service-token-for-tests"


class Workspace:
    """What a test holds: the client, the fake store, the audit rows, and who is signed in."""

    def __init__(self, store: FakeSsoStore, audit: List[Dict[str, Any]], dns: Dict[str, Any]) -> None:
        self.http = TestClient(app)
        self.store = store
        self.audit = audit
        self.dns = dns
        self.sign_in(TENANT, OWNER)

    def sign_in(self, tenant_id: str, user_id: str, *, method: str = "jwt") -> None:
        """Make the next requests come from ``user_id`` in ``tenant_id``."""
        app.dependency_overrides[validate_authentication] = lambda: {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_email": f"{user_id[:4]}@example.test",
            "auth_method": method,
        }

    def publish(self, domain: str, *values: str) -> None:
        """Put TXT values at a domain's challenge record."""
        self.dns[f"_apiome-challenge.{domain}"] = ("answered", list(values), None)


@pytest.fixture
def ws(monkeypatch):
    monkeypatch.setattr(settings, "auth_config_enc_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    monkeypatch.setattr(settings, "internal_service_token", SERVICE_TOKEN)
    monkeypatch.setattr(settings, "sso_public_domains", None)

    fake = FakeSsoStore()
    monkeypatch.setattr(routes, "store", fake)
    monkeypatch.setattr(admin_routes, "store", fake)

    async def fake_discover(issuer, *, client_id):
        if issuer.rstrip("/") != ISSUER:
            raise SsoConfigError("sso-discovery-mismatch", "mismatch")
        return {"issuer": ISSUER, "oidc_config": {"client_id": client_id, "jwks_uri": f"{ISSUER}/certs"}}

    monkeypatch.setattr(admin_routes, "discover_oidc", fake_discover)

    dns: Dict[str, Any] = {}

    async def fake_lookup(name: str):
        return dns.get(name, ("empty", [], "NXDOMAIN: the name does not exist."))

    async def check(domain, token):
        return await verification.check_domain_challenge(domain, token, lookup=fake_lookup)

    monkeypatch.setattr(routes, "check_domain_challenge", check)
    monkeypatch.setattr(verification, "_verify_limiter", verification.FixedWindowRateLimiter())

    admins = {(TENANT, OWNER), (OTHER_TENANT, OTHER_OWNER)}
    monkeypatch.setattr(routes.db, "is_user_tenant_admin", lambda tenant, user: (tenant, user) in admins)
    monkeypatch.setattr(
        routes.db,
        "list_roles",
        lambda tenant: [{"slug": slug} for slug in ("owner", "admin", "editor", "viewer")],
    )
    audit: List[Dict[str, Any]] = []
    monkeypatch.setattr(routes.db, "write_access_audit", lambda **row: audit.append(row))
    monkeypatch.setattr(admin_routes.db, "write_auth_event", lambda **row: None)

    yield Workspace(fake, audit, dns)
    app.dependency_overrides.clear()


def _oidc(ws: Workspace, **overrides) -> Dict[str, Any]:
    body = {
        "protocol": "oidc",
        "slug": "acme-okta",
        "display_name": "Acme Okta",
        "issuer": ISSUER,
        "client_id": "apiome",
        "client_secret": CLIENT_SECRET,
        **overrides,
    }
    response = ws.http.post(BASE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _add_domain(ws: Workspace, provider_id: str, domain: str = "acme.com") -> Dict[str, Any]:
    response = ws.http.post(f"{BASE}/{provider_id}/domains", json={"domain": domain})
    assert response.status_code == 201, response.text
    normalized = domain.rsplit("@", 1)[-1].lower()
    return next(d for d in response.json()["domains"] if d["domain"] == normalized)


def _routable_slugs(ws: Workspace) -> List[str]:
    response = ws.http.get("/v1/internal/sso/providers/resolved", headers={"X-Internal-Service-Token": SERVICE_TOKEN})
    assert response.status_code == 200, response.text
    return [provider["slug"] for provider in response.json()["providers"]]


# ---------------------------------------------------------------------------
# Who may call
# ---------------------------------------------------------------------------


def _every_route() -> List[tuple]:
    pid = "00000000-0000-4000-8000-000000000000"
    return [
        ("GET", BASE, None),
        ("POST", BASE, {"protocol": "oidc", "slug": "x-sso", "display_name": "X"}),
        ("GET", f"{BASE}/{pid}", None),
        ("PATCH", f"{BASE}/{pid}", {"enabled": True}),
        ("DELETE", f"{BASE}/{pid}", None),
        ("POST", f"{BASE}/{pid}/domains", {"domain": "acme.com"}),
        ("DELETE", f"{BASE}/{pid}/domains/acme.com", None),
        ("POST", f"{BASE}/{pid}/domains/acme.com/verify", None),
    ]


class TestGate:
    def test_the_routes_under_test_are_all_the_module_serves(self) -> None:
        served = {
            (method, route.path)
            for route in routes.router.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }
        # The owner routes, plus the one service-to-service route (EID-1.3), which has no session
        # to gate by and is covered in test_sso_provisioning.py.
        provision = ("POST", "/v1/tenants/{tenant_slug}/sso/providers/{provider_id}/provision")
        assert provision in served
        assert len(served - {provision}) == len(_every_route()) == 8

    @pytest.mark.parametrize("method,path,body", _every_route())
    def test_a_member_who_is_not_an_admin_is_refused(self, ws, method, path, body) -> None:
        ws.sign_in(TENANT, MEMBER)
        assert ws.http.request(method, path, json=body).status_code == 403

    @pytest.mark.parametrize("method,path,body", _every_route())
    def test_an_api_key_is_refused_even_for_an_admin(self, ws, method, path, body) -> None:
        ws.sign_in(TENANT, OWNER, method="api_key")
        assert ws.http.request(method, path, json=body).status_code == 403

    def test_without_credentials_nothing_is_served(self, ws) -> None:
        app.dependency_overrides.clear()
        assert ws.http.get(BASE).status_code in (401, 403)


# ---------------------------------------------------------------------------
# The acceptance path
# ---------------------------------------------------------------------------


class TestRegisterVerifyEnable:
    def test_only_a_verified_enabled_domain_routes(self, ws) -> None:
        provider = _oidc(ws)
        pid = provider["id"]
        assert provider["tenant_id"] == TENANT
        assert provider["enabled"] is False and provider["member_count"] == 0
        assert ws.store.providers[pid]["created_by"] == OWNER

        domain = _add_domain(ws, pid, "Ada@Acme.com")
        assert domain["domain"] == "acme.com" and domain["verified"] is False
        assert domain["record_name"] == "_apiome-challenge.acme.com"
        token = domain["verification_token"]

        # Enabled but unverified: nothing routes.
        enabled = ws.http.patch(f"{BASE}/{pid}", json={"enabled": True}).json()
        assert enabled["enabled"] is True and enabled["routable"] is False
        assert _routable_slugs(ws) == []

        # No record yet.
        missing = ws.http.post(f"{BASE}/{pid}/domains/acme.com/verify").json()
        assert missing["check"]["status"] == "not-found" and missing["check"]["verified"] is False
        assert missing["provider"]["routable"] is False

        # The wrong value.
        ws.publish("acme.com", "not-the-token")
        wrong = ws.http.post(f"{BASE}/{pid}/domains/acme.com/verify").json()
        assert wrong["check"]["status"] == "mismatch"
        assert wrong["check"]["observed"] == ["not-the-token"]
        assert wrong["check"]["expected"] == token
        assert _routable_slugs(ws) == []

        # The token.
        ws.publish("acme.com", "v=spf1 -all", token)
        done = ws.http.post(f"{BASE}/{pid}/domains/acme.com/verify")
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["check"]["status"] == "verified" and body["check"]["verified"] is True
        assert body["provider"]["domains"][0]["verified"] is True
        assert body["provider"]["domains"][0]["verified_by"] == OWNER
        assert body["provider"]["routable"] is True
        assert _routable_slugs(ws) == ["acme-okta"]

    def test_disabling_stops_routing(self, ws) -> None:
        provider = _oidc(ws)
        token = _add_domain(ws, provider["id"])["verification_token"]
        ws.publish("acme.com", token)
        ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify")
        ws.http.patch(f"{BASE}/{provider['id']}", json={"enabled": True})
        assert _routable_slugs(ws) == ["acme-okta"]

        disabled = ws.http.patch(f"{BASE}/{provider['id']}", json={"enabled": False}).json()
        assert disabled["enabled"] is False and disabled["routable"] is False
        assert _routable_slugs(ws) == []

    def test_a_failed_lookup_is_could_not_check_and_verifies_nothing(self, ws) -> None:
        provider = _oidc(ws)
        token = _add_domain(ws, provider["id"])["verification_token"]
        # Even with the token in hand, a lookup reported as failed proves nothing.
        ws.dns["_apiome-challenge.acme.com"] = ("failed", [token], "SERVFAIL: no nameserver answered for this name.")
        response = ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify")
        assert response.status_code == 200
        body = response.json()
        assert body["check"]["status"] == "could-not-check" and body["check"]["verified"] is False
        assert body["check"]["observed"] == ["SERVFAIL: no nameserver answered for this name."]
        assert body["provider"]["domains"][0]["verified"] is False
        assert not [row for row in ws.audit if row["action"] == "sso.domain.verified"]

    def test_a_verified_domain_answers_without_a_lookup_or_a_budget(self, ws, monkeypatch) -> None:
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        provider = _oidc(ws)
        token = _add_domain(ws, provider["id"])["verification_token"]
        ws.publish("acme.com", token)
        assert ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify").json()["check"]["verified"] is True
        ws.dns.clear()  # the record may be taken down afterwards
        for _ in range(verification.VERIFY_ATTEMPTS_PER_HOUR + 2):
            again = ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify")
            assert again.status_code == 200 and again.json()["check"]["status"] == "verified"
        assert len([row for row in ws.audit if row["action"] == "sso.domain.verified"]) == 1

    def test_three_checks_an_hour_per_domain(self, ws, monkeypatch) -> None:
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        provider = _oidc(ws)
        _add_domain(ws, provider["id"])
        for _ in range(verification.VERIFY_ATTEMPTS_PER_HOUR):
            assert ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify").status_code == 200
        limited = ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify")
        assert limited.status_code == 429
        assert limited.json()["detail"]["error"] == "sso-verify-rate-limited"
        assert int(limited.headers["Retry-After"]) > 0

    def test_registers_a_saml_provider_from_pasted_xml(self, ws) -> None:
        response = ws.http.post(
            BASE,
            json={
                "protocol": "saml",
                "slug": "acme-saml",
                "display_name": "Acme SAML",
                "metadata_xml": SAML_METADATA,
                "email_source": "attribute",
                "email_attribute": "mail",
                "sp_private_key": SP_PRIVATE_KEY,
                "default_role_slug": "viewer",
            },
        )
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["saml_config"]["email_attribute"] == "mail"
        assert view["has_sp_private_key"] is True and view["default_role_slug"] == "viewer"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.parametrize("domain", ["gmail.com", "someone@outlook.com", "mail.yahoo.com"])
    def test_a_public_mailbox_domain_is_refused(self, ws, domain) -> None:
        provider = _oidc(ws)
        response = ws.http.post(f"{BASE}/{provider['id']}/domains", json={"domain": domain})
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-domain-public"
        assert ws.store.domains == {}

    def test_the_deny_list_is_configurable(self, ws, monkeypatch) -> None:
        monkeypatch.setattr(settings, "sso_public_domains", "webmail.test")
        provider = _oidc(ws)
        refused = ws.http.post(f"{BASE}/{provider['id']}/domains", json={"domain": "webmail.test"})
        assert refused.json()["detail"]["error"] == "sso-domain-public"

    def test_an_invalid_domain_is_refused(self, ws) -> None:
        provider = _oidc(ws)
        response = ws.http.post(f"{BASE}/{provider['id']}/domains", json={"domain": "*.acme.com"})
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-domain-invalid"

    def test_a_second_workspace_cannot_claim_a_verified_domain(self, ws) -> None:
        mine = _oidc(ws)
        token = _add_domain(ws, mine["id"])["verification_token"]
        ws.publish("acme.com", token)
        assert ws.http.post(f"{BASE}/{mine['id']}/domains/acme.com/verify").json()["check"]["verified"] is True

        ws.sign_in(OTHER_TENANT, OTHER_OWNER)
        theirs = _oidc(ws, slug="rival-okta")
        response = ws.http.post(f"{BASE}/{theirs['id']}/domains", json={"domain": "acme.com"})
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "sso-domain-claimed"

    def test_an_unverified_claim_locks_nobody_out_and_the_first_proof_wins(self, ws) -> None:
        """A squatter who lists ``acme.com`` and never proves it cannot stop its owner."""
        ws.sign_in(OTHER_TENANT, OTHER_OWNER)
        squatter = _oidc(ws, slug="rival-okta")
        _add_domain(ws, squatter["id"])

        ws.sign_in(TENANT, OWNER)
        mine = _oidc(ws)
        token = _add_domain(ws, mine["id"])["verification_token"]
        ws.publish("acme.com", token)
        assert ws.http.post(f"{BASE}/{mine['id']}/domains/acme.com/verify").json()["check"]["verified"] is True

        # The squatter's own token is not in DNS, and the domain is now held: no lookup, no luck.
        ws.sign_in(OTHER_TENANT, OTHER_OWNER)
        late = ws.http.post(f"{BASE}/{squatter['id']}/domains/acme.com/verify")
        assert late.status_code == 409
        assert late.json()["detail"]["error"] == "sso-domain-claimed"
        assert _routable_slugs(ws) == []  # neither provider is enabled; and only one could ever route

    def test_verifying_a_domain_the_provider_does_not_list_is_404(self, ws) -> None:
        provider = _oidc(ws)
        response = ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify")
        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "sso-domain-not-found"

    @pytest.mark.parametrize("role", ["owner", "wizard"])
    def test_the_default_role_must_be_a_role_of_the_workspace_and_not_owner(self, ws, role) -> None:
        code = "sso-default-role-invalid"
        response = ws.http.post(
            BASE,
            json={
                "protocol": "oidc",
                "slug": "acme-okta",
                "display_name": "Acme",
                "issuer": ISSUER,
                "client_id": "apiome",
                "client_secret": CLIENT_SECRET,
                "default_role_slug": role,
            },
        )
        assert response.status_code == 422 and response.json()["detail"]["error"] == code
        provider = _oidc(ws, default_role_slug="editor")
        patched = ws.http.patch(f"{BASE}/{provider['id']}", json={"default_role_slug": role})
        assert patched.status_code == 422 and patched.json()["detail"]["error"] == code

    def test_enabling_an_oidc_provider_without_its_secret_is_refused(self, ws) -> None:
        provider = _oidc(ws)
        assert ws.http.patch(f"{BASE}/{provider['id']}", json={"client_secret": None}).status_code == 200
        response = ws.http.patch(f"{BASE}/{provider['id']}", json={"enabled": True})
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-enable-incomplete"

    def test_a_workspace_cannot_be_named_in_the_body(self, ws) -> None:
        provider = _oidc(ws)
        assert ws.http.patch(f"{BASE}/{provider['id']}", json={"tenant_id": OTHER_TENANT}).status_code == 422
        assert ws.store.providers[provider["id"]]["tenant_id"] == TENANT


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_another_workspaces_provider_does_not_exist_here(self, ws) -> None:
        mine = _oidc(ws)
        _add_domain(ws, mine["id"])

        ws.sign_in(OTHER_TENANT, OTHER_OWNER)
        assert ws.http.get(BASE).json() == {"providers": []}
        pid = mine["id"]
        for method, path, body in [
            ("GET", f"{BASE}/{pid}", None),
            ("PATCH", f"{BASE}/{pid}", {"enabled": True}),
            ("DELETE", f"{BASE}/{pid}", None),
            ("POST", f"{BASE}/{pid}/domains", {"domain": "rival.com"}),
            ("DELETE", f"{BASE}/{pid}/domains/acme.com", None),
            ("POST", f"{BASE}/{pid}/domains/acme.com/verify", None),
        ]:
            response = ws.http.request(method, path, json=body)
            assert response.status_code == 404, (method, path)
            assert response.json()["detail"]["error"] == "sso-provider-not-found"
        assert pid in ws.store.providers and ws.store.providers[pid]["enabled"] is False

    def test_a_malformed_id_is_404_not_a_database_error(self, ws) -> None:
        assert ws.http.get(f"{BASE}/not-a-uuid").status_code == 404

    def test_the_tenant_in_the_url_does_not_choose_the_workspace(self, ws) -> None:
        mine = _oidc(ws)
        ws.sign_in(OTHER_TENANT, OTHER_OWNER)
        # Naming the first workspace's slug does not reach its providers.
        assert ws.http.get(f"/v1/tenants/acme/sso/providers/{mine['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Removing, and what is recorded
# ---------------------------------------------------------------------------


class TestRemoveAndAudit:
    def test_removing_reports_how_many_members_used_the_provider(self, ws) -> None:
        provider = _oidc(ws)
        ws.store.linked[(TENANT, "acme-okta")] = 4
        assert ws.http.get(f"{BASE}/{provider['id']}").json()["member_count"] == 4
        removed = ws.http.delete(f"{BASE}/{provider['id']}")
        assert removed.status_code == 200 and removed.json()["member_count"] == 4
        assert ws.store.providers == {}
        assert ws.http.get(f"{BASE}/{provider['id']}").status_code == 404

    def test_removing_a_domain_stops_it_and_frees_it(self, ws) -> None:
        provider = _oidc(ws)
        token = _add_domain(ws, provider["id"])["verification_token"]
        ws.publish("acme.com", token)
        ws.http.post(f"{BASE}/{provider['id']}/domains/acme.com/verify")
        removed = ws.http.delete(f"{BASE}/{provider['id']}/domains/acme.com")
        assert removed.status_code == 200 and removed.json()["domains"] == []
        assert ws.http.delete(f"{BASE}/{provider['id']}/domains/acme.com").status_code == 404

    def test_every_change_is_audited_without_a_secret(self, ws) -> None:
        provider = _oidc(ws)
        pid = provider["id"]
        token = _add_domain(ws, pid)["verification_token"]
        ws.publish("acme.com", token)
        ws.http.post(f"{BASE}/{pid}/domains/acme.com/verify")
        ws.http.patch(f"{BASE}/{pid}", json={"enabled": True, "client_secret": "rotated-secret-9Kd"})
        ws.http.patch(f"{BASE}/{pid}", json={})  # a no-op writes nothing
        ws.http.delete(f"{BASE}/{pid}/domains/acme.com")
        ws.http.delete(f"{BASE}/{pid}")

        assert [row["action"] for row in ws.audit] == [
            "sso.provider.created",
            "sso.provider.updated",  # domain added
            "sso.domain.verified",
            "sso.provider.updated",  # enabled + secret rotated
            "sso.provider.updated",  # domain removed
            "sso.provider.deleted",
        ]
        for row in ws.audit:
            assert row["tenant_id"] == TENANT and row["actor_id"] == OWNER
            assert row["source"] == "web" and row["target"] == "sso:acme-okta"
        assert ws.audit[1]["detail"] == {"domain_added": "acme.com"}
        assert ws.audit[2]["detail"]["method"] == "dns_txt"
        assert ws.audit[3]["detail"] == {"fields": ["client_secret", "enabled"], "enabled": True}
        rendered = json.dumps(ws.audit, default=str)
        assert CLIENT_SECRET not in rendered and "rotated-secret-9Kd" not in rendered

    def test_no_response_carries_a_secret(self, ws) -> None:
        provider = _oidc(ws)
        pid = provider["id"]
        _add_domain(ws, pid)
        stored = ws.store.providers[pid]
        needles = [CLIENT_SECRET, base64.b64encode(stored["client_secret_encrypted"]).decode()]
        bodies = [
            json.dumps(provider),
            ws.http.get(BASE).text,
            ws.http.get(f"{BASE}/{pid}").text,
            ws.http.patch(f"{BASE}/{pid}", json={"display_name": "Renamed"}).text,
            ws.http.post(f"{BASE}/{pid}/domains/acme.com/verify").text,
            ws.http.delete(f"{BASE}/{pid}").text,
        ]
        for body in bodies:
            assert not any(needle in body for needle in needles)
            assert "_encrypted" not in body

    def test_a_malformed_request_does_not_echo_its_secret(self, ws) -> None:
        response = ws.http.post(BASE, json={"protocol": "oidc", "client_secret": CLIENT_SECRET, "bogus": 1})
        assert response.status_code == 422
        assert CLIENT_SECRET not in response.text
