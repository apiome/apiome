"""The maturity publish gate and the publish flow it drives (GVM-1.3, #5856)."""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.maturity_gate import judge_maturity
from app.maturity_publish_gate import (
    AUDIT_ACTION,
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_SATISFIED,
    STATUS_UNAVAILABLE,
    assess_maturity_gate,
)

client = TestClient(app)

_MOCK_JWT = {"tenant_id": "t1", "user_id": "user-a", "auth_method": "jwt"}

_LADDER: Dict[str, Any] = {
    "name": "Acme maturity",
    "levels": [
        {"key": "bronze", "label": "Bronze"},
        {"key": "silver", "label": "Silver"},
        {"key": "gold", "label": "Gold"},
    ],
}

_BLOCKER = {
    "levelKey": "silver",
    "kind": "rule",
    "ruleId": "operation-description",
    "maxSeverity": "none",
    "count": 2,
    "sample": ["fp-1", "fp-2"],
}

_SPEC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {"/pets": {"get": {"summary": "List", "responses": {"200": {"description": "ok"}}}}},
    "components": {"schemas": {}},
}


def _level(index: Optional[int]) -> Dict[str, Any]:
    keys = ["bronze", "silver", "gold"]
    return {
        "ladderName": "Acme maturity",
        "level": keys[index] if index is not None else None,
        "levelLabel": keys[index].title() if index is not None else None,
        "levelIndex": index,
        "blockers": [_BLOCKER] if index == 0 else [],
    }


def _judge(result, *, ladder=_LADDER, required="silver", raises: Optional[Exception] = None):
    """A judge double returning one judgement, the way the real read would."""

    def judge(_tenant, _project, _version):
        if raises is not None:
            raise raises
        return (
            judge_maturity(result, ladder=ladder, required_level=required),
            {"policyVersionId": "pack-1", "evaluationId": "eval-1"},
        )

    return judge


# ---------------------------------------------------------------------------------------------
# assess_maturity_gate
# ---------------------------------------------------------------------------------------------


def test_a_draft_below_the_required_level_is_blocked_with_a_dialog_ready_payload():
    assessment = assess_maturity_gate(
        tenant_id="t1", project_id="p1", version={"id": "v1"}, judge=_judge(_level(0))
    )
    assert assessment.status == STATUS_BLOCKED
    assert assessment.blocked is True
    payload = assessment.as_payload()
    assert payload["level"] == "bronze"
    assert payload["requiredLevel"] == "silver"
    assert payload["requiredLevelLabel"] == "Silver"
    assert payload["blockers"] == [_BLOCKER]
    assert payload["policyVersionId"] == "pack-1"
    assert payload["evaluationId"] == "eval-1"
    assert payload["reason"] == "maturity-below-required-level"
    assert "Silver is required" in payload["message"]


def test_a_draft_at_the_required_level_is_satisfied():
    assessment = assess_maturity_gate(
        tenant_id="t1", project_id="p1", version={"id": "v1"}, judge=_judge(_level(1))
    )
    assert assessment.status == STATUS_SATISFIED
    assert assessment.blocked is False


@pytest.mark.parametrize("ladder,required", [(None, "silver"), (_LADDER, None)])
def test_no_ladder_or_no_required_level_disables_the_gate(ladder, required):
    assessment = assess_maturity_gate(
        tenant_id="t1",
        project_id="p1",
        version={"id": "v1"},
        judge=_judge(_level(0), ladder=ladder, required=required),
    )
    assert assessment.status == STATUS_DISABLED
    assert assessment.blocked is False


def test_a_fault_or_an_unknown_level_degrades_to_unavailable_and_never_blocks():
    raised = assess_maturity_gate(
        tenant_id="t1",
        project_id="p1",
        version={"id": "v1"},
        judge=_judge(None, raises=RuntimeError("db down")),
    )
    assert raised.status == STATUS_UNAVAILABLE
    assert raised.as_payload()["detail"] == "db down"
    unknown = assess_maturity_gate(
        tenant_id="t1",
        project_id="p1",
        version={"id": "v1"},
        judge=_judge(_level(2), required="platinum"),
    )
    assert unknown.status == STATUS_UNAVAILABLE
    assert unknown.blocked is False


def test_the_default_judge_is_the_shared_lint_policy_read():
    judgement = judge_maturity(_level(2), ladder=_LADDER, required_level="gold")
    with patch(
        "app.lint_policy_service.judge_catalog_revision_maturity",
        return_value=(judgement, {"policyVersionId": "pack-9", "evaluationId": None}),
    ) as read:
        assessment = assess_maturity_gate(tenant_id="t1", project_id="p1", version={"id": "v1"})
    assert assessment.status == STATUS_SATISFIED
    assert assessment.policy_version_id == "pack-9"
    assert read.call_args.kwargs == {
        "tenant_id": "t1",
        "project_id": "p1",
        "version_record_id": "v1",
    }


