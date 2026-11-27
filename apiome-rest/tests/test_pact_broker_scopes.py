"""Broker-compatible auth and the Pact API key scopes — PFX-4.2 (#6939).

Covers:

* the ``pact:read`` / ``pact:publish`` / ``pact:verify`` allowlist, route by route;
* a guard that every real route under ``/pact-broker`` and ``/pact-verifier`` has been classified,
  so a new route cannot silently become reachable (or unreachable) by a restricted key;
* that no pact scope admits anything outside the two mounts (bar the pacticipant registry's reads),
  and no other scope admits them;
* end to end through the app: bearer, basic and ``X-API-Key`` all authenticate; malformed basic
  auth, an unsupported scheme, a key of another tenant and a too-narrow scope are refused with the
  reason; and the ``pacts`` RBAC check still applies to a correctly scoped key.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth import (
    API_KEY_SCOPE_PACT_PUBLISH,
    API_KEY_SCOPE_PACT_READ,
    API_KEY_SCOPE_PACT_VERIFY,
    acceptable_scopes_for_request,
)
from app.main import app

READ = API_KEY_SCOPE_PACT_READ
PUBLISH = API_KEY_SCOPE_PACT_PUBLISH
VERIFY = API_KEY_SCOPE_PACT_VERIFY
PACT_SCOPES = {READ, PUBLISH, VERIFY}

PB = "/v1/tenants/acme/pact-broker"
PV = "/v1/tenants/acme/pact-verifier"
PAIR = f"{PB}/pacts/provider/Ledger/consumer/Billing"
SHA = f"{PAIR}/pact-version/abc123"

KEY = "sk_pact0000000000000000000000000000000000000"


def _scopes(method: str, path: str) -> Set[str]:
    """The pact scopes that admit ``method`` + ``path``."""
    return set(acceptable_scopes_for_request(method, path)) & PACT_SCOPES


# --------------------------------------------------------------------------- the allowlist


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        # Reads.
        ("GET", PB, {READ}),
        ("GET", f"{PB}/", {READ}),
        ("GET", f"{PB}/matrix", {READ}),
        ("GET", f"{PB}/can-i-deploy", {READ}),
        ("GET", f"{PAIR}/latest", {READ}),
        ("GET", f"{SHA}/verification-results/latest", {READ}),
        ("GET", f"{PB}/webhooks", {READ}),
        ("POST", f"{PB}/pacts/provider/Ledger/for-verification", {READ}),
        ("POST", f"{PB}/pacts/check", {READ}),
        ("GET", f"{PV}/providers/Ledger/provider-states", {READ}),
        ("POST", f"{PV}/providers/Ledger/provider-states/check", {READ}),
        # Consumer and deploy pipeline.
        ("POST", f"{PB}/contracts/publish", {PUBLISH}),
        ("PUT", f"{PAIR}/version/1.0.0", {PUBLISH}),
        ("PUT", f"{PB}/contracts/provider/Ledger/version/2.0.0", {PUBLISH}),
        ("POST", f"{PB}/pacticipants/Billing/versions/1.0.0/deployed-versions/environment/env-1", {PUBLISH}),
        ("POST", f"{PB}/pacticipants/Billing/versions/1.0.0/released-versions/environment/env-1", {PUBLISH}),
        ("PATCH", f"{PB}/deployed-versions/dv-1", {PUBLISH}),
        ("PATCH", f"{PB}/released-versions/rv-1", {PUBLISH}),
        # Both pipelines tag and branch their own version.
        ("PUT", f"{PB}/pacticipants/Billing/versions/1.0.0/tags/rc", {PUBLISH, VERIFY}),
        ("PUT", f"{PB}/pacticipants/Billing/branches/main/versions/1.0.0", {PUBLISH, VERIFY}),
        ("PUT", f"{PB}/pacticipants/Billing/branches/feat/x/versions/1.0.0", {PUBLISH, VERIFY}),
        # Provider pipeline.
        ("POST", f"{SHA}/verification-results", {VERIFY}),
        ("POST", f"{SHA}/metadata/e30/verification-results", {VERIFY}),
        ("POST", f"{SHA}/external-verification-results", {VERIFY}),
        ("POST", f"{PV}/pacts/provider/Ledger/verify", {VERIFY}),
        ("POST", f"{PV}/providers/Ledger/provider-states", {VERIFY}),
        ("PUT", f"{PV}/providers/Ledger/provider-states/state-1", {VERIFY}),
        # The pacticipant registry's reads (list-pacticipants, describe-version --latest).
        ("GET", "/v1/tenants/acme/pacticipants", {READ}),
        ("GET", "/v1/tenants/acme/pacticipants/billing/versions", {READ}),
        ("GET", "/v1/tenants/acme/pacticipant-labels", {READ}),
    ],
)
def test_the_pact_scope_allowlist(method: str, path: str, expected: Set[str]) -> None:
    assert _scopes(method, path) == expected


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", f"{PAIR}/version/1.0.0"),
        ("DELETE", f"{PB}/pacticipants/Billing"),
        ("DELETE", f"{PB}/pacticipants/Billing/versions/1.0.0"),
        ("POST", f"{PB}/webhooks"),
        ("PUT", f"{PB}/webhooks/wh-1"),
        ("DELETE", f"{PB}/webhooks/wh-1"),
        ("POST", f"{PB}/webhooks/execute"),
        ("POST", f"{PB}/webhooks/wh-1/execute"),
        ("POST", f"{PB}/environments"),
        ("PUT", f"{PB}/environments/env-1"),
        ("DELETE", f"{PB}/environments/env-1"),
        ("PUT", f"{PB}/pacticipants/Billing/labels/team-a"),
        ("DELETE", f"{PB}/integrations"),
        ("POST", f"{PB}/test/error"),
        ("DELETE", f"{PV}/providers/Ledger/provider-states/state-1"),
    ],
)
def test_deletes_webhooks_and_environments_stay_full_access(method: str, path: str) -> None:
    assert _scopes(method, path) == set()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/tenants/acme/pacticipants"),
        ("PATCH", "/v1/tenants/acme/pacticipants/billing"),
        ("DELETE", "/v1/tenants/acme/pacticipants/billing"),
        ("GET", "/v1/tenants/acme/pact-comparisons"),
        ("POST", "/v1/tenants/acme/pact-suites/provider/L/consumer/B/pact-version/abc"),
        ("POST", "/v1/tenants/acme/pact-retention"),
        ("GET", "/v1/tenants/acme/projects"),
        ("GET", "/v1/tenants/acme/pact-broker-elsewhere"),
        ("GET", "/registry/schema/acme/subjects"),
        ("POST", "/v1/diff/acme/classified"),
    ],
)
def test_pact_scopes_admit_nothing_else(method: str, path: str) -> None:
    assert _scopes(method, path) == set()


def test_no_other_scope_admits_the_pact_mounts() -> None:
    for method, path in [("GET", PB), ("POST", f"{PB}/contracts/publish"), ("POST", f"{PV}/pacts/provider/L/verify")]:
        assert set(acceptable_scopes_for_request(method, path)) <= PACT_SCOPES


# --------------------------------------------------------------------------- every route classified

#: Real (non-501) write routes a restricted key may not call — full access only. Reads are all
#: ``pact:read``; anything not here and not admitted by a pact scope fails the guard below.
_FULL_ACCESS_ONLY: Set[Tuple[str, str]] = {
    ("DELETE", "/pact-broker/environments/{uuid}"),
    ("POST", "/pact-broker/environments"),
    ("PUT", "/pact-broker/environments/{uuid}"),
    ("DELETE", "/pact-broker/pacticipants/{pacticipant}"),
    ("DELETE", "/pact-broker/pacticipants/{pacticipant}/labels/{label:path}"),
    ("PUT", "/pact-broker/pacticipants/{pacticipant}/labels/{label:path}"),
    ("DELETE", "/pact-broker/pacticipants/{pacticipant}/versions/{number}"),
    ("DELETE", "/pact-broker/webhooks/{uuid}"),
    ("POST", "/pact-broker/webhooks"),
    ("POST", "/pact-broker/webhooks/consumer/{consumer}"),
    ("POST", "/pact-broker/webhooks/execute"),
    ("POST", "/pact-broker/webhooks/provider/{provider}"),
    ("POST", "/pact-broker/webhooks/provider/{provider}/consumer/{consumer}"),
    ("POST", "/pact-broker/webhooks/{uuid}/execute"),
    ("PUT", "/pact-broker/webhooks/{uuid}"),
    ("POST", "/pact-broker/pacts/provider/{provider}/consumer/{consumer}/webhooks"),
    ("DELETE", "/pact-verifier/providers/{provider}/provider-states/{state_id}"),
}

_PREFIX = "/v1/tenants/{tenant_slug}"


def _concrete(template: str) -> str:
    """Fill a route template with sample values (``{x:path}`` gets two segments)."""
    filled = re.sub(r"\{[^}]+:path\}", "a/b", template)
    return re.sub(r"\{[^}]+\}", "x", filled)


def _real_pact_routes() -> List[Tuple[str, str]]:
    """Every (method, path-after-tenant) of a real route under the two mounts (501 routes excluded)."""
    rows: List[Tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(_PREFIX + "/pact-"):
            continue
        if route.endpoint.__name__ == "pact_broker_not_implemented":
            continue
        tail = route.path[len(_PREFIX):]
        if not tail.startswith(("/pact-broker", "/pact-verifier")):
            continue
        rows.extend((method, tail) for method in route.methods)
    return rows


def test_every_real_pact_route_is_classified() -> None:
    rows = _real_pact_routes()
    assert len(rows) > 40  # the whole surface was found
    unclassified = []
    for method, tail in rows:
        path = "/v1/tenants/acme" + _concrete(tail)
        scopes = _scopes(method, path)
        if method == "GET":
            assert scopes == {READ}, (method, tail)
        elif (method, tail) in _FULL_ACCESS_ONLY:
            assert scopes == set(), (method, tail)
        elif not scopes:
            unclassified.append((method, tail))
    assert unclassified == [], "classify these routes in app.auth or _FULL_ACCESS_ONLY"


def test_the_full_access_list_names_only_real_routes() -> None:
    assert _FULL_ACCESS_ONLY <= set(_real_pact_routes())


# --------------------------------------------------------------------------- end to end


class _Keys:
    """One API key whose tenant and scopes a test can change."""

    def __init__(self) -> None:
        self.scopes: List[str] = [READ]
        self.tenant_slug = "acme"
        self.seen: List[str] = []

    def validate_api_key(self, key: str) -> Optional[Dict[str, Any]]:
        self.seen.append(key)
        if key != KEY:
            return None
        return {
            "id": "key-1",
            "tenant_id": "tenant-1",
            "tenant_slug": self.tenant_slug,
            "tenant_name": "Acme",
            "created_by_user_id": "user-1",
            "scopes": list(self.scopes),
        }


@pytest.fixture
def keys() -> Iterator[_Keys]:
    """Patch key validation and the index route's RBAC; nothing reaches a database."""
    k = _Keys()
    rbac = MagicMock()
    rbac.user_has_permission.return_value = True
    with patch("app.auth.db.validate_api_key", k.validate_api_key), patch("app.pact_broker_routes.db", rbac):
        k.rbac = rbac  # type: ignore[attr-defined]
        yield k


