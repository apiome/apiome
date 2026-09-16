"""A psycopg2 stand-in that answers statements from a script, for accessor-level tests.

Several accessors on :class:`app.database.Database` run more than one statement in a single
transaction — a review decision and its audit rows (COL-2.1, #4517), a comment and the inbox rows
it fans out to (COL-3.1, #4521). What matters about them is not the rows they return but *when they
commit*: the whole point of writing fan-out and audit inside the write is that a rolled-back write
leaves neither behind.

A live database cannot show that cheaply, and a fake accessor cannot show it at all — it has no
transaction. This connection double does: it records every statement in order, counts commits and
rollbacks, and answers each statement with the next scripted result, so a test can assert exactly
which statements ran inside which transaction.

The SQL text itself is exercised separately against a scratch database built from the real schema.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional, Sequence

import psycopg2

from app.database import Database

__all__ = ["ScriptedConnection", "ScriptedCursor", "database_with"]


class ScriptedCursor:
    """A cursor that answers each statement with the connection's next scripted rows."""

    def __init__(self, conn: "ScriptedConnection") -> None:
        """Create a cursor over a scripted connection.

        Args:
            conn: The connection whose script it reads.
        """
        self._conn = conn
        self._rows: List[Any] = []

    def __enter__(self) -> "ScriptedCursor":
        """Enter the ``with`` block."""
        return self

    def __exit__(self, *exc: Any) -> bool:
        """Leave the ``with`` block without swallowing anything."""
        return False

    @property
    def rowcount(self) -> int:
        """How many rows the last statement's scripted answer held."""
        return len(self._rows)

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> None:
        """Record a statement, fail it when scripted to, and load its answer.

        Args:
            sql: The statement, recorded with its whitespace collapsed.
            params: Its parameters.

        Raises:
            psycopg2.DatabaseError: When this is the statement the connection was told to fail on.
        """
        self._conn.statements.append((" ".join(sql.split()), params))
        if self._conn.fail_on is not None and len(self._conn.statements) == self._conn.fail_on:
            raise psycopg2.DatabaseError("boom")
        self._rows = self._conn.responses.pop(0) if self._conn.responses else []

    def fetchone(self) -> Any:
        """The first row of the last statement's answer, or ``None``."""
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Any]:
        """Every row of the last statement's answer."""
        return list(self._rows)


class ScriptedConnection:
    """A connection that records statements, commits, and rollbacks.

    Attributes:
        statements: ``(sql, params)`` of every statement, in order.
        commits: How many times the connection was committed.
        rollbacks: How many times it was rolled back.
    """

    def __init__(self, responses: Sequence[List[Any]], fail_on: Optional[int] = None) -> None:
        """Create the double.

        Args:
            responses: One answer per statement, in order; a statement past the end answers empty.
            fail_on: The 1-based statement number that should raise, or ``None``.
        """
        self.responses = list(responses)
        self.fail_on = fail_on
        self.statements: List[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.autocommit = True
        self.closed = False
        self.info = SimpleNamespace(transaction_status=psycopg2.extensions.TRANSACTION_STATUS_IDLE)

    def cursor(self) -> ScriptedCursor:
        """A cursor over this connection's script."""
        return ScriptedCursor(self)

    def commit(self) -> None:
        """Count a commit."""
        self.commits += 1

    def rollback(self) -> None:
        """Count a rollback."""
        self.rollbacks += 1


def database_with(monkeypatch, conn: Optional[ScriptedConnection]) -> Database:
    """A :class:`Database` whose connection is ``conn``.

    Args:
        monkeypatch: The pytest fixture.
        conn: The scripted connection, or ``None`` to assert the call never connects at all —
              which is how a guard that rejects a malformed id is proven.

    Returns:
        The database.
    """
    database = Database()

    def connect() -> ScriptedConnection:
        if conn is None:
            raise AssertionError("a guarded call must not reach the database")
        return conn

    monkeypatch.setattr(database, "connect", connect)
    return database
