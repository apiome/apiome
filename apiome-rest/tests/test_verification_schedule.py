"""Unit tests for the pure scheduled-verification module — CTG-4.4 (#4501).

Nothing here touches the database, the network, or the sweep. What is asserted is the judgment the
ticket is actually about:

* the definition rules (handle shape, reference shape, cadence band and presets);
* the **alert machine** — a pass→fail transition notifies exactly once, a repeat of the same
  failure is silent, a *changed* failure speaks again, and recovery always clears the state even
  when it is not announced;
* the fingerprint that decides what "the same failure" means, including the values it deliberately
  ignores; and
* the alert payload's caps, and that what it drops it counts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.provider_verification import (
    ConformanceReport,
    CoverageSummary,
    DriftFinding,
    OperationConformance,
    TargetIdentity,
)
from app.verification_schedule import (
    ALERT_REASON_NEW_VIOLATIONS,
    ALERT_REASON_RECOVERED,
    ALERT_REASON_TRANSITION,
    ALERT_STATE_ALERTING,
    ALERT_STATE_OK,
    CADENCE_PRESETS,
    CODE_CADENCE_INVALID,
    CODE_SLUG_INVALID,
    CODE_VERSION_REF_INVALID,
    MAX_ALERT_DRIFT_PER_OPERATION,
    MAX_ALERT_MESSAGE_CHARS,
    MAX_ALERT_OPERATIONS,
    MAX_CADENCE_SECONDS,
    MIN_CADENCE_SECONDS,
    STATUS_ERRORED,
    STATUS_FAILED,
    STATUS_PASSED,
    AlertState,
    ScheduleValidationError,
    TickOutcome,
    VerificationScheduleInput,
    VerificationScheduleRecord,
    build_alert_payload,
    decide_alert,
    freshness_seconds,
    record_from_row,
    resolve_cadence_seconds,
    run_fingerprint,
    summarize_tick,
    validate_schedule_slug,
    validate_version_ref,
)

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------
# Definition rules
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["staging", "petstore-staging", "a", "eu-prod-2"])
def test_valid_slugs_pass_through(slug):
    """A usable handle is returned unchanged."""
    assert validate_schedule_slug(slug) == slug


@pytest.mark.parametrize(
    "slug", ["", "-leading", "trailing-", "Upper", "has space", "under_score", "a" * 129]
)
def test_unusable_slugs_are_refused(slug):
    """An unusable handle is refused with the schedule's own code, not the target's."""
    with pytest.raises(ScheduleValidationError) as exc:
        validate_schedule_slug(slug)
    assert exc.value.code == CODE_SLUG_INVALID


@pytest.mark.parametrize(
    "ref", ["project/petstore/1.0.0", "catalog/pets/2.1.0-rc1", "project/a/b"]
)
def test_valid_version_refs_pass_through(ref):
    """A reference the resolver can address is accepted on shape."""
    assert validate_version_ref(ref) == ref


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "petstore/1.0.0",
        "project/petstore",
        "project/petstore/1.0.0/extra",
        "other/petstore/1.0.0",
        "project/pet store/1.0.0",
    ],
)
def test_malformed_version_refs_are_refused(ref):
    """A reference that is not shaped like one is refused before anything is stored."""
    with pytest.raises(ScheduleValidationError) as exc:
        validate_version_ref(ref)
    assert exc.value.code == CODE_VERSION_REF_INVALID


def test_version_ref_existence_is_not_checked_here():
    """Shape only: a schedule may name a version the pipeline is about to publish.

    Refusing at definition time would make a not-yet-published version unschedulable; a reference
    that stops resolving later must surface as a failing tick in the history, which is visible.
    """
    assert validate_version_ref("project/not-published-yet/9.9.9")


@pytest.mark.parametrize("name,seconds", sorted(CADENCE_PRESETS.items()))
def test_cadence_presets_resolve(name, seconds):
    """Every advertised preset resolves to its documented interval."""
    assert resolve_cadence_seconds(name) == seconds


def test_cadence_accepts_explicit_seconds_and_numeric_strings():
    """A caller may say 3600 or "3600"; both mean the same hour."""
    assert resolve_cadence_seconds(3600) == 3600
    assert resolve_cadence_seconds("3600") == 3600


@pytest.mark.parametrize(
    "cadence",
    [MIN_CADENCE_SECONDS - 1, 0, -60, MAX_CADENCE_SECONDS + 1, "nightly", None, True, "abc"],
)
def test_cadence_outside_the_band_is_refused(cadence):
    """Sub-floor, over-ceiling, unknown-preset, and non-numeric cadences are all refused.

    The floor matters most: a one-minute schedule against a live deployment is load, not
    monitoring, and the database keeps the same rule.
    """
    with pytest.raises(ScheduleValidationError) as exc:
        resolve_cadence_seconds(cadence)
    assert exc.value.code == CODE_CADENCE_INVALID


def test_schedule_input_refuses_a_fixture_carrying_credentials():
    """A stored fixture may not smuggle authentication past the target's credential reference."""
    with pytest.raises(Exception):
        VerificationScheduleInput(
            slug="petstore-staging",
            name="Petstore",
            version_ref="project/petstore/1.0.0",
            target_ref="staging",
            verification={
                "allow_mutating": True,
                "fixtures": [
                    {
                        "operation_key": "DELETE /pets/{petId}",
                        "headers": {"Authorization": "Bearer nope"},
                    }
                ],
            },
        )


