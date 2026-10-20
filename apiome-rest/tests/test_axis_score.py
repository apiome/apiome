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
    REASON_PROTOCOL,
    REASON_SECURITY_CATALOG,
    REASON_SUPPLY_CHAIN,
    catalog_axis_evaluation,
    evaluate_axes,
    grade_for_score,
    mcp_axis_evaluation,
    score_from_finding_dicts,
)
from app.lint_evidence import SUBJECT_CATALOG_REVISION


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


# ===========================================================================
# Protocol axis — fed by the MCP conformance report (CLX-3.1, #4855)
# ===========================================================================


def _conformance_report(**overrides):
    """A conformance report in the ``ConformanceReport.report_dict()`` shape."""
    base = {
        "profile": "mcp-conformance",
        "spec_version": "2025-06-18",
        "score": 78,
        "grade": "C",
        "report_fingerprint": "conf-fp",
        "rule_hits": {"protocol.declared-capability-empty": 1},
        "severity_counts": {"error": 0, "warning": 0, "info": 1},
        "findings": [
            {
                "id": "mcp-conf-1",
                "path": "surface.capabilities.prompts",
                "category": "protocol",
                "rule": "protocol.declared-capability-empty",
                "severity": "info",
                "message": "Server declared the 'prompts' capability but listed no prompts.",
            }
        ],
        "evaluated_rules": ["protocol.declared-capability-empty"],
        "skipped_rules": [],
        "transcript_captured": True,
    }
    base.update(overrides)
    return base


def test_protocol_axis_not_assessed_without_a_conformance_report():
    """Pre-CLX-3.1 behaviour is preserved: no conformance scan ⇒ the axis is a visible gap."""
    protocol = _by_key(mcp_axis_evaluation(_report()))[AXIS_PROTOCOL]
    assert protocol["assessed"] is False
    assert protocol["score"] is None and protocol["grade"] is None
    assert protocol["coverage"]["state"] == "none"
    assert protocol["not_assessed_reason"] == REASON_PROTOCOL


def test_protocol_axis_takes_the_conformance_score_and_grade():
    """A fully-evidenced conformance run assesses the axis with the report's own score/grade."""
    report = _conformance_report()
    ev = mcp_axis_evaluation(_report(), conformance_report=report)
    protocol = _by_key(ev)[AXIS_PROTOCOL]

    assert protocol["assessed"] is True
    # Taken from the report, not recomputed — the axis can never disagree with the run.
    assert protocol["score"] == 78
    assert protocol["grade"] == "C"
    assert protocol["coverage"]["state"] == "full"
    assert protocol["not_assessed_reason"] is None
    assert protocol["severity_counts"] == {"error": 0, "warning": 0, "info": 1}
    # The axis is now assessed, so it contributes its own weight to the composite.
    assert ev.composite_score is not None
    assert ev.composite_score < mcp_axis_evaluation(_report()).composite_score


def test_protocol_axis_is_partial_when_rules_were_skipped():
    """Skipped (transcript-backed) rules make the axis assessed but only *partially* covered.

    The surface-derived rules genuinely ran, so the axis is not a gap — but a consumer must be
    able to tell a fully-observed pass from one where the wire was never seen.
    """
    report = _conformance_report(
        score=100,
        grade="A",
        findings=[],
        severity_counts={"error": 0, "warning": 0, "info": 0},
        skipped_rules=["protocol.response-id-not-echoed"],
        transcript_captured=False,
    )
    protocol = _by_key(mcp_axis_evaluation(_report(), conformance_report=report))[AXIS_PROTOCOL]

    assert protocol["assessed"] is True
    assert protocol["score"] == 100 and protocol["grade"] == "A"
    assert protocol["coverage"]["state"] == "partial"
    assert protocol["not_assessed_reason"] is None


def test_protocol_axis_ignores_conformance_report_for_catalog_subjects():
    """A catalog revision is a document, not a server: it has no protocol surface to assess."""
    protocol = _by_key(
        catalog_axis_evaluation(_report(), conformance_report=_conformance_report())
    )[AXIS_PROTOCOL]
    assert protocol["assessed"] is False
    assert protocol["not_assessed_reason"] == REASON_PROTOCOL


def test_protocol_axis_does_not_leak_conformance_findings_into_other_axes():
    """Conformance findings feed only the protocol axis — the lint report's score is untouched."""
    conformance = _conformance_report(
        findings=[
            {
                "id": "mcp-conf-2",
                "path": "tools.wipe",
                "category": "security",
                "rule": "readiness.tool-destructive-not-declared",
                "severity": "error",
                "message": "destructive",
            }
        ],
        score=90,
        grade="A",
    )
    ev = mcp_axis_evaluation(_report(score=100, grade="A"), conformance_report=conformance)
    axes = _by_key(ev)
    # The quality and security axes are computed from the *lint* report only.
    assert axes[AXIS_QUALITY]["score"] == 100
    assert axes[AXIS_SECURITY]["score"] == 100
    assert axes[AXIS_PROTOCOL]["score"] == 90