client = TestClient(app)


def _basic(user: str, password: str) -> Dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": f"Bearer {KEY}"},
        _basic("apiome", KEY),
        _basic("", KEY),
        {"X-API-Key": KEY},
    ],
    ids=["bearer", "basic", "basic-no-username", "x-api-key"],
)
def test_bearer_basic_and_x_api_key_all_authenticate(keys: _Keys, headers: Dict[str, str]) -> None:
    resp = client.get(PB, headers=headers)
    assert resp.status_code == 200, resp.text
    assert "pb:publish-contracts" in resp.json()["_links"]
    assert keys.seen == [KEY]


def test_a_wrong_password_is_an_invalid_key(keys: _Keys) -> None:
    resp = client.get(PB, headers=_basic("apiome", "sk_wrong"))
    assert resp.status_code == 401
    assert "Invalid or expired API key" in resp.text


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic %%%not-base64",
        "Basic " + base64.b64encode(b"no-colon").decode(),
        "Basic " + base64.b64encode(f"{KEY}:".encode()).decode(),
    ],
    ids=["not-base64", "no-colon", "key-as-username"],
)
def test_malformed_basic_auth_is_refused_with_where_the_key_goes(keys: _Keys, authorization: str) -> None:
    resp = client.get(PB, headers={"Authorization": authorization})
    assert resp.status_code == 401
    assert "API key as the password" in resp.text
    assert KEY not in resp.text
    assert "Basic" in resp.headers["www-authenticate"]
    assert keys.seen == []


