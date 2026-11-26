"""HTTP contract tests for the contract health routes — PFX-6.3 (#6955).

The routes of :mod:`app.pact_health_routes` with the store faked:

* both need ``pacts:view``; a denial is a 403 before anything is read;
* the tenant comes from the credential, never the URL;
* the query parameters reach the store; each refusal maps to its status and code (400, 404);
* the routes stay off the catalogued Pact Broker surface.
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
from app.pact_health import (
    CODE_PAIR_NOT_FOUND,
    CODE_STATE_INVALID,
    CODE_WINDOW_INVALID,
    BucketCounts,
    HealthError,
    PactHealthCounts,
    PactHealthOverview,
    PactPairHealth,
    PactPairHealthDetail,
    PairSignals,
    fuse,
    metrics_from,
)
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session", "user_email": "a@example.test"}
_ROUTES = "app.pact_health_routes"
_URL = "/v1/tenants/acme/pact-health"
_PAIR_URL = f"{_URL}/providers/ledger-api/consumers/billing-service"


def _pair() -> PactPairHealth:
    state, components, metrics = fuse(PairSignals(pact_version_sha="a" * 64, latest=None))
    return PactPairHealth(
        provider="ledger-api",
        provider_name="Ledger API",
        consumer="billing-service",
        consumer_name="Billing Service",
        pact_version_sha="a" * 64,
        consumer_version="1.4.0",
        state=state,
        components=components,
        metrics=metrics,
    )


def _overview() -> PactHealthOverview:
    return PactHealthOverview(
        window="30d",
        since="2026-10-28T00:00:00+00:00",
        until="2026-11-27T00:00:00+00:00",
        bucket_days=1,
        generated_at="2026-11-26T12:00:00+00:00",
        counts=PactHealthCounts(pairs=1, healthy=0, degraded=1, failing=0, unknown=0),
        totals=metrics_from(BucketCounts()),
        pairs=[_pair()],
    )


def _detail() -> PactPairHealthDetail:
    return PactPairHealthDetail(
        window="7d",
        since="2026-11-20T00:00:00+00:00",
        until="2026-11-27T00:00:00+00:00",
        bucket_days=1,
        generated_at="2026-11-26T12:00:00+00:00",
        pair=_pair(),
        trend=[],
    )


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


def _deny(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=403, detail="Permission denied")


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def test_the_overview_needs_view_and_reads_the_callers_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.workspace_health", return_value=_overview()) as read:
        response = client.get(_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["degraded"] == 1 and body["pairs"][0]["state"] == "degraded"
    assert [c["key"] for c in body["pairs"][0]["components"]][0] == "latest-verdict"
    assert read.call_args.args[1] == _TENANT
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)


def test_the_overview_passes_every_filter_to_the_store(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.workspace_health", return_value=_overview()) as read:
        response = client.get(
            _URL, params={"window": "7d", "provider": "ledger-api", "consumer": "web", "state": "failing"}
        )
    assert response.status_code == 200, response.text
    assert read.call_args.kwargs == {
        "window": "7d",
        "provider_ref": "ledger-api",
        "consumer_ref": "web",
        "state": "failing",
    }


def test_the_overview_is_denied_without_view() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_deny),
        patch(f"{_ROUTES}.workspace_health") as read,
    ):
        response = client.get(_URL)
    assert response.status_code == 403
    read.assert_not_called()


@pytest.mark.parametrize(
    "error, status",
    [
        (HealthError(CODE_WINDOW_INVALID, "window '1d' is not one of 7d, 30d, 90d"), 400),
        (HealthError(CODE_STATE_INVALID, "state 'red' is not one of …"), 400),
        (PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant 'nope'"), 404),
    ],
)
def test_overview_refusals_map_to_their_status_and_code(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.workspace_health", side_effect=error):
        response = client.get(_URL, params={"window": "1d"})
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == error.code  # type: ignore[attr-defined]


def test_an_over_long_parameter_is_refused_before_the_store(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.workspace_health") as read:
        response = client.get(_URL, params={"provider": "x" * 256})
    assert response.status_code == 422
    read.assert_not_called()


def test_a_credential_without_a_tenant_is_forbidden(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"user_id": "u"}
    with patch(f"{_ROUTES}.workspace_health") as read:
        response = client.get(_URL)
    assert response.status_code == 403
    read.assert_not_called()


# ---------------------------------------------------------------------------
# One pair
# ---------------------------------------------------------------------------


def test_the_pair_read_needs_view_and_passes_the_pair_and_window(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.pair_health", return_value=_detail()) as read:
        response = client.get(_PAIR_URL, params={"window": "7d"})
    assert response.status_code == 200, response.text
    assert response.json()["pair"]["consumer"] == "billing-service"
    assert read.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service")
    assert read.call_args.kwargs == {"window": "7d"}
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)


def test_the_pair_read_is_denied_without_view() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_deny),
        patch(f"{_ROUTES}.pair_health") as read,
    ):
        response = client.get(_PAIR_URL)
    assert response.status_code == 403
    read.assert_not_called()


@pytest.mark.parametrize(
    "error, status",
    [
        (HealthError(CODE_WINDOW_INVALID, "bad window"), 400),
        (HealthError(CODE_PAIR_NOT_FOUND, "'web' has published no pact for 'ledger-api'"), 404),
        (PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant"), 404),
    ],
)
def test_pair_refusals_map_to_their_status_and_code(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.pair_health", side_effect=error):
        response = client.get(_PAIR_URL)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == error.code  # type: ignore[attr-defined]


def test_the_routes_stay_off_the_catalogued_broker_surface() -> None:
    paths = [route.path for route in app.routes if "/pact-health" in getattr(route, "path", "")]
    assert len(paths) == 2
    assert all(BROKER_PREFIX not in path for path in paths)
