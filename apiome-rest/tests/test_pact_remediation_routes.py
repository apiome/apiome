"""HTTP contract tests for the verification settings and re-publish request routes — PFX-6.2 (#6954).

The routes of :mod:`app.pact_remediation_routes` with the store faked:

* reads need ``pacts:view`` and writes ``pacts:edit``; a denial is a 403 before anything is read or written;
* the tenant comes from the credential, never the URL;
* each refusal maps to its status and code (400, 404, 409, 422);
* bodies are validated (out of range, unknown cadence, unknown fields → 422);
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
from app.pact_remediation import (
    CODE_OVERRIDE_INVALID,
    CODE_OVERRIDE_NOT_FOUND,
    CODE_REQUEST_CLOSED,
    CODE_REQUEST_CURSOR_INVALID,
    CODE_REQUEST_NOT_FOUND,
    OverrideList,
    OverrideRecord,
    RemediationError,
    RepublishRequestPage,
    RepublishRequestRecord,
    default_settings,
)
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource
from app.verification_target import CODE_NOT_FOUND as TARGET_NOT_FOUND
from app.verification_target import TargetValidationError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session", "user_email": "a@example.test"}
_ROUTES = "app.pact_remediation_routes"
_SETTINGS_URL = "/v1/tenants/acme/pact-verification-settings"
_REQUESTS_URL = "/v1/tenants/acme/pact-republish-requests"
_REQUEST_ID = "44444444-4444-4444-8444-444444444444"
_SETTINGS_BODY = {
    "cadence": "nightly",
    "stale_threshold_hours": 48,
    "max_concurrent_runs": 3,
    "request_window_hours": 24,
    "republish_requests_enabled": True,
}


def _override() -> OverrideRecord:
    return OverrideRecord(
        id="o-1", provider="ledger-api", provider_name="Ledger API", cadence="hourly", target="ledger-staging"
    )


def _request(state: str = "acknowledged") -> RepublishRequestRecord:
    return RepublishRequestRecord(
        id=_REQUEST_ID,
        provider="ledger-api",
        provider_name="Ledger API",
        consumer="billing-service",
        consumer_name="Billing Service",
        pact_version_sha="a" * 64,
        consumer_version="1.4.0",
        state=state,
        threshold_hours=72,
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
# Settings
# ---------------------------------------------------------------------------


def test_reading_the_settings_needs_view_and_reads_the_callers_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_settings", return_value=default_settings()) as read:
        response = client.get(_SETTINGS_URL)
    assert response.status_code == 200, response.text
    assert response.json()["cadence"] == "manual-only" and response.json()["customised"] is False
    assert read.call_args.args[1] == _TENANT
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)


def test_saving_the_settings_needs_edit(allowed: MagicMock) -> None:
    saved = default_settings().model_copy(update={**_SETTINGS_BODY, "customised": True})
    with patch(f"{_ROUTES}.save_settings", return_value=saved) as save:
        response = client.put(_SETTINGS_URL, json=_SETTINGS_BODY)
    assert response.status_code == 200, response.text
    assert response.json()["stale_threshold_hours"] == 48
    assert save.call_args.args[1] == _TENANT and save.call_args.args[2].cadence == "nightly"
    assert save.call_args.kwargs["actor"].user_id == "test-user-id"
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.EDIT)


@pytest.mark.parametrize(
    "change",
    [
        {"cadence": "weekly"},
        {"stale_threshold_hours": 0},
        {"max_concurrent_runs": 50},
        {"request_window_hours": 10_000},
        {"colour": "blue"},
    ],
)
def test_settings_out_of_range_are_a_422_naming_the_field(allowed: MagicMock, change: dict) -> None:
    with patch(f"{_ROUTES}.save_settings") as save:
        response = client.put(_SETTINGS_URL, json={**_SETTINGS_BODY, **change})
    assert response.status_code == 422
    assert list(change)[0] in str(response.json()["detail"])
    save.assert_not_called()


def test_a_settings_field_left_out_is_a_422(allowed: MagicMock) -> None:
    body = dict(_SETTINGS_BODY)
    body.pop("cadence")
    assert client.put(_SETTINGS_URL, json=body).status_code == 422


def test_a_viewer_cannot_save_the_settings() -> None:
    with patch(f"{_ROUTES}.enforce_permission", side_effect=_deny), patch(f"{_ROUTES}.save_settings") as save:
        assert client.put(_SETTINGS_URL, json=_SETTINGS_BODY).status_code == 403
    save.assert_not_called()


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_listing_overrides_needs_view(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_overrides", return_value=OverrideList(overrides=[_override()])):
        response = client.get(_SETTINGS_URL + "/overrides")
    assert response.status_code == 200 and response.json()["overrides"][0]["target"] == "ledger-staging"
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)


def test_saving_an_override_needs_edit_on_the_provider(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.put_override", return_value=_override()) as put:
        response = client.put(
            _SETTINGS_URL + "/overrides", json={"provider": "ledger-api", "cadence": "hourly", "target_ref": "staging"}
        )
    assert response.status_code == 200, response.text
    assert put.call_args.args[1] == _TENANT and put.call_args.args[2].target_ref == "staging"
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.EDIT)
    assert allowed.call_args.kwargs["target"] == "ledger-api"


@pytest.mark.parametrize(
    "error,status,code",
    [
        (RemediationError(CODE_OVERRIDE_INVALID, "sets nothing"), 422, CODE_OVERRIDE_INVALID),
        (PacticipantValidationError(CODE_NOT_FOUND, "no such"), 404, CODE_NOT_FOUND),
        (TargetValidationError(TARGET_NOT_FOUND, "no such target"), 404, TARGET_NOT_FOUND),
    ],
)
def test_override_refusals_map_to_their_status(allowed: MagicMock, error: Exception, status: int, code: str) -> None:
    with patch(f"{_ROUTES}.put_override", side_effect=error):
        response = client.put(_SETTINGS_URL + "/overrides", json={"provider": "ledger-api", "cadence": "hourly"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_an_override_with_an_unknown_cadence_is_a_422(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.put_override") as put:
        response = client.put(_SETTINGS_URL + "/overrides", json={"provider": "ledger-api", "cadence": "often"})
    assert response.status_code == 422
    put.assert_not_called()


def test_removing_an_override_is_a_204_or_a_404(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.delete_override") as delete:
        assert client.delete(_SETTINGS_URL + "/overrides/o-1").status_code == 204
    assert delete.call_args.args[1:] == (_TENANT, "o-1")
    with patch(f"{_ROUTES}.delete_override", side_effect=RemediationError(CODE_OVERRIDE_NOT_FOUND, "gone")):
        response = client.delete(_SETTINGS_URL + "/overrides/o-1")
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_OVERRIDE_NOT_FOUND


# ---------------------------------------------------------------------------
# Re-publish requests
# ---------------------------------------------------------------------------


def test_listing_requests_passes_the_filters(allowed: MagicMock) -> None:
    page = RepublishRequestPage(requests=[_request()], next_cursor="7")
    with patch(f"{_ROUTES}.list_requests", return_value=page) as listed:
        response = client.get(
            _REQUESTS_URL, params={"provider": "ledger-api", "state": "open", "cursor": "9", "limit": 10}
        )
    assert response.status_code == 200, response.text
    assert response.json()["next_cursor"] == "7"
    assert listed.call_args.args[1] == _TENANT
    assert listed.call_args.kwargs == {
        "provider_ref": "ledger-api",
        "consumer_ref": None,
        "state": "open",
        "cursor": "9",
        "limit": 10,
    }


def test_an_unknown_state_filter_is_a_422(allowed: MagicMock) -> None:
    assert client.get(_REQUESTS_URL, params={"state": "lost"}).status_code == 422


def test_a_bad_cursor_is_a_400(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_requests", side_effect=RemediationError(CODE_REQUEST_CURSOR_INVALID, "bad")):
        response = client.get(_REQUESTS_URL, params={"cursor": "x"})
    assert response.status_code == 400 and response.json()["detail"]["code"] == CODE_REQUEST_CURSOR_INVALID


def test_reading_an_unknown_request_is_a_404(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_request", side_effect=RemediationError(CODE_REQUEST_NOT_FOUND, "no")):
        response = client.get(f"{_REQUESTS_URL}/{_REQUEST_ID}")
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_REQUEST_NOT_FOUND


def test_acknowledging_needs_edit_and_passes_the_note(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.acknowledge_request", return_value=_request()) as ack:
        response = client.post(f"{_REQUESTS_URL}/{_REQUEST_ID}/acknowledge", json={"note": "re-publishing Friday"})
    assert response.status_code == 200 and response.json()["state"] == "acknowledged"
    assert ack.call_args.args[1:4] == (_TENANT, _REQUEST_ID, "re-publishing Friday")
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.EDIT)


def test_acknowledging_a_closed_request_is_a_409(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.acknowledge_request", side_effect=RemediationError(CODE_REQUEST_CLOSED, "expired")):
        response = client.post(f"{_REQUESTS_URL}/{_REQUEST_ID}/acknowledge", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == CODE_REQUEST_CLOSED


def test_a_viewer_cannot_acknowledge() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_deny),
        patch(f"{_ROUTES}.acknowledge_request") as ack,
    ):
        assert client.post(f"{_REQUESTS_URL}/{_REQUEST_ID}/acknowledge", json={}).status_code == 403
    ack.assert_not_called()


def test_the_routes_stay_off_the_broker_surface() -> None:
    paths = [route.path for route in app.routes if "pact-verification-settings" in getattr(route, "path", "")]
    paths += [route.path for route in app.routes if "pact-republish-requests" in getattr(route, "path", "")]
    assert len(paths) == 8
    assert all(BROKER_PREFIX not in path for path in paths)
