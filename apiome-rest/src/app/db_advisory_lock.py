"""A session advisory lock that stays on one connection (DBP-1.2, #7185).

``pg_try_advisory_lock`` takes a *session* lock: it belongs to the connection that ran it, and only
``pg_advisory_unlock`` on that same connection releases it. ``Database`` gives every thread its own
connection, so a sweep that takes its lock in one ``asyncio.to_thread`` call and releases it in
another can run the two on different connections: the release returns ``false``, and the lock
stays held by an idle pooled connection, so every later tick — on every replica — finds the sweep
"busy" until that connection closes.

:class:`SessionAdvisoryLock` checks out one connection for the lock's lifetime
(:meth:`app.database.Database.checkout`) and runs both statements on it, whatever thread calls::

    lock = SessionAdvisoryLock(db, "apiome.catalog_refresh_sweep")
    if not await asyncio.to_thread(lock.acquire):
        return None  # another replica holds it
    try:
        ...  # work, on any threads
    finally:
        await asyncio.to_thread(lock.release)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import psycopg2
import psycopg2.extensions

__all__ = ["SessionAdvisoryLock"]

_logger = logging.getLogger(__name__)


class SessionAdvisoryLock:
    """``pg_try_advisory_lock(hashtext(key))`` and its release on one dedicated connection.

    Attributes:
        key: The lock name every replica shares (hashed with ``hashtext``).
    """

    def __init__(self, db: Any, key: str) -> None:
        """Prepare the lock; nothing is sent until :meth:`acquire`.

        Args:
            db: A :class:`~app.database.Database` (anything with ``checkout``/``checkin``).
            key: The lock name.
        """
        self.key = key
        self._db = db
        self._conn: Optional[Any] = None
        self._guard = threading.Lock()

    @property
    def held(self) -> bool:
        """Whether this object holds the lock right now."""
        return self._conn is not None

    def _run(self, conn: Any, statement: str) -> bool:
        """Run one lock statement in autocommit on ``conn`` and return its boolean result."""
        real = isinstance(conn, psycopg2.extensions.connection)
        previous = conn.autocommit if real else None
        if real:
            if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            conn.autocommit = True
        try:
            with conn.cursor() as cursor:
                cursor.execute(statement, (self.key,))
                row = cursor.fetchone()
        finally:
            if real and not conn.closed:
                conn.autocommit = previous
        if row is None:
            return False
        value = row.get("ok") if isinstance(row, dict) else row[0]
        return bool(value)

    def acquire(self) -> bool:
        """Try to take the lock without waiting.

        Returns:
            ``True`` when this object now holds it (also when it already did), ``False`` when
            another session holds it.

        Raises:
            app.database.ConnectionPoolExhausted: No connection could be checked out.
            psycopg2.Error: The statement failed; the connection is returned first.
        """
        with self._guard:
            if self._conn is not None:
                return True
            conn = self._db.checkout()
            try:
                locked = self._run(conn, "SELECT pg_try_advisory_lock(hashtext(%s)) AS ok")
            except BaseException:
                self._db.checkin(conn)
                raise
            if not locked:
                self._db.checkin(conn)
                return False
            self._conn = conn
            return True

    def release(self) -> None:
        """Release the lock and return its connection; a no-op when it is not held.

        A failed unlock (the connection died, which ends the session and its locks anyway) is
        logged and the connection closed, so a broken session never goes back to the pool.
        """
        with self._guard:
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                if not self._run(conn, "SELECT pg_advisory_unlock(hashtext(%s)) AS ok"):
                    _logger.warning("advisory lock %s was not held at release", self.key)
            except Exception:
                _logger.warning("advisory lock %s release failed; closing its connection", self.key, exc_info=True)
                try:
                    conn.close()
                except Exception:
                    pass
            self._db.checkin(conn)
