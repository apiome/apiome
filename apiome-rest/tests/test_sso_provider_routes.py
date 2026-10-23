"""SSO provider admin routes and the login-time read path — EID-1.1 (#5011).

Route contract of :mod:`app.sso_provider_routes`, with the store replaced by an in-memory fake and
the IdP fetches replaced by canned documents (no network); the OLO-8.3 crypto runs for real
against a test key so sealing and unsealing are covered end to end.

* the admin surface is gated by the super-admin session (401 / 403);
* OIDC and SAML registration, domains, verification and enabling — and every refusal's stable
  ``sso-*`` code;
* **secrets never appear in any GET**: a sweep over *every* GET route the application serves,
  searching for each secret and its ciphertext in every rendering (the AGX-2.2 sweep pattern);
* the internal read path returns only enabled providers' verified domains, needs the service
  token, and drops a provider whose secret cannot be decrypted;
* every admin change lands in ``auth_events`` as an ``sso_provider`` row with no secret in it.
"""

from __future__ import annotations

import base64
import copy
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, List, Set
from urllib.parse import quote, quote_plus

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import sso_provider_routes as routes
from app.config import settings
from app.main import app
from app.sso_metadata import CODE_DOMAIN_CLAIMED, CODE_SLUG_TAKEN, SsoConfigError

client = TestClient(app)

BASE = "/v1/admin/sso/providers"
ISSUER = "https://idp.example.com/realms/acme"
CLIENT_SECRET = "oidc-client-secret-7Hq2Lw9Zp"
SP_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvsp-test-key-4fK9\n-----END PRIVATE KEY-----"
SERVICE_TOKEN = "internal-service-token-for-tests"
CERT = "MIIC" + "B" * 60

SAML_METADATA = f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="https://idp.example.com/saml">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>
      <ds:X509Certificate>{CERT}</ds:X509Certificate>
    </ds:X509Data></ds:KeyInfo></md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        Location="https://idp.example.com/saml/sso"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""


# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------


class FakeSsoStore:
    """An in-memory stand-in for :mod:`app.sso_provider_store` with the same read guarantees:
    admin reads never carry the ciphertext; only :meth:`list_routable_with_secrets` does."""

    def __init__(self) -> None:
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.domains: Dict[str, Dict[str, Any]] = {}

    def _public(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            k: copy.deepcopy(v) for k, v in row.items() if not k.endswith("_encrypted") and not k.endswith("_key_id")
        }
        out["has_client_secret"] = row.get("client_secret_key_id") is not None
        out["has_sp_private_key"] = row.get("sp_private_key_key_id") is not None
        out["tenant_name"] = None
        out["domains"] = self.list_domains(None, row["id"])
        return out

    def list_domains(self, _db, provider_id):
        return sorted(
            (dict(d) for d in self.domains.values() if d["provider_id"] == provider_id),
            key=lambda d: d["domain"],
        )

    def list_providers(self, _db):
        return [self._public(r) for r in self.providers.values()]

    def get_provider(self, _db, provider_id):
        row = self.providers.get(provider_id)
        return self._public(row) if row else None

    def create_provider(self, _db, values, *, actor):
        if any(r["slug"] == values["slug"] for r in self.providers.values()):
            raise SsoConfigError(CODE_SLUG_TAKEN, "taken")
        now = datetime.now(timezone.utc)
        row = {
            "id": str(uuid.uuid4()),
            "enabled": False,
            "client_secret_encrypted": None,
            "client_secret_key_id": None,
            "sp_private_key_encrypted": None,
            "sp_private_key_key_id": None,
            "tenant_id": None,
            "oidc_config": None,
            "saml_config": None,
            "preset": None,
            "default_role_slug": None,
            "created_by": actor,
            "updated_by": actor,
            "created_at": now,
            "updated_at": now,
            **copy.deepcopy(dict(values)),
        }
        self.providers[row["id"]] = row
        return self._public(row)

    def update_provider(self, _db, provider_id, updates, *, actor):
        row = self.providers.get(provider_id)
        if row is None:
            return None
        row.update(copy.deepcopy(dict(updates)))
        row["updated_by"] = actor
        return self._public(row)

    def delete_provider(self, _db, provider_id):
        row = self.providers.pop(provider_id, None)
        if row is None:
            return None
        public = self._public(row)
        for key in [k for k, d in self.domains.items() if d["provider_id"] == provider_id]:
            del self.domains[key]
        return public

    def add_domain(self, _db, provider_id, domain, *, token):
        if domain in self.domains:
            raise SsoConfigError(CODE_DOMAIN_CLAIMED, "claimed")
        self.domains[domain] = {
            "id": str(uuid.uuid4()),
            "provider_id": provider_id,
            "domain": domain,
            "verification_token": token,
            "verified_at": None,
            "verified_by": None,
            "created_at": datetime.now(timezone.utc),
        }
        return dict(self.domains[domain])

    def verify_domain(self, _db, provider_id, domain, *, actor):
        row = self.domains.get(domain)
        if row is None or row["provider_id"] != provider_id:
            return None
        row["verified_at"] = row["verified_at"] or datetime.now(timezone.utc)
        row["verified_by"] = row["verified_by"] or actor
        return dict(row)

    def remove_domain(self, _db, provider_id, domain):
        row = self.domains.get(domain)
        if row is None or row["provider_id"] != provider_id:
            return False
        del self.domains[domain]
        return True

    def list_routable_with_secrets(self, _db):
        out = []
        for row in self.providers.values():
            verified = sorted(
                d["domain"]
                for d in self.domains.values()
                if d["provider_id"] == row["id"] and d["verified_at"] is not None
            )
            if row["enabled"] and verified:
                out.append({**copy.deepcopy(row), "domains": verified})
        return out