# ---------------------------------------------------------------------------------------------
# Fingerprints — what "the same failure" means
# ---------------------------------------------------------------------------------------------


def _drift(pointer="/id", code="response-schema-mismatch", actual="1", message="type") -> DriftFinding:
    """One located violation."""
    return DriftFinding(
        operation_key="GET /pets/{petId}",
        case_id="get-pets-petid-example",
        http_method="GET",
        http_path="/pets/{petId}",
        kind="response_schema",
        code=code,
        pointer=pointer,
        expected="integer",
        actual=actual,
        message=message,
    )


def test_a_clean_tick_has_no_fingerprint():
    """There is nothing to digest when nothing is wrong."""
    assert run_fingerprint(status=STATUS_PASSED, drift=[_drift()]) is None


def test_the_same_violations_in_any_order_share_a_fingerprint():
    """Ordering is not a change: the digest is over a *set*."""
    a = _drift(pointer="/id")
    b = _drift(pointer="/name")
    assert run_fingerprint(status=STATUS_FAILED, drift=[a, b]) == run_fingerprint(
        status=STATUS_FAILED, drift=[b, a]
    )


def test_a_changing_observed_value_is_not_new_drift():
    """A deployment returning a different wrong value every time is the same violation.

    Folding ``actual`` (or the message) into the identity would make every tick look like new
    drift and reinstate exactly the alert storm this module exists to prevent.
    """
    first = run_fingerprint(status=STATUS_FAILED, drift=[_drift(actual="1", message="a")])
    second = run_fingerprint(status=STATUS_FAILED, drift=[_drift(actual="99", message="b")])
    assert first == second


def test_a_new_pointer_is_new_drift():
    """A violation in a place that was previously fine changes the fingerprint."""
    first = run_fingerprint(status=STATUS_FAILED, drift=[_drift(pointer="/id")])
    second = run_fingerprint(
        status=STATUS_FAILED, drift=[_drift(pointer="/id"), _drift(pointer="/name")]
    )
    assert first != second


def test_a_run_that_could_not_happen_fingerprints_its_refusal():
    """No violations to digest, so the refusal code is the identity — and a different one speaks."""
    first = run_fingerprint(status=STATUS_ERRORED, drift=[], error_code="FORMAT_MISMATCH")
    again = run_fingerprint(status=STATUS_ERRORED, drift=[], error_code="FORMAT_MISMATCH")
    other = run_fingerprint(status=STATUS_ERRORED, drift=[], error_code="SOURCE_AUTH_REQUIRED")
    assert first == again
    assert first != other


