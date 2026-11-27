"""Rename, aliases, display name and deletion impact — PFX-8.10 (#7307).

The database is a double. What is asserted is what the store decides: a rename keeps the handle and
records the old and the new name as aliases inside one transaction, refuses a name another live
pacticipant answers to, a reference that misses every handle is tried as an old name, publishing
under an old name never registers a new pacticipant, and the deletion impact reads one pacticipant
only and reports the in-use versions the delete itself would refuse.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.consumer_contract_store import ConsumerActor
from app.pacticipant import (
    CODE_INVALID_NAME,
    CODE_INVALID_SLUG,
    CODE_NOT_FOUND,
    CODE_SLUG_TAKEN,
    PacticipantInput,
    PacticipantPatch,
    PacticipantValidationError,
    pacticipant_record_from_row,
    validate_display_name,
)
from app.pacticipant_deletion_impact import read_deletion_impact
from app.pacticipant_store import create_pacticipant, ensure_pacticipant_tx, get_pacticipant, update_pacticipant

TENANT = "11111111-1111-4111-8111-111111111111"
USER = "77777777-7777-4777-8777-777777777777"
ACTOR = ConsumerActor(user_id=USER, label="dev@example.com")
PID = "22222222-2222-4222-8222-222222222222"

ROW: Dict[str, Any] = {
    "id": PID,
    "tenant_id": TENANT,
    "slug": "orders-ui",
    "name": "Orders UI",
    "display_name": None,
    "aliases": [],
    "main_branch": "main",
}


def _code(call, *args, **kwargs) -> str:
    with pytest.raises(PacticipantValidationError) as caught:
        call(*args, **kwargs)
    return caught.value.code


def _flat(sql: str) -> str:
    return " ".join(sql.split())


class _Cursor:
    """A cursor double: ``fetchone`` answers from a queue, every statement is kept."""

    def __init__(self, answers: List[Optional[Dict[str, Any]]]) -> None:
        self.answers = list(answers)
        self.statements: List[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append((_flat(sql), params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.answers.pop(0) if self.answers else None


def _db_with_tx(cursor: _Cursor, read: Optional[List[Dict[str, Any]]] = None) -> MagicMock:
    """A database whose reads answer ``read`` and whose transaction runs on ``cursor``."""
    db = MagicMock()
    db.execute_query.return_value = [ROW] if read is None else read
    db._guarded_tx.side_effect = lambda work: work(cursor)
    return db


# ---------------------------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------------------------


def test_a_rename_keeps_the_handle_and_records_both_names_in_one_transaction() -> None:
    renamed = {**ROW, "name": "Orders Web", "aliases": ["Orders UI", "Orders Web"]}
    cursor = _Cursor([None, renamed])  # no collision, then the UPDATE's row
    db = _db_with_tx(cursor)

    record = update_pacticipant(db, TENANT, "orders-ui", PacticipantPatch(name="Orders Web"), actor=ACTOR)

    assert record.slug == "orders-ui" and record.name == "Orders Web"
    assert record.aliases == ["Orders UI"]  # the current name is not listed as an old one
    db._guarded_tx.assert_called_once()
    collision, *aliases, update = cursor.statements
    assert "slug = %s OR id IN (SELECT pa.pacticipant_id" in collision[0]
    assert collision[1] == (TENANT, PID, "orders-web", TENANT, "orders-web")
    assert [params[2:4] for _, params in aliases] == [("orders-web", "Orders Web"), ("orders-ui", "Orders UI")]
    assert all("INSERT INTO apiome.pacticipant_alias" in sql and "NOT EXISTS" in sql for sql, _ in aliases)
    assert "SET name = %s" in update[0] and "slug =" not in update[0].split("WHERE")[0]


def test_a_name_another_pacticipant_answers_to_is_refused_and_nothing_is_written() -> None:
    cursor = _Cursor([{"name": "Billing Service"}])
    db = _db_with_tx(cursor)
    with pytest.raises(PacticipantValidationError) as caught:
        update_pacticipant(db, TENANT, "orders-ui", PacticipantPatch(name="billing service"), actor=ACTOR)
    assert caught.value.code == CODE_SLUG_TAKEN
    assert str(caught.value) == "A pacticipant named Billing Service already exists."
    assert len(cursor.statements) == 1  # the check only


def test_a_name_without_a_letter_or_digit_is_refused_before_any_transaction() -> None:
    db = _db_with_tx(_Cursor([]))
    assert _code(update_pacticipant, db, TENANT, "orders-ui", PacticipantPatch(name="!!!"), actor=ACTOR) == (
        CODE_INVALID_SLUG
    )
    db._guarded_tx.assert_not_called()


def test_the_same_name_again_is_not_a_rename() -> None:
    db = _db_with_tx(_Cursor([]))
    update_pacticipant(db, TENANT, "orders-ui", PacticipantPatch(name="Orders UI"), actor=ACTOR)
    db._guarded_tx.assert_not_called()
    assert "UPDATE apiome.pacticipant" in db.execute_query.call_args.args[0]


def test_a_display_name_is_written_and_blank_clears_it() -> None:
    db = _db_with_tx(_Cursor([]))
    update_pacticipant(db, TENANT, "orders-ui", PacticipantPatch(display_name="  Orders (web) "), actor=ACTOR)
    sql, params = db.execute_query.call_args.args
    assert "SET display_name = %s" in _flat(sql) and params[0] == "Orders (web)"
    update_pacticipant(db, TENANT, "orders-ui", PacticipantPatch(display_name="   "), actor=ACTOR)
    assert db.execute_query.call_args.args[1][0] is None


def test_a_display_name_over_255_characters_is_refused() -> None:
    assert validate_display_name(None) is None
    with pytest.raises(PacticipantValidationError) as caught:
        validate_display_name("x" * 256)
    assert caught.value.code == CODE_INVALID_NAME


def test_a_rename_of_a_pacticipant_deleted_meanwhile_is_not_found() -> None:
    cursor = _Cursor([None, None])  # no collision, then the UPDATE matched nothing
    db = _db_with_tx(cursor)
    db._guarded_tx.side_effect = lambda work: work(cursor)
    assert _code(update_pacticipant, db, TENANT, "orders-ui", PacticipantPatch(name="Orders Web"), actor=ACTOR) == (
        CODE_NOT_FOUND
    )


# ---------------------------------------------------------------------------------------------
# Resolution by an old name
# ---------------------------------------------------------------------------------------------


def test_a_reference_that_misses_every_handle_is_tried_as_an_old_name() -> None:
    db = MagicMock()
    db.execute_query.side_effect = [[], [ROW]]
    assert get_pacticipant(db, TENANT, "Orders Web").id == PID
    sql, params = db.execute_query.call_args.args
    assert "pa.tenant_id = %s::uuid AND pa.slug = %s" in _flat(sql) and "deleted_at IS NULL" in sql
    assert params == (TENANT, TENANT, "orders-web")


def test_a_handle_hit_never_reads_the_aliases() -> None:
    db = MagicMock()
    db.execute_query.return_value = [ROW]
    get_pacticipant(db, TENANT, "orders-ui")
    assert db.execute_query.call_count == 1


def test_nothing_under_any_name_is_not_found() -> None:
    db = MagicMock()
    db.execute_query.side_effect = [[], []]
    assert _code(get_pacticipant, db, TENANT, "Nobody") == CODE_NOT_FOUND


def test_publishing_under_an_old_name_registers_nothing_new() -> None:
    cursor = _Cursor([ROW])
    ensure_pacticipant_tx(cursor, TENANT, "Orders Web", actor=ACTOR)
    insert, select = cursor.statements
    assert "WHERE NOT EXISTS" in insert[0] and insert[1][-3:] == (TENANT, TENANT, "orders-web")
    assert "ORDER BY (slug = %s) DESC" in select[0]  # the handle wins over an alias


def test_creating_a_name_a_renamed_pacticipant_answers_to_is_refused() -> None:
    db = MagicMock()
    db.execute_query.return_value = []  # the INSERT's alias guard held: nothing was written
    assert _code(create_pacticipant, db, TENANT, PacticipantInput(name="Orders Web"), actor=ACTOR) == CODE_SLUG_TAKEN


def test_a_record_lists_each_old_name_once() -> None:
    record = pacticipant_record_from_row(
        {**ROW, "name": "Orders Next", "aliases": ["Orders UI", "orders ui", "Orders Next", "Orders Web"]}
    )
    assert record.aliases == ["Orders UI", "Orders Web"]


# ---------------------------------------------------------------------------------------------
# Deletion impact
# ---------------------------------------------------------------------------------------------


def test_the_impact_counts_one_pacticipant_and_names_both_sides() -> None:
    db = MagicMock()
    db.execute_query.side_effect = [
        [{"versions": 214, "pacts": 31, "results": 90}],
        [{"name": "Billing Service", "total": 2}, {"name": "Orders API", "total": 2}],
        [],
        [{"number": "3.3.2"}],
    ]
    impact = read_deletion_impact(db, pacticipant_record_from_row(ROW))
    assert (impact.versions, impact.pacts, impact.verification_results) == (214, 31, 90)
    assert impact.providers == ["Billing Service", "Orders API"] and impact.providers_total == 2
    assert impact.consumers == [] and impact.consumers_total == 0
    assert impact.in_use == ["3.3.2"] and impact.blocked is True
    assert impact.grace_days >= 1
    counts, providers, consumers, in_use = (call.args for call in db.execute_query.call_args_list)
    assert counts[1] == (PID,) * 6
    assert "pp.consumer_id = %s::uuid" in _flat(providers[0]) and "SELECT pp.provider_id" in _flat(providers[0])
    assert "pp.provider_id = %s::uuid" in _flat(consumers[0]) and "SELECT pp.consumer_id" in _flat(consumers[0])
    assert "currently_deployed" in in_use[0] and in_use[1] == (PID,)


def test_an_unused_pacticipant_is_not_blocked() -> None:
    db = MagicMock()
    db.execute_query.side_effect = [[{"versions": 0, "pacts": 0, "results": 0}], [], [], []]
    impact = read_deletion_impact(db, pacticipant_record_from_row(ROW))
    assert impact.blocked is False and impact.in_use == [] and impact.versions == 0
