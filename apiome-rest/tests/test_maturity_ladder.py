"""Unit tests for the pure maturity-level engine — GVM-1.2 (#5855).

:func:`app.maturity_ladder.evaluate_ladder` is pure, so these run without a database: the walk
stops at the first unsatisfied level, accumulated requirements, rule / axis / evidence blockers,
the not-assessed honesty rule, waivers per level, resolved decisions, and the explicit
no-ladder and below-first-level results.
"""

from datetime import datetime, timedelta, timezone

from app.maturity_ladder import (
    BLOCKER_AXIS,
    BLOCKER_EVIDENCE,
    BLOCKER_RULE,
    REASON_BELOW_FIRST_LEVEL,
    REASON_NO_LADDER,
    evaluate_ladder,
    no_ladder_result,
)

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def _level(key, *, rules=(), axes=(), evidence=(), waivers=True):
    return {
        "key": key,
        "label": key.title(),
        "rules": [{"ruleId": r, "maxSeverity": s} for r, s in rules],
        "axes": list(axes),
        "evidence": list(evidence),
        "waiversSatisfy": waivers,
    }


LADDER = {
    "name": "Maturity",
    "levels": [
        _level("bronze", rules=[("naming.a", "warning")]),
        _level("silver", axes=[{"axis": "quality", "minGrade": "B"}]),
        _level(
            "gold",
            rules=[("security.s", "none")],
            axes=[{"axis": "quality", "minGrade": "A"}, {"axis": "security", "minGrade": "A"}],
            evidence=["review_approved"],
            waivers=False,
        ),
    ],
}


def _finding(rule, severity, fp):
    return {"rule_id": rule, "severity": severity, "source_fingerprint": fp}


def _axis(key, grade, score=90, assessed=True):
    return {"axis": key, "assessed": assessed, "grade": grade, "score": score}


def _evaluate(findings=(), axes=None, decisions=None, ladder=LADDER, evidence=None):
    return evaluate_ladder(
        list(findings), axes, decisions or {}, ladder, evidence=evidence, now=NOW
    )


ALL_A = [_axis("quality", "A"), _axis("security", "A")]


# ---------------------------------------------------------------------------
# No ladder / no level
# ---------------------------------------------------------------------------


def test_no_ladder_is_never_a_level():
    for ladder in (None, {"name": "Empty", "levels": []}):
        result = _evaluate(ladder=ladder)
        assert result == no_ladder_result()
        assert result["level"] is None and result["reason"] == REASON_NO_LADDER


def test_a_subject_below_the_first_level_has_no_level_and_lists_its_blockers():
    result = _evaluate([_finding("naming.a", "error", "f1")], axes=ALL_A)
    assert result["level"] is None
    assert result["levelIndex"] is None
    assert result["reason"] == REASON_BELOW_FIRST_LEVEL
    assert result["nextLevel"] == "bronze"
    assert result["blockers"] == [
        {
            "levelKey": "bronze",
            "kind": BLOCKER_RULE,
            "ruleId": "naming.a",
            "maxSeverity": "warning",
            "count": 1,
            "sample": ["f1"],
        }
    ]


# ---------------------------------------------------------------------------
# Walking the ladder
# ---------------------------------------------------------------------------


def test_the_walk_stops_at_the_first_unsatisfied_level():
    result = _evaluate(axes=[_axis("quality", "C")])
    assert (result["level"], result["levelIndex"], result["nextLevel"]) == ("bronze", 0, "silver")
    assert result["reason"] is None
    (blocker,) = result["blockers"]
    assert blocker["kind"] == BLOCKER_AXIS
    assert blocker["reason"] == "below_threshold"
    assert (blocker["axis"], blocker["grade"], blocker["minGrade"]) == ("quality", "C", "B")


def test_the_top_level_has_no_next_level_and_no_blockers():
    result = _evaluate(axes=ALL_A, evidence={"review_approved": True})
    assert (result["level"], result["levelLabel"], result["levelIndex"]) == ("gold", "Gold", 2)
    assert result["nextLevel"] is None and result["blockers"] == []
    assert result["ladderName"] == "Maturity"


def test_a_higher_level_is_judged_on_the_accumulated_requirements():
    # Silver adds nothing about naming.a, but Bronze's cap still applies at Silver.
    ladder = {
        "name": "L",
        "levels": [
            _level("bronze", rules=[("naming.a", "warning")], waivers=True),
            _level("silver", waivers=False),
        ],
    }
    waived = {"f1": {"state": "waived", "expires_at": NOW + timedelta(days=1)}}
    result = _evaluate([_finding("naming.a", "error", "f1")], decisions=waived, ladder=ladder)
    # Bronze excuses the waiver; Silver does not, and its blocker is Bronze's rule.
    assert result["level"] == "bronze"
    assert result["blockers"][0]["ruleId"] == "naming.a"
    assert result["blockers"][0]["levelKey"] == "silver"


def test_findings_within_the_cap_and_of_unlisted_rules_do_not_block():
    result = _evaluate(
        [_finding("naming.a", "warning", "f1"), _finding("other.rule", "error", "f2")],
        axes=[_axis("quality", "B")],
    )
    assert result["level"] == "silver"