def test_failed_and_errored_with_identical_drift_differ():
    """"The body is wrong" and "there was no answer" are different facts."""
    assert run_fingerprint(status=STATUS_FAILED, drift=[_drift()]) != run_fingerprint(
        status=STATUS_ERRORED, drift=[_drift()]
    )


# ---------------------------------------------------------------------------------------------
# The alert machine
# ---------------------------------------------------------------------------------------------


def test_healthy_from_ok_is_silent():
    """A passing tick on a healthy schedule says nothing."""
    decision = decide_alert(
        status=STATUS_PASSED, fingerprint=None, previous=AlertState(ALERT_STATE_OK)
    )
    assert decision.notify is False
    assert decision.reason is None
    assert decision.next_state == ALERT_STATE_OK
    assert decision.next_fingerprint is None


@pytest.mark.parametrize("status", [STATUS_FAILED, STATUS_ERRORED])
def test_pass_to_fail_alerts_once(status):
    """The acceptance criterion: the transition notifies, and the next identical tick does not."""
    fingerprint = run_fingerprint(status=status, drift=[_drift()])
    first = decide_alert(
        status=status, fingerprint=fingerprint, previous=AlertState(ALERT_STATE_OK)
    )
    assert first.notify is True
    assert first.reason == ALERT_REASON_TRANSITION
    assert first.next_state == ALERT_STATE_ALERTING
    assert first.next_fingerprint == fingerprint

    second = decide_alert(
        status=status,
        fingerprint=fingerprint,
        previous=AlertState(first.next_state, first.next_fingerprint),
    )
    assert second.notify is False
    assert second.reason is None
    assert second.next_state == ALERT_STATE_ALERTING
    assert second.next_fingerprint == fingerprint


def test_a_hundred_identical_failures_produce_one_alert():
    """No storm: the state carried on the row is what keeps every later tick quiet."""
    fingerprint = run_fingerprint(status=STATUS_FAILED, drift=[_drift()])
    state = AlertState(ALERT_STATE_OK)
    alerts = 0
    for _ in range(100):
        decision = decide_alert(
            status=STATUS_FAILED, fingerprint=fingerprint, previous=state
        )
        alerts += 1 if decision.notify else 0
        state = AlertState(decision.next_state, decision.next_fingerprint)
    assert alerts == 1


def test_new_violations_behind_old_ones_speak_again():
    """A second regression must not hide behind the first."""
    first_fp = run_fingerprint(status=STATUS_FAILED, drift=[_drift(pointer="/id")])
    worse_fp = run_fingerprint(
        status=STATUS_FAILED, drift=[_drift(pointer="/id"), _drift(pointer="/name")]
    )
    decision = decide_alert(
        status=STATUS_FAILED,
        fingerprint=worse_fp,
        previous=AlertState(ALERT_STATE_ALERTING, first_fp),
    )
    assert decision.notify is True
    assert decision.reason == ALERT_REASON_NEW_VIOLATIONS
    assert decision.next_fingerprint == worse_fp


def test_recovery_alerts_and_clears():
    """Coming back clean notifies once and returns the schedule to `ok`."""
    decision = decide_alert(
        status=STATUS_PASSED,
        fingerprint=None,
        previous=AlertState(ALERT_STATE_ALERTING, "sha256:" + "a" * 64),
    )
    assert decision.notify is True
    assert decision.reason == ALERT_REASON_RECOVERED
    assert decision.next_state == ALERT_STATE_OK
    assert decision.next_fingerprint is None


