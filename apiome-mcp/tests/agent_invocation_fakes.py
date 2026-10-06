"""Recording stand-in for the psycopg pool the AGX-3.3 invocation audit and usage sweep use (#4539).

:class:`RecordingPool` quacks like ``AsyncConnectionPool`` for the calls those modules make —
``pool.connection()``, ``conn.transaction()``, ``conn.execute()`` (returning a cursor with
``fetchone``) and ``conn.cursor(row_factory=...)``. Every statement lands in
:attr:`RecordingPool.statements` as ``(sql, params)``; answers come from ``responder``.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

#: Given ``(sql, params)``, returns the row ``fetchone`` should yield (or ``None``).
Responder = Callable[[str, Any], Any]


class _Cursor:
    def __init__(self, pool: RecordingPool) -> None:
        self._pool = pool
        self._row: Any = None

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._row = self._pool.run(sql, params)
        return self

    async def fetchone(self) -> Any:
        return self._row

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Connection:
    def __init__(self, pool: RecordingPool) -> None:
        self._pool = pool

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        return await _Cursor(self._pool).execute(sql, params)

    def cursor(self, row_factory: Any = None) -> _Cursor:
        return _Cursor(self._pool)

    @asynccontextmanager
    async def transaction(self) -> Any:
        self._pool.transactions += 1
        try:
            yield
        except BaseException:
            self._pool.rollbacks += 1
            raise


class RecordingPool:
    """Records statements; answers ``fetchone`` through ``responder``.

    Attributes:
        statements: ``(sql, params)`` of every statement, in order.
        transactions: Transactions opened.
        rollbacks: Transactions that ended in an exception.
        fail_on: A substring; a statement containing it raises ``RuntimeError``.
    """

    def __init__(self, responder: Responder | None = None, *, fail_on: str | None = None) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.transactions = 0
        self.rollbacks = 0
        self.fail_on = fail_on
        self._responder = responder or (lambda sql, params: None)

    def run(self, sql: str, params: Any) -> Any:
        if self.fail_on is not None and self.fail_on in sql:
            raise RuntimeError("database unavailable")
        self.statements.append((sql, params))
        return self._responder(sql, params)

    def sql_containing(self, needle: str) -> list[tuple[str, Any]]:
        """The recorded statements whose SQL contains ``needle``."""
        return [(sql, params) for sql, params in self.statements if needle in sql]

    @asynccontextmanager
    async def connection(self) -> Any:
        yield _Connection(self)