def test_max_severity_none_blocks_any_finding():
    result = _evaluate(
        [_finding("security.s", "info", "f1")],
        axes=ALL_A,
        evidence={"review_approved": True},
    )
    assert result["level"] == "silver"
    assert result["blockers"][0]["ruleId"] == "security.s"


def test_native_findings_use_rule_and_id():
    result = _evaluate([{"rule": "naming.a", "severity": "error", "id": "n1"}])
    assert result["blockers"][0]["sample"] == ["n1"]


def test_a_rule_blocker_counts_every_finding_and_samples_three():
    findings = [_finding("naming.a", "error", f"f{i}") for i in range(5)]
    (blocker,) = _evaluate(findings)["blockers"]
    assert blocker["count"] == 5
    assert blocker["sample"] == ["f0", "f1", "f2"]


# ---------------------------------------------------------------------------
# Axes: the not-assessed honesty rule
# ---------------------------------------------------------------------------


def test_an_unassessed_axis_cannot_satisfy_a_level_and_says_not_assessed():
    result = _evaluate(axes=[_axis("quality", "A")], evidence={"review_approved": True})
    assert result["level"] == "silver"
    blocker = next(b for b in result["blockers"] if b["kind"] == BLOCKER_AXIS)
    assert (blocker["axis"], blocker["reason"]) == ("security", "not_assessed")
    assert result["unassessedAxes"] == ["security"]


def test_an_axis_flagged_unassessed_counts_as_unassessed_even_with_a_grade():
    result = _evaluate(axes=[_axis("quality", "A", assessed=False)])
    assert result["level"] == "bronze"
    assert result["blockers"][0]["reason"] == "not_assessed"
    assert result["unassessedAxes"] == ["quality", "security"]


def test_no_axes_at_all_means_every_named_axis_is_unassessed():
    result = _evaluate(axes=None)
    assert result["unassessedAxes"] == ["quality", "security"]


def test_a_min_score_floor_is_checked():
    ladder = {"name": "L", "levels": [_level("bronze", axes=[{"axis": "quality", "minScore": 80}])]}
    assert _evaluate(axes=[_axis("quality", "B", score=79)], ladder=ladder)["level"] is None
    assert _evaluate(axes=[_axis("quality", "B", score=80)], ladder=ladder)["level"] == "bronze"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_missing_and_unknown_evidence_block_with_different_reasons():
    missing = _evaluate(axes=ALL_A, evidence={"review_approved": False})
    unknown = _evaluate(axes=ALL_A)
    for result, reason in ((missing, "missing"), (unknown, "not_assessed")):
        assert result["level"] == "silver"
        (blocker,) = result["blockers"]
        assert (blocker["kind"], blocker["evidence"], blocker["reason"]) == (
            BLOCKER_EVIDENCE,
            "review_approved",
            reason,
        )


# ---------------------------------------------------------------------------
# Decisions and waivers
# ---------------------------------------------------------------------------


def test_a_waiver_satisfies_a_rule_only_where_waivers_satisfy():
    decisions = {"f1": {"state": "waived", "expires_at": NOW + timedelta(days=30)}}
    findings = [_finding("security.s", "error", "f1")]
    # security.s is unlisted below Gold; at Gold it must be clean and waivers do not count.
    result = _evaluate(findings, axes=ALL_A, decisions=decisions, evidence={"review_approved": True})
    assert result["level"] == "silver"
    assert result["blockers"][0]["ruleId"] == "security.s"


def test_waivers_counted_reports_the_findings_the_satisfied_levels_excused():
    decisions = {"f1": {"state": "waived", "expires_at": NOW + timedelta(days=30)}}
    result = _evaluate([_finding("naming.a", "error", "f1")], axes=[_axis("quality", "A")], decisions=decisions)
    assert result["level"] == "silver"
    assert result["waiversCounted"] == 1


def test_an_expired_waiver_counts_as_open():
    decisions = {"f1": {"state": "waived", "expires_at": NOW - timedelta(days=1)}}
    result = _evaluate([_finding("naming.a", "error", "f1")], decisions=decisions)
    assert result["level"] is None
    assert result["waiversCounted"] == 0


def test_fixed_and_false_positive_findings_never_count():
    decisions = {"f1": {"state": "false_positive"}, "f2": {"state": "fixed"}}
    findings = [_finding("security.s", "error", "f1"), _finding("security.s", "error", "f2")]
    result = _evaluate(findings, axes=ALL_A, decisions=decisions, evidence={"review_approved": True})
    assert result["level"] == "gold"


def test_a_requested_waiver_still_counts():
    decisions = {"f1": {"state": "waiver_requested"}}
    result = _evaluate([_finding("naming.a", "error", "f1")], decisions=decisions)
    assert result["level"] is None


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_result_does_not_depend_on_finding_order():
    findings = [_finding("naming.a", "error", "f2"), _finding("naming.a", "error", "f1")]
    assert _evaluate(findings) == _evaluate(list(reversed(findings)))