def test_muted_recovery_still_clears_the_state():
    """The trap: a silent recovery that left the state alerting would mute the next failure too."""
    decision = decide_alert(
        status=STATUS_PASSED,
        fingerprint=None,
        previous=AlertState(ALERT_STATE_ALERTING, "sha256:" + "a" * 64),
        alert_on_recovery=False,
    )
    assert decision.notify is False
    assert decision.reason is None
    assert decision.next_state == ALERT_STATE_OK

    # …and the next failure is therefore a transition, which speaks.
    fingerprint = run_fingerprint(status=STATUS_FAILED, drift=[_drift()])
    following = decide_alert(
        status=STATUS_FAILED,
        fingerprint=fingerprint,
        previous=AlertState(decision.next_state, decision.next_fingerprint),
    )
    assert following.notify is True
    assert following.reason == ALERT_REASON_TRANSITION


# ---------------------------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------------------------


def test_freshness_is_none_when_nothing_ever_verified_clean():
    """Unknown, never fresh — a gate that confuses the two is worse than no gate."""
    assert freshness_seconds(None, now=_NOW) is None


def test_freshness_counts_seconds_since_the_last_clean_run():
    """The anchor is the last success, not the last run."""
    assert freshness_seconds(_NOW - timedelta(hours=2), now=_NOW) == 7200


def test_freshness_treats_a_naive_anchor_as_utc():
    """A driver that returns a naive timestamp must not produce a negative or absurd age."""
    naive = (_NOW - timedelta(minutes=5)).replace(tzinfo=None)
    assert freshness_seconds(naive, now=_NOW) == 300


def test_freshness_never_goes_negative():
    """Clock skew must not make a stale deployment look like it verified in the future."""
    assert freshness_seconds(_NOW + timedelta(hours=1), now=_NOW) == 0


# ---------------------------------------------------------------------------------------------
# The alert payload
# ---------------------------------------------------------------------------------------------


def _operation(key: str, drift_count: int = 1) -> OperationConformance:
    """One violating operation carrying ``drift_count`` located violations."""
    return OperationConformance(
        operation_key=key,
        http_method="GET",
        http_path="/pets",
        outcome=STATUS_FAILED,
        exercised=True,
        cases_total=drift_count,
        cases_passed=0,
        cases_failed=drift_count,
        cases_errored=0,
        cases_skipped=0,
        drift=[_drift(pointer=f"/f{i}") for i in range(drift_count)],
    )


def _report(operations, drift) -> ConformanceReport:
    """A conformance report over the supplied operations."""
    return ConformanceReport(
        outcome=STATUS_FAILED,
        suite_digest="sha256:" + "b" * 64,
        api_title="Pets",
        target=TargetIdentity(
            target_id="22222222-2222-4222-8222-222222222222",
            slug="staging",
            environment="staging",
            base_url="https://staging.example.test/v1",
        ),
        started_at=_NOW,
        finished_at=_NOW + timedelta(seconds=2),
        duration_ms=2000,
        coverage=CoverageSummary(
            operations_total=40,
            operations_exercised=len(operations),
            operations_passed=0,
            operations_failed=len(operations),
            operations_errored=0,
            operations_skipped=0,
            operations_uncompiled=0,
            uncovered_named=0,
            coverage_percent=50.0,
            cases_total=len(operations),
            cases_passed=0,
            cases_failed=len(operations),
            cases_errored=0,
            cases_skipped=0,
        ),
        operations=operations,
        drift=drift,
        mutating_allowed=False,
    )


def _schedule(**overrides) -> VerificationScheduleRecord:
    """A stored schedule record with sensible defaults."""
    fields = {
        "id": "77777777-7777-4777-8777-777777777777",
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "version_ref": "project/petstore/1.0.0",
        "target_id": "22222222-2222-4222-8222-222222222222",
        "target_slug": "staging",
        "cadence_seconds": 3600,
        "enabled": True,
        "alert_on_recovery": True,
        "last_status": STATUS_PASSED,
        "last_success_at": _NOW - timedelta(days=1),
    }
    fields.update(overrides)
    return VerificationScheduleRecord(**fields)


