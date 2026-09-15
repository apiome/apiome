"""Renaming or moving an element keeps its comment threads anchored — COL-1.4 (#4516).

A thread anchors to an element by the element's primary key (V259). That only survives a rename or
a move if every rename and move is an **in-place UPDATE keyed by that id** — never a delete and a
re-insert, which would mint a new id, and never a write to ``deleted_at``, which is what V260's
orphan triggers watch. This module pins exactly that for each write the Studio makes when an element
is renamed or moved:

* a class's name, and its canvas position (``canvas_metadata``);
* a class property's name;
* a path's pathname;
* an operation's method, and its summary / operationId labels.

Each accessor runs against a recording connection, so the SQL it would send is asserted without a
database. The trigger side — that no orphan trigger watches a name column — is pinned by
``tests/test_comment_anchor_resilience_migration.py``; the store side — that a thread is read back by
its anchor id alone — by the COL-1.4 cases in ``tests/test_comment_routes.py``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

import pytest

from app.database import Database

TENANT = "7d1c6a2e-3b4f-4c5d-8e9f-0a1b2c3d0001"
CLASS_ID = "7d1c6a2e-3b4f-4c5d-8e9f-0a1b2c3d0020"
PROPERTY_ID = "7d1c6a2e-3b4f-4c5d-8e9f-0a1b2c3d0021"
PATH_ID = "7d1c6a2e-3b4f-4c5d-8e9f-0a1b2c3d0022"
OPERATION_ID = "7d1c6a2e-3b4f-4c5d-8e9f-0a1b2c3d0023"


class _RecordingCursor:
    """A cursor that records each statement and answers with one row."""

    def __init__(self, statements: List[Tuple[str, Sequence[Any]]]) -> None:
        """Record into ``statements``."""
        self._statements = statements
        self.rowcount = 1

    def __enter__(self) -> "_RecordingCursor":
        """Enter the ``with`` block."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the ``with`` block."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        """Record one statement."""
        self._statements.append((sql, tuple(params)))

    def fetchone(self) -> Dict[str, Any]:
        """Answer with a row carrying the updated element's id."""
        return {"id": "row"}


class _RecordingConnection:
    """A connection whose cursors record into one list."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.statements: List[Tuple[str, Sequence[Any]]] = []
        self.commits = 0

    def cursor(self) -> _RecordingCursor:
        """A recording cursor."""
        return _RecordingCursor(self.statements)

    def commit(self) -> None:
        """Count a commit."""
        self.commits += 1

    def rollback(self) -> None:
        """Nothing to undo."""


@pytest.fixture
def recorded(monkeypatch) -> Tuple[Database, _RecordingConnection]:
    """A ``Database`` that owns every element of the tenant and records what it writes."""
    database = Database.__new__(Database)
    connection = _RecordingConnection()
    monkeypatch.setattr(database, "connect", lambda: connection)
    monkeypatch.setattr(database, "get_class_by_id", lambda class_id, tenant_id: {"id": class_id})
    monkeypatch.setattr(database, "get_path_by_id", lambda path_id, tenant_id: {"id": path_id})
    monkeypatch.setattr(database, "get_operation_by_id", lambda operation_id, tenant_id: {"id": operation_id})
    monkeypatch.setattr(
        database,
        "execute_query",
        lambda query, params=None: [{"id": PROPERTY_ID, "class_id": CLASS_ID, "primitive_id": None}],
    )
    return database, connection


def _only_write(connection: _RecordingConnection) -> Tuple[str, Sequence[Any]]:
    """The single statement a rename sent, whitespace collapsed.

    Args:
        connection: The recording connection.

    Returns:
        ``(sql, params)``.
    """
    assert len(connection.statements) == 1, connection.statements
    sql, params = connection.statements[0]
    return " ".join(sql.split()), params


def _assert_in_place_update(sql: str, table: str, key_column: str) -> None:
    """Assert a statement updates one table in place, keyed by an id, without a soft delete.

    Args:
        sql: The statement, whitespace collapsed.
        table: The ``apiome.<table>`` expected to be updated.
        key_column: The column the WHERE clause must key on.
    """
    assert sql.startswith(f"UPDATE apiome.{table} SET "), sql
    assert re.search(rf"WHERE {key_column} = %s", sql), sql
    set_clause = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
    assert "deleted_at" not in set_clause, sql
    assert not re.search(r"\b(DELETE|INSERT)\b", sql), sql


@pytest.mark.parametrize(
    "updates",
    [
        pytest.param({"name": "Client"}, id="rename"),
        pytest.param({"canvas_metadata": {"position": {"x": 480, "y": 120}}}, id="move-on-canvas"),
    ],
)
def test_renaming_or_moving_a_class_updates_its_row_by_id(recorded, updates: Dict[str, Any]):
    database, connection = recorded
    database.update_class(CLASS_ID, TENANT, updates)
    sql, params = _only_write(connection)
    _assert_in_place_update(sql, "classes", "id")
    assert params[-1] == CLASS_ID


def test_renaming_a_class_property_updates_its_row_by_id(recorded):
    database, connection = recorded
    database.update_class_property(PROPERTY_ID, CLASS_ID, TENANT, {"name": "emailAddress"})
    sql, params = _only_write(connection)
    _assert_in_place_update(sql, "class_properties", "id")
    assert params == ("emailAddress", PROPERTY_ID)


def test_renaming_a_path_updates_its_row_by_id(recorded):
    database, connection = recorded
    database.update_path(PATH_ID, TENANT, {"pathname": "/clients/{id}"})
    sql, params = _only_write(connection)
    _assert_in_place_update(sql, "version_path", "id")
    assert params == ("/clients/{id}", PATH_ID)


def test_changing_an_operation_method_updates_its_row_by_id(recorded):
    database, connection = recorded
    database.update_operation(OPERATION_ID, TENANT, {"operation": "put"})
    sql, params = _only_write(connection)
    _assert_in_place_update(sql, "path_operation", "id")
    assert params == ("PUT", OPERATION_ID)


def test_relabelling_an_operation_never_touches_the_operation_row(recorded):
    """Summary and operationId live on ``path_operation_description``, keyed by the operation id."""
    database, connection = recorded
    database.create_operation_description(OPERATION_ID, summary="List clients", operation_id="listClients")
    sql, params = _only_write(connection)
    _assert_in_place_update(sql, "path_operation_description", "path_operation_id")
    assert params[-1] == OPERATION_ID
    assert "apiome.path_operation " not in sql
