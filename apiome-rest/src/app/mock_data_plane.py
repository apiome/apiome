"""Keeping the mock data plane's hot path off the database (DBP-1.13, #7196).

Every request to ``/mock/{id}/…`` used to read the instance's frozen ``spec`` document and then
write the row to bump its request counter. Two small in-process pieces take both off the request:

* :class:`SpecCache` — the spec never changes after an instance is provisioned, so it is read once
  and kept for a short while. A request then runs one narrow statement
  (:meth:`app.database.Database.get_mock_serving_row`).
* :class:`ActivityBuffer` — served requests are counted in memory and added to their rows in one
  ``UPDATE`` every few seconds (and at shutdown), by the sweep in :mod:`app.main`.

Both are per process. A count is therefore up to one flush interval behind in the management
views and in the monthly quota sum; a process killed without a shutdown loses at most that
interval's counts. Neither affects what a mock serves.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "ACTIVITY_FLUSH_SECONDS",
    "ActivityBuffer",
    "SpecCache",
    "activity_buffer",
    "flush_activity",
    "spec_cache",
]

logger = logging.getLogger(__name__)

#: How long a cached spec is served before it is read again.
SPEC_TTL_SECONDS = 300.0
#: How many instances' specs one process keeps (least recently used are dropped first).
SPEC_CACHE_ENTRIES = 64
#: How often buffered request counts are written.
ACTIVITY_FLUSH_SECONDS = 5.0
#: Above this many distinct instances the buffer stops taking new ones until the next flush.
ACTIVITY_MAX_INSTANCES = 10_000


class SpecCache:
    """A small time-bounded, size-bounded cache of frozen mock specs, keyed by instance id."""

    def __init__(
        self,
        *,
        ttl_seconds: float = SPEC_TTL_SECONDS,
        max_entries: int = SPEC_CACHE_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty cache.

        Args:
            ttl_seconds: How long an entry is served.
            max_entries: How many entries are kept.
            clock: A monotonic clock (replaceable in tests).
        """
        self._ttl = float(ttl_seconds)
        self._max = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()

    def get(
        self, mock_id: str, load: Callable[[str], Optional[Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """Return an instance's spec, reading it through ``load`` on a miss.

        Args:
            mock_id: The instance id.
            load: Reads the spec from the database; ``None`` when the instance is gone.

        Returns:
            The spec, or ``None`` when ``load`` found none (a miss is not cached).
        """
        key = str(mock_id)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > now:
                self._entries.move_to_end(key)
                return entry[1]
        spec = load(key)
        if spec is None:
            self.forget(key)
            return None
        with self._lock:
            self._entries[key] = (now + self._ttl, spec)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return spec

    def forget(self, mock_id: str) -> None:
        """Drop one instance's entry (it was deleted or expired).

        Args:
            mock_id: The instance id.
        """
        with self._lock:
            self._entries.pop(str(mock_id), None)

    def clear(self) -> None:
        """Drop every entry."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        """How many specs are cached."""
        with self._lock:
            return len(self._entries)


class ActivityBuffer:
    """Counts served requests per instance until the next flush."""

    def __init__(self, *, max_instances: int = ACTIVITY_MAX_INSTANCES) -> None:
        """Create an empty buffer.

        Args:
            max_instances: How many distinct instances are tracked between two flushes.
        """
        self._max = max(1, int(max_instances))
        self._lock = threading.Lock()
        self._pending: Dict[str, Tuple[int, datetime]] = {}

    def record(self, mock_id: str, *, at: Optional[datetime] = None) -> None:
        """Count one served request. Never touches the database and never raises.

        Args:
            mock_id: The instance that served.
            at: When it served; now when omitted.
        """
        key = str(mock_id)
        stamp = at or datetime.now(timezone.utc)
        with self._lock:
            current = self._pending.get(key)
            if current is None:
                if len(self._pending) >= self._max:
                    return
                self._pending[key] = (1, stamp)
            else:
                self._pending[key] = (current[0] + 1, max(current[1], stamp))

    def drain(self) -> List[Tuple[str, int, datetime]]:
        """Take everything counted so far.

        Returns:
            ``(mock_id, requests, last_activity_at)`` per instance; the buffer is left empty.
        """
        with self._lock:
            pending, self._pending = self._pending, {}
        return [(mock_id, count, stamp) for mock_id, (count, stamp) in pending.items()]

    def restore(self, batch: List[Tuple[str, int, datetime]]) -> None:
        """Put back a batch whose write failed, so the next flush retries it.

        Args:
            batch: What :meth:`drain` returned.
        """
        with self._lock:
            for mock_id, count, stamp in batch:
                current = self._pending.get(mock_id)
                if current is None:
                    if len(self._pending) < self._max:
                        self._pending[mock_id] = (count, stamp)
                else:
                    self._pending[mock_id] = (current[0] + count, max(current[1], stamp))

    def __len__(self) -> int:
        """How many instances have unflushed requests."""
        with self._lock:
            return len(self._pending)


#: The process-wide spec cache the data plane reads through.
spec_cache = SpecCache()
#: The process-wide request counter the data plane records into.
activity_buffer = ActivityBuffer()


def flush_activity(database: Any, buffer: Optional[ActivityBuffer] = None) -> int:
    """Write the buffered request counts in one statement.

    Best effort, as the per-request write it replaces was: a failure is logged and the batch is
    kept for the next flush.

    Args:
        database: The database handle to write through.
        buffer: The buffer to flush; the process-wide one when omitted.

    Returns:
        How many instances were updated.
    """
    target = buffer if buffer is not None else activity_buffer
    batch = target.drain()
    if not batch:
        return 0
    try:
        return int(database.add_mock_instance_activity(batch) or 0)
    except Exception as exc:  # accounting must never raise
        logger.warning("Failed to flush mock activity for %d instance(s): %s", len(batch), exc)
        target.restore(batch)
        return 0
