"""Unit tests for the scheduled-verification sweep — CTG-4.4 (#4501).

The database handle is a mock and the CTG-4.3 service is patched, so nothing here compiles a suite
or reaches a deployment. What is asserted is the worker's behaviour:

* the kill switch halts a tick entirely;
* a schedule another worker holds is skipped, not waited for;
* the cadence anchor advances on **every** processed schedule — clean, drifting, or unable to run
  — so a broken schedule cannot monopolise the sweep;
* one schedule's failure never aborts the rest of the tick;
* a run that could not happen is recorded as an errored tick rather than escaping; and
* across ticks, a pass→fail→fail→pass sequence produces exactly two alerts on the right events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.provider_verification import (
    ConformanceReport,
    CoverageSummary,
    DriftFinding,
    OperationConformance,
    TargetIdentity,
)
from app.provider_verification_service import ProviderVerificationResponse
from app.verification_schedule import (
    ALERT_STATE_ALERTING,
    ALERT_STATE_OK,
    STATUS_ERRORED,
    STATUS_FAILED,
    STATUS_PASSED,
)
from app.verification_schedule_notifications import (
    EVENT_VERIFICATION_DRIFT_DETECTED,
    EVENT_VERIFICATION_DRIFT_RESOLVED,
)
from app.verification_schedule_sweep import (
    process_verification_schedule_sweep,
    run_due_schedule,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_SCHEDULE = "77777777-7777-4777-8777-777777777777"
_TARGET = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _row(**overrides) -> Dict[str, Any]:
    """A due ``verification_schedule`` row."""
    row = {
        "id": _SCHEDULE,
        "tenant_id": _TENANT,
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "version_ref": "project/petstore/1.0.0",
        "target_id": _TARGET,
        "target_slug": "staging",
        "cadence_seconds": 3600,
        "enabled": True,
        "alert_on_recovery": True,
        "verification": {},
        "suite_options": {},
        "last_status": None,
        "last_success_at": None,
        "consecutive_failures": 0,
        "alert_state": ALERT_STATE_OK,
        "alert_fingerprint": None,
    }
    row.update(overrides)
    return row


def _report(outcome: str, *, pointer: str = "/id") -> ConformanceReport:
    """A conformance report with one located drift when it is not clean."""
    drift = (
        []
        if outcome == STATUS_PASSED
        else [
            DriftFinding(
                operation_key="GET /pets",
                case_id="c1",
                http_method="GET",
                http_path="/pets",
                kind="response_schema",
                code="response-schema-mismatch",
                pointer=pointer,
                expected="integer",
                actual="x",
                message="type",
            )
        ]
    )
    return ConformanceReport(
        outcome=outcome,
        suite_digest="sha256:" + "b" * 64,
        target=TargetIdentity(
            target_id=_TARGET,
            slug="staging",
            environment="staging",
            base_url="https://staging.test/v1",
        ),
        started_at=_NOW,
        finished_at=_NOW,
        duration_ms=0,
        coverage=CoverageSummary(
            operations_total=4,
            operations_exercised=2,
            operations_passed=1 if drift else 2,
            operations_failed=1 if drift else 0,
            operations_errored=0,
            operations_skipped=0,
            operations_uncompiled=2,
            uncovered_named=2,
            coverage_percent=50.0,
            cases_total=2,
            cases_passed=1 if drift else 2,
            cases_failed=1 if drift else 0,
            cases_errored=0,
            cases_skipped=0,
        ),
        operations=[
            OperationConformance(
                operation_key="GET /pets",
                http_method="GET",
                http_path="/pets",
                outcome=outcome,
                exercised=True,
                cases_total=1,
                cases_passed=0 if drift else 1,
                cases_failed=1 if drift else 0,
                cases_errored=0,
                cases_skipped=0,
                drift=list(drift),
            )
        ],
        drift=list(drift),
        mutating_allowed=False,
    )


def _response(outcome: str, **overrides) -> ProviderVerificationResponse:
    """A successful CTG-4.3 service response."""
    stored = MagicMock()
    stored.id = "55555555-5555-4555-8555-555555555555"
    run = MagicMock()
    run.id = "44444444-4444-4444-8444-444444444444"
    fields = {
        "ok": True,
        "version_ref": "project/petstore/1.0.0",
        "suite_digest": "sha256:" + "b" * 64,
        "report": _report(outcome, **overrides),
    }
    response = ProviderVerificationResponse(**fields)
    response.stored = None
    response.run = None
    return response


def _db(rows: List[Dict[str, Any]], *, locked: bool = True) -> MagicMock:
    """A database mock returning ``rows`` as due."""
    db = MagicMock()
    db.list_due_verification_schedules.return_value = rows
    db.try_acquire_verification_schedule_lock.return_value = locked
    db.insert_verification_schedule_run.return_value = None
    db.list_active_push_webhook_subscription_ids.return_value = ["sub-1"]
    db.enqueue_push_webhook_delivery.return_value = {"id": "evt-1"}
    return db


@pytest.fixture()
def _enabled(monkeypatch):
    """Turn the sweep on with a batch of two."""
    from app.config import settings

    monkeypatch.setattr(settings, "verification_schedule_enabled", True, raising=False)
    monkeypatch.setattr(settings, "verification_schedule_batch_size", 2, raising=False)
    yield


# ---------------------------------------------------------------------------------------------
# Tick control
# ---------------------------------------------------------------------------------------------


def test_kill_switch_halts_the_whole_tick(monkeypatch):
    """Incident response: no selection, no run, no alert — independent of per-schedule state."""
    from app.config import settings

    monkeypatch.setattr(settings, "verification_schedule_enabled", False, raising=False)
    db = _db([_row()])
    assert process_verification_schedule_sweep(db) == 0
    db.list_due_verification_schedules.assert_not_called()


def test_a_schedule_another_worker_holds_is_skipped(_enabled):
    """Single-flight: skipped, not waited for — its next tick is one cadence away."""
    db = _db([_row()], locked=False)
    with patch(
        "app.verification_schedule_sweep.execute_scheduled_verification"
    ) as execute:
        assert process_verification_schedule_sweep(db) == 0
    execute.assert_not_called()
    db.mark_verification_schedule_ran.assert_not_called()


def test_the_lock_is_released_even_when_the_schedule_raises(_enabled):
    """A leaked session lock would silence the schedule until the connection died."""
    db = _db([_row()])
    with patch(
        "app.verification_schedule_sweep.run_due_schedule",
        side_effect=RuntimeError("boom"),
    ):
        assert process_verification_schedule_sweep(db) == 0
    db.release_verification_schedule_lock.assert_called_once_with(_SCHEDULE)


def test_one_schedules_failure_never_aborts_the_rest(_enabled):
    """The second schedule still runs after the first one blows up."""
    other = _row(id="99999999-9999-4999-8999-999999999999", slug="other")
    db = _db([_row(), other])
    seen: List[str] = []

    def _run(_db, row):
        if row["id"] == _SCHEDULE:
            raise RuntimeError("boom")
        seen.append(row["id"])
        return STATUS_PASSED

    with patch("app.verification_schedule_sweep.run_due_schedule", side_effect=_run):
        executed = process_verification_schedule_sweep(db)
    assert executed == 1
    assert seen == [other["id"]]


def test_a_failed_due_selection_is_logged_not_raised(_enabled):
    """A database blip retries on the next tick rather than killing the loop."""
    db = _db([])
    db.list_due_verification_schedules.side_effect = RuntimeError("no connection")
    assert process_verification_schedule_sweep(db) == 0


# ---------------------------------------------------------------------------------------------
# Executing one schedule
# ---------------------------------------------------------------------------------------------


def test_a_clean_tick_is_recorded_and_says_nothing(_enabled):
    """A passing run advances the anchor, records history, and notifies nobody."""
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=_response(STATUS_PASSED),
    ):
        assert process_verification_schedule_sweep(db) == 1
    db.enqueue_push_webhook_delivery.assert_not_called()
    marked = db.mark_verification_schedule_ran.call_args.kwargs
    assert marked["status"] == STATUS_PASSED
    assert marked["succeeded"] is True
    assert marked["alert_state"] == ALERT_STATE_OK


def test_a_drifting_tick_alerts_once_and_records_why(_enabled):
    """The transition fires one `verification.drift.detected` per active subscription."""
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=_response(STATUS_FAILED),
    ):
        assert process_verification_schedule_sweep(db) == 1

    db.enqueue_push_webhook_delivery.assert_called_once()
    args = db.enqueue_push_webhook_delivery.call_args.args
    assert args[2] == EVENT_VERIFICATION_DRIFT_DETECTED
    payload = args[3]
    assert payload["reason"] == "transition"
    assert payload["versionRef"] == "project/petstore/1.0.0"
    assert payload["operations"][0]["operationKey"] == "GET /pets"

    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["status"] == STATUS_FAILED
    assert run["alerted"] is True
    assert run["alert_reason"] == "transition"

    marked = db.mark_verification_schedule_ran.call_args.kwargs
    assert marked["alert_state"] == ALERT_STATE_ALERTING
    assert marked["succeeded"] is False


def test_a_run_that_could_not_happen_is_an_errored_tick(_enabled):
    """`ok: false` is recorded with its taxonomy code — never allowed to escape unrecorded."""
    refusal = ProviderVerificationResponse(
        ok=False,
        version_ref="project/petstore/1.0.0",
        error={
            "code": "FORMAT_MISMATCH",
            "category": "format",
            "message": "No contract suite could be compiled.",
            "remediation": "Fix the suite findings.",
            "retriable": False,
        },
    )
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=refusal,
    ):
        assert process_verification_schedule_sweep(db) == 1
    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["status"] == STATUS_ERRORED
    assert run["error_code"] == "FORMAT_MISMATCH"
    # The first refusal is still news, so it alerts once.
    assert run["alerted"] is True


def test_an_unexpected_exception_becomes_an_errored_tick_not_a_dead_sweep(_enabled):
    """Letting it escape would leave the tick unrecorded and the next replica equally silent."""
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        side_effect=RuntimeError("kaboom"),
    ):
        assert process_verification_schedule_sweep(db) == 1
    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["status"] == STATUS_ERRORED
    assert run["error_code"] == "INTERNAL_ERROR"
    db.mark_verification_schedule_ran.assert_called_once()


def test_the_anchor_advances_even_when_the_run_cannot_happen(_enabled):
    """A schedule whose version stopped compiling must not stay perpetually due."""
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        side_effect=RuntimeError("kaboom"),
    ):
        process_verification_schedule_sweep(db)
    db.mark_verification_schedule_ran.assert_called_once()


def test_no_idempotency_key_is_passed_to_the_run(_enabled):
    """The trap: a key derived from the anchor would replay a stale verdict as current."""
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=_response(STATUS_PASSED),
    ) as verify:
        process_verification_schedule_sweep(db)
    request = verify.call_args.args[1]
    assert request.idempotency_key is None
    assert request.context["trigger"] == "schedule"


def test_the_scheduled_run_is_attributed_to_the_system(_enabled):
    """Evidence must not be attributed to whoever happened to define the schedule."""
    db = _db([_row()])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=_response(STATUS_PASSED),
    ) as verify:
        process_verification_schedule_sweep(db)
    actor = verify.call_args.kwargs["actor"]
    assert actor.kind == "system"
    assert actor.user_id is None
    assert actor.label == "schedule:petstore-staging"


# ---------------------------------------------------------------------------------------------
# Across ticks: the acceptance criterion
# ---------------------------------------------------------------------------------------------


def test_pass_fail_fail_pass_produces_exactly_two_alerts(_enabled):
    """The whole point: one alert on the transition, silence on the repeat, one on recovery."""
    state = {"alert_state": ALERT_STATE_OK, "alert_fingerprint": None, "last_status": None}
    events: List[str] = []

    def _capture(_tenant, _sub, event_type, _payload):
        events.append(event_type)
        return {"id": "evt"}

    for outcome in (STATUS_PASSED, STATUS_FAILED, STATUS_FAILED, STATUS_PASSED):
        db = _db([_row(**state)])
        db.enqueue_push_webhook_delivery.side_effect = _capture
        with patch(
            "app.provider_verification_service.verify_version_against_target",
            return_value=_response(outcome),
        ):
            process_verification_schedule_sweep(db)
        marked = db.mark_verification_schedule_ran.call_args.kwargs
        state = {
            "alert_state": marked["alert_state"],
            "alert_fingerprint": marked["alert_fingerprint"],
            "last_status": marked["status"],
        }

    assert events == [EVENT_VERIFICATION_DRIFT_DETECTED, EVENT_VERIFICATION_DRIFT_RESOLVED]


def test_a_changed_violation_set_speaks_again_while_still_failing(_enabled):
    """A second regression must not hide behind the first."""
    state = {"alert_state": ALERT_STATE_OK, "alert_fingerprint": None, "last_status": None}
    reasons: List[str] = []

    def _capture(_tenant, _sub, _event_type, payload):
        reasons.append(payload["reason"])
        return {"id": "evt"}

    for pointer in ("/id", "/id", "/name"):
        db = _db([_row(**state)])
        db.enqueue_push_webhook_delivery.side_effect = _capture
        with patch(
            "app.provider_verification_service.verify_version_against_target",
            return_value=_response(STATUS_FAILED, pointer=pointer),
        ):
            process_verification_schedule_sweep(db)
        marked = db.mark_verification_schedule_ran.call_args.kwargs
        state = {
            "alert_state": marked["alert_state"],
            "alert_fingerprint": marked["alert_fingerprint"],
            "last_status": marked["status"],
        }

    assert reasons == ["transition", "new-violations"]


def test_a_muted_recovery_sends_nothing_but_still_clears(_enabled):
    """Silence is a choice about notification, never about state."""
    db = _db([_row(alert_state=ALERT_STATE_ALERTING, alert_fingerprint="sha256:x",
                   alert_on_recovery=False, last_status=STATUS_FAILED)])
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=_response(STATUS_PASSED),
    ):
        process_verification_schedule_sweep(db)
    db.enqueue_push_webhook_delivery.assert_not_called()
    assert db.mark_verification_schedule_ran.call_args.kwargs["alert_state"] == ALERT_STATE_OK


def test_a_row_that_cannot_be_turned_into_a_request_is_a_recorded_errored_tick():
    """A stored row that no longer yields a valid request must not silently skip a window.

    It is recorded as ``errored`` with the internal code, which alerts once and keeps the anchor
    moving, rather than raising out of the tick and leaving nothing behind.
    """
    db = MagicMock()
    db.insert_verification_schedule_run.return_value = None
    db.list_active_push_webhook_subscription_ids.return_value = []
    assert run_due_schedule(db, _row(target_slug="")) == STATUS_ERRORED
    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["status"] == STATUS_ERRORED
    assert run["error_code"] == "INTERNAL_ERROR"
    db.mark_verification_schedule_ran.assert_called_once()


def test_a_fan_out_failure_never_fails_the_tick(_enabled):
    """A notification problem must not turn a recorded verification into a lost one."""
    db = _db([_row()])
    db.list_active_push_webhook_subscription_ids.side_effect = RuntimeError("no subs table")
    with patch(
        "app.provider_verification_service.verify_version_against_target",
        return_value=_response(STATUS_FAILED),
    ):
        assert process_verification_schedule_sweep(db) == 1
    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["alerted"] is True
    assert run["alert_deliveries"] == 0