def test_payload_carries_the_summary_and_the_violating_operations():
    """The three questions somebody woken at 3am asks, answered without a follow-up call."""
    operations = [_operation("GET /pets"), _operation("GET /pets/{petId}")]
    report = _report(operations, [_drift()])
    payload = build_alert_payload(
        event="verification.drift.detected",
        reason=ALERT_REASON_TRANSITION,
        schedule=_schedule(),
        outcome=TickOutcome(
            status=STATUS_FAILED, report=report, report_id="55555555-5555-4555-8555-555555555555"
        ),
        previous_status=STATUS_PASSED,
        consecutive_failures=1,
        occurred_at=_NOW,
    )
    assert payload["reason"] == ALERT_REASON_TRANSITION
    assert payload["versionRef"] == "project/petstore/1.0.0"
    assert payload["status"] == STATUS_FAILED
    assert payload["previousStatus"] == STATUS_PASSED
    assert payload["coverage"]["operationsTotal"] == 40
    assert payload["target"]["baseUrl"] == "https://staging.example.test/v1"
    assert [op["operationKey"] for op in payload["operations"]] == [
        "GET /pets",
        "GET /pets/{petId}",
    ]
    assert payload["freshnessSeconds"] == 86400
    assert payload["reportId"] == "55555555-5555-4555-8555-555555555555"


def test_payload_caps_operations_and_counts_what_it_dropped():
    """An alert enumerating four hundred operations is one nobody reads — but nothing is hidden."""
    operations = [_operation(f"GET /r{i}") for i in range(MAX_ALERT_OPERATIONS + 7)]
    payload = build_alert_payload(
        event="verification.drift.detected",
        reason=ALERT_REASON_TRANSITION,
        schedule=_schedule(),
        outcome=TickOutcome(status=STATUS_FAILED, report=_report(operations, [])),
        previous_status=STATUS_PASSED,
        consecutive_failures=1,
        occurred_at=_NOW,
    )
    assert len(payload["operations"]) == MAX_ALERT_OPERATIONS
    assert payload["operationsTruncated"] is True
    assert payload["operationsTotal"] == MAX_ALERT_OPERATIONS + 7


def test_payload_caps_drift_per_operation_and_counts_it():
    """The same reasoning one level down."""
    operation = _operation("GET /pets", drift_count=MAX_ALERT_DRIFT_PER_OPERATION + 3)
    payload = build_alert_payload(
        event="verification.drift.detected",
        reason=ALERT_REASON_TRANSITION,
        schedule=_schedule(),
        outcome=TickOutcome(status=STATUS_FAILED, report=_report([operation], [])),
        previous_status=STATUS_PASSED,
        consecutive_failures=1,
        occurred_at=_NOW,
    )
    entry = payload["operations"][0]
    assert len(entry["drift"]) == MAX_ALERT_DRIFT_PER_OPERATION
    assert entry["driftTruncated"] is True
    assert entry["driftTotal"] == MAX_ALERT_DRIFT_PER_OPERATION + 3


def test_payload_bounds_deployment_controlled_strings():
    """The message originates in a response body the deployment controls, so it is bounded."""
    huge = "x" * (MAX_ALERT_MESSAGE_CHARS * 3)
    operation = OperationConformance(
        operation_key="GET /pets",
        http_method="GET",
        http_path="/pets",
        outcome=STATUS_FAILED,
        exercised=True,
        cases_total=1,
        cases_passed=0,
        cases_failed=1,
        cases_errored=0,
        cases_skipped=0,
        drift=[_drift(message=huge, actual=huge)],
    )
    payload = build_alert_payload(
        event="verification.drift.detected",
        reason=ALERT_REASON_TRANSITION,
        schedule=_schedule(),
        outcome=TickOutcome(status=STATUS_FAILED, report=_report([operation], [])),
        previous_status=STATUS_PASSED,
        consecutive_failures=1,
        occurred_at=_NOW,
    )
    entry = payload["operations"][0]["drift"][0]
    assert len(entry["message"]) <= MAX_ALERT_MESSAGE_CHARS
    assert len(entry["actual"]) <= MAX_ALERT_MESSAGE_CHARS


