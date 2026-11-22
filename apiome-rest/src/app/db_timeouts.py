"""Statement timeouts for apiome-rest's database connections (DBP-1.2, #7185).

Every pooled connection starts with ``statement_timeout = settings.db_statement_timeout_ms``
(30 s by default), so one runaway query on a request fails instead of holding a worker thread
and its locks for as long as it likes.

Imports, exports, document migrations and the background sweeps legitimately run longer
statements. They run inside :func:`long_statements`, which raises the ceiling to
``settings.db_long_statement_timeout_ms`` for the code in its ``with`` block:

    with long_statements():
        run_document_migration(db, store, options)

The override lives in a :class:`contextvars.ContextVar`, so it follows the work into
``asyncio.to_thread`` workers and into tasks created inside the block. ``Database.connect`` reads
it and, when the calling thread's connection is idle and runs under a different ceiling, sends
one ``SET statement_timeout`` before handing the connection out (see :func:`apply_statement_timeout`).
A connection that is inside a transaction keeps the ceiling it started the transaction with.

A statement cut off by the ceiling raises :class:`StatementTimeout` from ``Database.execute_query``
and ``Database._execute_write``; anywhere else psycopg2 raises its own
``psycopg2.errors.QueryCanceled``, which :class:`StatementTimeout` subclasses, so one ``except``
catches both.
"""

from __future__ import annotations

import contextvars
import weakref
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg2
import psycopg2.extensions
from psycopg2 import errors as pg_errors

__all__ = [
    "StatementTimeout",
    "apply_statement_timeout",
    "is_statement_timeout",
    "long_statements",
    "statement_timeout_override",
]

#: The ceiling (ms) the current context asks for, or ``None`` for the connection's default.
_override_ms: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "apiome_statement_timeout_override_ms", default=None
)

#: The ceiling each connection currently runs under, when it differs from its startup default.
#: Weak, so a closed and collected connection drops out on its own.
_applied: "weakref.WeakKeyDictionary[Any, int]" = weakref.WeakKeyDictionary()


class StatementTimeout(pg_errors.QueryCanceled):
    """A statement ran past its ``statement_timeout`` and PostgreSQL cancelled it.

    Subclasses ``psycopg2.errors.QueryCanceled`` (SQLSTATE ``57014``), so handlers written for
    psycopg2's error keep working.

    Attributes:
        timeout_ms: The ceiling the statement ran under, when known (``None`` otherwise).
    """

    def __init__(self, message: str, timeout_ms: Optional[int] = None) -> None:
        super().__init__(message)
        self.timeout_ms = timeout_ms


def is_statement_timeout(exc: BaseException) -> bool:
    """Whether ``exc`` is PostgreSQL cancelling a statement for running past its timeout.

    A ``QueryCanceled`` also comes from an explicit ``pg_cancel_backend``; only the timeout
    carries the "statement timeout" message.

    Args:
        exc: Any exception.

    Returns:
        ``True`` for a statement-timeout cancellation.
    """
    if isinstance(exc, StatementTimeout):
        return True
    return isinstance(exc, pg_errors.QueryCanceled) and "statement timeout" in str(exc).lower()


def statement_timeout_override() -> Optional[int]:
    """The ceiling (ms) the current context asks for, or ``None`` for the connection default."""
    return _override_ms.get()


@contextmanager
def long_statements(timeout_ms: Optional[int] = None) -> Iterator[int]:
    """Run the block's statements under the long ceiling (imports, exports, migrations, sweeps).

    Args:
        timeout_ms: The ceiling in milliseconds; ``settings.db_long_statement_timeout_ms`` when
            omitted. ``0`` means no limit.

    Yields:
        The ceiling in force inside the block.

    Raises:
        ValueError: ``timeout_ms`` is negative.
    """
    if timeout_ms is None:
        from .config import settings

        timeout_ms = int(settings.db_long_statement_timeout_ms)
    if int(timeout_ms) < 0:
        raise ValueError("a statement timeout cannot be negative")
    token = _override_ms.set(int(timeout_ms))
    try:
        yield int(timeout_ms)
    finally:
        _override_ms.reset(token)


def _is_real_connection(conn: Any) -> bool:
    """Whether ``conn`` is a psycopg2 connection (test doubles and wrappers are left alone)."""
    return isinstance(conn, psycopg2.extensions.connection)


def apply_statement_timeout(conn: Any) -> None:
    """Bring ``conn``'s ceiling in line with the current context, if it can be changed now.

    Sends ``SET statement_timeout`` (or ``RESET`` back to the startup default) only when the
    ceiling differs from the one the connection already runs under, and only while it is idle;
    the statement runs in autocommit, so no transaction is left open. It runs on a plain cursor,
    so it is not counted against a request's statement budget (DBP-1.1): it is connection
    housekeeping, not work the request asked for.

    Args:
        conn: The connection about to be handed out.
    """
    if not _is_real_connection(conn) or conn.closed:
        return
    wanted = _override_ms.get()
    current = _applied.get(conn)
    if wanted == current:
        return
    try:
        if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            return
        previous = conn.autocommit
        conn.autocommit = True
        try:
            with conn.cursor(cursor_factory=psycopg2.extensions.cursor) as cursor:
                if wanted is None:
                    cursor.execute("RESET statement_timeout")
                else:
                    cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(wanted),))
        finally:
            conn.autocommit = previous
    except psycopg2.Error:
        # A connection that cannot take the SET is broken; the caller's next statement reports it.
        return
    if wanted is None:
        _applied.pop(conn, None)
    else:
        _applied[conn] = wanted


def forget_statement_timeout(conn: Any) -> None:
    """Drop what is known about ``conn``'s ceiling (after a ``RESET`` or ``DISCARD ALL`` elsewhere)."""
    try:
        _applied.pop(conn, None)
    except TypeError:
        pass


def typed_timeout(exc: BaseException) -> BaseException:
    """``exc`` as a :class:`StatementTimeout` when it is a statement timeout, else ``exc`` itself.

    Args:
        exc: The exception a statement raised.

    Returns:
        The exception to raise (chain it ``from exc``).
    """
    if isinstance(exc, StatementTimeout) or not is_statement_timeout(exc):
        return exc
    return StatementTimeout(str(exc).strip(), timeout_ms=_override_ms.get())
