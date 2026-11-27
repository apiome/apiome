"""HTTP contract tests for the integrations list route — PFX-8.1 (#7298).

:mod:`app.pact_integrations_routes` with the store faked:

* it needs ``pacts:view``; a denial is a 403 before anything is read;
* the tenant comes from the credential, never the URL;
* the query reaches the store checked; each refusal is a 400 with its code (or FastAPI's 422 for an
  out-of-range page);
* ``filter=mine`` without a user is refused with a reason, not answered empty;
* the route stays off the catalogued Pact Broker surface.
"""

from __future__ import annotations

from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_compat import BROKER_PREFIX
from app.pact_integrations import (
    CODE_FILTER_INVALID,
    CODE_MINE_NEEDS_USER,
    CODE_SEARCH_INVALID,
    IntegrationFacts,
    build_page,
    parse_query,
)
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "22222222-2222-4222-8222-222222222222"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "session", "user_email": "a@example.test"}
_ROUTES = "app.pact_integrations_routes"
_URL = "/v1/tenants/acme/pact-integrations"


def _page() -> Any:
    facts = IntegrationFacts(
        provider="ledger-api",
        provider_name="Ledger API",
        consumer="billing-service",
        consumer_name="Billing Service",
        consumer_version="1.4.0",
        pact_version_sha="a" * 64,
        latest_success=False,
        latest_kind="native",
    )
    return build_page([facts], parse_query(), pacticipants=2, environments=1)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value=_USER) as enforce:
        yield enforce


def _deny(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=403, detail="Permission denied")


def test_the_list_needs_view_and_reads_the_callers_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_integrations", return_value=_page()) as read:
        response = client.get(_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["integrations"][0]["verdict"] == "failing"
    assert body["counts"]["failing"] == 1 and body["attention"]["failing"][0]["consumer"] == "billing-service"
    assert (body["pacticipants"], body["environments"]) == (2, 1)
    assert read.call_args.args[1] == _TENANT
    assert read.call_args.kwargs == {"user_id": _USER}
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)


def test_the_query_reaches_the_store_checked(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_integrations", return_value=_page()) as read:
        response = client.get(_URL, params={"q": " Ledger ", "filter": "stale", "limit": 10, "offset": 20})
    assert response.status_code == 200, response.text
    assert read.call_args.args[2] == parse_query(search="ledger", filter="stale", limit=10, offset=20)


def test_the_list_is_denied_without_view() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_deny),
        patch(f"{_ROUTES}.list_integrations") as read,
    ):
        response = client.get(_URL)
    assert response.status_code == 403
    read.assert_not_called()


@pytest.mark.parametrize(
    "params, code",
    [({"filter": "red"}, CODE_FILTER_INVALID), ({"q": "bad\x01"}, CODE_SEARCH_INVALID)],
)
def test_a_refused_query_is_a_400_with_its_code(allowed: MagicMock, params: Any, code: str) -> None:
    with patch(f"{_ROUTES}.list_integrations") as read:
        response = client.get(_URL, params=params)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == code
    read.assert_not_called()


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 1001}, {"q": "x" * 101}])
def test_an_out_of_range_parameter_is_refused_before_the_store(allowed: MagicMock, params: Any) -> None:
    with patch(f"{_ROUTES}.list_integrations") as read:
        response = client.get(_URL, params=params)
    assert response.status_code == 422
    read.assert_not_called()


def test_mine_without_a_user_is_refused_with_a_reason(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"tenant_id": _TENANT, "auth_method": "api_key"}
    with patch(f"{_ROUTES}.list_integrations") as read:
        response = client.get(_URL, params={"filter": "mine"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == CODE_MINE_NEEDS_USER
    read.assert_not_called()


def test_a_credential_without_a_tenant_is_forbidden(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"user_id": _USER}
    with patch(f"{_ROUTES}.list_integrations") as read:
        response = client.get(_URL)
    assert response.status_code == 403
    read.assert_not_called()


def test_the_route_stays_off_the_catalogued_broker_surface() -> None:
    paths = [route.path for route in app.routes if "/pact-integrations" in getattr(route, "path", "")]
    assert paths == ["/v1/tenants/{tenant_slug}/pact-integrations"]
    assert all(BROKER_PREFIX not in path for path in paths)
