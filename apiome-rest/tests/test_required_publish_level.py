"""The required publish level: frozen into packs, fingerprint-stable, read once (GVM-1.3, #5856).

Covers the data side of the level gates: the ``required_publish_level`` the policy pack freezes,
the ``failOnMaturityLevel`` CI toggle, the fingerprints that must not move for packs and
policies that use neither, and :func:`app.lint_policy_service.judge_catalog_revision_maturity` —
the one read behind the publish gate, the deploy gate and the check suite.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.api_check_suite import (
    COMPONENT_MATURITY,
    DEFAULT_POLICY,
    policy_fingerprint,
    policy_from_body,
    requirements_fingerprint,
)
from app.database import Database
from app.deploy_gate import (
    DEFAULT_THRESHOLDS,
    GateThresholdError,
    canonical_thresholds_body,
    thresholds_content_fingerprint,
    thresholds_from_body,
)
from app.lint_policy_service import judge_catalog_revision_maturity, snapshot_style_guide_policy
from app.models import style_guide_ci_outcomes_from_raw, style_guide_policy_version_out_from_row
from app.policy_evaluate import default_ci_outcomes, policy_content_fingerprint

TENANT = "00000000-0000-4000-8000-0000000000a1"
GUIDE = "00000000-0000-4000-8000-0000000000c1"
PROJECT = "00000000-0000-4000-8000-0000000000d1"
REVISION = "00000000-0000-4000-8000-0000000000e1"

LEVELS = [
    {"key": "bronze", "label": "Bronze", "rules": [], "axes": [], "evidence": []},
    {"key": "silver", "label": "Silver", "rules": [], "axes": [], "evidence": []},
]
LADDER_ROW = {"id": "l1", "name": "Maturity", "levels": LEVELS}


# ---------------------------------------------------------------------------------------------
# The CI toggle
# ---------------------------------------------------------------------------------------------


def test_fail_on_maturity_level_defaults_off_and_round_trips():
    assert default_ci_outcomes(None)["failOnMaturityLevel"] is False
    assert default_ci_outcomes({"fail_on_maturity_level": True})["failOnMaturityLevel"] is True
    out = style_guide_ci_outcomes_from_raw({"failOnMaturityLevel": True}).model_dump(by_alias=True)
    assert out["failOnMaturityLevel"] is True
    assert style_guide_ci_outcomes_from_raw(None).fail_on_maturity_level is False


# ---------------------------------------------------------------------------------------------
# Pack fingerprints
# ---------------------------------------------------------------------------------------------

_LEGACY_OUTCOMES = {
    "failOnUnwaivedErrors": True,
    "failOnRequiredCoverage": True,
    "failOnAxisGates": True,
}


def _fp(**kwargs):
    base = dict(rules_snapshot=[], axis_gates={}, required_coverage=["quality"])
    return policy_content_fingerprint(**{**base, **kwargs})


def test_a_pack_using_neither_the_level_nor_the_toggle_keeps_its_fingerprint():
    legacy = _fp(ci_outcomes=_LEGACY_OUTCOMES)
    assert _fp(ci_outcomes={**_LEGACY_OUTCOMES, "failOnMaturityLevel": False}) == legacy
    assert _fp(ci_outcomes=_LEGACY_OUTCOMES, required_publish_level=None) == legacy


def test_the_level_and_the_toggle_each_move_the_fingerprint():
    ladder = {"name": "Maturity", "levels": LEVELS}
    plain = _fp(ci_outcomes=_LEGACY_OUTCOMES, ladder=ladder)
    assert _fp(ci_outcomes=_LEGACY_OUTCOMES, ladder=ladder, required_publish_level="silver") != plain
    assert _fp(ci_outcomes={"failOnMaturityLevel": True}, ladder=ladder) != plain


# ---------------------------------------------------------------------------------------------
# Snapshot freezes the level
# ---------------------------------------------------------------------------------------------


def _snapshot(*, required, ladder_row=LADDER_ROW):
    guide = {
        "id": GUIDE,
        "axis_gates": None,
        "required_coverage": None,
        "ci_outcomes": None,
        "required_publish_level": required,
    }
    with patch("app.lint_policy_service.db.get_style_guide_by_id", return_value=guide), patch(
        "app.lint_policy_service.db.get_style_guide_rules", return_value=[]
    ), patch(
        "app.lint_policy_service.db.get_style_guide_ladder", return_value=ladder_row
    ), patch(
        "app.lint_policy_service.db.insert_style_guide_policy_version",
        return_value={"id": "pv"},
    ) as insert:
        snapshot_style_guide_policy(GUIDE, TENANT)
    return insert.call_args.kwargs


def test_a_pack_freezes_the_required_level_and_its_fingerprint_moves():
    without = _snapshot(required=None)
    frozen = _snapshot(required="silver")
    assert without["required_publish_level"] is None
    assert frozen["required_publish_level"] == "silver"
    assert frozen["content_fingerprint"] != without["content_fingerprint"]


@pytest.mark.parametrize("ladder_row", [None, {"name": "Other", "levels": [{"key": "gold"}]}])
def test_a_level_the_ladder_does_not_have_is_never_frozen(ladder_row):
    kwargs = _snapshot(required="silver", ladder_row=ladder_row)
    assert kwargs["required_publish_level"] is None


def test_insert_policy_version_stores_the_required_level():
    db = Database.__new__(Database)
    db.execute_query = MagicMock(return_value=[{"id": "pv"}])
    db.insert_style_guide_policy_version(
        guide_id=GUIDE,
        tenant_id=TENANT,
        rules_snapshot=[],
        axis_gates={},
        required_coverage=["quality"],
        ci_outcomes={},
        content_fingerprint="f",
        required_publish_level="silver",
    )
    query, params = db.execute_query.call_args.args
    assert "required_publish_level" in query
    assert params[9] == "silver"


def test_the_policy_version_projection_exposes_the_frozen_level():
    row = {"id": "pv", "guide_id": GUIDE, "version_number": 1, "content_fingerprint": "f"}
    out = style_guide_policy_version_out_from_row({**row, "required_publish_level": "silver"})
    assert out.model_dump(by_alias=True)["requiredPublishLevel"] == "silver"
    assert style_guide_policy_version_out_from_row(row).required_publish_level is None


def test_update_policy_settings_writes_the_level_only_when_asked():
    db = Database.__new__(Database)
    db.execute_query = MagicMock(return_value=[{"id": GUIDE}])
    db.update_style_guide_policy_settings(GUIDE, TENANT)
    query, params = db.execute_query.call_args.args
    assert "required_publish_level = CASE" in query
    assert params[-4:-2] == (False, None)
    db.update_style_guide_policy_settings(
        GUIDE, TENANT, required_publish_level="silver", set_required_publish_level=True
    )
    assert db.execute_query.call_args.args[1][-4:-2] == (True, "silver")


# ---------------------------------------------------------------------------------------------
# Deploy-gate and check-suite fingerprints stay put
# ---------------------------------------------------------------------------------------------


def test_deploy_gate_thresholds_without_a_min_level_keep_their_fingerprint():
    body = canonical_thresholds_body(DEFAULT_THRESHOLDS)
    body.pop("maturity")
    legacy = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert thresholds_content_fingerprint(DEFAULT_THRESHOLDS) == legacy
    moved = thresholds_from_body({"maturity": {"minMaturityLevel": "silver"}})
    assert thresholds_content_fingerprint(moved) != legacy


@pytest.mark.parametrize("bad", ["Silver", "", "a b", "x" * 80])
def test_min_maturity_level_must_look_like_a_level_key(bad):
    with pytest.raises(GateThresholdError) as refused:
        thresholds_from_body({"maturity": {"minMaturityLevel": bad}})
    assert "maturity.minMaturityLevel" in str(refused.value)


def test_check_suite_policies_keep_their_fingerprint_while_maturity_is_advisory():
    explicit = policy_from_body({"components": {COMPONENT_MATURITY: "advisory"}})
    assert policy_fingerprint(explicit) == policy_fingerprint(DEFAULT_POLICY)
    required = policy_from_body({"components": {COMPONENT_MATURITY: "required"}})
    assert requirements_fingerprint(required) != requirements_fingerprint(DEFAULT_POLICY)
    assert policy_fingerprint(required) != policy_fingerprint(DEFAULT_POLICY)


# ---------------------------------------------------------------------------------------------
# judge_catalog_revision_maturity
# ---------------------------------------------------------------------------------------------


def _pack(**overrides):
    return {
        "id": "pack-1",
        "ladder": {"name": "Maturity", "levels": LEVELS},
        "required_publish_level": "silver",
        **overrides,
    }


def _policy_with(maturity):
    evaluation = SimpleNamespace(id="eval-1", gate_results={"maturity": maturity})
    return SimpleNamespace(evaluation=evaluation)


def _judge(pack, *, policy=None, required_level=None, evaluate_error=None):
    with patch("app.lint_policy_service.resolve_policy_pack", return_value=pack) as resolve, patch(
        "app.lint_policy_service.evaluate_catalog_revision_policy",
        side_effect=evaluate_error,
        return_value=policy,
    ) as evaluate:
        result = judge_catalog_revision_maturity(
            tenant_id=TENANT,
            project_id=PROJECT,
            version_record_id=REVISION,
            required_level=required_level,
        )
    return result, resolve, evaluate


def test_the_read_judges_the_stored_level_under_the_pack_it_pinned():
    level = {"level": "bronze", "levelLabel": "Bronze", "levelIndex": 0, "blockers": []}
    (judgement, context), _, evaluate = _judge(_pack(), policy=_policy_with(level))
    assert judgement.status == "fail"
    assert judgement.required_level == "silver"
    assert context == {"policyVersionId": "pack-1", "evaluationId": "eval-1"}
    assert evaluate.call_args.kwargs["policy_version_id"] == "pack-1"


def test_an_explicit_required_level_overrides_the_pack():
    level = {"level": "bronze", "levelLabel": "Bronze", "levelIndex": 0, "blockers": []}
    (judgement, _), _, _ = _judge(_pack(), policy=_policy_with(level), required_level="bronze")
    assert judgement.status == "pass"


def test_a_pack_without_a_ladder_is_not_configured_and_never_evaluated():
    (judgement, context), _, evaluate = _judge(_pack(ladder=None))
    assert judgement.status == "not_configured"
    assert context["policyVersionId"] == "pack-1"
    evaluate.assert_not_called()


def test_no_assignable_guide_is_not_configured():
    with patch(
        "app.lint_policy_service.resolve_policy_pack", side_effect=ValueError("no guide")
    ):
        judgement, context = judge_catalog_revision_maturity(
            tenant_id=TENANT, project_id=PROJECT, version_record_id=REVISION
        )
    assert judgement.status == "not_configured"
    assert context["policyVersionId"] is None


def test_an_evaluation_fault_is_unknown_not_a_block():
    (judgement, _), _, _ = _judge(_pack(), evaluate_error=RuntimeError("db down"))
    assert judgement.status == "unknown"
    assert judgement.reason == "maturity-unreadable"
    assert judgement.detail == "db down"