def test_an_unsupported_scheme_is_refused_with_the_reason(keys: _Keys) -> None:
    resp = client.get(PB, headers={"Authorization": f"Token {KEY}"})
    assert resp.status_code == 401
    assert "Unsupported Authorization scheme 'Token'" in resp.text
    assert KEY not in resp.text


def test_a_bare_header_is_refused_without_echoing_it(keys: _Keys) -> None:
    resp = client.get(PB, headers={"Authorization": KEY})
    assert resp.status_code == 401
    assert "no scheme" in resp.text
    assert KEY not in resp.text


def test_no_credential_is_refused(keys: _Keys) -> None:
    assert client.get(PB).status_code == 401


def test_another_tenants_key_is_refused(keys: _Keys) -> None:
    keys.tenant_slug = "other"
    resp = client.get(PB, headers=_basic("apiome", KEY))
    assert resp.status_code == 403
    assert "does not have access to this tenant" in resp.text


def test_a_ci_key_cannot_reach_the_broker(keys: _Keys) -> None:
    keys.scopes = ["lint:read"]
    resp = client.get(PB, headers={"Authorization": f"Bearer {KEY}"})
    assert resp.status_code == 403
    assert "required=pact:read" in resp.text


def test_a_read_only_key_cannot_publish(keys: _Keys) -> None:
    resp = client.post(f"{PB}/contracts/publish", headers={"Authorization": f"Bearer {KEY}"}, json={})
    assert resp.status_code == 403
    assert "required=pact:publish" in resp.text


