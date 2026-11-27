"""The contracts publish gate and the publish flow it drives (PFX-7.3, #6963)."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.contracts_publish_gate import (
    AUDIT_ACTION,
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_NO_CONTRACTS,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_UNAVAILABLE,
    STATUS_WARNING,
    assess_contracts_publish_gate,
)
from app.deploy_gate import (
    REASON_CONTRACTS_DEPLOYABLE,
    REASON_CONTRACTS_FORBIDDEN,
    REASON_CONTRACTS_NOT_BOUND,
    REASON_CONTRACTS_NOT_DEPLOYABLE,
    REASON_CONTRACTS_PENDING_RESULTS,
    REASON_CONTRACTS_UNVERIFIED_PROVIDER,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    STATUS_WARN,
    DeployGateThresholds,
    GateSignal,
    thresholds_content_fingerprint,
)
from app.main import app

client = TestClient(app)

_MOCK_JWT = {"tenant_id": "t1", "user_id": "user-a", "auth_method": "jwt"}

_SPEC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {"/pets": {"get": {"summary": "List", "responses": {"200": {"description": "ok"}}}}},
    "components": {"schemas": {}},
}

_ROW = {"type": "error", "code": "verification-failed", "text": "Verification failed for web"}


def _signal(status: str, reason: str, *, deployable: Optional[bool] = None, rows=()) -> GateSignal:
    """A deploy-gate ``contracts`` signal double shaped like ``evaluate_contracts``'s output."""
    return GateSignal(
        signal="contracts",
        status=status,
        satisfied={STATUS_PASS: True, STATUS_FAIL: False, STATUS_WARN: False}.get(status),
        reason=reason,
        detail="Verdict text.",
        data={
            "pacticipant": "billing",
            "version": "1.1.0",
            "environment": None,
            "deployable": deployable,
            "counts": {"verified": 0},
            "reasons": list(rows),
        },
    )


FAIL = _signal(STATUS_FAIL, REASON_CONTRACTS_NOT_DEPLOYABLE, deployable=False, rows=[_ROW])
PASS = _signal(STATUS_PASS, REASON_CONTRACTS_DEPLOYABLE, deployable=True)
WARN = _signal(STATUS_WARN, REASON_CONTRACTS_UNVERIFIED_PROVIDER, deployable=True)
PENDING = _signal(STATUS_UNKNOWN, REASON_CONTRACTS_PENDING_RESULTS)
FORBIDDEN = _signal(STATUS_UNKNOWN, REASON_CONTRACTS_FORBIDDEN)
NOT_BOUND = _signal(STATUS_NOT_CONFIGURED, REASON_CONTRACTS_NOT_BOUND)


def _reader(signal: Optional[GateSignal], calls: Optional[List[tuple]] = None, raises=None):
    """A signal reader double that records what it was asked."""

    def read(tenant_id, project_id, label, environment, permitted):
        if calls is not None:
            calls.append((tenant_id, project_id, label, environment, permitted))
        if raises is not None:
            raise raises
        return signal

    return read


def _assess(signal, policy="block", **kw):
    return assess_contracts_publish_gate(
        tenant_id="t1",
        project_id="p1",
        version={"id": "v1", "version_id": "1.1.0"},
        policy=policy,
        reader=_reader(signal, kw.pop("calls", None), kw.pop("raises", None)),
        **kw,
    )


@pytest.fixture(autouse=True)
def _env_policy():
    """Policy resolution never reaches a real database in these tests."""
    with patch("app.contracts_publish_gate._policy_and_environment", return_value=("warn", "prod")):
        yield


# ---------------------------------------------------------------------------------------------
# assess_contracts_publish_gate
# ---------------------------------------------------------------------------------------------


def test_a_failing_verdict_under_block_is_blocked_with_the_rows():
    assessment = _assess(FAIL, "block", permitted=True)
    assert assessment.status == STATUS_BLOCKED
    assert assessment.blocked and assessment.triggered
    payload = assessment.as_payload()
    assert payload["policy"] == "block"
    assert payload["pacticipant"] == "billing"
    assert payload["version"] == "1.1.0"
    assert payload["deployable"] is False
    assert payload["reasons"] == [_ROW]
    assert payload["reason"] == REASON_CONTRACTS_NOT_DEPLOYABLE
    assert "blocked by failing contracts" in payload["message"]


