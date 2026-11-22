"""Test doubles for :class:`app.db_advisory_lock.SessionAdvisoryLock` (DBP-1.2, #7185)."""

from __future__ import annotations

from typing import Any, List, Optional


class FakeLockCursor:
    """Records each lock statement and answers it with ``{"ok": <owner.locked>}``."""

    def __init__(self, owner: "FakeLockConnection") -> None:
        self._owner = owner
        self._row: Optional[dict] = None

    def __enter__(self) -> "FakeLockCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, query: str, params: Any = None) -> None:
        self._owner.queries.append(query)
        locked = self._owner.locked if "pg_try_advisory_lock" in query else True
        self._row = {"ok": locked}

    def fetchone(self) -> Optional[dict]:
        return self._row


class FakeLockConnection:
    """A connection double whose lock statements succeed unless ``locked`` is ``False``."""

    closed = False

    def __init__(self, locked: bool, queries: List[str]) -> None:
        self.locked = locked
        self.queries = queries

    def cursor(self, *args: Any, **kwargs: Any) -> FakeLockCursor:
        return FakeLockCursor(self)

    def close(self) -> None:
        self.closed = True


class LockingDbMixin:
    """Adds ``checkout``/``checkin`` to a test database double.

    The host class sets ``self.locked`` and ``self.queries``; ``checked_out`` counts connections
    not yet returned, so a test can assert the lock gave its connection back.
    """

    locked: bool = True
    queries: List[str]
    checked_out: int = 0

    def checkout(self) -> FakeLockConnection:
        if not hasattr(self, "queries"):
            self.queries = []
        self.checked_out += 1
        return FakeLockConnection(self.locked, self.queries)

    def checkin(self, conn: Any) -> None:
        self.checked_out -= 1
