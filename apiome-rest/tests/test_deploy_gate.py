"""The deploy-gate rules — CTG-4.5 (#4502).

:mod:`app.deploy_gate` is the whole ticket as a pure function: four measurements in, one verdict
out. These tests pin the decisions that are easy to relax by accident and expensive to discover in
production — the partial-inputs rule, the two-rung thresholds, and the difference between "nothing
is configured", "I could not read it", and "it passed".
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.consumer_impact import ConsumerImpactReport
from app.deploy_gate import (
    DEFAULT_THRESHOLDS,
    GATE_SIGNALS,
    REASON_BREAKING_CLASSIFICATION_FAILED,
    REASON_BREAKING_INITIAL_PUBLICATION,
    REASON_BREAKING_NOT_CLASSIFIED,
    REASON_BREAKING_PRESENT,
    REASON_CONSUMERS_BREAKING,
    REASON_CONSUMERS_NONE_REGISTERED,
    REASON_LINT_BELOW_FAIL,
    REASON_LINT_BELOW_WARN,
    REASON_LINT_NOT_CAPTURED,
    REASON_VERIFICATION_NEVER_RUN,
    REASON_VERIFICATION_NEVER_SUCCEEDED,
    REASON_VERIFICATION_STALE_FAIL,
    REASON_VERIFICATION_STALE_WARN,
    REASON_VERIFICATION_UNHEALTHY,
    SIGNAL_BREAKING,
    SIGNAL_CONSUMERS,
    SIGNAL_LINT,
    SIGNAL_VERIFICATION,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    STATUS_WARN,
    BreakingThresholds,
    ConsumerThresholds,
    DeployGatePolicyOut,
    DeployGateThresholds,
    GateSignal,
    GateThresholdError,
    LintThresholds,
    VerificationThresholds,
    build_gate_report,
    canonical_thresholds_body,
    evaluate_breaking,
    evaluate_consumers,
    evaluate_lint,
    evaluate_verification,
    overall_status,
    status_counts,
    thresholds_content_fingerprint,
    thresholds_from_body,
    unavailable_signal,
)

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _policy() -> DeployGatePolicyOut:
    """The default policy, as a response would carry it."""
    return DeployGatePolicyOut(
        source="default",
        content_fingerprint=thresholds_content_fingerprint(DEFAULT_THRESHOLDS),
        thresholds=DEFAULT_THRESHOLDS,
    )


def _consumer_report(**counts) -> ConsumerImpactReport:
    """A consumer-impact report carrying only the tallies the gate reads."""
    tallies = {
        "consumers_total": 0,
        "consumers_declared": 0,
        "consumers_undeclared": 0,
        "consumers_affected": 0,
        "consumers_breaking": 0,
    }
    tallies.update(counts)
    return ConsumerImpactReport(
        summary="breaks 0 of 0 consumers",
        counts=tallies,
        consumers=[],
        breaking_consumers=[],
        attribution=[],
    )


# ---------------------------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------------------------


def test_default_thresholds_gate_on_breaking_and_broken_consumers():
    """The documented default has teeth: nothing hangs off this endpoint that could break."""
    assert DEFAULT_THRESHOLDS.breaking.fail_at_severity == "breaking"
    assert DEFAULT_THRESHOLDS.consumers.fail_above_breaking == 0
    assert DEFAULT_THRESHOLDS.lint.warn_below_grade == "B"
    assert DEFAULT_THRESHOLDS.verification.warn_after_seconds == 86_400


def test_a_body_naming_one_threshold_leaves_the_rest_at_their_defaults():
    """Configuring one rung must not silently unset the other seven."""
    thresholds = thresholds_from_body({"lint": {"failBelowGrade": "B"}})
    assert thresholds.lint.fail_below_grade == "B"
    assert thresholds.lint.warn_below_grade == DEFAULT_THRESHOLDS.lint.warn_below_grade
    assert thresholds.verification == DEFAULT_THRESHOLDS.verification


def test_snake_case_is_accepted_as_well_as_camel_case():
    """Both spellings parse, so a hand-written CI payload is not a puzzle."""
    assert thresholds_from_body({"lint": {"fail_below_grade": "C"}}).lint.fail_below_grade == "C"


def test_null_disables_a_rung_rather_than_restoring_its_default():
    """`null` and "absent" mean different things — this is why the body is JSON, not columns."""
    thresholds = thresholds_from_body({"breaking": {"failAtSeverity": None}})
    assert thresholds.breaking.fail_at_severity is None


def test_an_unknown_grade_letter_is_refused():
    """A typo'd threshold must not silently become "no threshold"."""
    with pytest.raises(GateThresholdError) as excinfo:
        thresholds_from_body({"lint": {"failBelowGrade": "Z"}})
    assert "lint.failBelowGrade" in str(excinfo.value)