def test_a_failing_verdict_under_warn_warns_and_never_blocks():
    assessment = _assess(FAIL, "warn", permitted=True)
    assert assessment.status == STATUS_WARNING
    assert assessment.triggered and not assessment.blocked


def test_off_never_reads_the_verdict():
    calls: List[tuple] = []
    assessment = _assess(FAIL, "off", calls=calls, permitted=True)
    assert assessment.status == STATUS_DISABLED
    assert not assessment.triggered
    assert calls == []


@pytest.mark.parametrize(
    "signal,expected",
    [
        (PASS, STATUS_OK),
        (WARN, STATUS_WARNING),
        (PENDING, STATUS_PENDING),
        (FORBIDDEN, STATUS_UNAVAILABLE),
        (NOT_BOUND, STATUS_NO_CONTRACTS),
    ],
)
def test_every_other_signal_maps_and_none_of_them_block(signal, expected):
    assessment = _assess(signal, "block", permitted=True)
    assert assessment.status == expected
    assert assessment.blocked is False


def test_a_fault_degrades_to_unavailable_and_never_blocks():
    assessment = _assess(None, "block", raises=RuntimeError("db down"), permitted=True)
    assert assessment.status == STATUS_UNAVAILABLE
    assert assessment.blocked is False
    assert "db down" in assessment.as_payload()["detail"]


def test_reasons_are_capped_but_counted():
    rows = [{"type": "error", "code": "c", "text": f"row {i}"} for i in range(60)]
    payload = _assess(
        _signal(STATUS_FAIL, REASON_CONTRACTS_NOT_DEPLOYABLE, deployable=False, rows=rows),
        "block",
        permitted=True,
    ).as_payload()
    assert len(payload["reasons"]) == 50
    assert payload["reasonCount"] == 60


def test_the_reader_gets_the_tenant_version_label_environment_and_permission():
    calls: List[tuple] = []
    _assess(PASS, "block", calls=calls, permitted=False)
    assert calls == [("t1", "p1", "1.1.0", "prod", False)]


def test_an_unknown_policy_value_never_escalates_to_block():
    assert _assess(FAIL, "BLOCK!!", permitted=True).blocked is False


def test_the_default_reader_is_the_deploy_gate_contracts_signal():
    with patch("app.deploy_gate_service._contracts_signal", return_value=PASS) as read:
        assessment = assess_contracts_publish_gate(
            tenant_id="t1",
            project_id="p1",
            version={"id": "v1", "version_id": "1.1.0"},
            policy="block",
            permitted=True,
        )
    assert assessment.status == STATUS_OK
    args, kwargs = read.call_args
    assert args == ("t1", "p1", "1.1.0")
    assert kwargs["thresholds"].environment == "prod"
    assert kwargs["permitted"] is True


def test_without_pacts_view_the_default_reader_reports_unavailable():
    """RBAC: the real signal refuses to read pacts for a caller without ``pacts:view``."""
    assessment = assess_contracts_publish_gate(
        tenant_id="t1",
        project_id="p1",
        version={"id": "v1", "version_id": "1.1.0"},
        policy="block",
        permitted=False,
    )
    assert assessment.status == STATUS_UNAVAILABLE
    assert assessment.blocked is False
    assert assessment.as_payload()["reasons"] == []


# ---------------------------------------------------------------------------------------------
# The policy field
# ---------------------------------------------------------------------------------------------


def test_publish_policy_defaults_to_warn_and_normalizes_unknown_values():
    assert DeployGateThresholds().contracts.publish_policy == "warn"
    assert DeployGateThresholds.model_validate(
        {"contracts": {"publishPolicy": "BLOCK"}}
    ).contracts.publish_policy == "block"
    assert DeployGateThresholds.model_validate(
        {"contracts": {"publishPolicy": "nonsense"}}
    ).contracts.publish_policy == "warn"


def test_the_publish_policy_does_not_move_the_gate_fingerprint():
    base = thresholds_content_fingerprint(DeployGateThresholds())
    blocked = thresholds_content_fingerprint(
        DeployGateThresholds.model_validate({"contracts": {"publishPolicy": "block"}})
    )
    assert base == blocked


# ---------------------------------------------------------------------------------------------
# The publish flow and the preflight
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _db() -> MagicMock:
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


