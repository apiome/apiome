"""Unit tests for verification-schedule persistence — CTG-4.4 (#4501).

The ``db`` handle is a mock, so nothing here reaches Postgres. What is asserted is the contract the
store owes its callers:

* a definition is refused in cheapest-first order, so a bad handle never costs a target resolution;
* both uniqueness rules are refused with stable codes rather than a driver error about an index;
* a PATCH can never reach the scheduling or alerting state — the sweep's record of what happened is
  not editable by the thing being monitored;
* retiring a schedule is a soft delete, so its history survives; and
* a tick's trend counts are derived from its report, and a failure to file the history row still
  advances the cadence anchor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from app.provider_verification import (
    ConformanceReport,
    CoverageSummary,
    DriftFinding,
    TargetIdentity,
)
from app.verification_schedule import (
    ALERT_STATE_ALERTING,
    ALERT_STATE_OK,
    CODE_CADENCE_INVALID,
    CODE_NOT_FOUND,
    CODE_PAIR_TAKEN,
    CODE_SLUG_INVALID,
    CODE_SLUG_TAKEN,
    CODE_TARGET_UNKNOWN,
    STATUS_FAILED,
    STATUS_PASSED,
    AlertDecision,
    ScheduleValidationError,
    TickOutcome,
    VerificationScheduleInput,
    VerificationSchedulePatch,
    record_from_row,
)
from app.verification_schedule_store import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_runs,
    list_schedules,
    record_tick,
    update_schedule,
)
from app.verification_target import CODE_NOT_FOUND as TARGET_NOT_FOUND
from app.verification_target import TargetValidationError
from app.verification_target_store import TargetActor

_TENANT = "11111111-1111-4111-8111-111111111111"
_SCHEDULE = "77777777-7777-4777-8777-777777777777"
_TARGET = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
_ACTOR = TargetActor(user_id="33333333-3333-4333-8333-333333333333", label="a@b.test")


def _row(**overrides) -> Dict[str, Any]:
    """A ``verification_schedule`` row."""
    row = {
        "id": _SCHEDULE,
        "tenant_id": _TENANT,
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "description": None,
        "version_ref": "project/petstore/1.0.0",
        "target_id": _TARGET,
        "target_slug": "staging",
        "cadence_seconds": 3600,
        "enabled": True,
        "alert_on_recovery": True,
        "verification": {},
        "suite_options": {},
        "last_run_at": None,
        "last_status": None,
        "last_success_at": None,
        "last_report_id": None,
        "consecutive_failures": 0,
        "run_count": 0,
        "alert_state": ALERT_STATE_OK,
        "alert_fingerprint": None,
        "last_alert_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": None,
        "updated_by": None,
    }
    row.update(overrides)
    return row


def _definition(**overrides) -> VerificationScheduleInput:
    """A schedule definition."""
    fields = {
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "version_ref": "project/petstore/1.0.0",
        "target_ref": "staging",
        "cadence": "hourly",
    }
    fields.update(overrides)
    return VerificationScheduleInput(**fields)


def _target(monkeypatch, *, slug: str = "staging", target_id: str = _TARGET) -> None:
    """Make ``get_target`` resolve to a live target."""
    resolved = MagicMock()
    resolved.id = target_id
    resolved.slug = slug
    monkeypatch.setattr(
        "app.verification_schedule_store.get_target", lambda *a, **k: resolved
    )


def _missing_target(monkeypatch) -> None:
    """Make ``get_target`` refuse."""

    def _raise(*_a, **_k):
        raise TargetValidationError(TARGET_NOT_FOUND, "no verification target 'staging'")

    monkeypatch.setattr("app.verification_schedule_store.get_target", _raise)


# ---------------------------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------------------------


def test_create_stores_the_resolved_target_and_normalized_cadence(monkeypatch):
    """The stored row carries the resolved target's id *and* its handle, and seconds not a preset."""
    _target(monkeypatch)
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = None
    db.find_verification_schedule_for_pair.return_value = None
    db.insert_verification_schedule.return_value = _row()

    record = create_schedule(_TENANT, _definition(), actor=_ACTOR, handle=db)

    stored = db.insert_verification_schedule.call_args.kwargs["schedule"]
    assert stored["target_id"] == _TARGET
    assert stored["target_slug"] == "staging"
    assert stored["cadence_seconds"] == 3600
    assert stored["created_by"] == _ACTOR.user_id
    assert record.slug == "petstore-staging"


