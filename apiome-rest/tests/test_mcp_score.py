"""Unit tests for MCP lint scoring, grading & fingerprint roll-up (V2-MCP-21.4, #3685).

These exercise :mod:`app.mcp_score`: the pure, no-I/O layer that consumes the deterministic
findings from :mod:`app.mcp_lint` and rolls them up into a weighted 0-100 score, an A-F grade
(the V124 house bands), and a stable report fingerprint. Persistence and the best-effort
capture-on-discovery hook are covered in ``test_mcp_discovery_trigger.py``; here we pin the
scoring contract on hand-built surfaces and synthetic findings.
"""

from __future__ import annotations

from typing import List, Optional

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_lint import LintFinding
from app.mcp_score import (
    GRADE_THRESHOLDS,
    PER_RULE_PENALTY_CAP,
    MCPScoreResult,
    _grade_for_score,
    _score_from_findings,
    score_mcp_surface,
)

# --- Fixture builders -----------------------------------------------------------------------

_GOOD_SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def _clean_tool(name: str = "search", ordinal: int = 0) -> CapabilityItem:
    """A tool with no hygiene/annotation defects (mirrors the lint hygiene fixture)."""
    return CapabilityItem(
        item_type=ITEM_TYPE_TOOL,
        name=name,
        ordinal=ordinal,
        title="Search",
        description="Search the corpus.",
        input_schema=dict(_GOOD_SCHEMA),
        output_schema={"type": "object"},
        raw={"name": name, "inputSchema": dict(_GOOD_SCHEMA)},
    )


def _surface(
    tools: Optional[List[CapabilityItem]] = None,
    *,
    instructions: Optional[str] = "Drive this server by calling its tools.",
) -> DiscoverySurface:
    """A discovery surface; ``instructions`` defaults to non-blank so the advisory rule stays quiet."""
    return DiscoverySurface(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Server", version="1.0.0"),
        capabilities={},
        instructions=instructions,
        tools=tuple(tools or ()),
        resources=(),
        resource_templates=(),
        prompts=(),
    )


def _finding(rule: str, severity: str, path: str = "tools.x") -> LintFinding:
    """A synthetic finding for scoring tests (scoring reads only ``rule`` and ``severity``)."""
    category = rule.split(".")[0]
    return LintFinding(
        path=path, category=category, rule=rule, severity=severity, message=f"{rule} on {path}"
    )


# A surface with one fully clean tool and server instructions: no rule should fire at all.
CLEAN_SURFACE = _surface(tools=[_clean_tool()])


# --- Grade bands (reuse the V124 house thresholds) ------------------------------------------


def test_grade_thresholds_are_the_v124_house_bands() -> None:
    assert GRADE_THRESHOLDS == ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F"))


def test_grade_for_score_maps_each_band() -> None:
    assert _grade_for_score(100) == "A"
    assert _grade_for_score(90) == "A"
    assert _grade_for_score(89) == "B"
    assert _grade_for_score(80) == "B"
    assert _grade_for_score(70) == "C"
    assert _grade_for_score(60) == "D"
    assert _grade_for_score(59) == "F"
    assert _grade_for_score(0) == "F"


# --- Clean surface scores a perfect 100 / A -------------------------------------------------


def test_clean_surface_scores_100_grade_a() -> None:
    result = score_mcp_surface(CLEAN_SURFACE)
    assert isinstance(result, MCPScoreResult)
    assert result.score == 100
    assert result.grade == "A"
    assert result.findings == ()
    assert result.severity_counts == {"error": 0, "warning": 0, "info": 0}
    assert result.rule_hits == {}


# --- Determinism ----------------------------------------------------------------------------


def test_score_is_deterministic_for_a_fixed_surface() -> None:
    first = score_mcp_surface(CLEAN_SURFACE)
    second = score_mcp_surface(CLEAN_SURFACE)
    assert first.score == second.score
    assert first.grade == second.grade
    assert first.report_fingerprint == second.report_fingerprint
    assert first.finding_dicts() == second.finding_dicts()


