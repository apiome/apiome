"""Unit tests for policy pack evaluation and waiver semantics (CLX-1.3, #4850)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.policy_evaluate import (
    DEFAULT_CI_OUTCOMES,
    DEFAULT_REQUIRED_COVERAGE,
    effective_decision_state,
    evaluate_policy,
    grade_meets_minimum,
    match_decision_for_fingerprint,
    policy_content_fingerprint,
    rules_snapshot_from_rows,
)


def _finding(**overrides):
    base = {
        "source_fingerprint": "lint-abc",
        "rule_id": "naming.schema-pascal-case",
        "severity": "error",
        "message": "bad name",
    }
    base.update(overrides)
    return base


def _axes(quality_assessed=True, quality_grade="A", quality_score=95):
    return [
        {
            "key": "quality",
            "assessed": quality_assessed,
            "grade": quality_grade if quality_assessed else None,
            "score": quality_score if quality_assessed else None,
        },
        {"key": "protocol", "assessed": False, "grade": None, "score": None},
    ]


def test_defaults_match_acceptance_gates():
    assert DEFAULT_REQUIRED_COVERAGE == ("quality",)
    assert DEFAULT_CI_OUTCOMES["failOnUnwaivedErrors"] is True
    assert DEFAULT_CI_OUTCOMES["failOnRequiredCoverage"] is True
    assert DEFAULT_CI_OUTCOMES["failOnAxisGates"] is True


def test_policy_content_fingerprint_is_stable():
    rules = rules_snapshot_from_rows(
        [{"rule_id": "a", "enabled": True, "severity": "error"}]
    )
    fp1 = policy_content_fingerprint(
        rules_snapshot=rules,
        axis_gates={"quality": {"minGrade": "B"}},
        required_coverage=["quality"],
        ci_outcomes=DEFAULT_CI_OUTCOMES,
    )
    fp2 = policy_content_fingerprint(
        rules_snapshot=rules,
        axis_gates={"quality": {"minGrade": "B"}},
        required_coverage=["quality"],
        ci_outcomes=dict(DEFAULT_CI_OUTCOMES),
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_expired_waiver_reopens_to_open():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    decision = {
        "state": "waived",
        "expires_at": now - timedelta(days=1),
        "rationale": "temp",
    }
    assert effective_decision_state(decision, now=now) == "open"


def test_active_waiver_stays_waived():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    decision = {
        "state": "waived",
        "expires_at": now + timedelta(days=30),
        "rationale": "accepted risk",
    }
    assert effective_decision_state(decision, now=now) == "waived"


def test_missing_finding_reopens_waiver():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    decision = {
        "state": "waived",
        "expires_at": now + timedelta(days=30),
        "rationale": "accepted risk",
    }
    assert (
        effective_decision_state(decision, now=now, finding_present=False) == "open"
    )


def test_unwaived_error_fails_gate():
    ev = evaluate_policy(
        findings=[_finding()],
        decisions_by_fingerprint={},
        axes=_axes(),
    )
    assert ev.passed is False
    assert ev.gate_results["unwaived_errors"]["passed"] is False
    assert ev.finding_decisions[0]["effective_state"] == "open"
    assert ev.finding_decisions[0]["waived"] is False
    assert ev.finding_decisions[0]["raw_severity"] == "error"


def test_active_waiver_suppresses_error_gate():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    decision = {
        "state": "waived",
        "expires_at": now + timedelta(days=7),
        "rationale": "ticket-1",
        "source_fingerprint": "lint-abc",
    }
    ev = evaluate_policy(
        findings=[_finding()],
        decisions_by_fingerprint={"lint-abc": decision},
        axes=_axes(),
        now=now,
    )
    assert ev.gate_results["unwaived_errors"]["passed"] is True
    assert ev.finding_decisions[0]["waived"] is True
    assert ev.finding_decisions[0]["effective_state"] == "waived"
    assert ev.passed is True


def test_expired_waiver_fails_unwaived_errors_again():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    decision = {
        "state": "waived",
        "expires_at": now - timedelta(hours=1),
        "rationale": "old",
        "source_fingerprint": "lint-abc",
    }
    ev = evaluate_policy(
        findings=[_finding()],
        decisions_by_fingerprint={"lint-abc": decision},
        axes=_axes(),
        now=now,
    )
    assert ev.gate_results["unwaived_errors"]["passed"] is False
    assert ev.finding_decisions[0]["effective_state"] == "open"
    assert ev.passed is False


def test_required_coverage_fails_when_quality_not_assessed():
    ev = evaluate_policy(
        findings=[],
        decisions_by_fingerprint={},
        axes=_axes(quality_assessed=False),
    )
    assert ev.gate_results["required_coverage"]["passed"] is False
    assert "quality" in ev.gate_results["required_coverage"]["detail"]["missing"]
    assert ev.passed is False


def test_axis_gate_min_grade():
    ev = evaluate_policy(
        findings=[],
        decisions_by_fingerprint={},
        axes=_axes(quality_grade="C", quality_score=72),
        axis_gates={"quality": {"minGrade": "B"}},
    )
    assert ev.gate_results["axis_gates"]["passed"] is False
    assert ev.passed is False

    ok = evaluate_policy(
        findings=[],
        decisions_by_fingerprint={},
        axes=_axes(quality_grade="A", quality_score=95),
        axis_gates={"quality": {"minGrade": "B"}},
    )
    assert ok.gate_results["axis_gates"]["passed"] is True
    assert ok.passed is True


def test_disabled_ci_outcome_skips_gate():
    ev = evaluate_policy(
        findings=[_finding()],
        decisions_by_fingerprint={},
        axes=_axes(quality_assessed=False),
        ci_outcomes={
            "failOnUnwaivedErrors": False,
            "failOnRequiredCoverage": False,
            "failOnAxisGates": True,
        },
    )
    assert ev.gate_results["unwaived_errors"]["passed"] is False
    assert ev.gate_results["required_coverage"]["passed"] is False
    assert ev.passed is True  # failing gates disabled


def test_grade_meets_minimum():
    assert grade_meets_minimum("A", "B") is True
    assert grade_meets_minimum("C", "B") is False
    assert grade_meets_minimum("B", "B") is True


def test_project_scoped_decision_beats_tenant():
    decisions = [
        {"source_fingerprint": "fp1", "project_id": None, "state": "open"},
        {"source_fingerprint": "fp1", "project_id": "proj-1", "state": "waived"},
    ]
    hit = match_decision_for_fingerprint(decisions, "fp1", project_id="proj-1")
    assert hit is not None
    assert hit["state"] == "waived"


def test_native_finding_id_used_as_fingerprint():
    ev = evaluate_policy(
        findings=[{"id": "lint-native", "rule": "x", "severity": "error", "message": "m"}],
        decisions_by_fingerprint={},
        axes=_axes(),
    )
    assert ev.finding_decisions[0]["source_fingerprint"] == "lint-native"
