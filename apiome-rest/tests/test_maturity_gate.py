"""The cumulative level judgement every GVM-1.3 (#5856) gate shares.

:func:`app.maturity_gate.judge_maturity` is the one place a level is compared with a required
level. These tests pin its five-status vocabulary and — the acceptance criterion — that the
deploy gate's ``maturity`` signal and the check suite's ``maturity`` component, judged from the
same draft, always agree.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.api_check_suite import (
    COMPONENT_MATURITY,
    REQUIREMENT_ADVISORY,
    REQUIREMENT_REQUIRED,
    judge_maturity_component,
)
from app.deploy_gate import (
    SIGNAL_MATURITY,
    MaturityThresholds,
    evaluate_maturity,
)
from app.maturity_gate import (
    REASON_BELOW_REQUIRED_LEVEL,
    REASON_LEVEL_MET,
    REASON_NO_LADDER,
    REASON_NO_REQUIRED_LEVEL,
    REASON_REQUIRED_LEVEL_UNKNOWN,
    REASON_UNREADABLE,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    is_level_key,
    judge_maturity,
    ladder_level_keys,
    required_publish_level,
)
from app.maturity_ladder import evaluate_ladder

LADDER: Dict[str, Any] = {
    "name": "Acme maturity",
    "levels": [
        {"key": "bronze", "label": "Bronze", "rules": [], "axes": [], "evidence": []},
        {
            "key": "silver",
            "label": "Silver",
            "rules": [{"ruleId": "operation-description", "maxSeverity": "none"}],
            "axes": [],
            "evidence": [],
            "waiversSatisfy": True,
        },
        {
            "key": "gold",
            "label": "Gold",
            "rules": [{"ruleId": "operation-summary", "maxSeverity": "none"}],
            "axes": [],
            "evidence": [],
            "waiversSatisfy": False,
        },
    ],
}


def _finding(rule: str, fp: str) -> Dict[str, Any]:
    return {"rule_id": rule, "severity": "warning", "source_fingerprint": fp}


def _level(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The real GVM-1.2 result for ``findings`` under :data:`LADDER`."""
    return evaluate_ladder(findings, None, {}, LADDER)


BRONZE = _level([_finding("operation-description", "fp-1"), _finding("operation-description", "fp-2")])
SILVER = _level([_finding("operation-summary", "fp-3")])
GOLD = _level([])


def test_the_fixtures_sit_where_their_names_say():
    assert (BRONZE["level"], SILVER["level"], GOLD["level"]) == ("bronze", "silver", "gold")


# ---------------------------------------------------------------------------------------------
# judge_maturity
# ---------------------------------------------------------------------------------------------


def test_a_draft_at_bronze_requiring_silver_fails_with_the_blockers_listed():
    judged = judge_maturity(BRONZE, ladder=LADDER, required_level="silver")
    assert judged.status == STATUS_FAIL
    assert judged.reason == REASON_BELOW_REQUIRED_LEVEL
    assert (judged.level, judged.required_level) == ("bronze", "silver")
    assert (judged.level_index, judged.required_level_index) == (0, 1)
    assert judged.required_level_label == "Silver"
    assert len(judged.blockers) == 1
    blocker = judged.blockers[0]
    assert blocker["ruleId"] == "operation-description"
    assert blocker["count"] == 2
    payload = judged.as_payload()
    assert payload["blockers"] == [blocker]
    assert "Bronze" in payload["message"] and "Silver is required" in payload["message"]
    assert "1 blocker" in payload["message"]


@pytest.mark.parametrize("result,required", [(SILVER, "silver"), (GOLD, "silver"), (GOLD, "gold")])
def test_reaching_or_passing_the_required_level_passes(result, required):
    judged = judge_maturity(result, ladder=LADDER, required_level=required)
    assert judged.status == STATUS_PASS
    assert judged.reason == REASON_LEVEL_MET
    assert judged.blockers == ()


def test_a_draft_below_the_first_level_fails_any_requirement():
    below = {**BRONZE, "level": None, "levelLabel": None, "levelIndex": None}
    judged = judge_maturity(below, ladder=LADDER, required_level="bronze")
    assert judged.status == STATUS_FAIL
    assert "below the first level" in judged.message()