def test_create_refuses_a_bad_handle_before_resolving_the_target(monkeypatch):
    """Cheapest check first: an unusable handle never costs a target read."""
    calls = []
    monkeypatch.setattr(
        "app.verification_schedule_store.get_target",
        lambda *a, **k: calls.append(a) or MagicMock(),
    )
    db = MagicMock()
    with pytest.raises(ScheduleValidationError) as exc:
        create_schedule(_TENANT, _definition(slug="Not A Slug"), actor=_ACTOR, handle=db)
    assert exc.value.code == CODE_SLUG_INVALID
    assert calls == []
    db.insert_verification_schedule.assert_not_called()


def test_create_refuses_a_bad_cadence_before_resolving_the_target(monkeypatch):
    """Same rule, one step later."""
    calls = []
    monkeypatch.setattr(
        "app.verification_schedule_store.get_target",
        lambda *a, **k: calls.append(a) or MagicMock(),
    )
    db = MagicMock()
    with pytest.raises(ScheduleValidationError) as exc:
        create_schedule(_TENANT, _definition(cadence=30), actor=_ACTOR, handle=db)
    assert exc.value.code == CODE_CADENCE_INVALID
    assert calls == []


def test_create_refuses_an_unknown_target(monkeypatch):
    """A schedule aimed at nothing would tick forever and fail forever."""
    _missing_target(monkeypatch)
    db = MagicMock()
    with pytest.raises(ScheduleValidationError) as exc:
        create_schedule(_TENANT, _definition(), actor=_ACTOR, handle=db)
    assert exc.value.code == CODE_TARGET_UNKNOWN
    db.insert_verification_schedule.assert_not_called()


def test_create_refuses_a_duplicate_handle(monkeypatch):
    """A stable code, not a driver error about a unique index."""
    _target(monkeypatch)
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = _row()
    with pytest.raises(ScheduleValidationError) as exc:
        create_schedule(_TENANT, _definition(), actor=_ACTOR, handle=db)
    assert exc.value.code == CODE_SLUG_TAKEN


def test_create_refuses_a_second_schedule_for_the_same_pair(monkeypatch):
    """Two schedules on one (version, deployment) would double the traffic and every alert."""
    _target(monkeypatch)
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = None
    db.find_verification_schedule_for_pair.return_value = _row(slug="already-watching")
    with pytest.raises(ScheduleValidationError) as exc:
        create_schedule(_TENANT, _definition(slug="second-one"), actor=_ACTOR, handle=db)
    assert exc.value.code == CODE_PAIR_TAKEN
    assert "already-watching" in str(exc.value)


# ---------------------------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------------------------


def test_get_resolves_a_handle_first_then_an_id():
    """A pipeline names a handle; an alert payload names an id. One accessor answers both."""
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = None
    db.get_verification_schedule_by_id.return_value = _row()
    record = get_schedule(_TENANT, _SCHEDULE, handle=db)
    assert record.id == _SCHEDULE


def test_get_refuses_when_nothing_live_matches():
    """A retired or foreign schedule is simply not found."""
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = None
    db.get_verification_schedule_by_id.return_value = None
    with pytest.raises(ScheduleValidationError) as exc:
        get_schedule(_TENANT, "ghost", handle=db)
    assert exc.value.code == CODE_NOT_FOUND


def test_list_clamps_the_limit_and_forwards_the_filters():
    """The gate's questions are the filters; nobody needs a tenant's whole history in one read."""
    db = MagicMock()
    db.list_verification_schedules.return_value = [_row()]
    list_schedules(
        _TENANT,
        version_ref="project/petstore/1.0.0",
        target_id=_TARGET,
        enabled=True,
        limit=10_000,
        handle=db,
    )
    kwargs = db.list_verification_schedules.call_args.kwargs
    assert kwargs["version_ref"] == "project/petstore/1.0.0"
    assert kwargs["target_id"] == _TARGET
    assert kwargs["enabled"] is True
    assert kwargs["limit"] == 200