# --- Supply-chain axis (CLX-3.2, #4856) -------------------------------------------------------


def _posture_report(**overrides):
    """A trust-posture report in the ``PostureReport.report_dict()`` shape."""
    base = {
        "profile": "mcp-trust-posture",
        "owasp_revision": "2025",
        "score": 64,
        "grade": "D",
        "report_fingerprint": "posture-fp",
        "rule_hits": {"metadata.hidden-instruction": 1},
        "severity_counts": {"error": 1, "warning": 0, "info": 0},
        "findings": [
            {
                "id": "mcp-posture-1",
                "path": "tools.read_file",
                "category": "metadata",
                "rule": "metadata.hidden-instruction",
                "severity": "error",
                "message": "hidden instruction",
                "origin": "metadata",
                "owasp_ids": ["MCP01", "MCP02"],
                "exploitability": "static_signal",
            }
        ],
        "evaluated_rules": ["metadata.hidden-instruction"],
        "skipped_rules": [],
        "skip_reasons": {},
        "proven_count": 0,
    }
    base.update(overrides)
    return base


def test_supply_chain_axis_not_assessed_without_a_posture_report():
    """No posture scan ⇒ the axis stays a visible gap, exactly as it was pre-CLX-3.2."""
    axis = _by_key(mcp_axis_evaluation(_report()))[AXIS_SUPPLY_CHAIN]
    assert axis["assessed"] is False
    assert axis["score"] is None
    assert axis["coverage"]["state"] == "none"
    assert axis["not_assessed_reason"] == REASON_SUPPLY_CHAIN


def test_supply_chain_axis_takes_the_posture_score_and_grade():
    ev = mcp_axis_evaluation(_report(), posture_report=_posture_report())
    axis = _by_key(ev)[AXIS_SUPPLY_CHAIN]
    assert axis["assessed"] is True
    assert axis["score"] == 64
    assert axis["grade"] == "D"
    assert axis["coverage"]["state"] == "full"
    assert axis["not_assessed_reason"] is None


def test_supply_chain_axis_is_partial_when_rules_were_skipped():
    """Skipped source/dependency rules make the axis assessed but only partially covered."""
    report = _posture_report(
        score=100,
        grade="A",
        findings=[],
        severity_counts={"error": 0, "warning": 0, "info": 0},
        skipped_rules=["source.hardcoded-provider-credential"],
    )
    axis = _by_key(mcp_axis_evaluation(_report(), posture_report=report))[AXIS_SUPPLY_CHAIN]
    assert axis["assessed"] is True
    assert axis["coverage"]["state"] == "partial"


def test_supply_chain_axis_ignores_posture_report_for_catalog_subjects():
    axis = _by_key(
        catalog_axis_evaluation(_report(), posture_report=_posture_report())
    )[AXIS_SUPPLY_CHAIN]
    assert axis["assessed"] is False
    assert axis["not_assessed_reason"] == REASON_SUPPLY_CHAIN


def test_protocol_and_supply_chain_axes_are_independent():
    """The two reserved axes fill from their own reports and do not affect each other."""
    ev = mcp_axis_evaluation(
        _report(), conformance_report=_conformance_report(), posture_report=_posture_report()
    )
    axes = _by_key(ev)
    assert axes[AXIS_PROTOCOL]["score"] == 78
    assert axes[AXIS_SUPPLY_CHAIN]["score"] == 64


# --- Security axis for API-paradigm catalog revisions (ASP-1.3, #5921; revision 3) -------------

_SECURITY_BAR = [{"name": "security", "score": 100}]


def _security_finding(rule: str, severity: str = "error") -> dict:
    return {"rule": rule, "category": "security", "severity": severity, "message": rule}


def test_revision_three_keeps_the_algorithm_id():
    assert ALGORITHM_ID == "clx-axis-v1"
    assert ALGORITHM_VERSION == "3"


def test_catalog_security_is_assessed_from_the_pack_bar_with_published_weights():
    """Acceptance: one error-severity weight-2 finding scores exactly 80 and grades B."""
    ev = catalog_axis_evaluation(
        _report(
            score=90,
            grade="A",
            findings=[_security_finding("security.write-operation-missing-auth")],
            categories=_SECURITY_BAR,
        )
    )
    security = _by_key(ev)[AXIS_SECURITY]
    assert security["assessed"] is True
    assert (security["score"], security["grade"]) == (80, "B")
    assert security["coverage"] == {"state": "full"}
    assert security["severity_counts"] == {"error": 1, "warning": 0, "info": 0}
    assert security["ruleset"] == "security"
    assert security["skipped_rules"] == []
    assert [sub["risk_id"] for sub in security["owasp"]] == [f"API{n}" for n in range(1, 11)]
    for sub in security["owasp"]:
        assert set(sub) == {"risk_id", "title", "score", "finding_count", "coverage"}
        # A category none of whose rules evaluated is not assessed — never 100.
        if sub["coverage"] == "none":
            assert sub["score"] is None