def _mint_admin_token(key: str) -> str:
    payload = {"v": 1, "sub": "admin", "iat": 0, "exp": 9_999_999_999_999}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(key.encode(), encoded.encode(), sha256).digest()).rstrip(b"=").decode()
    return f"{encoded}.{sig}"


@pytest.fixture
def admin(monkeypatch):
    """Admin session header, a real KEK, a fake store, canned IdP fetches and captured audit rows."""
    monkeypatch.setattr(settings, "admin_session_secret", "sso-admin-secret")
    monkeypatch.setattr(settings, "admin_password", None)
    monkeypatch.setattr(settings, "auth_config_enc_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    monkeypatch.setattr(settings, "internal_service_token", SERVICE_TOKEN)

    fake = FakeSsoStore()
    monkeypatch.setattr(routes, "store", fake)

    async def fake_discover(issuer, *, client_id):
        if issuer.rstrip("/") != ISSUER:
            raise SsoConfigError("sso-discovery-mismatch", "mismatch")
        if not (client_id or "").strip():
            raise SsoConfigError("sso-enable-incomplete", "client id")
        return {
            "issuer": ISSUER,
            "oidc_config": {
                "client_id": client_id,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/certs",
                "userinfo_endpoint": None,
                "scopes": ["openid", "email", "profile"],
                "pkce": True,
                "token_endpoint_authentication": "client_secret_basic",
            },
        }

    async def fake_fetch_metadata(url):
        from app.sso_metadata import parse_saml_metadata

        return parse_saml_metadata(SAML_METADATA)

    monkeypatch.setattr(routes, "discover_oidc", fake_discover)
    monkeypatch.setattr(routes, "fetch_saml_metadata", fake_fetch_metadata)

    audit: List[Dict[str, Any]] = []
    monkeypatch.setattr(routes.db, "write_auth_event", lambda **kw: audit.append(kw))

    headers = {"X-Admin-Session": _mint_admin_token("sso-admin-secret")}
    return {"headers": headers, "store": fake, "audit": audit}


def _create_oidc(headers, **overrides) -> Dict[str, Any]:
    body = {
        "protocol": "oidc",
        "slug": "acme-okta",
        "display_name": "Acme Okta",
        "issuer": ISSUER,
        "client_id": "apiome",
        "client_secret": CLIENT_SECRET,
        **overrides,
    }
    response = client.post(BASE, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _create_saml(headers, **overrides) -> Dict[str, Any]:
    body = {
        "protocol": "saml",
        "slug": "acme-saml",
        "display_name": "Acme SAML",
        "metadata_url": "https://idp.example.com/saml/metadata",
        "email_source": "nameid",
        "sp_private_key": SP_PRIVATE_KEY,
        **overrides,
    }
    response = client.post(BASE, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _verified(headers, provider_id: str, domain: str) -> Dict[str, Any]:
    assert client.post(f"{BASE}/{provider_id}/domains", json={"domain": domain}, headers=headers).status_code == 201
    response = client.post(f"{BASE}/{provider_id}/domains/{domain}/verify", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class TestGate:
    def test_no_session_is_401(self, admin) -> None:
        assert client.get(BASE).status_code == 401

    def test_forged_session_is_403(self, admin) -> None:
        assert client.get(BASE, headers={"X-Admin-Session": _mint_admin_token("wrong")}).status_code == 403

    def test_internal_path_needs_the_service_token(self, admin) -> None:
        assert client.get("/v1/internal/sso/providers/resolved").status_code == 401
        assert (
            client.get("/v1/internal/sso/providers/resolved", headers={"X-Internal-Service-Token": "nope"}).status_code
            == 403
        )

    def test_internal_path_is_closed_without_a_configured_token(self, admin, monkeypatch) -> None:
        monkeypatch.setattr(settings, "internal_service_token", "")
        response = client.get("/v1/internal/sso/providers/resolved", headers={"X-Internal-Service-Token": "x"})
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_an_oidc_provider_disabled_with_a_sealed_secret(self, admin) -> None:
        view = _create_oidc(admin["headers"])
        assert view["protocol"] == "oidc"
        assert view["plugin_provider_id"] == "sso-acme-okta"
        assert view["identity_kind"] == "sso:acme-okta"
        assert view["issuer"] == ISSUER
        assert view["oidc_config"]["jwks_uri"] == f"{ISSUER}/certs"
        assert view["has_client_secret"] is True
        assert view["enabled"] is False and view["routable"] is False
        stored = admin["store"].providers[view["id"]]
        assert isinstance(stored["client_secret_encrypted"], bytes)
        assert CLIENT_SECRET.encode() not in stored["client_secret_encrypted"]

    def test_registers_a_saml_provider_from_metadata(self, admin) -> None:
        view = _create_saml(admin["headers"])
        assert view["issuer"] == "https://idp.example.com/saml"
        assert view["saml_config"]["sso_url"] == "https://idp.example.com/saml/sso"
        assert view["saml_config"]["certificates"] == [CERT]
        assert view["saml_config"]["email_source"] == "nameid"
        assert view["has_sp_private_key"] is True

    def test_registers_a_saml_provider_from_pasted_xml(self, admin) -> None:
        view = _create_saml(admin["headers"], metadata_url=None, metadata_xml=SAML_METADATA, sp_private_key=None)
        assert view["saml_config"]["metadata_url"] is None
        assert view["has_sp_private_key"] is False

    def test_refuses_an_artifact_only_saml_idp(self, admin) -> None:
        artifact = SAML_METADATA.replace("HTTP-Redirect", "HTTP-Artifact")
        response = client.post(
            BASE,
            json={
                "protocol": "saml",
                "slug": "acme-art",
                "display_name": "Artifact",
                "metadata_xml": artifact,
                "email_source": "nameid",
            },
            headers=admin["headers"],
        )
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-binding-unsupported"

    @pytest.mark.parametrize(
        "overrides,code",
        [
            ({"slug": "Bad Slug"}, "sso-slug-invalid"),
            ({"slug": "okta"}, "sso-slug-reserved"),
            ({"issuer": "https://other.example.com"}, "sso-discovery-mismatch"),
            ({"client_secret": ""}, "sso-enable-incomplete"),
            ({"protocol": "ldap"}, "sso-protocol-invalid"),
        ],
    )
    def test_refusals_carry_stable_codes(self, admin, overrides, code) -> None:
        body = {
            "protocol": "oidc",
            "slug": "acme-okta",
            "display_name": "Acme",
            "issuer": ISSUER,
            "client_id": "apiome",
            "client_secret": CLIENT_SECRET,
            **overrides,
        }
        response = client.post(BASE, json=body, headers=admin["headers"])
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == code

    def test_refuses_a_taken_slug(self, admin) -> None:
        _create_oidc(admin["headers"])
        response = client.post(
            BASE,
            json={
                "protocol": "oidc",
                "slug": "acme-okta",
                "display_name": "x",
                "issuer": ISSUER,
                "client_id": "a",
                "client_secret": "s",
            },
            headers=admin["headers"],
        )
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-slug-taken"

    def test_refuses_a_secret_when_encryption_is_unconfigured(self, admin, monkeypatch) -> None:
        monkeypatch.setattr(settings, "auth_config_enc_key", None)
        response = client.post(
            BASE,
            json={
                "protocol": "oidc",
                "slug": "acme-okta",
                "display_name": "x",
                "issuer": ISSUER,
                "client_id": "a",
                "client_secret": "s",
            },
            headers=admin["headers"],
        )
        assert response.status_code == 503
        assert admin["store"].providers == {}


# ---------------------------------------------------------------------------
# Domains, enabling and routing
# ---------------------------------------------------------------------------


class TestDomainsAndEnabling:
    def test_a_domain_routes_only_once_verified_and_enabled(self, admin) -> None:
        headers = admin["headers"]
        provider = _create_oidc(headers)
        pid = provider["id"]

        added = client.post(f"{BASE}/{pid}/domains", json={"domain": "Ada@Acme.com"}, headers=headers).json()
        assert added["domains"][0]["domain"] == "acme.com"
        assert added["domains"][0]["verified"] is False
        assert added["domains"][0]["verification_token"]

        enabled = client.patch(f"{BASE}/{pid}", json={"enabled": True}, headers=headers).json()
        assert enabled["enabled"] is True and enabled["routable"] is False

        verified = client.post(f"{BASE}/{pid}/domains/acme.com/verify", headers=headers).json()
        assert verified["domains"][0]["verified"] is True
        assert verified["domains"][0]["verified_by"] == "admin"
        assert verified["routable"] is True

    def test_a_domain_belongs_to_one_provider(self, admin) -> None:
        headers = admin["headers"]
        first = _create_oidc(headers)
        second = _create_saml(headers)
        assert (
            client.post(f"{BASE}/{first['id']}/domains", json={"domain": "acme.com"}, headers=headers).status_code
            == 201
        )
        response = client.post(f"{BASE}/{second['id']}/domains", json={"domain": "acme.com"}, headers=headers)
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "sso-domain-claimed"

    def test_refuses_an_invalid_domain(self, admin) -> None:
        provider = _create_oidc(admin["headers"])
        response = client.post(
            f"{BASE}/{provider['id']}/domains", json={"domain": "*.acme.com"}, headers=admin["headers"]
        )
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-domain-invalid"

    def test_verifying_an_unknown_domain_is_404(self, admin) -> None:
        provider = _create_oidc(admin["headers"])
        response = client.post(f"{BASE}/{provider['id']}/domains/acme.com/verify", headers=admin["headers"])
        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "sso-domain-not-found"

    def test_removing_a_domain_stops_routing(self, admin) -> None:
        headers = admin["headers"]
        provider = _create_oidc(headers)
        _verified(headers, provider["id"], "acme.com")
        client.patch(f"{BASE}/{provider['id']}", json={"enabled": True}, headers=headers)
        removed = client.delete(f"{BASE}/{provider['id']}/domains/acme.com", headers=headers).json()
        assert removed["domains"] == [] and removed["routable"] is False

    def test_an_oidc_provider_without_a_secret_cannot_be_enabled(self, admin) -> None:
        headers = admin["headers"]
        provider = _create_oidc(headers)
        assert (
            client.patch(f"{BASE}/{provider['id']}", json={"client_secret": None}, headers=headers).json()[
                "has_client_secret"
            ]
            is False
        )
        response = client.patch(f"{BASE}/{provider['id']}", json={"enabled": True}, headers=headers)
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "sso-enable-incomplete"

    def test_an_omitted_secret_is_kept(self, admin) -> None:
        headers = admin["headers"]
        provider = _create_oidc(headers)
        before = admin["store"].providers[provider["id"]]["client_secret_encrypted"]
        client.patch(f"{BASE}/{provider['id']}", json={"display_name": "Renamed"}, headers=headers)
        assert admin["store"].providers[provider["id"]]["client_secret_encrypted"] == before

    def test_changing_the_saml_email_source_keeps_the_metadata(self, admin) -> None:
        headers = admin["headers"]
        provider = _create_saml(headers)
        updated = client.patch(
            f"{BASE}/{provider['id']}", json={"email_source": "attribute", "email_attribute": "mail"}, headers=headers
        ).json()
        assert updated["saml_config"]["email_attribute"] == "mail"
        assert updated["saml_config"]["certificates"] == [CERT]

    def test_unknown_provider_is_404(self, admin) -> None:
        missing = str(uuid.uuid4())
        assert client.get(f"{BASE}/{missing}", headers=admin["headers"]).status_code == 404
        assert client.delete(f"{BASE}/{missing}", headers=admin["headers"]).status_code == 404

    def test_delete_removes_the_provider(self, admin) -> None:
        provider = _create_oidc(admin["headers"])
        assert client.delete(f"{BASE}/{provider['id']}", headers=admin["headers"]).status_code == 200
        assert client.get(BASE, headers=admin["headers"]).json()["providers"] == []


# ---------------------------------------------------------------------------
# Internal read path
# ---------------------------------------------------------------------------


class TestResolved:
    def _resolved(self) -> Dict[str, Any]:
        response = client.get(
            "/v1/internal/sso/providers/resolved", headers={"X-Internal-Service-Token": SERVICE_TOKEN}
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_returns_only_enabled_providers_with_verified_domains(self, admin) -> None:
        headers = admin["headers"]
        oidc = _create_oidc(headers)
        saml = _create_saml(headers)
        _verified(headers, oidc["id"], "acme.com")
        client.post(f"{BASE}/{saml['id']}/domains", json={"domain": "unverified.com"}, headers=headers)
        client.patch(f"{BASE}/{saml['id']}", json={"enabled": True}, headers=headers)

        assert self._resolved()["providers"] == []  # verified but disabled; enabled but unverified

        client.patch(f"{BASE}/{oidc['id']}", json={"enabled": True}, headers=headers)
        resolved = self._resolved()
        assert [p["slug"] for p in resolved["providers"]] == ["acme-okta"]
        only = resolved["providers"][0]
        assert only["domains"] == ["acme.com"]
        assert only["client_secret"] == CLIENT_SECRET
        assert only["plugin_provider_id"] == "sso-acme-okta"

    def test_unseals_the_saml_sp_key(self, admin) -> None:
        headers = admin["headers"]
        saml = _create_saml(headers)
        _verified(headers, saml["id"], "acme.com")
        client.patch(f"{BASE}/{saml['id']}", json={"enabled": True}, headers=headers)
        provider = self._resolved()["providers"][0]
        assert provider["sp_private_key"] == SP_PRIVATE_KEY
        assert provider["client_secret"] is None

    def test_the_fingerprint_changes_with_the_secret_but_never_reveals_it(self, admin) -> None:
        headers = admin["headers"]
        oidc = _create_oidc(headers)
        _verified(headers, oidc["id"], "acme.com")
        client.patch(f"{BASE}/{oidc['id']}", json={"enabled": True}, headers=headers)
        before = self._resolved()["fingerprint"]
        client.patch(f"{BASE}/{oidc['id']}", json={"client_secret": "rotated-secret-xyz"}, headers=headers)
        after = self._resolved()["fingerprint"]
        assert before != after
        assert CLIENT_SECRET not in before and "rotated-secret-xyz" not in after

    def test_drops_a_provider_whose_secret_cannot_be_decrypted(self, admin, monkeypatch) -> None:
        headers = admin["headers"]
        oidc = _create_oidc(headers)
        _verified(headers, oidc["id"], "acme.com")
        client.patch(f"{BASE}/{oidc['id']}", json={"enabled": True}, headers=headers)
        # The key that sealed it is rotated away.
        monkeypatch.setattr(settings, "auth_config_enc_key", base64.b64encode(os.urandom(32)).decode())
        assert self._resolved()["providers"] == []

    def test_a_database_fault_is_503(self, admin, monkeypatch) -> None:
        def boom(_db):
            raise RuntimeError("down")

        monkeypatch.setattr(admin["store"], "list_routable_with_secrets", boom)
        response = client.get(
            "/v1/internal/sso/providers/resolved", headers={"X-Internal-Service-Token": SERVICE_TOKEN}
        )
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_every_change_is_an_sso_provider_event_without_a_secret(self, admin) -> None:
        headers = admin["headers"]
        provider = _create_oidc(headers)
        _verified(headers, provider["id"], "acme.com")
        client.patch(
            f"{BASE}/{provider['id']}", json={"enabled": True, "client_secret": "next-secret-abc"}, headers=headers
        )
        client.delete(f"{BASE}/{provider['id']}/domains/acme.com", headers=headers)
        client.delete(f"{BASE}/{provider['id']}", headers=headers)

        actions = [row["detail"]["action"] for row in admin["audit"]]
        assert actions == ["created", "domain_added", "domain_verified", "updated", "domain_removed", "deleted"]
        assert all(row["event_type"] == "sso_provider" for row in admin["audit"])
        assert all(row["provider"] == "sso:acme-okta" for row in admin["audit"])
        assert all(row["detail"]["actor_kind"] == "admin" for row in admin["audit"])
        updated = next(row for row in admin["audit"] if row["detail"]["action"] == "updated")
        assert updated["detail"]["fields"] == ["client_secret", "enabled"]
        rendered = json.dumps(admin["audit"], default=str)
        assert CLIENT_SECRET not in rendered and "next-secret-abc" not in rendered


# ---------------------------------------------------------------------------
# Secret sweep (AGX-2.2 pattern)
# ---------------------------------------------------------------------------


def _forms(secret: str) -> Set[str]:
    """Every rendering of a secret a response could plausibly carry."""
    raw = secret.encode("utf-8")
    return {
        secret,
        quote(secret, safe=""),
        quote_plus(secret),
        json.dumps(secret)[1:-1],
        base64.b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode(),
        raw.hex(),
    }


def _blob_forms(blob: bytes) -> Set[str]:
    return {base64.b64encode(blob).decode(), base64.urlsafe_b64encode(blob).decode(), blob.hex(), "\\x" + blob.hex()}


def _fill(path: str, ids: Dict[str, str]) -> str:
    def value(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name == "domain":
            return "acme.com"
        if "tenant" in name:
            return "acme"
        if "id" in name:
            return ids["provider_id"]
        return "x"

    return re.sub(r"\{(\w+)(?::\w+)?\}", value, path)


#: The one route whose job is to return decrypted secrets — to apiome-ui's server, behind the
#: service token. Swept separately below: it must refuse every caller without that token.
_SECRET_BEARING = {"/v1/internal/sso/providers/resolved"}


def test_no_get_route_returns_an_sso_secret_or_its_ciphertext(admin) -> None:
    headers = admin["headers"]
    oidc = _create_oidc(headers)
    saml = _create_saml(headers)
    for provider in (oidc, saml):
        _verified(headers, provider["id"], f"{provider['slug']}.example.com")
        client.patch(f"{BASE}/{provider['id']}", json={"enabled": True}, headers=headers)

    needles = _forms(CLIENT_SECRET) | _forms(SP_PRIVATE_KEY)
    for stored in admin["store"].providers.values():
        for column in ("client_secret_encrypted", "sp_private_key_encrypted"):
            if stored[column]:
                needles |= _blob_forms(stored[column])

    routes_checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in (route.methods or set()):
            continue
        if route.path in _SECRET_BEARING:
            continue
        for provider in (oidc, saml):
            response = client.get(_fill(route.path, {"provider_id": provider["id"]}), headers=headers)
            body = response.text
            leaks = [n for n in needles if n and n in body]
            assert not leaks, f"GET {route.path} returned SSO secret material"
        routes_checked += 1
    assert routes_checked > 100  # the sweep really walked the application

    # And the secret-bearing route refuses anyone without the service token — including the admin.
    for path in _SECRET_BEARING:
        assert client.get(path, headers=headers).status_code in (401, 403)


def test_the_openapi_schema_carries_no_secret(admin) -> None:
    _create_oidc(admin["headers"])
    schema = json.dumps(app.openapi())
    assert CLIENT_SECRET not in schema