def test_a_warn_rung_that_can_never_fire_is_refused():
    """Warning below D while failing below B means the warn branch is dead code."""
    with pytest.raises(GateThresholdError):
        thresholds_from_body({"lint": {"warnBelowGrade": "D", "failBelowGrade": "B"}})
    with pytest.raises(GateThresholdError):
        thresholds_from_body(
            {"breaking": {"warnAtSeverity": "breaking", "failAtSeverity": "non-breaking"}}
        )
    with pytest.raises(GateThresholdError):
        thresholds_from_body(
            {"verification": {"warnAfterSeconds": 100, "failAfterSeconds": 10}}
        )


def test_an_unknown_key_is_refused_rather_than_ignored():
    """A misspelled threshold that is silently dropped is a policy nobody set."""
    with pytest.raises(GateThresholdError):
        thresholds_from_body({"lint": {"failBelowGade": "C"}})


def test_the_fingerprint_covers_every_threshold_even_the_defaulted_ones():
    """A stored policy must keep meaning the same thing after a release changes a default."""
    body = canonical_thresholds_body(DEFAULT_THRESHOLDS)
    assert set(body) == {"schemaVersion", "lint", "breaking", "consumers", "verification"}
    assert body["lint"] == {"warnBelowGrade": "B", "failBelowGrade": "D"}

    moved = thresholds_from_body({"lint": {"failBelowGrade": "C"}})
    assert thresholds_content_fingerprint(moved) != thresholds_content_fingerprint(
        DEFAULT_THRESHOLDS
    )
    assert thresholds_content_fingerprint(
        thresholds_from_body(canonical_thresholds_body(moved))
    ) == thresholds_content_fingerprint(moved)


# ---------------------------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------------------------


def test_a_revision_that_was_never_linted_is_not_configured_not_passing():
    """The partial-inputs rule: an absent signal is excluded, never green."""
    signal = evaluate_lint(grade=None, score=None, thresholds=LintThresholds())
    assert signal.status == STATUS_NOT_CONFIGURED
    assert signal.reason == REASON_LINT_NOT_CAPTURED
    assert signal.satisfied is None


def test_lint_grade_below_the_fail_rung_fails_and_below_the_warn_rung_warns():
    """Fail is checked first: a grade below both rungs is a failure, not a warning."""
    thresholds = LintThresholds(warn_below_grade="B", fail_below_grade="D")
    assert evaluate_lint(grade="F", score=12, thresholds=thresholds).reason == (
        REASON_LINT_BELOW_FAIL
    )
    assert evaluate_lint(grade="C", score=75, thresholds=thresholds).reason == (
        REASON_LINT_BELOW_WARN
    )
    assert evaluate_lint(grade="A", score=95, thresholds=thresholds).status == STATUS_PASS


def test_a_disabled_lint_rung_stops_firing():
    """`null` really means "do not gate on this"."""
    thresholds = LintThresholds(warn_below_grade=None, fail_below_grade=None)
    assert evaluate_lint(grade="F", score=0, thresholds=thresholds).status == STATUS_PASS


def test_an_unrecognised_stored_grade_is_unknown_not_a_pass():
    """A grade this release cannot rank is missing information, not reassurance."""
    signal = evaluate_lint(grade="A+", score=None, thresholds=LintThresholds())
    assert signal.status == STATUS_UNKNOWN


