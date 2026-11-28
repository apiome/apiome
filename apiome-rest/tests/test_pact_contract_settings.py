"""Contracts commit-status and agent switches — PFX-8.15 (#7312).

Without a database (``test_pact_contract_settings_db`` runs the SQL):

* the defaults are the mockup's: statuses on both commits, bi-directional off; agents read and draft,
  never publish or record until allowed; an unknown field is refused, never dropped;
* saving upserts only its group for the caller's tenant and audits in the same transaction;
* the routes: reading needs ``pacts:view``, saving ``pacts:delete``; ``can_edit`` follows
  ``pacts:delete``; the tenant is the authenticated one, never the URL's;
* the commit-status switches: a switched-off side is recorded ``suppressed`` with
  ``pact-status-switched-off`` and the reason, never silently dropped; a bi-directional verdict obeys
  its own switch first;
* a bi-directional verdict fires its webhooks and posts its statuses when the switch is on — and
  neither when it is off; a failure never reaches the publish;
* the bi-directional store calls the hook for each newly stored comparison only.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import bidirectional_events, pact_commit_status_store
from app.auth import validate_authentication
from app.consumer_contract_store import ConsumerActor
from app.main import app
from app.pact_commit_status import CODE_SWITCHED_OFF, SIDE_CONSUMER, SIDE_PROVIDER
from app.pact_contract_settings import (
    AgentSettings,
    CommitStatusSettings,
    ContractSettings,
    read_settings,
    save_agents,
    save_commit_statuses,
    settings_from_row,
)

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = ConsumerActor(user_id="33333333-3333-4333-8333-333333333333", label="ada@example.com")
_AUTH = {"tenant_id": TENANT, "user_id": "u-1", "auth_method": "jwt", "user_email": "ada@example.com"}
_ROUTES = "app.pact_contract_settings_routes"


def _row(**overrides: Any) -> Dict[str, Any]:
    row = {
        "status_consumer_commit": True,
        "status_provider_commit": True,
        "status_bidirectional": False,
        "agent_read": True,
        "agent_draft": True,
        "agent_publish": False,
        "agent_record": False,
        "updated_by_label": "ada@example.com",
        "updated_at": "2026-11-28T10:00:00+00:00",
    }
    row.update(overrides)
    return row


class _Cursor:
    """Records statements; ``fetchone`` / ``fetchall`` answer from a list of rows."""

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        self.rows = rows or []
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self.rows)


def _db(cursor: _Cursor) -> MagicMock:
    database = MagicMock()
    database._guarded_tx.side_effect = lambda work: work(cursor)
    return database


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------


def test_the_defaults_are_the_mockups() -> None:
    settings = settings_from_row(None)
    assert settings.configured is False
    assert settings.commit_statuses.model_dump() == {
        "consumer_commit": True,
        "provider_commit": True,
        "bidirectional": False,
    }
    assert settings.agents.model_dump() == {"read": True, "draft": True, "publish": False, "record": False}


def test_an_unknown_switch_is_refused_not_dropped() -> None:
    with pytest.raises(ValidationError, match="extra"):
        CommitStatusSettings(check_runs=True)
    with pytest.raises(ValidationError, match="extra"):
        AgentSettings(delete=True)


def test_a_stored_row_reads_back() -> None:
    settings = settings_from_row(_row(status_bidirectional=True, agent_record=True), can_edit=True)
    assert settings.configured and settings.can_edit
    assert settings.commit_statuses.bidirectional is True and settings.agents.record is True
    assert settings.updated_by == "ada@example.com"


def test_reading_scopes_by_tenant_and_a_bad_tenant_reads_the_defaults() -> None:
    fetch = MagicMock(return_value=[_row(agent_read=False)])
    assert read_settings(fetch, TENANT).agents.read is False
    assert fetch.call_args.args[1] == (TENANT,)
    fetch.reset_mock()
    assert read_settings(fetch, "not-a-tenant").configured is False
    fetch.assert_not_called()


def test_saving_upserts_only_its_group_and_audits_in_the_transaction() -> None:
    cursor = _Cursor([_row(status_bidirectional=True)])
    database = _db(cursor)
    saved = save_commit_statuses(database, TENANT, CommitStatusSettings(bidirectional=True), actor=ACTOR)
    ((query, params),) = cursor.statements
    assert "status_bidirectional = EXCLUDED.status_bidirectional" in query
    assert "agent_" not in query.split("RETURNING")[0]
    assert params[0] == TENANT and params[1:4] == (True, True, True) and params[4] == ACTOR.user_id
    audit = database._append_access_audit.call_args.kwargs
    assert audit["action"] == "pacts.settings.commit_statuses" and audit["tenant_id"] == TENANT
    assert saved.commit_statuses.bidirectional is True and saved.can_edit is True

    cursor = _Cursor([_row(agent_record=True)])
    database = _db(cursor)
    save_agents(database, TENANT, AgentSettings(record=True), actor=ACTOR)
    query = cursor.statements[0][0]
    assert "agent_record = EXCLUDED.agent_record" in query and "status_" not in query.split("RETURNING")[0]
    assert database._append_access_audit.call_args.kwargs["action"] == "pacts.settings.agents"


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def routes() -> Iterator[Dict[str, MagicMock]]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    stored = ContractSettings(
        commit_statuses=CommitStatusSettings(), agents=AgentSettings(), configured=True, can_edit=True
    )
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u-1") as enforce,
        patch(f"{_ROUTES}.has_permission", return_value=True) as has,
        patch(f"{_ROUTES}.read_settings", return_value=stored) as read,
        patch(f"{_ROUTES}.save_commit_statuses", return_value=stored) as statuses,
        patch(f"{_ROUTES}.save_agents", return_value=stored) as agents,
    ):
        yield {"enforce": enforce, "has": has, "read": read, "statuses": statuses, "agents": agents}
    app.dependency_overrides.clear()


_CALLS = [
    ("get", "", None, "view", "read"),
    ("put", "/commit-statuses", {"consumer_commit": False}, "delete", "statuses"),
    ("put", "/agents", {"record": True}, "delete", "agents"),
]


@pytest.mark.parametrize(("method", "path", "body", "action", "store"), _CALLS)
def test_each_route_is_gated_and_uses_the_callers_tenant(
    routes: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, store: str
) -> None:
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(f"/v1/tenants/someone-else/pact-contract-settings{path}", **kwargs)
    assert response.status_code == 200, response.text
    assert routes["enforce"].call_args.args[2:4] == ("pacts", action)
    assert routes[store].call_args.args[1] == TENANT


@pytest.mark.parametrize(("method", "path", "body", "action", "store"), _CALLS)
def test_a_denied_caller_is_refused_before_the_store(
    routes: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, store: str
) -> None:
    routes["enforce"].side_effect = HTTPException(status_code=403, detail="no")
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(f"/v1/tenants/t/pact-contract-settings{path}", **kwargs).status_code == 403
    assert routes[store].call_count == 0


def test_can_edit_follows_pacts_delete(routes: Dict[str, MagicMock]) -> None:
    routes["has"].return_value = False
    client.get("/v1/tenants/t/pact-contract-settings")
    assert routes["read"].call_args.kwargs["can_edit"] is False
    assert routes["has"].call_args.args[2:4] == ("pacts", "delete")


@pytest.mark.parametrize(
    ("path", "body"),
    [("/commit-statuses", {"check_runs": True}), ("/agents", {"delete": True}), ("/agents", {"record": "yes"})],
)
def test_unsupported_input_is_refused_with_a_reason(routes: Dict[str, MagicMock], path: str, body: Any) -> None:
    response = client.put(f"/v1/tenants/t/pact-contract-settings{path}", json=body)
    assert response.status_code == 422 and response.json()["detail"]
    assert routes["statuses"].call_count == 0 and routes["agents"].call_count == 0


# ---------------------------------------------------------------------------------------------
# Commit-status switches
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("switches", "side", "bidirectional", "allowed"),
    [
        (CommitStatusSettings(), SIDE_CONSUMER, False, True),
        (CommitStatusSettings(consumer_commit=False), SIDE_CONSUMER, False, False),
        (CommitStatusSettings(consumer_commit=False), SIDE_PROVIDER, False, True),
        (CommitStatusSettings(provider_commit=False), SIDE_PROVIDER, False, False),
        (CommitStatusSettings(), SIDE_PROVIDER, True, False),
        (CommitStatusSettings(bidirectional=True), SIDE_PROVIDER, True, True),
        (CommitStatusSettings(bidirectional=True, provider_commit=False), SIDE_PROVIDER, True, False),
    ],
)
def test_switched_off(switches: CommitStatusSettings, side: str, bidirectional: bool, allowed: bool) -> None:
    reason = pact_commit_status_store.switched_off(switches, side, bidirectional=bidirectional)
    assert (reason is None) is allowed
    if reason:
        assert "Contracts → Settings → CI and commit statuses" in reason and "recorded only" in reason


def test_a_switched_off_status_is_recorded_suppressed_with_the_reason() -> None:
    intent = MagicMock(
        tenant_id=TENANT, side=SIDE_CONSUMER, repository_url="https://github.com/a/b", version_number="x"
    )
    cursor = _Cursor([_row(status_consumer_commit=False)])
    database = _db(cursor)
    with (
        patch.object(pact_commit_status_store, "_upsert", side_effect=lambda _c, _i, resolution: resolution) as upsert,
        patch.object(pact_commit_status_store, "resolve_target") as resolve,
    ):
        (resolution,) = pact_commit_status_store._record_all(database, lambda _cursor: [intent])
    assert resolution.outcome == "suppressed" and resolution.reason_code == CODE_SWITCHED_OFF
    assert "consumer's commit are switched off" in resolution.message
    resolve.assert_not_called()
    assert upsert.call_count == 1
    assert cursor.statements[0][1] == (TENANT,)


def test_an_allowed_status_is_resolved_as_before() -> None:
    intent = MagicMock(
        tenant_id=TENANT, side=SIDE_PROVIDER, repository_url="https://github.com/a/b", version_number="x"
    )
    database = _db(_Cursor([]))  # no row: the defaults, both commits on
    with (
        patch.object(pact_commit_status_store, "_upsert", side_effect=lambda _c, _i, resolution: resolution),
        patch.object(pact_commit_status_store, "resolve_target", return_value="resolved") as resolve,
    ):
        assert pact_commit_status_store._record_all(database, lambda _cursor: [intent]) == ["resolved"]
    resolve.assert_called_once()


# ---------------------------------------------------------------------------------------------
# Bi-directional verdicts
# ---------------------------------------------------------------------------------------------


def _with_switch(on: bool) -> ContractSettings:
    return settings_from_row(_row(status_bidirectional=on))


def test_a_bidirectional_verdict_fires_its_webhook_and_sets_its_status_when_on() -> None:
    database = MagicMock()
    database.execute_query.return_value = [{"slug": "acme"}]
    record = MagicMock(kind="bidirectional")
    with (
        patch.object(bidirectional_events, "read_settings", return_value=_with_switch(True)),
        patch.object(bidirectional_events, "get_verification_result", return_value=record) as read,
        patch.object(bidirectional_events, "fire_verification_events") as fire,
        patch.object(bidirectional_events, "post_verification_statuses") as post,
    ):
        assert bidirectional_events.publish_bidirectional_verdict(
            database, TENANT, provider_ref="p-id", consumer_ref="c-id", sha="abc", number=3
        )
    assert read.call_args.args[1:] == (TENANT, "p-id", "c-id", "abc", 3)
    assert fire.call_args.args[1:] == (TENANT, "/v1/tenants/acme/pact-broker", record)
    assert post.call_args.args[1:] == (TENANT, "/v1/tenants/acme/pact-broker", record)


def test_the_client_base_url_is_used_when_given() -> None:
    with (
        patch.object(bidirectional_events, "read_settings", return_value=_with_switch(True)),
        patch.object(bidirectional_events, "get_verification_result", return_value=MagicMock()),
        patch.object(bidirectional_events, "fire_verification_events") as fire,
        patch.object(bidirectional_events, "post_verification_statuses"),
    ):
        bidirectional_events.publish_bidirectional_verdict(
            MagicMock(), TENANT, provider_ref="p", consumer_ref="c", sha="s", number=1, base="https://b/pact-broker"
        )
    assert fire.call_args.args[2] == "https://b/pact-broker"


def test_a_bidirectional_verdict_fires_nothing_when_off() -> None:
    with (
        patch.object(bidirectional_events, "read_settings", return_value=_with_switch(False)),
        patch.object(bidirectional_events, "get_verification_result") as read,
        patch.object(bidirectional_events, "fire_verification_events") as fire,
        patch.object(bidirectional_events, "post_verification_statuses") as post,
    ):
        assert not bidirectional_events.publish_bidirectional_verdict(
            MagicMock(), TENANT, provider_ref="p", consumer_ref="c", sha="s", number=1
        )
    read.assert_not_called()
    fire.assert_not_called()
    post.assert_not_called()


def test_a_failing_hook_never_reaches_the_publish() -> None:
    with (
        patch.object(bidirectional_events, "read_settings", return_value=_with_switch(True)),
        patch.object(bidirectional_events, "get_verification_result", side_effect=RuntimeError("gone")),
    ):
        assert not bidirectional_events.publish_bidirectional_verdict(
            MagicMock(), TENANT, provider_ref="p", consumer_ref="c", sha="s", number=1
        )


def test_the_store_calls_the_hook_only_for_a_newly_stored_comparison() -> None:
    from app import bidirectional_store

    database = MagicMock()
    database.execute_query.side_effect = [[{"id": "pv-1"}], []]
    database._guarded_tx.return_value = 4
    provider = MagicMock(id="p-id", slug="ledger-api")
    provider.name = "Ledger API"
    pact = bidirectional_store._Pact("c-id", "Billing", "1.0.0", "abc")
    target = MagicMock(version_number="5.1.0", version_id="v-1", contract_id="k-1")
    stored = MagicMock(verdict="pass", success=True)
    with (
        patch.object(bidirectional_store, "compare_with_target", return_value=stored),
        patch.object(bidirectional_store, "publish_bidirectional_verdict") as hook,
    ):
        entry = bidirectional_store._compare_pair(
            database, MagicMock(), TENANT, provider, pact, target, ACTOR, "https://b/pact-broker"
        )
    assert entry.status == "compared"
    assert hook.call_args.kwargs == {
        "provider_ref": "p-id",
        "consumer_ref": "c-id",
        "sha": "abc",
        "number": 4,
        "base": "https://b/pact-broker",
    }

    database.execute_query.side_effect = [[{"id": "pv-1"}], [{"number": 2, "success": True, "verdict": "pass"}]]
    with patch.object(bidirectional_store, "publish_bidirectional_verdict") as hook:
        entry = bidirectional_store._compare_pair(database, MagicMock(), TENANT, provider, pact, target, ACTOR)
    assert entry.status == "already-compared"
    hook.assert_not_called()