def test_list_runs_clamps_the_limit():
    """A trend view asks for the newest few hundred, not the archive."""
    db = MagicMock()
    db.list_verification_schedule_runs.return_value = []
    list_runs(_TENANT, _SCHEDULE, limit=10_000, handle=db)
    assert db.list_verification_schedule_runs.call_args.kwargs["limit"] == 500


# ---------------------------------------------------------------------------------------------
# Update and delete
# ---------------------------------------------------------------------------------------------


def test_patch_sets_only_what_it_names():
    """An unset field is left alone; a set one is normalized on the way in."""
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = _row()
    db.update_verification_schedule.return_value = _row(cadence_seconds=86400, enabled=False)

    update_schedule(
        _TENANT,
        "petstore-staging",
        VerificationSchedulePatch(cadence="daily", enabled=False),
        actor=_ACTOR,
        handle=db,
    )
    fields = db.update_verification_schedule.call_args.kwargs["fields"]
    assert fields == {"cadence_seconds": 86400, "enabled": False}


def test_patch_cannot_reach_the_scheduling_or_alert_state():
    """A monitor whose freshness could be edited by a request would not be a monitor.

    The patch model forbids extras, so an attempt to set the sweep's own columns is refused at the
    request boundary rather than quietly dropped.
    """
    with pytest.raises(Exception):
        VerificationSchedulePatch(last_success_at=_NOW)
    with pytest.raises(Exception):
        VerificationSchedulePatch(alert_state=ALERT_STATE_OK)
    with pytest.raises(Exception):
        VerificationSchedulePatch(consecutive_failures=0)


def test_an_empty_patch_reads_the_schedule_back_unchanged():
    """A PATCH that sets nothing is not an error; it means nothing changed."""
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = _row()
    record = update_schedule(
        _TENANT, "petstore-staging", VerificationSchedulePatch(), actor=_ACTOR, handle=db
    )
    db.update_verification_schedule.assert_not_called()
    assert record.slug == "petstore-staging"


def test_an_explicit_null_only_clears_the_one_nullable_field():
    """A null `description` clears it; a null anywhere else is a client mistake, not an instruction.

    `enabled: null` silently pausing a monitor, or `name: null` reaching a NOT NULL column as a
    500, are exactly the outcomes coercing a null would produce.
    """
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = _row(description="watching prod")
    db.update_verification_schedule.return_value = _row(description=None)
    update_schedule(
        _TENANT,
        "petstore-staging",
        VerificationSchedulePatch(description=None, name=None, enabled=None, cadence=None),
        actor=_ACTOR,
        handle=db,
    )
    assert db.update_verification_schedule.call_args.kwargs["fields"] == {"description": None}


def test_patch_refuses_a_cadence_outside_the_band():
    """The floor is enforced on update as well as on create."""
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = _row()
    with pytest.raises(ScheduleValidationError) as exc:
        update_schedule(
            _TENANT,
            "petstore-staging",
            VerificationSchedulePatch(cadence=10),
            actor=_ACTOR,
            handle=db,
        )
    assert exc.value.code == CODE_CADENCE_INVALID


def test_delete_is_a_soft_delete():
    """The freshness answer outlives the instruction that produced it."""
    db = MagicMock()
    db.get_verification_schedule_by_slug.return_value = _row()
    db.soft_delete_verification_schedule.return_value = True
    assert delete_schedule(_TENANT, "petstore-staging", actor=_ACTOR, handle=db) is True
    db.soft_delete_verification_schedule.assert_called_once()


# ---------------------------------------------------------------------------------------------
# Recording a tick
# ---------------------------------------------------------------------------------------------


