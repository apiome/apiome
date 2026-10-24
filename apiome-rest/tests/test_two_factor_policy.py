"""Tenant two-factor policy — TFA-1.3 (#5657).

* The rule: a member's deadline is the later of the policy being turned on and the member joining,
  plus the grace days; each member is ``not_required``, ``enabled``, ``grace`` or ``overdue``. Run
  against Postgres itself, since the rule is SQL shared by the policy read and the members list.
* The policy read/write: turning the policy on stamps ``two_factor_required_since`` once, turning it
  off clears it; changes are audited in the same transaction; unchanged saves are not.
* The routes: ``members:view`` to read, ``members:edit`` to change, ``grace_days`` bounded 0–90.
* The members list carries each member's status and deadline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import two_factor_policy as policy
from app import two_factor_policy_routes as routes
from app.auth import validate_authentication
from app.consumer_contract_store import ConsumerActor
from app.database import db
from app.main import app
from app.two_factor_policy import DUE_AT_SQL, STATUS_SQL, TwoFactorPolicy, TwoFactorPolicyInput

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "33333333-3333-4333-8333-333333333333"


# ---------------------------------------------------------------------------------------------
# the rule, in Postgres
# ---------------------------------------------------------------------------------------------


def _evaluate(required: bool, since_days_ago: Optional[int], joined_days_ago: int, enabled: bool,
              grace_days: int = 7) -> Dict[str, Any]:
    """Run the shared SQL over one literal tenant / membership / user row."""
    since = "NULL::timestamptz" if since_days_ago is None else f"now() - interval '{since_days_ago} days'"
    sql = f"""
        SELECT ({STATUS_SQL}) AS status, ({DUE_AT_SQL}) AS due_at,
               ({DUE_AT_SQL}) - now() AS remaining
        FROM (SELECT {str(required).upper()} AS require_two_factor, {grace_days} AS two_factor_grace_days,
                     {since} AS two_factor_required_since) tn,
             (SELECT now() - interval '{joined_days_ago} days' AS created_at) tu,
             (SELECT {str(enabled).upper()} AS "twoFactorEnabled") u
    """
    try:
        rows = db.execute_query(sql)
    except Exception as exc:  # pragma: no cover - needs the local database
        pytest.skip(f"database unavailable: {exc}")
    return dict(rows[0])


def test_the_policy_off_requires_nothing() -> None:
    row = _evaluate(required=False, since_days_ago=None, joined_days_ago=30, enabled=False)
    assert row["status"] == "not_required" and row["due_at"] is None


def test_a_member_with_two_factor_is_compliant_whatever_the_deadline() -> None:
    assert _evaluate(required=True, since_days_ago=60, joined_days_ago=60, enabled=True)["status"] == "enabled"


def test_existing_members_share_the_deadline_from_when_the_policy_was_turned_on() -> None:
    inside = _evaluate(required=True, since_days_ago=3, joined_days_ago=400, enabled=False)
    assert inside["status"] == "grace"
    assert 3 * 86400 < inside["remaining"].total_seconds() <= 4 * 86400
    past = _evaluate(required=True, since_days_ago=8, joined_days_ago=400, enabled=False)
    assert past["status"] == "overdue"


def test_a_member_who_joins_later_gets_their_own_full_grace_period() -> None:
    # The policy has been on for a month; this member joined yesterday.
    row = _evaluate(required=True, since_days_ago=30, joined_days_ago=1, enabled=False)
    assert row["status"] == "grace"
    assert 5 * 86400 < row["remaining"].total_seconds() <= 6 * 86400


def test_a_zero_day_grace_period_is_due_at_once() -> None:
    assert _evaluate(required=True, since_days_ago=0, joined_days_ago=10, enabled=False, grace_days=0)[
        "status"
    ] == "overdue"


# ---------------------------------------------------------------------------------------------
# the policy read / write
# ---------------------------------------------------------------------------------------------


class _Cursor:
    """A cursor that answers each ``fetchone`` / ``fetchall`` from a queue."""

    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.statements: List[str] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append(" ".join(sql.split()))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.answers.pop(0)

    def fetchall(self) -> List[Dict[str, Any]]:
        return self.answers.pop(0)


def _row(on: bool = False, days: int = 7, since: Optional[str] = None) -> Dict[str, Any]:
    return {"require_two_factor": on, "two_factor_grace_days": days, "two_factor_required_since": since}


@pytest.fixture
def audits(monkeypatch):
    recorded: List[Dict[str, Any]] = []
    monkeypatch.setattr(policy.db, "_append_access_audit", lambda cursor, **kw: recorded.append(kw))
    return recorded


def test_read_counts_active_members_by_state(monkeypatch) -> None:
    answers = [[_row(on=True, since="2026-10-01T00:00:00+00:00")],
               [{"status": "enabled", "members": 4}, {"status": "overdue", "members": 1}]]
    seen: List[str] = []
    monkeypatch.setattr(policy.db, "execute_query", lambda sql, params=None: seen.append(sql) or answers.pop(0))
    result = policy.read_policy(_TENANT)
    assert result.require_two_factor is True and result.grace_days == 7
    assert result.compliance.model_dump() == {"enabled": 4, "grace": 0, "overdue": 1}
    # Only active members count: an invitation is not yet a member who can comply.
    assert "tu.status = 'active'" in seen[1]


def test_read_of_an_unknown_tenant_is_the_defaults() -> None:
    result = policy.read_policy("t1")
    assert result == TwoFactorPolicy(require_two_factor=False, grace_days=policy.DEFAULT_GRACE_DAYS)


def test_turning_it_on_stamps_the_start_and_is_audited(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(), [], _row(on=True, since="2026-10-23T12:00:00+00:00"), []])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    result = policy.update_policy(
        _TENANT, TwoFactorPolicyInput(require_two_factor=True), actor=ConsumerActor(user_id=_USER, label="ada")
    )
    assert result.require_two_factor is True
    update = next(s for s in cursor.statements if s.startswith("UPDATE apiome.tenants"))
    # COALESCE keeps an existing stamp, so saving while on never restarts anyone's clock.
    assert "two_factor_required_since = COALESCE(two_factor_required_since, now())" in update
    assert "two_factor_grace_days" not in update
    assert audits[0]["action"] == "two_factor_policy.update"
    assert audits[0]["target"] == "two-factor-policy"
    assert audits[0]["detail"]["from"]["require_two_factor"] is False
    assert audits[0]["detail"]["to"]["require_two_factor"] is True
    # Compliance counts move on their own; they are not part of the audited change.
    assert "compliance" not in audits[0]["detail"]["to"]


def test_turning_it_off_clears_the_start(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(on=True, since="2026-10-01T00:00:00+00:00"), [], _row(), []])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    policy.update_policy(_TENANT, TwoFactorPolicyInput(require_two_factor=False), actor=ConsumerActor(user_id=_USER))
    update = next(s for s in cursor.statements if s.startswith("UPDATE apiome.tenants"))
    assert "two_factor_required_since = NULL" in update
    assert audits and audits[0]["detail"]["to"]["required_since"] is None


def test_changing_only_the_grace_period_touches_only_that(monkeypatch, audits) -> None:
    since = "2026-10-01T00:00:00+00:00"
    cursor = _Cursor([_row(on=True, since=since), [], _row(on=True, days=14, since=since), []])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    policy.update_policy(_TENANT, TwoFactorPolicyInput(grace_days=14), actor=ConsumerActor(user_id=_USER))
    update = next(s for s in cursor.statements if s.startswith("UPDATE apiome.tenants"))
    assert "two_factor_grace_days = %s" in update and "require_two_factor" not in update
    assert audits[0]["detail"]["to"]["grace_days"] == 14


def test_an_unchanged_policy_is_not_audited(monkeypatch, audits) -> None:
    cursor = _Cursor([_row(on=True, since="x"), [], _row(on=True, since="x"), []])
    monkeypatch.setattr(policy.db, "_guarded_tx", lambda work: work(cursor))
    policy.update_policy(_TENANT, TwoFactorPolicyInput(require_two_factor=True), actor=ConsumerActor())
    assert audits == []


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
    changes: List[TwoFactorPolicyInput] = []
    monkeypatch.setattr(routes, "read_policy", lambda tenant: TwoFactorPolicy(require_two_factor=False, grace_days=7))
    monkeypatch.setattr(
        routes,
        "update_policy",
        lambda tenant, body, actor: changes.append(body) or TwoFactorPolicy(require_two_factor=True, grace_days=14),
    )

    assert http.get("/v1/tenants/acme/two-factor-policy").json()["grace_days"] == 7
    body = http.put("/v1/tenants/acme/two-factor-policy", json={"require_two_factor": True, "grace_days": 14}).json()
    assert body["require_two_factor"] is True and body["compliance"] == {"enabled": 0, "grace": 0, "overdue": 0}
    assert changes[0].model_fields_set == {"require_two_factor", "grace_days"}
    assert asked == ["members:view", "members:edit"]


@pytest.mark.parametrize("payload", [{"grace_days": -1}, {"grace_days": 91}, {"unknown": True}])
def test_the_routes_refuse_a_bad_change(client, payload) -> None:
    http, _ = client
    assert http.put("/v1/tenants/acme/two-factor-policy", json=payload).status_code == 422


def test_the_members_list_carries_each_members_compliance(monkeypatch) -> None:
    seen: List[str] = []
    monkeypatch.setattr(db, "execute_query", lambda sql, params=None: seen.append(sql) or [])
    db.list_members(_TENANT)
    assert "AS two_factor_status" in seen[0] and "AS two_factor_due_at" in seen[0]
    assert "{STATUS_SQL}" not in seen[0] and "GREATEST(tn.two_factor_required_since, tu.created_at)" in seen[0]
