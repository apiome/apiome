"""Unowned-entity policy and ownership drift — CDG-2.5 (#5964).

* The owner gate: ``disabled`` unless the tenant turned it on; ``blocked`` (reason ``no-owner``)
  without a confirmed live owner; a 422 from the publish prechecks after the approval gate, and the
  verdict attached either way.
* The policy read/write: a catch-all slug must name a live team; changes are audited in the same
  transaction; routes are gated on ``teams:view`` / ``teams:edit``.
* Drift: the three reasons, capped per reason, with totals.
* Facts: ``owner.present`` / ``owner.contactable``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import ownership_policy as policy
from app import ownership_policy_routes as routes
from app.auth import validate_authentication
from app.consumer_contract_store import ConsumerActor
from app.main import app
from app.ownership_policy import (
    GATE_BLOCKED,
    GATE_DISABLED,
    GATE_SATISFIED,
    REASON_NO_OWNER,
    OwnershipPolicyError,
    OwnershipPolicyInput,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_USER = "33333333-3333-4333-8333-333333333333"
_TEAM = "44444444-4444-4444-8444-444444444444"


# ---------------------------------------------------------------------------------------------
# the owner gate
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row,status",
    [
        ({"require_owner_to_publish": False, "slug": None, "name": None}, GATE_DISABLED),
        ({"require_owner_to_publish": False, "slug": "payments", "name": "Payments"}, GATE_DISABLED),
        ({"require_owner_to_publish": True, "slug": "payments", "name": "Payments"}, GATE_SATISFIED),
        ({"require_owner_to_publish": True, "slug": None, "name": None}, GATE_BLOCKED),
    ],
)
def test_the_owner_gate(monkeypatch, row, status) -> None:
    seen: List[str] = []
    monkeypatch.setattr(policy.db, "execute_query", lambda sql, params=None: seen.append(sql) or [row])
    assessment = policy.assess_owner_gate(tenant_id=_TENANT, project_id=_PROJECT)
    assert assessment.status == status
    payload = assessment.as_payload()
    assert payload["message"]
    assert (payload.get("reason") == REASON_NO_OWNER) is (status == GATE_BLOCKED)
    # Only a confirmed owner on a live team counts.
    assert "eo.status = 'confirmed'" in seen[0] and "t.deleted_at IS NULL" in seen[0]


def test_a_disabled_gate_says_so() -> None:
    assessment = policy.OwnerGateAssessment(status=GATE_DISABLED)
    assert "off" in assessment.message() and assessment.blocked is False


def test_the_prechecks_refuse_an_unowned_project_with_no_owner(monkeypatch) -> None:
    from app.version_publish_prechecks import PublishPrecheckOutcome, _with_owner_gate

    monkeypatch.setattr(
        policy, "assess_owner_gate", lambda **kw: policy.OwnerGateAssessment(status=GATE_BLOCKED)
    )
    with pytest.raises(HTTPException) as caught:
        _with_owner_gate(PublishPrecheckOutcome(), tenant_id=_TENANT, project_id=_PROJECT)
    assert caught.value.status_code == 422
    assert caught.value.detail["reason"] == REASON_NO_OWNER
    assert caught.value.detail["ownerGate"]["status"] == GATE_BLOCKED

    monkeypatch.setattr(
        policy, "assess_owner_gate", lambda **kw: policy.OwnerGateAssessment(status=GATE_DISABLED)
    )
    outcome = _with_owner_gate(PublishPrecheckOutcome(), tenant_id=_TENANT, project_id=_PROJECT)
    assert outcome.owner_gate["status"] == GATE_DISABLED


def test_the_owner_gate_runs_after_the_approval_gate() -> None:
    import inspect

    from app import version_publish_prechecks

    source = inspect.getsource(version_publish_prechecks.enforce_publish_prechecks)
    assert source.index("_with_approval_gate(") < source.index("_with_owner_gate(")


# ---------------------------------------------------------------------------------------------
# the policy
# ---------------------------------------------------------------------------------------------


class _Cursor:
    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.statements: List[str] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append(" ".join(sql.split()))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.answers.pop(0)


def _row(team: bool = False, gate: bool = False) -> Dict[str, Any]:
    return {
        "require_owner_to_publish": gate,
        "team_id": _TEAM if team else None,
        "team_slug": "platform" if team else None,
        "team_name": "Platform" if team else None,
        "team_deleted": False,
        "team_members": 3,
    }


@pytest.fixture
def audits(monkeypatch):
    recorded: List[Dict[str, Any]] = []
    monkeypatch.setattr(policy.db, "_append_access_audit", lambda cursor, **kw: recorded.append(kw))
    return recorded


def test_setting_the_catch_all_and_the_gate_is_audited(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(), {"id": _TEAM}, _row(team=True, gate=True)])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    result = policy.update_policy(
        _TENANT,
        OwnershipPolicyInput(unowned_findings_team="Platform", require_owner_to_publish=True),
        actor=ConsumerActor(user_id=_USER, label="ada"),
    )
    assert result.unowned_findings_team and result.unowned_findings_team.slug == "platform"
    assert result.require_owner_to_publish is True
    update = next(s for s in cursor.statements if s.startswith("UPDATE apiome.tenants"))
    assert "unowned_findings_team_id = %s::uuid" in update and "require_owner_to_publish = %s" in update
    assert audits[0]["action"] == "ownership_policy.update"
    assert audits[0]["detail"]["to"]["require_owner_to_publish"] is True


def test_an_unknown_catch_all_team_is_refused(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(), None])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    with pytest.raises(OwnershipPolicyError):
        policy.update_policy(
            _TENANT, OwnershipPolicyInput(unowned_findings_team="ghost"), actor=ConsumerActor(user_id=_USER)
        )
    assert audits == []


def test_clearing_the_catch_all_only_touches_that_field(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(team=True), _row()])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    policy.update_policy(_TENANT, OwnershipPolicyInput(unowned_findings_team=None), actor=ConsumerActor(user_id=_USER))
    update = next(s for s in cursor.statements if s.startswith("UPDATE apiome.tenants"))
    assert "unowned_findings_team_id" in update and "require_owner_to_publish" not in update


def test_an_unchanged_policy_is_not_audited(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(gate=True), _row(gate=True)])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    policy.update_policy(_TENANT, OwnershipPolicyInput(require_owner_to_publish=True), actor=ConsumerActor())
    assert audits == []


# ---------------------------------------------------------------------------------------------
# drift and facts
# ---------------------------------------------------------------------------------------------


def test_drift_reports_each_reason_with_totals(monkeypatch) -> None:
    rows = [
        {"reason": "deleted_team", "entity_kind": "project", "entity_id": _PROJECT, "entity_name": "Payments API",
         "team_slug": "old", "team_name": "Old", "since": None, "reason_total": 1},
        {"reason": "stale_suggestion", "entity_kind": "connector", "entity_id": _TEAM, "entity_name": "Kong",
         "team_slug": "platform", "team_name": "Platform", "since": None, "reason_total": 250},
    ]
    seen: List[Any] = []
    monkeypatch.setattr(policy.db, "execute_query", lambda sql, params=None: seen.append((sql, params)) or rows)
    report = policy.ownership_drift(_TENANT)
    assert report["counts"] == {"deleted_team": 1, "stale_suggestion": 250}
    assert report["items"][0]["team"] == {"slug": "old", "name": "Old"}
    sql, params = seen[0]
    assert "t.deleted_at IS NOT NULL" in sql and "NOT EXISTS (SELECT 1 FROM apiome.team_members" in sql
    assert params[2] == policy.STALE_SUGGESTION_DAYS


def test_facts(monkeypatch) -> None:
    monkeypatch.setattr(policy.db, "execute_query", lambda sql, params=None: [{"contactable": True}])
    assert policy.owner_facts(_TENANT, "project", _PROJECT) == {"owner.present": True, "owner.contactable": True}
    monkeypatch.setattr(policy.db, "execute_query", lambda sql, params=None: [])
    assert policy.owner_facts(_TENANT, "connector", _PROJECT) == {"owner.present": False, "owner.contactable": False}
    assert policy.owner_facts("t1", "project", _PROJECT)["owner.present"] is False


# ---------------------------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return True

    monkeypatch.setattr(routes.db, "user_has_permission", _has)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield TestClient(app), asked
    app.dependency_overrides.clear()


def test_routes_and_their_permissions(client, monkeypatch) -> None:
    http, asked = client
    monkeypatch.setattr(routes, "read_policy", lambda tenant: policy.OwnershipPolicy(require_owner_to_publish=False))
    monkeypatch.setattr(
        routes, "update_policy", lambda tenant, body, actor: policy.OwnershipPolicy(require_owner_to_publish=True)
    )
    monkeypatch.setattr(routes, "ownership_drift", lambda tenant: {"items": [], "counts": {}, "stale_after_days": 30})
    monkeypatch.setattr(routes, "assess_owner_gate", lambda **kw: policy.OwnerGateAssessment(status=GATE_BLOCKED))

    assert http.get("/v1/tenants/acme/ownership-policy").json()["require_owner_to_publish"] is False
    assert http.put("/v1/tenants/acme/ownership-policy", json={"require_owner_to_publish": True}).json()[
        "require_owner_to_publish"
    ] is True
    assert http.get("/v1/tenants/acme/ownership-drift").json()["stale_after_days"] == 30
    gate = http.get("/v1/tenants/acme/ownership-policy/publish-gate", params={"project": _PROJECT}).json()
    assert gate["status"] == GATE_BLOCKED and gate["reason"] == REASON_NO_OWNER
    assert http.get("/v1/tenants/acme/ownership-policy/publish-gate", params={"project": "x"}).status_code == 400
    assert asked == ["teams:view", "teams:edit", "teams:view", "versions:view", "versions:view"]


def test_an_unknown_catch_all_is_404(client, monkeypatch) -> None:
    http, _ = client

    def _refuse(tenant, body, actor):
        raise OwnershipPolicyError(policy.CODE_TEAM_NOT_FOUND, "no team 'ghost'")

    monkeypatch.setattr(routes, "update_policy", _refuse)
    response = http.put("/v1/tenants/acme/ownership-policy", json={"unowned_findings_team": "ghost"})
    assert response.status_code == 404 and response.json()["detail"]["code"] == policy.CODE_TEAM_NOT_FOUND


def test_the_owners_read_carries_the_facts(client, monkeypatch) -> None:
    from app import entity_owner_routes
    from app.entity_owners import OwnersResponse

    http, _ = client
    monkeypatch.setattr(entity_owner_routes, "read_owners", lambda t, k, i: OwnersResponse(kind=k, entity_id=i))
    facts = {"owner.present": False, "owner.contactable": False}
    monkeypatch.setattr(entity_owner_routes, "owner_facts", lambda t, k, i: facts)
    body = http.get(f"/v1/tenants/acme/owners/project/{_PROJECT}").json()
    assert body["facts"] == {"owner.present": False, "owner.contactable": False}


def test_migration(repo_root) -> None:
    text = (repo_root / "apiome-db/scripts/V287__ownership_policy_cdg_2_5.sql").read_text()
    assert "unowned_findings_team_id UUID REFERENCES teams(id) ON DELETE SET NULL" in text
    assert "require_owner_to_publish BOOLEAN NOT NULL DEFAULT FALSE" in text

