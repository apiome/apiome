"""Route tests for the scheduled-verification endpoints — CTG-4.4 (#4501).

Authentication is overridden and the store layer is patched on the routes module, so these tests
assert the HTTP contract only: which permission each route enforces, the statuses each refusal
maps to, the filters the list read forwards, and that the run-history read is gated on *evidence*
rather than on target configuration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.verification_schedule import (
    ALERT_STATE_ALERTING,
    CODE_CADENCE_INVALID,
    CODE_NOT_FOUND,
    CODE_PAIR_TAKEN,
    CODE_SLUG_TAKEN,
    CODE_TARGET_UNKNOWN,
    STATUS_FAILED,
    STATUS_PASSED,
    ScheduleValidationError,
    VerificationScheduleRecord,
    VerificationScheduleRunRecord,
)

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "auth_method": "jwt",
}
_TENANT_SLUG = "acme"
_BASE = f"/v1/tenants/{_TENANT_SLUG}/verification-schedules"
_SCHEDULE = "77777777-7777-4777-8777-777777777777"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request; permission enforcement is asserted per test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _record(**overrides) -> VerificationScheduleRecord:
    """A stored schedule record."""
    fields = {
        "id": _SCHEDULE,
        "tenant_id": _MOCK_AUTH["tenant_id"],
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "version_ref": "project/petstore/1.0.0",
        "target_id": "22222222-2222-4222-8222-222222222222",
        "target_slug": "staging",
        "cadence_seconds": 3600,
        "enabled": True,
        "alert_on_recovery": True,
        "last_status": STATUS_PASSED,
        "last_success_at": _NOW,
        "freshness_seconds": 120,
    }
    fields.update(overrides)
    return VerificationScheduleRecord(**fields)


def _run(**overrides) -> VerificationScheduleRunRecord:
    """A stored history row."""
    fields = {
        "id": "88888888-8888-4888-8888-888888888888",
        "tenant_id": _MOCK_AUTH["tenant_id"],
        "schedule_id": _SCHEDULE,
        "status": STATUS_FAILED,
        "alerted": True,
        "alert_reason": "transition",
        "drift_count": 3,
    }
    fields.update(overrides)
    return VerificationScheduleRunRecord(**fields)


def _payload(**overrides) -> Dict[str, Any]:
    """A create body."""
    body = {
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "version_ref": "project/petstore/1.0.0",
        "target_ref": "staging",
        "cadence": "hourly",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------------------------


def test_list_requires_target_view():
    """Reading what is watched is target configuration, which an Editor may see."""
    with patch(
        "app.verification_schedule_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.verification_schedule_routes.list_schedules", return_value=[]
    ):
        assert client.get(_BASE).status_code == 200
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_TARGETS, Action.VIEW)


def test_create_requires_target_create():
    """Deciding where and how often a deployment is hit is not an Editor's call."""
    with patch(
        "app.verification_schedule_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.verification_schedule_routes.create_schedule", return_value=_record()
    ):
        assert client.post(_BASE, json=_payload()).status_code == 201
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_TARGETS, Action.CREATE)


def test_patch_requires_target_edit():
    """Retuning a cadence is the same class of decision as defining the target."""
    with patch(
        "app.verification_schedule_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.verification_schedule_routes.update_schedule", return_value=_record()
    ):
        assert client.patch(f"{_BASE}/petstore-staging", json={"cadence": "daily"}).status_code == 200
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_TARGETS, Action.EDIT)


def test_delete_requires_target_delete_and_answers_204():
    """Retirement is a soft delete, so there is nothing to return."""
    with patch(
        "app.verification_schedule_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.verification_schedule_routes.delete_schedule", return_value=True
    ):
        assert client.delete(f"{_BASE}/petstore-staging").status_code == 204
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_TARGETS, Action.DELETE)


def test_run_history_requires_evidence_view():
    """A verification history *is* evidence, so it is gated on the evidence resource."""
    with patch(
        "app.verification_schedule_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.verification_schedule_routes.get_schedule", return_value=_record()
    ), patch(
        "app.verification_schedule_routes.list_runs", return_value=[_run()]
    ):
        response = client.get(f"{_BASE}/petstore-staging/runs")
    assert response.status_code == 200
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    assert response.json()[0]["alert_reason"] == "transition"