# ---------------------------------------------------------------------------------------------
# Breaking
# ---------------------------------------------------------------------------------------------


def test_an_unclassified_publish_is_not_configured():
    """Nothing has classified it yet — the endpoint ships before every project has."""
    signal = evaluate_breaking(
        status=None, max_severity=None, thresholds=BreakingThresholds()
    )
    assert (signal.status, signal.reason) == (
        STATUS_NOT_CONFIGURED,
        REASON_BREAKING_NOT_CLASSIFIED,
    )


def test_a_failed_classification_is_unknown_not_not_configured():
    """"I tried and could not" is a different fact from "nobody has tried"."""
    signal = evaluate_breaking(
        status="failed", max_severity=None, thresholds=BreakingThresholds()
    )
    assert (signal.status, signal.reason) == (
        STATUS_UNKNOWN,
        REASON_BREAKING_CLASSIFICATION_FAILED,
    )


def test_a_first_publication_passes_because_there_is_nothing_to_break():
    """An initial publication has no predecessor, so it cannot be breaking."""
    signal = evaluate_breaking(
        status="initial", max_severity=None, thresholds=BreakingThresholds()
    )
    assert (signal.status, signal.reason) == (
        STATUS_PASS,
        REASON_BREAKING_INITIAL_PUBLICATION,
    )


def test_a_breaking_publish_fails_under_the_default_policy():
    """The default bar: a breaking change blocks promotion until a tenant says otherwise."""
    signal = evaluate_breaking(
        status="ready",
        max_severity="breaking",
        counts={"breaking": 3, "total": 9},
        baseline_version_label="1.0.0",
        thresholds=BreakingThresholds(),
    )
    assert (signal.status, signal.reason) == (STATUS_FAIL, REASON_BREAKING_PRESENT)
    assert "1.0.0" in signal.detail
    assert signal.data["counts"]["breaking"] == 3


def test_a_tenant_can_stop_gating_on_whole_spec_breaking():
    """Setting the rung to null is how a tenant leans on the consumer signal instead."""
    signal = evaluate_breaking(
        status="ready",
        max_severity="breaking",
        thresholds=BreakingThresholds(fail_at_severity=None),
    )
    assert signal.status == STATUS_PASS


def test_a_non_breaking_publish_can_be_made_to_warn():
    """The warn rung exists so "something changed" is reportable without blocking."""
    signal = evaluate_breaking(
        status="ready",
        max_severity="non-breaking",
        thresholds=BreakingThresholds(warn_at_severity="non-breaking"),
    )
    assert signal.status == STATUS_WARN


# ---------------------------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------------------------


def test_a_project_with_no_registered_consumers_is_not_configured():
    """"Breaks 0 of 0" is not a reassurance, so it is excluded rather than counted as a pass."""
    signal = evaluate_consumers(
        report=_consumer_report(), thresholds=ConsumerThresholds()
    )
    assert (signal.status, signal.reason) == (
        STATUS_NOT_CONFIGURED,
        REASON_CONSUMERS_NONE_REGISTERED,
    )


def test_one_broken_consumer_fails_under_the_default_tolerance():
    """`failAboveBreaking: 0` means a single broken consumer trips the gate."""
    report = _consumer_report(
        consumers_total=7, consumers_declared=7, consumers_affected=2, consumers_breaking=2
    )
    signal = evaluate_consumers(report=report, thresholds=ConsumerThresholds())
    assert (signal.status, signal.reason) == (STATUS_FAIL, REASON_CONSUMERS_BREAKING)


def test_affected_but_unbroken_consumers_warn():
    """A change that touches a consumer without breaking it is worth saying, not blocking."""
    report = _consumer_report(
        consumers_total=7, consumers_declared=7, consumers_affected=3, consumers_breaking=0
    )
    signal = evaluate_consumers(report=report, thresholds=ConsumerThresholds())
    assert signal.status == STATUS_WARN