def test_payload_for_a_run_that_could_not_happen_says_so():
    """No report to summarise, so the alert carries the refusal instead of an empty green shape."""
    payload = build_alert_payload(
        event="verification.drift.detected",
        reason=ALERT_REASON_TRANSITION,
        schedule=_schedule(last_success_at=None),
        outcome=TickOutcome(
            status=STATUS_ERRORED,
            error_code="FORMAT_MISMATCH",
            error_message="No contract suite could be compiled for this version.",
        ),
        previous_status=STATUS_PASSED,
        consecutive_failures=1,
        occurred_at=_NOW,
    )
    assert payload["status"] == STATUS_ERRORED
    assert payload["errorCode"] == "FORMAT_MISMATCH"
    assert payload["operations"] == []
    assert payload["coverage"] == {}
    # Never verified clean: the payload must not claim a freshness it does not have.
    assert "freshnessSeconds" not in payload
    assert "lastSuccessAt" not in payload


def test_most_drift_first_survives_truncation():
    """The operation with the most to say is the one a truncated list keeps."""
    operations = [
        _operation("GET /quiet", drift_count=1),
        _operation("GET /loud", drift_count=9),
    ]
    payload = build_alert_payload(
        event="verification.drift.detected",
        reason=ALERT_REASON_TRANSITION,
        schedule=_schedule(),
        outcome=TickOutcome(status=STATUS_FAILED, report=_report(operations, [])),
        previous_status=STATUS_PASSED,
        consecutive_failures=1,
        occurred_at=_NOW,
    )
    assert payload["operations"][0]["operationKey"] == "GET /loud"


# ---------------------------------------------------------------------------------------------
# Row adaptation and tick summary
# ---------------------------------------------------------------------------------------------


def test_summarize_tick_reads_the_counts_from_the_report():
    """A stored history row can never contradict the report it points at."""
    report = _report([_operation("GET /pets")], [_drift(), _drift(pointer="/name")])
    summary = summarize_tick(TickOutcome(status=STATUS_FAILED, report=report))
    assert summary["operations_total"] == 40
    assert summary["operations_failed"] == 1
    assert summary["coverage_percent"] == 50.0
    assert summary["drift_count"] == 2


def test_summarize_tick_of_a_run_that_produced_nothing_is_all_zero():
    """Zero coverage is the honest reading of a run that never happened."""
    summary = summarize_tick(TickOutcome(status=STATUS_ERRORED, error_code="FORMAT_MISMATCH"))
    assert set(summary.values()) == {0, 0.0}


def test_record_from_row_computes_freshness_and_survives_unknown_options():
    """A stored options blob from a newer build must not silence the monitor."""
    record = record_from_row(
        {
            "id": "77777777-7777-4777-8777-777777777777",
            "tenant_id": "11111111-1111-4111-8111-111111111111",
            "slug": "petstore-staging",
            "name": "Petstore",
            "version_ref": "project/petstore/1.0.0",
            "target_id": "22222222-2222-4222-8222-222222222222",
            "target_slug": "staging",
            "cadence_seconds": 3600,
            "enabled": True,
            "alert_on_recovery": True,
            "verification": {"allow_mutating": False, "unknown_future_key": 1},
            "suite_options": {"seed": 7},
            "last_success_at": _NOW - timedelta(minutes=30),
            "alert_state": ALERT_STATE_ALERTING,
        },
        now=_NOW,
    )
    assert record.freshness_seconds == 1800
    assert record.alert_state == ALERT_STATE_ALERTING
    # The unreadable blob fell back to defaults rather than raising.
    assert record.verification.allow_mutating is False
    assert record.options.seed == 7


def test_tick_duration_is_zero_when_the_tick_was_not_timed():
    """A tick with no clock is reported as zero, never as a negative or an exception."""
    assert TickOutcome(status=STATUS_ERRORED).duration_ms == 0
    timed = TickOutcome(
        status=STATUS_PASSED, started_at=_NOW, finished_at=_NOW + timedelta(seconds=3)
    )
    assert timed.duration_ms == 3000