def test_a_denied_permission_is_a_403():
    """The enforcement call is what refuses; the route does not second-guess it."""
    with patch(
        "app.verification_schedule_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="nope"),
    ):
        assert client.get(_BASE).status_code == 403


# ---------------------------------------------------------------------------------------------
# The reads
# ---------------------------------------------------------------------------------------------


def test_list_forwards_its_filters_and_returns_freshness():
    """The CTG-4.5 lookup: filter by version, read the freshness off the record."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.list_schedules", return_value=[_record()]
    ) as listed:
        response = client.get(
            _BASE,
            params={
                "version_ref": "project/petstore/1.0.0",
                "target_id": "22222222-2222-4222-8222-222222222222",
                "enabled": "true",
                "limit": 5,
            },
        )
    assert response.status_code == 200
    kwargs = listed.call_args.kwargs
    assert kwargs["version_ref"] == "project/petstore/1.0.0"
    assert kwargs["enabled"] is True
    assert kwargs["limit"] == 5
    assert response.json()[0]["freshness_seconds"] == 120


def test_a_never_verified_schedule_reports_unknown_freshness():
    """Null means unknown; a gate must not read it as fresh."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.list_schedules",
        return_value=[_record(last_status=None, last_success_at=None, freshness_seconds=None)],
    ):
        body = client.get(_BASE).json()
    assert body[0]["freshness_seconds"] is None
    assert body[0]["last_success_at"] is None


def test_read_exposes_the_alert_state():
    """`alerting` is what makes a repeated failure quiet, so it is visible."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.get_schedule",
        return_value=_record(alert_state=ALERT_STATE_ALERTING),
    ):
        body = client.get(f"{_BASE}/petstore-staging").json()
    assert body["alert_state"] == ALERT_STATE_ALERTING


def test_run_history_rejects_an_unknown_status_filter():
    """A typo'd filter must not silently return everything."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"):
        response = client.get(f"{_BASE}/petstore-staging/runs", params={"status": "green"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "schedule-run-status-invalid"


# ---------------------------------------------------------------------------------------------
# Refusal statuses
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,status",
    [
        (CODE_NOT_FOUND, 404),
        (CODE_TARGET_UNKNOWN, 404),
        (CODE_SLUG_TAKEN, 409),
        (CODE_PAIR_TAKEN, 409),
        (CODE_CADENCE_INVALID, 400),
    ],
)
def test_create_maps_each_refusal_to_its_status(code, status):
    """A caller can branch on the status, and be precise with the code."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.create_schedule",
        side_effect=ScheduleValidationError(code, "no"),
    ):
        response = client.post(_BASE, json=_payload())
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_reading_a_missing_schedule_is_a_404():
    """A retired or foreign schedule is simply not found."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.get_schedule",
        side_effect=ScheduleValidationError(CODE_NOT_FOUND, "no such schedule"),
    ):
        response = client.get(f"{_BASE}/ghost")
    assert response.status_code == 404


def test_a_malformed_definition_is_refused_by_the_model():
    """An unknown key or a missing required field never reaches the store."""
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.create_schedule"
    ) as create:
        assert client.post(_BASE, json=_payload(unexpected="x")).status_code == 422
        assert client.post(_BASE, json={"slug": "only-a-slug"}).status_code == 422
    create.assert_not_called()


def test_a_fixture_carrying_credentials_is_refused_at_the_boundary():
    """Authentication belongs to the target's credential reference, never to a stored fixture."""
    body = _payload(
        verification={
            "allow_mutating": True,
            "fixtures": [
                {
                    "operation_key": "DELETE /pets/{petId}",
                    "headers": {"X-Api-Key": "secret"},
                }
            ],
        }
    )
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"), patch(
        "app.verification_schedule_routes.create_schedule"
    ) as create:
        assert client.post(_BASE, json=body).status_code == 422
    create.assert_not_called()


def test_a_credential_missing_tenant_context_is_refused():
    """No tenant, no scope — the read is refused rather than silently unscoped."""
    app.dependency_overrides[validate_authentication] = lambda: {"auth_method": "jwt"}
    with patch("app.verification_schedule_routes.enforce_permission", return_value="u"):
        assert client.get(_BASE).status_code == 403