def test_catalog_security_with_the_bar_and_no_findings_is_a_clean_100():
    ev = catalog_axis_evaluation(_report(findings=[], categories=_SECURITY_BAR))
    security = _by_key(ev)[AXIS_SECURITY]
    assert security["assessed"] is True
    assert (security["score"], security["grade"]) == (100, "A")


def test_catalog_security_without_the_bar_is_not_assessed_even_with_findings():
    """No pack bar means no security pack evaluated the revision (or its guide disables it)."""
    ev = catalog_axis_evaluation(
        _report(findings=[_security_finding("security.write-operation-missing-auth")])
    )
    security = _by_key(ev)[AXIS_SECURITY]
    assert security["assessed"] is False
    assert security["score"] is None
    assert security["coverage"]["state"] == "none"
    assert security["not_assessed_reason"] == REASON_SECURITY_CATALOG
    assert "owasp" not in security


def test_catalog_security_bar_name_is_matched_case_insensitively():
    ev = catalog_axis_evaluation(_report(categories=[{"name": " Security ", "score": 100}]))
    assert _by_key(ev)[AXIS_SECURITY]["assessed"] is True


def test_catalog_security_coverage_is_partial_when_the_run_skipped_a_registered_rule(monkeypatch):
    from app import security_score

    monkeypatch.setattr(
        security_score,
        "rule_owasp_ids",
        lambda: {
            "security.write-operation-missing-auth": ("API2",),
            "security.deprecated-without-sunset": ("API9",),
        },
    )
    ev = catalog_axis_evaluation(
        _report(
            findings=[_security_finding("security.write-operation-missing-auth")],
            categories=_SECURITY_BAR,
            skipped_rules=["security.deprecated-without-sunset", "naming.not-security"],
        )
    )
    security = _by_key(ev)[AXIS_SECURITY]
    assert security["assessed"] is True
    assert security["score"] == 80
    assert security["coverage"] == {"state": "partial"}
    assert security["skipped_rules"] == ["security.deprecated-without-sunset"]
    owasp = {sub["risk_id"]: sub for sub in security["owasp"]}
    assert owasp["API2"] == {
        "risk_id": "API2",
        "title": "Broken authentication",
        "score": 80,
        "finding_count": 1,
        "coverage": "full",
    }
    assert owasp["API9"]["coverage"] == "none" and owasp["API9"]["score"] is None
    assert owasp["API1"]["coverage"] == "none"


def test_quality_axis_and_score_are_byte_identical_with_or_without_the_security_axis():
    """Security findings never enter the quality axis; the stored score/grade pass through."""
    findings = [
        _security_finding("security.write-operation-missing-auth"),
        {"rule": "naming.schema-pascal-case", "category": "naming", "severity": "warning"},
    ]
    before = catalog_axis_evaluation(_report(score=96, grade="A", findings=findings))
    after = catalog_axis_evaluation(
        _report(score=96, grade="A", findings=findings, categories=_SECURITY_BAR)
    )
    assert _by_key(before)[AXIS_QUALITY] == _by_key(after)[AXIS_QUALITY]
    assert _by_key(after)[AXIS_QUALITY]["score"] == 96
    assert _by_key(after)[AXIS_QUALITY]["severity_counts"] == {"error": 0, "warning": 1, "info": 0}
    assert before.source_report_fingerprint == after.source_report_fingerprint


def test_composite_includes_an_assessed_catalog_security_axis_at_equal_weight():
    ev = catalog_axis_evaluation(
        _report(
            score=90,
            grade="A",
            findings=[_security_finding("security.write-operation-missing-auth")],
            categories=_SECURITY_BAR,
        )
    )
    assert ev.composite_score == 85  # mean of quality 90 and security 80
    assert ev.composite_grade == "B"


def test_mcp_security_axis_is_unchanged_by_revision_three():
    """MCP snapshots keep the plain formula: a weight-2 rule id costs 10 there, not 20."""
    ev = mcp_axis_evaluation(
        _report(
            score=90,
            grade="A",
            findings=[_security_finding("security.write-operation-missing-auth")],
        )
    )
    security = _by_key(ev)[AXIS_SECURITY]
    assert security["assessed"] is True
    assert security["score"] == 90
    assert "owasp" not in security and "ruleset" not in security


def test_security_headline_reads_the_assessed_axis_and_never_fakes_zero():
    from app.axis_score import security_headline

    assessed = catalog_axis_evaluation(
        _report(
            findings=[_security_finding("security.write-operation-missing-auth")],
            categories=_SECURITY_BAR,
        )
    )
    assert security_headline(assessed.axes) == (80, "B")
    assert security_headline(catalog_axis_evaluation(_report()).axes) == (None, None)
    assert security_headline([]) == (None, None)
    # A stored axis without a grade (defensive) gets one from the house bands.
    assert security_headline([{"key": "security", "assessed": True, "score": 72}]) == (72, "C")
    assert security_headline([{"key": "security", "assessed": True, "score": None}]) == (None, None)