def test_the_undeclared_count_is_reported_beside_the_verdict_not_inside_it():
    """CTG-4.2's denominator rule: a consumer with no contract is never counted as safe."""
    report = _consumer_report(
        consumers_total=7,
        consumers_declared=5,
        consumers_undeclared=2,
        consumers_affected=0,
        consumers_breaking=0,
    )
    signal = evaluate_consumers(report=report, thresholds=ConsumerThresholds())
    assert signal.status == STATUS_PASS
    assert "2 registered consumers have declared no surface" in signal.detail
    assert signal.data["counts"]["consumers_undeclared"] == 2


# ---------------------------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------------------------


def test_a_never_verified_deployment_is_not_configured():
    """Nothing has verified it, so freshness is not part of the verdict."""
    signal = evaluate_verification(
        source=None,
        freshness_seconds=None,
        last_status=None,
        thresholds=VerificationThresholds(),
    )
    assert (signal.status, signal.reason) == (
        STATUS_NOT_CONFIGURED,
        REASON_VERIFICATION_NEVER_RUN,
    )


def test_a_recent_failure_fails_regardless_of_how_fresh_the_last_success_was():
    """The most alarming fact wins: a passing check an hour ago does not undo a failure now."""
    signal = evaluate_verification(
        source="schedule",
        freshness_seconds=60,
        last_status="failed",
        thresholds=VerificationThresholds(),
    )
    assert (signal.status, signal.reason) == (STATUS_FAIL, REASON_VERIFICATION_UNHEALTHY)


def test_unknown_freshness_is_never_read_as_fresh():
    """CTG-4.4's rule, kept where it matters: null freshness warns, it does not pass."""
    signal = evaluate_verification(
        source="schedule",
        freshness_seconds=None,
        last_status=None,
        thresholds=VerificationThresholds(),
    )
    assert (signal.status, signal.reason) == (
        STATUS_WARN,
        REASON_VERIFICATION_NEVER_SUCCEEDED,
    )


def test_unknown_freshness_passes_only_when_the_tenant_gates_on_neither_rung():
    """With both staleness rungs disabled, the tenant has said age is not their concern."""
    signal = evaluate_verification(
        source="schedule",
        freshness_seconds=None,
        last_status=None,
        thresholds=VerificationThresholds(
            warn_after_seconds=None, fail_after_seconds=None
        ),
    )
    assert signal.status == STATUS_PASS


def test_staleness_crosses_the_warn_then_the_fail_rung():
    """The two rungs make one measurement produce three outcomes."""
    thresholds = VerificationThresholds(warn_after_seconds=3600, fail_after_seconds=86_400)
    fresh = evaluate_verification(
        source="schedule", freshness_seconds=60, last_status="passed", thresholds=thresholds
    )
    warned = evaluate_verification(
        source="schedule", freshness_seconds=7_200, last_status="passed", thresholds=thresholds
    )
    failed = evaluate_verification(
        source="schedule",
        freshness_seconds=200_000,
        last_status="passed",
        thresholds=thresholds,
    )
    assert fresh.status == STATUS_PASS
    assert (warned.status, warned.reason) == (STATUS_WARN, REASON_VERIFICATION_STALE_WARN)
    assert (failed.status, failed.reason) == (STATUS_FAIL, REASON_VERIFICATION_STALE_FAIL)
    assert "2 hours" in warned.detail


def test_a_muted_unhealthy_run_falls_through_to_the_staleness_rungs():
    """`failOnUnhealthyRun: false` keeps the age judgment; it does not disable the signal."""
    signal = evaluate_verification(
        source="schedule",
        freshness_seconds=60,
        last_status="failed",
        thresholds=VerificationThresholds(fail_on_unhealthy_run=False),
    )
    assert signal.status == STATUS_PASS


# ---------------------------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------------------------


def _signal(name: str, status: str) -> GateSignal:
    """A judged signal with the given status."""
    return GateSignal(
        signal=name, status=status, satisfied=status == STATUS_PASS, reason="x", detail="x"
    )