def test_empty_surface_is_a_single_info_finding() -> None:
    # An empty surface trips only the info-level empty-surface rule: penalty 1 -> score 99 -> A.
    result = score_mcp_surface(_surface(tools=[]))
    assert result.severity_counts == {"error": 0, "warning": 0, "info": 1}
    assert result.score == 99
    assert result.grade == "A"


# --- MUST (error) is weighted heavier than SHOULD (warning) ---------------------------------


def test_must_failure_weighted_heavier_than_should_failure() -> None:
    error_only = _score_from_findings([_finding("schema.must", "error")])
    warning_only = _score_from_findings([_finding("quality.should", "warning")])
    info_only = _score_from_findings([_finding("quality.advisory", "info")])
    # error costs 10, warning 4, info 1 -> the MUST failure produces the lowest score.
    assert error_only == 90
    assert warning_only == 96
    assert info_only == 99
    assert error_only < warning_only < info_only


def test_extra_findings_fold_into_the_score() -> None:
    base = score_mcp_surface(CLEAN_SURFACE)
    with_error = score_mcp_surface(
        CLEAN_SURFACE, extra_findings=[_finding("schema.injected", "error")]
    )
    assert base.score == 100
    assert with_error.score == 90  # one injected error -> 10-point penalty
    assert with_error.grade == "A"
    assert "schema.injected" in with_error.rule_hits


# --- Penalty capping and clamping -----------------------------------------------------------


def test_per_rule_penalty_is_capped() -> None:
    # Many errors of ONE rule cannot exceed the per-rule cap (20), so the floor is 80, not 0.
    many = [_finding("schema.repeat", "error", path=f"tools.t{i}") for i in range(50)]
    assert _score_from_findings(many) == round(100.0 - PER_RULE_PENALTY_CAP)


def test_score_never_drops_below_zero() -> None:
    # Many DISTINCT error rules each contribute the full cap; the total clamps at 0, not negative.
    many = [_finding(f"schema.rule{i}", "error", path=f"tools.t{i}") for i in range(40)]
    assert _score_from_findings(many) == 0


# --- Fingerprint stability and sensitivity --------------------------------------------------


def test_fingerprint_is_independent_of_finding_input_order() -> None:
    a = _finding("schema.a", "error", path="tools.a")
    b = _finding("quality.b", "warning", path="tools.b")
    forward = score_mcp_surface(CLEAN_SURFACE, extra_findings=[a, b])
    reversed_ = score_mcp_surface(CLEAN_SURFACE, extra_findings=[b, a])
    assert forward.report_fingerprint == reversed_.report_fingerprint


def test_fingerprint_changes_when_the_report_changes() -> None:
    clean = score_mcp_surface(CLEAN_SURFACE)
    dirty = score_mcp_surface(CLEAN_SURFACE, extra_findings=[_finding("schema.x", "error")])
    assert clean.report_fingerprint != dirty.report_fingerprint


# --- Report payload (persisted into mcp_version_scores.report) ------------------------------


def test_report_dict_carries_the_full_scoring_report() -> None:
    result = score_mcp_surface(
        CLEAN_SURFACE, extra_findings=[_finding("schema.x", "error")]
    )
    report = result.report_dict()
    assert report["score"] == result.score
    assert report["grade"] == result.grade
    assert report["report_fingerprint"] == result.report_fingerprint
    assert report["rule_hits"] == dict(result.rule_hits)
    assert report["severity_counts"] == dict(result.severity_counts)
    assert report["findings"] == result.finding_dicts()
    # One injected error -> exactly one finding rendered, with the stable dict key set.
    assert len(report["findings"]) == 1
    assert set(report["findings"][0]) == {
        "id",
        "path",
        "category",
        "rule",
        "severity",
        "message",
    }