@pytest.mark.parametrize("required", [None, "silver", "nonsense"])
def test_a_guide_without_a_ladder_never_arms_the_gate(required):
    judged = judge_maturity(GOLD, ladder=None, required_level=required)
    assert judged.status == STATUS_NOT_CONFIGURED
    assert judged.reason == REASON_NO_LADDER
    assert judged.armed is False


def test_a_ladder_without_a_required_level_is_reported_but_not_judged():
    judged = judge_maturity(SILVER, ladder=LADDER, required_level=None)
    assert judged.status == STATUS_NOT_CONFIGURED
    assert judged.reason == REASON_NO_REQUIRED_LEVEL
    assert judged.level == "silver"
    assert "currently Silver" in judged.message()


def test_a_required_key_the_ladder_does_not_have_is_unknown_not_a_block():
    judged = judge_maturity(GOLD, ladder=LADDER, required_level="platinum")
    assert judged.status == STATUS_UNKNOWN
    assert judged.reason == REASON_REQUIRED_LEVEL_UNKNOWN
    assert "'platinum'" in judged.message()


def test_an_unreadable_level_is_unknown_and_carries_why():
    judged = judge_maturity(None, ladder=LADDER, required_level="silver", detail="db down")
    assert judged.status == STATUS_UNKNOWN
    assert judged.reason == REASON_UNREADABLE
    assert judged.as_payload()["detail"] == "db down"


def test_helpers():
    assert ladder_level_keys(LADDER) == ["bronze", "silver", "gold"]
    assert ladder_level_keys(None) == []
    assert required_publish_level({"required_publish_level": "silver"}) == "silver"
    assert required_publish_level({"required_publish_level": None}) is None
    assert required_publish_level(None) is None
    assert is_level_key("tier-2") and is_level_key("gold")
    assert not is_level_key("Gold") and not is_level_key("") and not is_level_key(3)


# ---------------------------------------------------------------------------------------------
# One evaluator: the deploy gate and the check suite agree on the same draft.
# ---------------------------------------------------------------------------------------------

#: Deploy-gate status → the check-suite state it must become (CTG-4.5 → GNC-3.1 mapping).
_EXPECTED_STATE = {
    STATUS_PASS: "pass",
    STATUS_FAIL: "fail",
    STATUS_NOT_CONFIGURED: "skipped",
    STATUS_UNKNOWN: "pending",
}


@pytest.mark.parametrize(
    "result,ladder,required",
    [
        (BRONZE, LADDER, "silver"),
        (SILVER, LADDER, "silver"),
        (GOLD, LADDER, "gold"),
        (GOLD, None, "silver"),
        (SILVER, LADDER, None),
        (GOLD, LADDER, "platinum"),
        (None, LADDER, "silver"),
    ],
)
def test_the_deploy_gate_and_the_check_suite_agree_on_one_draft(result, ladder, required):
    judgement = judge_maturity(result, ladder=ladder, required_level=required)
    signal = evaluate_maturity(judgement=judgement, link="/lint/level")
    component = judge_maturity_component(
        judgement,
        thresholds=MaturityThresholds(min_maturity_level=required),
        requirement=REQUIREMENT_REQUIRED,
        link="/lint/level",
    )
    assert signal.signal == SIGNAL_MATURITY
    assert component.component == COMPONENT_MATURITY
    assert signal.status == judgement.status
    assert component.state == _EXPECTED_STATE[signal.status]
    assert component.reason == signal.reason == judgement.reason
    assert component.detail == signal.detail
    assert component.evidence["level"] == signal.data["level"]
    assert component.evidence["blockers"] == signal.data["blockers"]
    assert signal.satisfied is ({STATUS_PASS: True, STATUS_FAIL: False}.get(signal.status))


def test_the_component_is_never_pass_without_a_ladder_and_advisory_never_counts():
    judgement = judge_maturity(GOLD, ladder=None, required_level="gold")
    component = judge_maturity_component(
        judgement,
        thresholds=MaturityThresholds(),
        requirement=REQUIREMENT_ADVISORY,
        link=None,
    )
    assert component.state == "skipped"
    assert component.counted is False
    assert component.rule["thresholdsFrom"] == "deploy-gate-policy"
    assert component.rule["thresholds"] == {"minMaturityLevel": None}
