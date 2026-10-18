"""Store rules for teams — CDG-2.1 (#5960).

:mod:`app.team_store` runs each write in one transaction through ``db._guarded_tx``. These tests
replace that transaction with a scripted cursor — every ``fetchone``/``fetchall`` answers from a
queue, every statement is recorded — so the rules are pinned without a database:

* a delete of a team that owns entities is refused with the count, and writes nothing;
* ``reassign_to`` moves the ownership rows and deletes in the same transaction;
* a membership write naming a non-member is refused before any membership row changes;
* every write appends its ``team.*`` audit row on the transaction's own cursor;
* a slug collision from the unique index becomes ``team-slug-taken``.

The SQL itself (and V284's triggers) was exercised against Postgres when the ticket was built;
``test_teams_migration`` pins the schema.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import psycopg2
import pytest

from app import team_store
from app.consumer_contract_store import ConsumerActor
from app.teams import (
    CODE_MEMBER_NOT_IN_TENANT,
    CODE_NOT_FOUND,
    CODE_OWNS_ENTITIES,
    CODE_REASSIGN_INVALID,
    CODE_SLUG_TAKEN,
    TeamInput,
    TeamMemberInput,
    TeamPatch,
    TeamValidationError,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_TEAM_ID = "22222222-2222-4222-8222-222222222222"
_OTHER_ID = "33333333-3333-4333-8333-333333333333"
_USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_ACTOR = ConsumerActor(user_id=_USER_A, label="lead@example.com")


def _team_row(**overrides: Any) -> Dict[str, Any]:
    """A ``teams`` row as ``_TEAM_COLUMNS`` selects it."""
    row: Dict[str, Any] = {
        "id": _TEAM_ID,
        "slug": "payments",
        "name": "Payments",
        "description": None,
        "contact_email": None,
        "chat_url": None,
        "oncall_url": None,
        "docs_url": None,
        "created_by": _USER_A,
        "created_at": None,
        "updated_at": None,
        "member_count": 0,
    }
    row.update(overrides)
    return row


class _ScriptedCursor:
    """A cursor whose reads answer from a queue and whose statements are recorded."""

    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.statements: List[str] = []
        self.rowcount = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append(" ".join(sql.split()))
        if "UPDATE apiome.entity_owners" in sql:
            self.rowcount = 2

    def _next(self) -> Any:
        assert self.answers, f"no scripted answer left after: {self.statements[-1]}"
        return self.answers.pop(0)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._next()

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._next()

    def ran(self, fragment: str) -> bool:
        return any(fragment in statement for statement in self.statements)


@pytest.fixture
def audits():
    """Record every in-transaction audit row and the cursor it was written on."""
    recorded: List[Dict[str, Any]] = []

    def _append(cursor: Any, **kwargs: Any) -> None:
        recorded.append({"cursor": cursor, **kwargs})

    with patch.object(team_store.db, "_append_access_audit", side_effect=_append):
        yield recorded


def _run_with(cursor: _ScriptedCursor):
    """Patch the store's transaction to hand ``work`` the scripted cursor."""
    return patch.object(team_store.db, "_guarded_tx", side_effect=lambda work: work(cursor))


# ---------------------------------------------------------------------------------------------
# create / update
# ---------------------------------------------------------------------------------------------


def test_create_inserts_audits_on_the_same_cursor_and_returns_the_team(audits) -> None:
    cursor = _ScriptedCursor([{"id": _TEAM_ID}, _team_row(chat_url="https://chat.example/pay")])
    with _run_with(cursor):
        team = team_store.create_team(
            _TENANT, TeamInput(name="Payments", chat_url="https://chat.example/pay"), actor=_ACTOR
        )
    assert team.slug == "payments" and team.members == []
    assert cursor.ran("INSERT INTO apiome.teams")
    assert [a["action"] for a in audits] == ["team.create"]
    assert audits[0]["cursor"] is cursor
    assert audits[0]["target"] == "team:payments"
    assert audits[0]["detail"]["chat_url"] == "https://chat.example/pay"


