"""Owner routing of findings — CDG-2.3 (#5962).

:func:`app.owner_routing.route_owner_finding` against a small in-memory database double: the reads
answer from fixtures, the transaction hands the routing a recording cursor, and the inbox and
direct-delivery writers record what they were given. Pinned here:

* a finding on an **owned** entity writes one inbox row per team member — minus the actor and anyone
  the producer already notified (a requester) — and **one** chat delivery, in one transaction;
* a Slack chat URL gets a Slack-shaped body, anything else the structured event;
* the throttle holds: a second claim in the window writes nothing;
* a finding on an **unowned** entity writes no inbox row and lands in the Unowned report;
* suggested owners never receive anything;
* malformed input is skipped, and the safe wrapper never raises.

The SQL (throttle claim, unowned upsert) ran against Postgres when the ticket was built.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.owner_routing import (
    OUTCOME_ROUTED,
    OUTCOME_SKIPPED,
    OUTCOME_THROTTLED,
    OUTCOME_UNOWNED,
    TYPE_OWNER_BREAKING_CHANGE,
    TYPE_OWNER_SYNC_FAILED,
    OwnerFinding,
    entity_link,
    owner_recipients,
    project_id_for_version_ref,
    route_mcp_endpoint_problem,
    route_owner_finding,
    route_owner_finding_safely,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_TEAM = "33333333-3333-4333-8333-333333333333"
_LEAD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_MEMBER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_REQUESTER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class _Cursor:
    def __init__(self, db: "_Db") -> None:
        self.db = db
        self.statements: List[str] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append(" ".join(sql.split()))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return {"claimed": self.db.claim}


class _Db:
    """The reads routing makes, plus recording transaction and writers."""

    def __init__(
        self,
        *,
        owner: Optional[Dict[str, Any]] = None,
        publishable: bool = True,
        claim: bool = True,
        catch_all: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.owner = owner
        self.catch_all = catch_all
        self.publishable = publishable
        self.claim = claim
        self.queries: List[str] = []
        self.cursors: List[_Cursor] = []
        self.drafts: List[Any] = []
        self.deliveries: List[Dict[str, Any]] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        self.queries.append(" ".join(sql.split()))
        if "FROM apiome.projects WHERE id" in sql:
            return [{"publishable": self.publishable}]
        if "unowned_findings_team_id" in sql:
            return [self.catch_all] if self.catch_all else []
        if "FROM apiome.entity_owners eo" in sql:
            assert "eo.status = 'confirmed'" in sql
            return [self.owner] if self.owner else []
        if "FROM apiome.projects" in sql and "slug = %s OR id::text = %s" in sql:
            return [{"id": _PROJECT}] if params[1] == "petstore" else []
        raise AssertionError(f"unexpected query: {sql}")

    def _guarded_tx(self, work: Any) -> Any:
        cursor = _Cursor(self)
        self.cursors.append(cursor)
        return work(cursor)

    def _insert_notifications(self, cursor: Any, *, tenant_id: str, notify: Any, produced: Any = None) -> int:
        assert cursor is self.cursors[-1]
        drafts = list(notify({}))
        self.drafts.extend(drafts)
        return len(drafts)

    def _insert_direct_delivery(self, cursor: Any, **kwargs: Any) -> str:
        assert cursor is self.cursors[-1]
        self.deliveries.append(kwargs)
        return f"d{len(self.deliveries)}"


def _owner(chat_url: Optional[str] = "https://hooks.slack.com/services/T/B/X") -> Dict[str, Any]:
    return {
        "team_id": _TEAM, "slug": "payments", "name": "Payments", "chat_url": chat_url,
        "members": [_LEAD, _MEMBER, _REQUESTER],
    }


def _finding(**overrides: Any) -> OwnerFinding:
    values: Dict[str, Any] = {
        "tenant_id": _TENANT,
        "entity_kind": "project",
        "entity_id": _PROJECT,
        "finding_type": TYPE_OWNER_BREAKING_CHANGE,
        "summary": "2 breaking changes on refresh",
        "link": f"/ade/dashboard/versions?projectId={_PROJECT}",
        "finding_id": "report-1",
        "details": {"breakingChangeCount": 2},
        "already_notified": (_REQUESTER,),
        "version_id": "44444444-4444-4444-8444-444444444444",
    }
    values.update(overrides)
    return OwnerFinding(**values)


# ---------------------------------------------------------------------------------------------
# owned
# ---------------------------------------------------------------------------------------------


def test_an_owned_breaking_change_reaches_each_member_once_and_the_chat_once() -> None:
    db = _Db(owner=_owner())
    outcome = route_owner_finding(db, _finding())
    assert outcome.status == OUTCOME_ROUTED and outcome.team_slug == "payments"
    # The requester was already notified, so the team's other two members get one row each.
    assert sorted(d.user_id for d in db.drafts) == sorted([_LEAD, _MEMBER])
    assert outcome.inbox_rows == 2
    assert {d.type for d in db.drafts} == {TYPE_OWNER_BREAKING_CHANGE}
    payload = db.drafts[0].payload
    assert payload["entity_kind"] == "project" and payload["entity_id"] == _PROJECT
    assert payload["team"] == {"id": _TEAM, "slug": "payments", "name": "Payments"}
    assert payload["finding_id"] == "report-1" and payload["link"].startswith("/ade/")
    assert db.drafts[0].project_id == _PROJECT
    # One delivery, Slack-shaped, written in the same transaction as the rows.
    assert len(db.deliveries) == 1 and len(db.cursors) == 1
    delivery = db.deliveries[0]
    assert delivery["target_url"].startswith("https://hooks.slack.com/")
    assert delivery["team_id"] == _TEAM and delivery["event_type"] == "owner.breaking_change"
    assert delivery["payload"]["text"] == "[Payments] 2 breaking changes on refresh"
    # The unowned entry for this entity and type is cleared in that transaction too.
    assert any("DELETE FROM apiome.unowned_findings" in s for s in db.cursors[0].statements)


def test_a_non_slack_chat_url_gets_the_structured_event() -> None:
    db = _Db(owner=_owner("https://chat.example.com/hooks/payments"))
    route_owner_finding(db, _finding())
    body = db.deliveries[0]["payload"]
    assert body["event"] == "owner.breaking_change" and body["team"] == "payments"
    assert body["entity_id"] == _PROJECT and body["reviewHref"].startswith("/ade/")


def test_a_team_without_a_chat_url_gets_inbox_rows_only() -> None:
    db = _Db(owner=_owner(None))
    outcome = route_owner_finding(db, _finding())
    assert outcome.chat_delivery_id is None and db.deliveries == []
    assert outcome.inbox_rows == 2


def test_the_actor_is_not_told_about_their_own_action() -> None:
    db = _Db(owner=_owner())
    route_owner_finding(db, _finding(actor_id=_LEAD, already_notified=()))
    assert sorted(d.user_id for d in db.drafts) == sorted([_MEMBER, _REQUESTER])
    assert all(d.actor_id == _LEAD for d in db.drafts)


def test_the_throttle_holds_a_repeat_in_the_window() -> None:
    db = _Db(owner=_owner(), claim=False)
    outcome = route_owner_finding(db, _finding())
    assert outcome.status == OUTCOME_THROTTLED
    assert db.drafts == [] and db.deliveries == []
    assert "INSERT INTO apiome.owner_notification_throttle" in db.cursors[0].statements[0]


def test_a_catalog_item_is_stored_as_its_own_kind() -> None:
    db = _Db(owner=_owner(), publishable=False)
    route_owner_finding(db, _finding())
    assert db.drafts[0].payload["entity_kind"] == "catalog_item"


def test_a_connector_finding_has_no_project_column() -> None:
    db = _Db(owner=_owner(None))
    route_owner_finding(db, _finding(entity_kind="connector", finding_type=TYPE_OWNER_SYNC_FAILED))
    assert db.drafts[0].project_id is None
    assert not any("FROM apiome.projects" in q for q in db.queries)


# ---------------------------------------------------------------------------------------------
# unowned
# ---------------------------------------------------------------------------------------------


def test_an_unowned_breaking_change_writes_no_row_and_lands_in_the_report() -> None:
    db = _Db(owner=None)
    outcome = route_owner_finding(db, _finding())
    assert outcome.status == OUTCOME_UNOWNED
    assert db.drafts == [] and db.deliveries == []
    upsert = db.cursors[0].statements[0]
    assert "INSERT INTO apiome.unowned_findings" in upsert
    assert "occurrences = apiome.unowned_findings.occurrences + 1" in upsert


def test_only_a_confirmed_owner_counts() -> None:
    """The owner query filters on confirmed rows; a suggestion is never a recipient."""
    db = _Db(owner=None)
    assert owner_recipients(db, _TENANT, "project", _PROJECT) is None
    assert any("eo.status = 'confirmed'" in q for q in db.queries)


# ---------------------------------------------------------------------------------------------
# skipped / safe
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"finding_type": "owner_everything"},
        {"entity_id": "not-a-uuid"},
        {"tenant_id": "t1"},
        {"entity_kind": "widget"},
    ],
)
def test_malformed_findings_are_skipped(overrides: Dict[str, Any]) -> None:
    db = _Db(owner=_owner())
    assert route_owner_finding(db, _finding(**overrides)).status == OUTCOME_SKIPPED
    assert db.drafts == []


def test_the_safe_wrapper_never_raises() -> None:
    class _Broken(_Db):
        def execute_query(self, sql: str, params: Any = None):
            raise RuntimeError("database unavailable")

    assert route_owner_finding_safely(_Broken(), _finding()).status == OUTCOME_SKIPPED


def test_mcp_endpoint_problems_route_as_trust_drift() -> None:
    db = _Db(owner=_owner(None))
    endpoint = {"id": _PROJECT, "name": "Tools", "slug": "tools"}
    outcome = route_mcp_endpoint_problem(
        db, tenant_id=_TENANT, endpoint=endpoint, summary="Tools drifted", details={"change_count": 3}
    )
    assert outcome.status == OUTCOME_ROUTED
    assert db.drafts[0].type == "owner_trust_drift"
    assert db.drafts[0].payload["link"] == f"/ade/dashboard/mcp/{_PROJECT}"
    assert db.drafts[0].payload["entity_name"] == "Tools"


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


def test_entity_links() -> None:
    assert entity_link("project", _PROJECT, tab="lint") == (
        f"/ade/dashboard/versions?projectId={_PROJECT}&tab=lint"
    )
    assert entity_link("catalog_item", _PROJECT, tab="lint") == f"/ade/dashboard/catalog/{_PROJECT}?tab=lint"
    assert entity_link("connector", _PROJECT, tab="runs") == f"/ade/dashboard/connectors/{_PROJECT}?tab=runs"
    assert entity_link("mcp_endpoint", _PROJECT) == f"/ade/dashboard/mcp/{_PROJECT}"
    assert entity_link("consumer", _PROJECT) is None


def test_a_verification_version_ref_resolves_to_its_project() -> None:
    db = _Db()
    assert project_id_for_version_ref(db, _TENANT, "project/petstore/1.0.0") == _PROJECT
    assert project_id_for_version_ref(db, _TENANT, "project/unknown/1.0.0") is None
    assert project_id_for_version_ref(db, _TENANT, "nonsense") is None


# ---------------------------------------------------------------------------------------------
# catch-all team (CDG-2.5)
# ---------------------------------------------------------------------------------------------


def _catch_all() -> Dict[str, Any]:
    return {"team_id": "55555555-5555-4555-8555-555555555555", "slug": "platform", "name": "Platform",
            "chat_url": None, "members": [_LEAD, _REQUESTER]}


def test_an_unowned_finding_also_reaches_the_catch_all_team() -> None:
    from app.owner_routing import OUTCOME_CATCH_ALL

    db = _Db(owner=None, catch_all=_catch_all())
    outcome = route_owner_finding(db, _finding())
    assert outcome.status == OUTCOME_CATCH_ALL and outcome.team_slug == "platform"
    # The report row is still written: the entity still has no owner.
    statements = db.cursors[0].statements
    assert "INSERT INTO apiome.unowned_findings" in statements[0]
    assert "INSERT INTO apiome.owner_notification_throttle" in statements[1]
    assert not any("DELETE FROM apiome.unowned_findings" in s for s in statements)
    # The requester was already notified, so only the lead is.
    assert [d.user_id for d in db.drafts] == [_LEAD]
    assert db.drafts[0].payload["catch_all"] is True
    assert db.drafts[0].payload["team"]["slug"] == "platform"


def test_the_catch_all_team_is_throttled_too() -> None:
    db = _Db(owner=None, catch_all=_catch_all(), claim=False)
    outcome = route_owner_finding(db, _finding())
    assert outcome.status == OUTCOME_UNOWNED and outcome.team_slug == "platform"
    assert db.drafts == []


def test_an_owned_finding_never_reaches_the_catch_all_team() -> None:
    db = _Db(owner=_owner(None), catch_all=_catch_all())
    route_owner_finding(db, _finding())
    assert {d.payload["team"]["slug"] for d in db.drafts} == {"payments"}
    assert not any("unowned_findings_team_id" in q for q in db.queries)
