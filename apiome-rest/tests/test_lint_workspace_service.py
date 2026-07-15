"""Pure-logic tests for the lint workspace service (CLX-4.1, #4859)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.lint_workspace import (
    ACTION_EDIT,
    ACTION_PUBLISH,
    WorkspaceValidationError,
    build_index_from_rows,
    build_summary,
    build_trends,
    facet_counts,
    filter_findings,
    normalize_filters,
    normalize_sort,
    paginate,
    required_action_for_transition,
    sort_findings,
    transition_error,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _run(
    run_id: str,
    *,
    scanner: str = "apiome.native-lint",
    version_record_id: str | None = "v1",
    mcp_version_id: str | None = None,
    findings: list | None = None,
    created_at: datetime = NOW,
    rn: int = 1,
    project_id: str | None = "p1",
    project_name: str | None = "Petstore",
    subject_label: str | None = "1.0.0",
    profile: str = "import-capture",
):
    """One row in the shape of ``list_latest_lint_evidence_runs_for_tenant``."""
    return {
        "id": run_id,
        "subject_type": "catalog_revision" if version_record_id else "mcp_endpoint_version",
        "version_record_id": version_record_id,
        "mcp_version_id": mcp_version_id,
        "scanner_id": scanner,
        "scanner_version": "1",
        "profile": profile,
        "outcome": "findings",
        "report_fingerprint": f"fp-{run_id}",
        "findings": findings or [],
        "coverage": {"state": "full"},
        "created_at": created_at,
        "project_id": project_id if version_record_id else None,
        "project_name": project_name if version_record_id else None,
        "publishable": True if version_record_id else None,
        "subject_label": subject_label,
        "rn": rn,
    }


def _finding(fp: str, *, severity: str = "error", category: str | None = None, rule: str = "r1"):
    return {
        "source_fingerprint": fp,
        "rule_id": rule,
        "message": f"message for {fp}",
        "severity": severity,
        "category": category,
        "location": {"path": "/pets"},
    }


# --- Index building ------------------------------------------------------------------------------


def test_index_merges_latest_run_per_scanner_and_flags_regressions():
    rows = [
        # Scanner A: latest run has f1 (old) + f2 (new); previous run had only f1.
        _run("run-a2", findings=[_finding("f1"), _finding("f2")], created_at=NOW, rn=1),
        _run(
            "run-a1",
            findings=[_finding("f1")],
            created_at=NOW - timedelta(days=1),
            rn=2,
        ),
        # Scanner B: first ever run — everything is new.
        _run(
            "run-b1",
            scanner="custom.linter",
            findings=[_finding("f3", severity="warning")],
            created_at=NOW - timedelta(hours=1),
            rn=1,
        ),
    ]
    index = build_index_from_rows(
        evidence_rows=rows, axis_rows=[], policy_rows=[], decisions=[], now=NOW
    )
    by_fp = {f["source_fingerprint"]: f for f in index["findings"]}
    assert set(by_fp) == {"f1", "f2", "f3"}
    assert by_fp["f1"]["is_new"] is False
    assert by_fp["f2"]["is_new"] is True
    assert by_fp["f3"]["is_new"] is True
    # Only the latest run per scanner contributes.
    assert by_fp["f1"]["evidence_run_id"] == "run-a2"
    assert by_fp["f3"]["scanner_id"] == "custom.linter"
    assert by_fp["f1"]["subject_label"] == "1.0.0"
    assert by_fp["f1"]["project_name"] == "Petstore"


def test_index_maps_findings_onto_axes():
    rows = [
        _run(
            "run-1",
            findings=[
                _finding("plain"),
                _finding("sec", category="security"),
                _finding("compat", category="compatibility"),
            ],
        ),
        _run(
            "run-2",
            scanner="apiome.mcp-conformance",
            version_record_id=None,
            mcp_version_id="mv1",
            subject_label="petstore-mcp",
            findings=[_finding("proto", category="readiness")],
        ),
        _run(
            "run-3",
            scanner="apiome.mcp-trust-posture",
            version_record_id=None,
            mcp_version_id="mv1",
            subject_label="petstore-mcp",
            findings=[_finding("supply", category="metadata")],
        ),
    ]
    index = build_index_from_rows(
        evidence_rows=rows, axis_rows=[], policy_rows=[], decisions=[], now=NOW
    )
    axis_by_fp = {f["source_fingerprint"]: f["axis_key"] for f in index["findings"]}
    assert axis_by_fp == {
        "plain": "quality",
        "sec": "security",
        "compat": "compatibility",
        "proto": "protocol",
        "supply": "supply_chain",
    }


def test_index_joins_decisions_project_scope_beats_tenant_and_expiry_reopens():
    findings = [_finding("f1"), _finding("f2")]
    rows = [_run("run-1", findings=findings)]
    decisions = [
        # Tenant-wide waiver for f1 (expired) — must read as open.
        {
            "id": "d1",
            "project_id": None,
            "source_fingerprint": "f1",
            "state": "waived",
            "rationale": "old",
            "expires_at": NOW - timedelta(days=1),
        },
        # Tenant-wide acknowledged for f2, overridden by a project-scoped waiver.
        {
            "id": "d2",
            "project_id": None,
            "source_fingerprint": "f2",
            "state": "acknowledged",
        },
        {
            "id": "d3",
            "project_id": "p1",
            "source_fingerprint": "f2",
            "state": "waived",
            "rationale": "scoped",
            "expires_at": NOW + timedelta(days=30),
        },
    ]
    index = build_index_from_rows(
        evidence_rows=rows, axis_rows=[], policy_rows=[], decisions=decisions, now=NOW
    )
    by_fp = {f["source_fingerprint"]: f for f in index["findings"]}
    assert by_fp["f1"]["effective_state"] == "open"
    assert by_fp["f1"]["waived"] is False
    assert by_fp["f2"]["effective_state"] == "waived"
    assert by_fp["f2"]["decision"]["id"] == "d3"


def test_index_attaches_axis_and_policy_rollups():
    rows = [_run("run-1", findings=[_finding("f1")])]
    axis_rows = [
        {
            "id": "ax1",
            "subject_type": "catalog_revision",
            "version_record_id": "v1",
            "mcp_version_id": None,
            "axes": [
                {"key": "quality", "assessed": True, "score": 90, "grade": "A",
                 "severity_counts": {"error": 1, "warning": 0, "info": 0}},
            ],
            "composite_score": 90,
            "composite_grade": "A",
            "required_coverage_met": True,
            "evaluated_at": NOW,
            "project_id": "p1",
            "project_name": "Petstore",
            "subject_label": "1.0.0",
        }
    ]
    policy_rows = [
        {
            "id": "pe1",
            "subject_type": "catalog_revision",
            "version_record_id": "v1",
            "mcp_version_id": None,
            "policy_version_id": "pv1",
            "passed": False,
            "gate_results": {
                "required_coverage": {"passed": False, "detail": {"missing": ["protocol"]}}
            },
            "evaluated_at": NOW,
        }
    ]
    index = build_index_from_rows(
        evidence_rows=rows, axis_rows=axis_rows, policy_rows=policy_rows,
        decisions=[], now=NOW,
    )
    finding = index["findings"][0]
    assert finding["composite_grade"] == "A"
    assert finding["required_coverage_met"] is True
    assert finding["latest_policy_evaluation_id"] == "pe1"
    assert finding["policy_passed"] is False
    subject = index["subjects"][0]
    assert subject["missing_axes"] == ["protocol"]


def test_index_fallback_missing_axes_without_policy_evaluation():
    axis_rows = [
        {
            "id": "ax1",
            "subject_type": "catalog_revision",
            "version_record_id": "v1",
            "mcp_version_id": None,
            "axes": [{"key": "quality", "assessed": False}],
            "composite_score": None,
            "composite_grade": None,
            "required_coverage_met": False,
            "evaluated_at": NOW,
            "project_id": "p1",
            "project_name": "Petstore",
            "subject_label": "1.0.0",
        }
    ]
    index = build_index_from_rows(
        evidence_rows=[], axis_rows=axis_rows, policy_rows=[], decisions=[], now=NOW
    )
    assert index["subjects"][0]["missing_axes"] == ["quality"]


# --- Filters / sort / pagination / facets ----------------------------------------------------------


def _sample_findings():
    rows = [
        _run(
            "run-1",
            findings=[
                _finding("e1", severity="error", category="security", rule="sec-1"),
                _finding("w1", severity="warning", rule="doc-1"),
                _finding("i1", severity="info", rule="doc-2"),
            ],
        ),
    ]
    decisions = [
        {"id": "d1", "project_id": None, "source_fingerprint": "w1",
         "state": "acknowledged", "owner_user_id": "owner-9"},
    ]
    index = build_index_from_rows(
        evidence_rows=rows, axis_rows=[], policy_rows=[], decisions=decisions, now=NOW
    )
    return index["findings"]


def test_filter_findings_by_closed_vocabularies():
    findings = _sample_findings()
    assert {f["source_fingerprint"] for f in filter_findings(findings, {"severity": ["error"]})} == {"e1"}
    assert {f["source_fingerprint"] for f in filter_findings(findings, {"state": ["acknowledged"]})} == {"w1"}
    assert {f["source_fingerprint"] for f in filter_findings(findings, {"axis": ["security"]})} == {"e1"}
    assert {f["source_fingerprint"] for f in filter_findings(findings, {"owner_user_id": "owner-9"})} == {"w1"}
    assert {f["source_fingerprint"] for f in filter_findings(findings, {"rule_id": "doc-2"})} == {"i1"}
    assert {f["source_fingerprint"] for f in filter_findings(findings, {"q": "message for e1"})} == {"e1"}
    # Everything in this fixture is first-run (new): new=False filters all out.
    assert filter_findings(findings, {"new": False}) == []


def test_filter_findings_by_coverage_flag():
    findings = _sample_findings()
    # required_coverage_met is None (no axis rows) — treated as not met.
    assert len(filter_findings(findings, {"coverage": "missing"})) == 3
    assert filter_findings(findings, {"coverage": "met"}) == []


def test_sort_findings_severity_then_rule_and_subject():
    findings = _sample_findings()
    ordered = sort_findings(findings, "severity")
    assert [f["severity"] for f in ordered] == ["error", "warning", "info"]
    by_rule = sort_findings(findings, "rule")
    assert [f["rule_id"] for f in by_rule] == ["doc-1", "doc-2", "sec-1"]


def test_paginate_slices_and_reports_total():
    page, total = paginate([1, 2, 3, 4, 5], limit=2, offset=2)
    assert page == [3, 4]
    assert total == 5


def test_facet_counts_cover_the_filtered_set():
    facets = facet_counts(_sample_findings())
    assert facets["severity"] == {"error": 1, "warning": 1, "info": 1}
    assert facets["effectiveState"]["acknowledged"] == 1
    assert facets["axis"]["security"] == 1
    assert facets["grade"] == {"ungraded": 3}


def test_normalize_filters_rejects_unknown_values_and_keys():
    assert normalize_filters({"severity": "error,warning"}) == {
        "severity": ["error", "warning"]
    }
    assert normalize_filters({"subjectType": "catalog_revision"}) == {
        "subject_type": "catalog_revision"
    }
    assert normalize_filters({"bogusKey": "x"}) == {}
    with pytest.raises(WorkspaceValidationError):
        normalize_filters({"severity": "catastrophic"})
    with pytest.raises(WorkspaceValidationError):
        normalize_filters({"coverage": "sometimes"})
    with pytest.raises(WorkspaceValidationError):
        normalize_filters({"axis": "vibes"})


def test_normalize_sort_defaults_and_rejects():
    assert normalize_sort(None) == "severity"
    assert normalize_sort("newest") == "newest"
    with pytest.raises(WorkspaceValidationError):
        normalize_sort("alphabetical")


# --- Summary --------------------------------------------------------------------------------------


def test_summary_counts_unwaived_security_errors_and_waivers():
    rows = [
        _run(
            "run-1",
            findings=[
                _finding("sec-err", severity="error", category="security"),
                _finding("plain-err", severity="error"),
                _finding("waived-err", severity="error"),
            ],
        )
    ]
    decisions = [
        {
            "id": "d1",
            "project_id": None,
            "source_fingerprint": "waived-err",
            "state": "waived",
            "rationale": "accepted",
            "expires_at": NOW + timedelta(days=7),  # inside the expiring-soon window
        },
        {
            "id": "d2",
            "project_id": None,
            "source_fingerprint": "plain-err",
            "state": "waiver_requested",
            "rationale": "please",
        },
    ]
    axis_rows = [
        {
            "id": "ax1",
            "subject_type": "catalog_revision",
            "version_record_id": "v1",
            "mcp_version_id": None,
            "axes": [{"key": "quality", "assessed": False}],
            "composite_score": None,
            "composite_grade": None,
            "required_coverage_met": False,
            "evaluated_at": NOW,
            "project_id": "p1",
            "project_name": "Petstore",
            "subject_label": "1.0.0",
        }
    ]
    index = build_index_from_rows(
        evidence_rows=rows, axis_rows=axis_rows, policy_rows=[],
        decisions=decisions, now=NOW,
    )
    summary = build_summary(index, now=NOW)
    # waived-err is suppressed; sec-err and plain-err (waiver_requested gates as open) count.
    assert summary["findings"]["unwaived_errors"] == 2
    assert summary["findings"]["unwaived_security_errors"] == 1
    assert summary["findings"]["waiver_requested"] == 1
    assert summary["waivers"] == {"active": 1, "requested": 1, "expiring_soon": 1}
    assert summary["coverage"]["missing_count"] == 1
    assert summary["coverage"]["subjects"][0]["missing_axes"] == ["quality"]
    assert summary["grade_distribution"]["ungraded"] == 1
    assert summary["subjects"]["catalog_revisions"] == 1


# --- Trends ---------------------------------------------------------------------------------------


def test_trends_separate_genuine_remediation_from_waivers():
    day1 = NOW - timedelta(days=2)
    day2 = NOW - timedelta(days=1)
    rows = [
        # Newest first, matching the DB ordering.
        _run(
            "run-2",
            findings=[_finding("kept")],
            created_at=day2,
            rn=1,
        ),
        _run(
            "run-1",
            findings=[_finding("kept"), _finding("fixed-fp"), _finding("waived-fp")],
            created_at=day1,
            rn=2,
        ),
    ]
    decisions = [
        {
            "id": "d1",
            "project_id": None,
            "source_fingerprint": "waived-fp",
            "state": "waived",
            "rationale": "accepted",
            "expires_at": NOW + timedelta(days=30),
        }
    ]
    events = [
        {"id": "ev1", "after_state": "waived", "created_at": day2},
        {"id": "ev2", "after_state": "false_positive", "created_at": day2},
    ]
    packs = [{"id": "pv1", "created_at": day2}]
    trends = build_trends(
        evidence_rows=rows,
        decision_events=events,
        policy_versions=packs,
        decisions=decisions,
        days=5,
        now=NOW,
    )
    by_date = {point["date"]: point for point in trends["series"]}
    d1_key = day1.date().isoformat()
    d2_key = day2.date().isoformat()
    # First run in window: all three fingerprints are new.
    assert by_date[d1_key]["new_findings"] == 3
    # fixed-fp disappeared with no suppressing decision => genuine remediation;
    # waived-fp disappeared because it was waived => counted under waivers, not remediation.
    assert by_date[d2_key]["remediated_findings"] == 1
    assert by_date[d2_key]["waivers_granted"] == 1
    assert by_date[d2_key]["marked_false_positive"] == 1
    assert by_date[d2_key]["policy_pack_publications"] == 1
    assert len(trends["series"]) == 5


def test_trends_count_expired_waivers():
    expired_at = NOW - timedelta(days=1)
    decisions = [
        {
            "id": "d1",
            "project_id": None,
            "source_fingerprint": "f1",
            "state": "waived",
            "rationale": "accepted",
            "expires_at": expired_at,
        }
    ]
    trends = build_trends(
        evidence_rows=[], decision_events=[], policy_versions=[],
        decisions=decisions, days=7, now=NOW,
    )
    by_date = {point["date"]: point for point in trends["series"]}
    assert by_date[expired_at.date().isoformat()]["waivers_expired"] == 1


# --- Waiver state machine ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (None, "acknowledged", ACTION_EDIT),
        (None, "fixed", ACTION_EDIT),
        (None, "false_positive", ACTION_EDIT),
        ("open", "waiver_requested", ACTION_EDIT),
        ("acknowledged", "open", ACTION_EDIT),
        ("fixed", "open", ACTION_EDIT),
        # Withdrawing one's own request stays an edit…
        ("waiver_requested", "acknowledged", ACTION_EDIT),
        ("waiver_requested", "waiver_requested", ACTION_EDIT),
        # …but resolving it (approve / reject) is a review decision.
        ("waiver_requested", "waived", ACTION_PUBLISH),
        ("waiver_requested", "open", ACTION_PUBLISH),
        # Entering or leaving waived always needs approval.
        (None, "waived", ACTION_PUBLISH),
        ("open", "waived", ACTION_PUBLISH),
        ("waived", "open", ACTION_PUBLISH),
        ("waived", "fixed", ACTION_PUBLISH),
    ],
)
def test_required_action_for_transition(before, after, expected):
    assert required_action_for_transition(before, after) == expected


def test_transition_error_field_requirements():
    assert transition_error("nonsense") is not None
    assert "rationale" in transition_error("waived", rationale="  ", expires_at=NOW).lower()
    assert "expires" in transition_error("waived", rationale="ok", expires_at=None).lower()
    assert "rationale" in transition_error("waiver_requested", rationale=None).lower()
    assert transition_error("waiver_requested", rationale="please") is None
    assert transition_error("acknowledged") is None
    assert transition_error("waived", rationale="ok", expires_at=NOW) is None