def test_a_slug_collision_is_team_slug_taken() -> None:
    def _collide(work: Any) -> Any:
        raise psycopg2.errors.UniqueViolation()

    with patch.object(team_store.db, "_guarded_tx", side_effect=_collide):
        with pytest.raises(TeamValidationError) as caught:
            team_store.create_team(_TENANT, TeamInput(name="Payments"), actor=_ACTOR)
    assert caught.value.code == CODE_SLUG_TAKEN


def test_update_writes_and_audits_only_the_fields_that_changed(audits) -> None:
    before = _team_row(description="Old", chat_url="https://chat.example/a")
    after = _team_row(description="New", chat_url="https://chat.example/a")
    cursor = _ScriptedCursor([before, after, []])
    with _run_with(cursor):
        team = team_store.update_team(
            _TENANT,
            "payments",
            TeamPatch(description="New", chat_url="https://chat.example/a"),
            actor=_ACTOR,
        )
    assert team.description == "New"
    update = next(s for s in cursor.statements if s.startswith("UPDATE apiome.teams SET"))
    assert "description = %s" in update and "chat_url" not in update
    assert audits[0]["action"] == "team.update"
    assert audits[0]["detail"]["changes"] == {"description": {"from": "Old", "to": "New"}}


def test_an_update_that_changes_nothing_writes_and_audits_nothing(audits) -> None:
    cursor = _ScriptedCursor([_team_row(name="Payments"), []])
    with _run_with(cursor):
        team_store.update_team(_TENANT, "payments", TeamPatch(name="Payments"), actor=_ACTOR)
    assert not cursor.ran("UPDATE apiome.teams")
    assert audits == []


def test_updating_an_unknown_team_is_not_found() -> None:
    cursor = _ScriptedCursor([None])
    with _run_with(cursor), pytest.raises(TeamValidationError) as caught:
        team_store.update_team(_TENANT, "ghost", TeamPatch(name="X"), actor=_ACTOR)
    assert caught.value.code == CODE_NOT_FOUND


# ---------------------------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------------------------


def test_deleting_a_team_that_owns_nothing_soft_deletes_and_audits(audits) -> None:
    cursor = _ScriptedCursor([_team_row(), {"present": True}, {"n": 0}])
    with _run_with(cursor):
        result = team_store.delete_team(_TENANT, "payments", actor=_ACTOR)
    assert result == {"slug": "payments", "owned_count": 0, "reassigned_to": None}
    assert cursor.ran("SET deleted_at = CURRENT_TIMESTAMP")
    assert not cursor.ran("DELETE FROM apiome.teams")
    assert audits[0]["action"] == "team.delete"


def test_without_the_ownership_table_a_team_owns_nothing(audits) -> None:
    """Before CDG-2.2's migration runs, ``entity_owners`` does not exist."""
    cursor = _ScriptedCursor([_team_row(), {"present": False}])
    with _run_with(cursor):
        result = team_store.delete_team(_TENANT, "payments", actor=_ACTOR)
    assert result["owned_count"] == 0
    assert not cursor.ran("FROM apiome.entity_owners")


def test_deleting_an_owning_team_without_reassign_is_refused_with_the_count(audits) -> None:
    cursor = _ScriptedCursor([_team_row(), {"present": True}, {"n": 3}])
    with _run_with(cursor), pytest.raises(TeamValidationError) as caught:
        team_store.delete_team(_TENANT, "payments", actor=_ACTOR)
    assert caught.value.code == CODE_OWNS_ENTITIES
    assert caught.value.owned_count == 3
    assert not cursor.ran("SET deleted_at")
    assert audits == []