def test_the_verdict_is_the_worst_evaluated_signal():
    """Three statuses, one rank order, no other input."""
    assert overall_status([_signal(SIGNAL_LINT, STATUS_PASS)]) == STATUS_PASS
    assert (
        overall_status([_signal(SIGNAL_LINT, STATUS_PASS), _signal(SIGNAL_BREAKING, STATUS_WARN)])
        == STATUS_WARN
    )
    assert (
        overall_status(
            [_signal(SIGNAL_LINT, STATUS_WARN), _signal(SIGNAL_BREAKING, STATUS_FAIL)]
        )
        == STATUS_FAIL
    )


def test_unconfigured_and_unknown_signals_never_fail_the_gate():
    """The acceptance criterion, stated as an assertion."""
    signals = [
        _signal(SIGNAL_LINT, STATUS_PASS),
        _signal(SIGNAL_BREAKING, STATUS_NOT_CONFIGURED),
        _signal(SIGNAL_CONSUMERS, STATUS_UNKNOWN),
    ]
    assert overall_status(signals) == STATUS_PASS
    counts = status_counts(signals)
    assert counts[STATUS_NOT_CONFIGURED] == 1
    assert counts[STATUS_UNKNOWN] == 1
    assert counts[STATUS_FAIL] == 0


def test_a_gate_with_nothing_to_judge_says_so_rather_than_vouching():
    """`status` is `pass` by the partial-inputs rule, so `evaluatedSignals` carries the truth."""
    report = build_gate_report(
        project_id="p",
        project_slug="petstore",
        revision_id="r",
        version_label="1.0.0",
        version_ref="project/petstore/1.0.0",
        published_at=_NOW,
        signals=[
            unavailable_signal(
                name, status=STATUS_NOT_CONFIGURED, reason="x", detail="x"
            )
            for name in GATE_SIGNALS
        ],
        policy=_policy(),
        evaluated_at=_NOW,
    )
    assert report.status == STATUS_PASS
    assert report.evaluated_signals == 0
    assert "nothing vouches for it" in report.summary


def test_the_report_always_carries_all_four_signals_in_a_fixed_order():
    """A diff of two gate responses must line up, whatever order the service gathered them in."""
    report = build_gate_report(
        project_id="p",
        project_slug="petstore",
        revision_id="r",
        version_label="1.0.0",
        version_ref="project/petstore/1.0.0",
        published_at=_NOW,
        signals=[
            _signal(SIGNAL_VERIFICATION, STATUS_PASS),
            _signal(SIGNAL_CONSUMERS, STATUS_FAIL),
            _signal(SIGNAL_BREAKING, STATUS_PASS),
            _signal(SIGNAL_LINT, STATUS_WARN),
        ],
        policy=_policy(),
        evaluated_at=_NOW,
    )
    assert [s.signal for s in report.signals] == list(GATE_SIGNALS)
    assert report.status == STATUS_FAIL
    assert report.evaluated_signals == 4
    assert "consumers" in report.summary


def test_the_wire_body_is_camel_case_and_carries_the_policy_fingerprint():
    """CI reads this with `jq`; the keys are part of the contract."""
    report = build_gate_report(
        project_id="p",
        project_slug="petstore",
        revision_id="r",
        version_label="1.0.0",
        version_ref="project/petstore/1.0.0",
        published_at=_NOW,
        signals=[_signal(SIGNAL_LINT, STATUS_PASS)],
        policy=_policy(),
        evaluated_at=_NOW,
    )
    body = report.model_dump(by_alias=True, mode="json")
    assert body["schemaVersion"] == "ctg.gate.v1"
    assert body["evaluatedSignals"] == 1
    assert body["versionRef"] == "project/petstore/1.0.0"
    assert body["policy"]["contentFingerprint"].startswith("sha256:")
    assert body["policy"]["thresholds"]["lint"]["warnBelowGrade"] == "B"


def test_thresholds_round_trip_through_their_own_wire_shape():
    """A body read back from the store must parse into the same policy it was saved from."""
    original = DeployGateThresholds(
        lint=LintThresholds(warn_below_grade="A", fail_below_grade="C"),
        verification=VerificationThresholds(fail_on_unhealthy_run=False),
    )
    assert thresholds_from_body(canonical_thresholds_body(original)) == original
