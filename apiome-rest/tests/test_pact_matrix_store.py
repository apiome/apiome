"""The matrix store without a database — PFX-1.6 (#6919).

Named statements (prepared once per connection, prepared again when the server forgot them, run
plainly on a connection that cannot be tracked) and the helpers that need no SQL.
``test_pact_matrix_db`` runs the statements themselves.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import psycopg2.errors
import pytest

from app.pact_matrix import MatrixOptions, UnresolvedSelector
from app.pact_matrix_store import (
    MAX_SELECTORS,
    _array,
    _execute_named,
    _inferred_selector,
    query_matrix,
    read_version_details,
)
from app.pact_publication import PactPublicationError


class _Connection:
    """A stand-in connection: hashable and weak-referenceable, like psycopg2's."""


class _Db:
    """Records what is prepared and executed; can forget a prepared statement once."""

    def __init__(self, connection: Any = None, forget: int = 0) -> None:
        self.connection = connection if connection is not None else _Connection()
        self.writes: List[str] = []
        self.queries: List[Tuple[str, Any]] = []
        self.forget = forget

    def connect(self) -> Any:
        return self.connection

    def _execute_write(self, query: str, params: Any = None) -> int:
        self.writes.append(query)
        return 0

    def execute_query(self, query: str, params: Any = None) -> List[Any]:
        self.queries.append((query, params))
        if query.startswith("EXECUTE") and self.forget:
            self.forget -= 1
            raise psycopg2.errors.InvalidSqlStatementName("prepared statement does not exist")
        return [{"id": "v-1"}]


def test_a_statement_is_prepared_once_per_connection() -> None:
    db = _Db()
    sql = "SELECT $1::uuid[] AS ids, $2::bigint AS n"
    assert _execute_named(db, "pfx_test", sql, ("{}", 5)) == [{"id": "v-1"}]
    assert _execute_named(db, "pfx_test", sql, ("{}", 6)) == [{"id": "v-1"}]
    assert db.writes == [f"PREPARE pfx_test AS {sql}"]
    assert db.queries == [("EXECUTE pfx_test (%s, %s)", ("{}", 5)), ("EXECUTE pfx_test (%s, %s)", ("{}", 6))]
    # Another connection prepares its own.
    other = _Db()
    _execute_named(other, "pfx_test", sql, ("{}", 5))
    assert len(other.writes) == 1


def test_a_forgotten_statement_is_prepared_again_once() -> None:
    db = _Db(forget=1)
    assert _execute_named(db, "pfx_test", "SELECT $1::int", (1,)) == [{"id": "v-1"}]
    assert len(db.writes) == 2 and len(db.queries) == 2
    stubborn = _Db(forget=5)
    with pytest.raises(psycopg2.errors.InvalidSqlStatementName):
        _execute_named(stubborn, "pfx_test", "SELECT $1::int", (1,))
    assert len(stubborn.queries) == 2


def test_an_untrackable_connection_runs_the_statement_plainly() -> None:
    db = _Db(connection=("not", "weak-referenceable"))
    _execute_named(db, "pfx_test", "SELECT $1::uuid[] WHERE $2::int > 0 AND $1::uuid[] IS NOT NULL", ("{}", 2))
    assert db.writes == []
    assert db.queries == [
        ("SELECT %(p1)s::uuid[] WHERE %(p2)s::int > 0 AND %(p1)s::uuid[] IS NOT NULL", {"p1": "{}", "p2": 2})
    ]


def test_arrays_are_literals_without_repeats_or_gaps() -> None:
    assert _array([]) == "{}"
    assert _array(["a", None, "b", "a"]) == "{a,b}"


def test_version_details_of_nothing_reads_nothing() -> None:
    db = _Db()
    assert read_version_details(db, [None, None]) == {}
    assert db.queries == []
    assert read_version_details(db, ["v-1", None, "v-1"]) == {"v-1": {"id": "v-1"}}
    assert db.queries[-1][1] == ("{v-1}",)


def test_the_other_pacticipants_take_the_destination() -> None:
    assert _inferred_selector("Bar", MatrixOptions(environment_name="production")) == UnresolvedSelector(
        pacticipant_name="Bar", environment_name="production"
    )
    assert _inferred_selector("Bar", MatrixOptions(latest=True, tag="prod")) == UnresolvedSelector(
        pacticipant_name="Bar", latest=True, tag="prod"
    )
    assert _inferred_selector("Bar", MatrixOptions(latest=True, main_branch=True)) == UnresolvedSelector(
        pacticipant_name="Bar", latest=True, main_branch=True
    )


def test_a_query_with_too_many_selectors_is_refused_before_any_lookup() -> None:
    db = _Db()
    selectors = [UnresolvedSelector(pacticipant_name=f"App {n}") for n in range(MAX_SELECTORS)]
    options = MatrixOptions(ignore_selectors=(UnresolvedSelector(pacticipant_name="One more"),))
    with pytest.raises(PactPublicationError) as refused:
        query_matrix(db, "11111111-1111-4111-8111-111111111111", selectors, options)
    assert (refused.value.code, str(refused.value)) == (
        "pact-matrix-invalid",
        "A query may carry at most 100 selectors.",
    )
    assert db.queries == []