def test_a_verifier_key_cannot_publish_a_pact(keys: _Keys) -> None:
    keys.scopes = [READ, VERIFY]
    resp = client.put(f"{PAIR}/version/1.0.0", headers=_basic("ci", KEY), json={})
    assert resp.status_code == 403
    assert "required=pact:publish" in resp.text


def test_a_pact_key_cannot_reach_the_rest_of_the_api(keys: _Keys) -> None:
    keys.scopes = [READ, PUBLISH, VERIFY]
    resp = client.post("/v1/tenants/acme/pacticipants", headers={"X-API-Key": KEY}, json={})
    assert resp.status_code == 403
    assert "full access" in resp.text


def test_a_scoped_key_still_needs_the_pacts_permission(keys: _Keys) -> None:
    keys.rbac.user_has_permission.return_value = False  # type: ignore[attr-defined]
    resp = client.get(PB, headers={"Authorization": f"Bearer {KEY}"})
    assert resp.status_code == 403
    assert "pacts:view" in resp.text
    keys.rbac.user_has_permission.assert_called_with("tenant-1", "user-1", "pacts", "view")  # type: ignore[attr-defined]


def test_an_unsupported_route_still_answers_501_to_a_read_key(keys: _Keys) -> None:
    resp = client.get(f"{PB}/metrics", headers=_basic("ci", KEY))
    assert resp.status_code == 501
