"""A cursor that ends the transaction it starts.

psycopg2 opens a transaction on the first statement and keeps it open until ``commit()`` or
``rollback()``. Every thread works on its own pooled connection (see :class:`app.database.Database`),
so a helper that runs a statement and returns without ending the transaction leaves that
connection "idle in transaction": it keeps its locks and its snapshot until the same thread
happens to commit something else, and an uncommitted write is rolled back when the thread ends.

:func:`db_cursor` is the cursor for a helper that takes a ``db`` handle and does not manage a
transaction itself.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2.extensions

__all__ = ["db_cursor", "rollback_quietly"]


def _starts_transaction(conn: Any) -> bool:
    """Whether ``conn`` is a real connection with no transaction open.

    A connection already inside a transaction belongs to a caller that will commit or roll back
    itself. A test double without ``info`` is left alone too.
    """
    info = getattr(conn, "info", None)
    try:
        return info is not None and info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
    except Exception:
        return False


def rollback_quietly(conn: Any) -> None:
    """Roll back, swallowing the failure a dead connection raises.

    A rollback in an ``except`` block must not replace the error being handled: on a connection
    the server already closed it raises ``InterfaceError``, which would hide the real cause.
    """
    try:
        conn.rollback()
    except Exception:
        pass


@contextmanager
def db_cursor(db: Any) -> Iterator[Any]:
    """Yield a cursor on the calling thread's connection and end the transaction it starts.

    Commits when the block finishes and rolls back when it raises — unless a transaction was
    already open on entry, in which case the caller that opened it stays in charge of it.

    Args:
        db: A database handle exposing ``connect()``.

    Yields:
        An open cursor.
    """
    conn = db.connect()
    owns = _starts_transaction(conn)
    try:
        with conn.cursor() as cursor:
            yield cursor
    except BaseException:
        if owns:
            rollback_quietly(conn)
        raise
    else:
        if owns:
            conn.commit()