def _report(outcome: str = STATUS_FAILED) -> ConformanceReport:
    """A conformance report with one located drift."""
    return ConformanceReport(
        outcome=outcome,
        suite_digest="sha256:" + "b" * 64,
        target=TargetIdentity(
            slug="staging", environment="staging", base_url="https://staging.test/v1"
        ),
        started_at=_NOW,
        finished_at=_NOW,
        duration_ms=0,
        coverage=CoverageSummary(
            operations_total=10,
            operations_exercised=4,
            operations_passed=3,
            operations_failed=1,
            operations_errored=0,
            operations_skipped=0,
            operations_uncompiled=6,
            uncovered_named=6,
            coverage_percent=40.0,
            cases_total=4,
            cases_passed=3,
            cases_failed=1,
            cases_errored=0,
            cases_skipped=0,
        ),
        drift=[
            DriftFinding(
                operation_key="GET /pets",
                case_id="c1",
                http_method="GET",
                http_path="/pets",
                kind="response_schema",
                code="response-schema-mismatch",
                pointer="/id",
                message="type",
            )
        ],
        mutating_allowed=False,
    )


def _decision(**overrides) -> AlertDecision:
    """An alert decision."""
    fields = {
        "notify": True,
        "reason": "transition",
        "next_state": ALERT_STATE_ALERTING,
        "next_fingerprint": "sha256:" + "c" * 64,
    }
    fields.update(overrides)
    return AlertDecision(**fields)


def test_record_tick_derives_the_trend_counts_from_the_report():
    """The history row cannot contradict the report it points at."""
    db = MagicMock()
    db.insert_verification_schedule_run.return_value = {
        "id": "88888888-8888-4888-8888-888888888888",
        "tenant_id": _TENANT,
        "schedule_id": _SCHEDULE,
        "status": STATUS_FAILED,
    }
    schedule = record_from_row(_row())
    outcome = TickOutcome(
        status=STATUS_FAILED, report=_report(), report_id="55555555-5555-4555-8555-555555555555"
    )
    record_tick(
        schedule,
        outcome,
        _decision(),
        fingerprint="sha256:" + "c" * 64,
        alert_deliveries=2,
        handle=db,
    )
    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["operations_total"] == 10
    assert run["operations_exercised"] == 4
    assert run["coverage_percent"] == 40.0
    assert run["drift_count"] == 1
    assert run["alerted"] is True
    assert run["alert_reason"] == "transition"
    assert run["alert_deliveries"] == 2
    assert run["drift_fingerprint"] == "sha256:" + "c" * 64


def test_record_tick_advances_the_anchor_even_when_the_history_write_fails():
    """A filing failure must not leave the schedule perpetually due.

    The history row is attempted first on purpose: a crash between the two writes leaves a
    recorded tick that will be re-run — honest — rather than an advanced anchor with nothing
    recorded, which would silently skip a verification window.
    """
    db = MagicMock()
    db.insert_verification_schedule_run.side_effect = RuntimeError("disk on fire")
    schedule = record_from_row(_row())
    stored = record_tick(
        schedule,
        TickOutcome(status=STATUS_FAILED, report=_report()),
        _decision(),
        fingerprint="sha256:" + "c" * 64,
        handle=db,
    )
    assert stored is None
    db.mark_verification_schedule_ran.assert_called_once()


def test_record_tick_of_a_clean_run_stores_no_fingerprint_and_advances_success():
    """A passing tick has nothing to fingerprint and moves the freshness anchor."""
    db = MagicMock()
    db.insert_verification_schedule_run.return_value = {
        "id": "88888888-8888-4888-8888-888888888888",
        "tenant_id": _TENANT,
        "schedule_id": _SCHEDULE,
        "status": STATUS_PASSED,
    }
    schedule = record_from_row(_row(alert_state=ALERT_STATE_ALERTING))
    record_tick(
        schedule,
        TickOutcome(status=STATUS_PASSED, report=_report(outcome=STATUS_PASSED)),
        _decision(notify=True, reason="recovered", next_state=ALERT_STATE_OK, next_fingerprint=None),
        fingerprint=None,
        handle=db,
    )
    run = db.insert_verification_schedule_run.call_args.kwargs["run"]
    assert run["drift_fingerprint"] is None
    marked = db.mark_verification_schedule_ran.call_args.kwargs
    assert marked["succeeded"] is True
    assert marked["alert_state"] == ALERT_STATE_OK
    assert marked["alerted"] is True