def test_reassign_moves_ownership_and_deletes_in_one_transaction(audits) -> None:
    target = _team_row(id=_OTHER_ID, slug="platform", name="Platform")
    cursor = _ScriptedCursor([_team_row(), target, {"present": True}, {"n": 2}])
    with _run_with(cursor):
        result = team_store.delete_team(
            _TENANT, "payments", actor=_ACTOR, reassign_to="Platform"
        )
    assert result == {"slug": "payments", "owned_count": 2, "reassigned_to": "platform"}
    moves = [s for s in cursor.statements if s.startswith("UPDATE apiome.entity_owners")]
    assert len(moves) == 1
    assert cursor.statements.index(moves[0]) < next(
        i for i, s in enumerate(cursor.statements) if "SET deleted_at" in s
    )
    assert audits[0]["detail"]["reassigned_to"] == "platform"


def test_reassigning_to_the_same_team_is_refused() -> None:
    cursor = _ScriptedCursor([_team_row()])
    with _run_with(cursor), pytest.raises(TeamValidationError) as caught:
        team_store.delete_team(_TENANT, "payments", actor=_ACTOR, reassign_to="payments")
    assert caught.value.code == CODE_REASSIGN_INVALID


def test_reassigning_to_an_unknown_team_is_refused() -> None:
    cursor = _ScriptedCursor([_team_row(), None])
    with _run_with(cursor), pytest.raises(TeamValidationError) as caught:
        team_store.delete_team(_TENANT, "payments", actor=_ACTOR, reassign_to="ghost")
    assert caught.value.code == CODE_REASSIGN_INVALID


# ---------------------------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------------------------


def test_a_member_outside_the_tenant_is_refused_before_anything_changes(audits) -> None:
    cursor = _ScriptedCursor([_team_row(), [{"user_id": _USER_A}]])
    with _run_with(cursor), pytest.raises(TeamValidationError) as caught:
        team_store.replace_team_members(
            _TENANT,
            "payments",
            [TeamMemberInput(user_id=_USER_A), TeamMemberInput(user_id=_USER_B)],
            actor=_ACTOR,
        )
    assert caught.value.code == CODE_MEMBER_NOT_IN_TENANT
    assert _USER_B in str(caught.value) and _USER_A not in str(caught.value)
    assert not cursor.ran("team_members WHERE team_id = %s::uuid AND NOT")
    assert not cursor.ran("INSERT INTO apiome.team_members")
    assert audits == []


def test_replacing_members_upserts_removes_the_rest_and_audits_the_diff(audits) -> None:
    members_after = [
        {"user_id": _USER_B, "role": "lead", "email": "b@example.com", "name": "B", "added_at": None}
    ]
    cursor = _ScriptedCursor(
        [
            _team_row(member_count=1),
            [{"user_id": _USER_B}],
            [{"user_id": _USER_A, "role": "lead"}],
            members_after,
        ]
    )
    with _run_with(cursor):
        team = team_store.replace_team_members(
            _TENANT, "payments", [TeamMemberInput(user_id=_USER_B, role="lead")], actor=_ACTOR
        )
    assert [(m.user_id, m.role) for m in team.members or []] == [(_USER_B, "lead")]
    assert team.member_count == 1
    assert cursor.ran("ON CONFLICT (team_id, user_id) DO UPDATE SET role = EXCLUDED.role")
    detail = audits[0]["detail"]
    assert audits[0]["action"] == "team.members.replace"
    assert detail["added"] == [_USER_B] and detail["removed"] == [_USER_A]
    assert detail["member_count"] == 1


def test_an_empty_membership_empties_the_team(audits) -> None:
    cursor = _ScriptedCursor([_team_row(), [{"user_id": _USER_A, "role": "member"}], []])
    with _run_with(cursor):
        team = team_store.replace_team_members(_TENANT, "payments", [], actor=_ACTOR)
    assert team.members == [] and team.member_count == 0
    assert not cursor.ran("FROM apiome.tenant_users")
    assert not cursor.ran("INSERT INTO apiome.team_members")
    assert audits[0]["detail"]["removed"] == [_USER_A]


# ---------------------------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------------------------


def test_reads_short_circuit_on_a_non_uuid_tenant() -> None:
    assert team_store.list_teams("t1") == []
    with pytest.raises(TeamValidationError) as caught:
        team_store.get_team("t1", "payments")
    assert caught.value.code == CODE_NOT_FOUND