# ---------------------------------------------------------------------------------------------
# The publish flow
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _publish_db() -> MagicMock:
    """A db double wired for the publish route with every other gate clean or off."""
    shared = MagicMock()
    shared.get_version_by_id.side_effect = lambda vid, _tid: (
        {
            "id": "vid-1",
            "project_id": "pid-1",
            "version_id": "1.1.0",
            "published": False,
            "creator_id": "user-a",
            "description": "Ship it",
        }
        if str(vid) == "vid-1"
        else None
    )
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay", "metadata": {}}
    shared.get_prior_published_baseline_revision_id.return_value = None
    shared.get_assigned_style_guide.return_value = {
        "id": "g1",
        "name": "Payments",
        "source": "custom",
        "breaking_publish_policy": "off",
        "required_approvals": 0,
    }
    shared.publish_version.return_value = {
        "id": "vid-1",
        "project_id": "pid-1",
        "version_id": "1.1.0",
        "published": True,
        "creator_id": "user-a",
        "visibility": "private",
        "description": "Ship it",
        "change_log": None,
    }
    return shared


def _publish(shared: MagicMock, body: Dict[str, Any], judgement, *, raises=None):
    """POST the publish endpoint with the maturity read returning ``judgement``."""
    read = (
        {"side_effect": raises}
        if raises is not None
        else {"return_value": (judgement, {"policyVersionId": "pack-1", "evaluationId": "e1"})}
    )
    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared
    ), patch("app.approval_publish_gate.db", shared), patch(
        "app.breaking_publish_guardrail.db", shared
    ), patch("app.publication_change_report.db", shared), patch(
        "app.version_publish_prechecks.openapi_for_revision", return_value=copy.deepcopy(_SPEC)
    ), patch("app.version_publish_prechecks.CompatibilityCheckEngine.run") as compat, patch(
        "app.version_publish_prechecks.evaluate_and_record",
        side_effect=RuntimeError("policy not configured"),
    ), patch(
        "app.lint_policy_service.judge_catalog_revision_maturity", **read
    ) as maturity_read:
        compat.return_value.overall = "non-breaking"
        response = client.post("/v1/versions/acme/pid-1/vid-1/publish", json=body)
    return response, maturity_read


def _maturity_audits(shared: MagicMock) -> list:
    """Every ``version.maturity_gate`` audit write recorded on the double."""
    return [
        call.args[6]
        for call in shared.insert_workflow_audit.call_args_list
        if len(call.args) > 6 and call.args[3] == AUDIT_ACTION
    ]


def test_publish_at_bronze_requiring_silver_is_refused_with_the_blockers():
    shared = _publish_db()
    judgement = judge_maturity(_level(0), ladder=_LADDER, required_level="silver")
    res, _ = _publish(shared, {"shortMessage": "Ship it"}, judgement)

    assert res.status_code == 422
    detail = res.json()["detail"]
    gate = detail["maturityGate"]
    assert gate["status"] == "blocked"
    assert gate["blocked"] is True
    assert gate["level"] == "bronze"
    assert gate["requiredLevel"] == "silver"
    assert gate["blockers"] == [_BLOCKER]
    assert "force-publish with a reason" in detail["message"]
    shared.publish_version.assert_not_called()
    assert _maturity_audits(shared) == []


def test_force_publish_succeeds_and_the_audit_row_says_forced():
    shared = _publish_db()
    judgement = judge_maturity(_level(0), ladder=_LADDER, required_level="silver")
    res, read = _publish(
        shared,
        {
            "shortMessage": "Hotfix",
            "skipPublishChecks": True,
            "forcePublishReason": "Incident 5856 — level to follow",
        },
        judgement,
    )

    assert res.status_code == 200
    shared.publish_version.assert_called_once()
    read.assert_called_once()
    audits = _maturity_audits(shared)
    assert len(audits) == 1
    assert audits[0]["action"] == "forced"
    assert audits[0]["reason"].startswith("Incident 5856")
    assert audits[0]["maturityGate"]["blocked"] is True
    assert audits[0]["maturityGate"]["requiredLevel"] == "silver"


def test_a_satisfied_publish_is_audited_with_the_level_reached():
    shared = _publish_db()
    judgement = judge_maturity(_level(2), ladder=_LADDER, required_level="silver")
    res, _ = _publish(shared, {"shortMessage": "Ship it"}, judgement)

    assert res.status_code == 200
    audits = _maturity_audits(shared)
    assert [a["action"] for a in audits] == ["satisfied"]
    assert audits[0]["maturityGate"]["level"] == "gold"
    assert audits[0]["reason"] is None


def test_a_guide_without_a_ladder_never_arms_the_gate_or_audits():
    shared = _publish_db()
    judgement = judge_maturity(_level(0), ladder=None, required_level="silver")
    res, _ = _publish(shared, {"shortMessage": "Ship it"}, judgement)

    assert res.status_code == 200
    assert _maturity_audits(shared) == []


def test_a_gate_fault_never_blocks_and_is_audited_as_unavailable():
    shared = _publish_db()
    res, _ = _publish(shared, {"shortMessage": "Ship it"}, None, raises=RuntimeError("db down"))

    assert res.status_code == 200
    audits = _maturity_audits(shared)
    assert [a["action"] for a in audits] == ["unavailable"]
    assert audits[0]["maturityGate"]["detail"] == "db down"