def _publish(shared: MagicMock, body: Dict[str, Any], signal: GateSignal, policy: str):
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
        "app.maturity_publish_gate._default_judge", side_effect=RuntimeError("no ladder")
    ), patch(
        "app.contracts_publish_gate._default_reader", return_value=signal
    ), patch(
        "app.contracts_publish_gate._policy_and_environment", return_value=(policy, None)
    ), patch(
        "app.versions_routes.has_permission", return_value=True
    ):
        compat.return_value.overall = "non-breaking"
        return client.post("/v1/versions/acme/pid-1/vid-1/publish", json=body)


def _audits(shared: MagicMock) -> list:
    return [
        call.args[6]
        for call in shared.insert_workflow_audit.call_args_list
        if len(call.args) > 6 and call.args[3] == AUDIT_ACTION
    ]


def test_publish_with_failing_contracts_under_block_is_refused():
    shared = _db()
    res = _publish(shared, {"shortMessage": "Ship it"}, FAIL, "block")
    assert res.status_code == 422
    detail = res.json()["detail"]
    gate = detail["contractsPublishGate"]
    assert gate["status"] == "blocked" and gate["blocked"] is True
    assert gate["reasons"] == [_ROW]
    assert "force-publish with a reason" in detail["message"]
    shared.publish_version.assert_not_called()
    assert _audits(shared) == []


def test_force_publish_goes_past_the_block_and_is_audited_with_the_reason():
    shared = _db()
    res = _publish(
        shared,
        {"shortMessage": "Hotfix", "skipPublishChecks": True, "forcePublishReason": "Incident 6963"},
        FAIL,
        "block",
    )
    assert res.status_code == 200
    audits = _audits(shared)
    assert len(audits) == 1
    assert audits[0]["action"] == "forced"
    assert audits[0]["reason"] == "Incident 6963"
    assert audits[0]["contractsPublishGate"]["blocked"] is True


def test_a_warned_publish_proceeds_and_is_audited_as_warned():
    shared = _db()
    res = _publish(shared, {"shortMessage": "Ship it"}, FAIL, "warn")
    assert res.status_code == 200
    audits = _audits(shared)
    assert [a["action"] for a in audits] == ["warned"]
    assert audits[0]["reason"] is None


@pytest.mark.parametrize("signal,policy", [(PASS, "block"), (PENDING, "block"), (FAIL, "off")])
def test_clean_pending_and_off_publishes_record_nothing(signal, policy):
    shared = _db()
    res = _publish(shared, {"shortMessage": "Ship it"}, signal, policy)
    assert res.status_code == 200
    assert _audits(shared) == []


def test_the_preflight_reports_the_assessment_and_publishes_nothing():
    shared = _db()
    with patch("app.versions_routes.db", shared), patch(
        "app.versions_routes.enforce_permission"
    ), patch("app.versions_routes.has_permission", return_value=True), patch(
        "app.contracts_publish_gate._default_reader", return_value=FAIL
    ), patch("app.contracts_publish_gate._policy_and_environment", return_value=("block", None)):
        res = client.get("/v1/versions/acme/pid-1/vid-1/contracts-publish-gate")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "blocked"
    assert body["policy"] == "block"
    assert body["pacticipant"] == "billing"
    shared.publish_version.assert_not_called()


def test_the_preflight_404s_for_a_revision_of_another_project():
    shared = _db()
    with patch("app.versions_routes.db", shared), patch("app.versions_routes.enforce_permission"):
        res = client.get("/v1/versions/acme/other-project/vid-1/contracts-publish-gate")
    assert res.status_code == 404


def test_the_preflight_requires_versions_view():
    from fastapi import HTTPException

    with patch(
        "app.versions_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="no"),
    ):
        res = client.get("/v1/versions/acme/pid-1/vid-1/contracts-publish-gate")
    assert res.status_code == 403


def test_the_preflight_without_pacts_view_never_discloses_the_verdict():
    shared = _db()
    with patch("app.versions_routes.db", shared), patch(
        "app.versions_routes.enforce_permission"
    ), patch("app.versions_routes.has_permission", return_value=False), patch(
        "app.contracts_publish_gate._policy_and_environment", return_value=("block", None)
    ):
        res = client.get("/v1/versions/acme/pid-1/vid-1/contracts-publish-gate")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unavailable"
    assert body["blocked"] is False
    assert body["reasons"] == []
