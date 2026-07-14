"""Unit tests for the multi-axis score and coverage model (CLX-1.2, #4849).

Pins :mod:`app.axis_score`: deterministic axis mapping, not-assessed vs clean (zero findings),
partial-coverage / required-coverage composite behaviour, and algorithm versioning.
"""

from __future__ import annotations

from app.axis_score import (
    ALGORITHM_ID,
    ALGORITHM_VERSION,
    AXIS_COMPATIBILITY,
    AXIS_KEYS,
    AXIS_PROTOCOL,
    AXIS_QUALITY,
    AXIS_SECURITY,
    AXIS_SUPPLY_CHAIN,
    AXIS_SUPPORTABILITY,
    REASON_COMPAT_NO_BASE,
    REASON_SECURITY_CATALOG,
    catalog_axis_evaluation,
    evaluate_axes,
    grade_for_score,
    mcp_axis_evaluation,
    score_from_finding_dicts,
)
from app.lint_evidence import SUBJECT_CATALOG_REVISION, SUBJECT_MCP_ENDPOINT_VERSION


def _report(**overrides):
    base = {
        "score": 90,
        "grade": "A",
        "findings": [],
        "severity_counts": {"error": 0, "warning": 0, "info": 0},
        "report_fingerprint": "fp-clean",
    }
    base.update(overrides)
    return base


def _by_key(evaluation):
    return {a["key"]: a for a in evaluation.axes}


def test_algorithm_identity_is_versioned():
    ev = catalog_axis_evaluation(_report())
    assert ev.algorithm_id == ALGORITHM_ID == "clx-axis-v1"
    assert ev.algorithm_version == ALGORITHM_VERSION
    assert ev.source_report_fingerprint == "fp-clean"


def test_canonical_axis_order():
    ev = catalog_axis_evaluation(_report())
    assert tuple(a["key"] for a in ev.axes) == AXIS_KEYS


def test_quality_maps_legacy_score_and_grade():
    ev = catalog_axis_evaluation(_report(score=82, grade="B"))
    quality = _by_key(ev)[AXIS_QUALITY]
    assert quality["assessed"] is True
    assert quality["score"] == 82
    assert quality["grade"] == "B"
    assert quality["coverage"]["state"] == "full"
    assert quality["not_assessed_reason"] is None


def test_not_assessed_is_distinct_from_clean_zero_findings():
    """A scored MCP security axis with no security findings is clean (100), not a gap."""
    ev = mcp_axis_evaluation(_report(score=100, grade="A", findings=[]))
    axes = _by_key(ev)

    security = axes[AXIS_SECURITY]
    assert security["assessed"] is True
    assert security["score"] == 100
    assert security["grade"] == "A"
    assert security["severity_counts"] == {"error": 0, "warning": 0, "info": 0}
    assert security["not_assessed_reason"] is None

    protocol = axes[AXIS_PROTOCOL]
    assert protocol["assessed"] is False
    assert protocol["score"] is None
    assert protocol["coverage"]["state"] == "none"
    assert protocol["not_assessed_reason"]


def test_catalog_security_is_not_assessed():
    ev = catalog_axis_evaluation(_report())
    security = _by_key(ev)[AXIS_SECURITY]
    assert security["assessed"] is False
    assert security["not_assessed_reason"] == REASON_SECURITY_CATALOG


def test_mcp_security_scores_security_category_findings():
    findings = [
        {
            "rule": "security.tool-token-passthrough-parameter",
            "category": "security",
            "severity": "warning",
            "message": "token passthrough",
        },
        {
            "rule": "naming.missing-name",
            "category": "naming",
            "severity": "error",
            "message": "missing name",
        },
    ]
    ev = mcp_axis_evaluation(_report(score=80, grade="B", findings=findings))
    axes = _by_key(ev)

    security = axes[AXIS_SECURITY]
    assert security["assessed"] is True
    assert security["score"] == score_from_finding_dicts([findings[0]])
    assert security["severity_counts"]["warning"] == 1
    assert security["severity_counts"]["error"] == 0


def test_compatibility_assessed_only_when_base_comparison_present():
    findings = [
        {
            "rule": "compatibility.breaking",
            "category": "compatibility",
            "severity": "error",
            "message": "removed field",
        }
    ]
    without = catalog_axis_evaluation(_report(findings=findings))
    assert _by_key(without)[AXIS_COMPATIBILITY]["assessed"] is False
    assert _by_key(without)[AXIS_COMPATIBILITY]["not_assessed_reason"] == REASON_COMPAT_NO_BASE

    with_base = catalog_axis_evaluation(
        _report(findings=findings, base_revision_id="base-1", compatibility_overall="breaking")
    )
    compat = _by_key(with_base)[AXIS_COMPATIBILITY]
    assert compat["assessed"] is True
    assert compat["score"] < 100
    assert compat["severity_counts"]["error"] == 1


def test_mcp_compatibility_always_not_assessed():
    ev = mcp_axis_evaluation(
        _report(base_revision_id="x", compatibility_overall="safe")
    )
    assert _by_key(ev)[AXIS_COMPATIBILITY]["assessed"] is False


def test_scanner_pending_axes_are_not_assessed():
    ev = catalog_axis_evaluation(_report())
    axes = _by_key(ev)
    for key in (AXIS_PROTOCOL, AXIS_SUPPLY_CHAIN, AXIS_SUPPORTABILITY):
        assert axes[key]["assessed"] is False
        assert axes[key]["score"] is None
        assert axes[key]["coverage"]["state"] == "none"


def test_composite_null_when_quality_missing():
    ev = evaluate_axes(
        {"findings": [], "report_fingerprint": "fp"},
        subject_type=SUBJECT_CATALOG_REVISION,
    )
    assert _by_key(ev)[AXIS_QUALITY]["assessed"] is False
    assert ev.required_coverage_met is False
    assert ev.composite_score is None
    assert ev.composite_grade is None


def test_composite_equals_quality_when_only_quality_assessed():
    ev = catalog_axis_evaluation(_report(score=88, grade="B"))
    assert ev.required_coverage_met is True
    assert ev.composite_score == 88
    assert ev.composite_grade == "B"


def test_composite_means_assessed_axes_only():
    findings = [
        {
            "rule": "security.ssrf-risky-resource-uri",
            "category": "security",
            "severity": "error",
            "message": "ssrf",
        }
    ]
    # quality 100, security scored from one error (penalty 10 => 90)
    ev = mcp_axis_evaluation(_report(score=100, grade="A", findings=findings))
    security_score = _by_key(ev)[AXIS_SECURITY]["score"]
    assert ev.composite_score == round((100 + security_score) / 2)
    assert ev.composite_grade == grade_for_score(ev.composite_score)


def test_evaluate_axes_is_deterministic():
    report = _report(
        findings=[
            {
                "rule": "security.over-broad-auth-scope",
                "category": "security",
                "severity": "warning",
                "message": "scope",
            }
        ]
    )
    a = mcp_axis_evaluation(report)
    b = mcp_axis_evaluation(report)
    assert a.as_dict() == b.as_dict()


def test_grade_for_score_bands():
    assert grade_for_score(100) == "A"
    assert grade_for_score(90) == "A"
    assert grade_for_score(80) == "B"
    assert grade_for_score(70) == "C"
    assert grade_for_score(60) == "D"
    assert grade_for_score(59) == "F"


def test_empty_finding_set_scores_clean_not_gap():
    assert score_from_finding_dicts([]) == 100
