"""Verified-key cache and ``last_used_at`` throttle for both MCP planes (DBP-1.21, #7204).

Same design as apiome-rest's DBP-1.3 key cache (``app.authz_cache``):

* **What is cached** is the outcome of one bcrypt check: ``sha256(secret)`` → the key's id and its
  stored hash. The secret itself is never stored.
* **What is not cached** is whether the key may still be used. Every call re-reads the key row *by
  id and hash* (one indexed lookup instead of a prefix scan plus bcrypt), so a key revoked,
  disabled, expired or regenerated anywhere is refused on its next call. A re-read that finds no
  usable row drops the entry (:meth:`VerifiedKeyCache.invalidate`) and the caller falls back to
  the full check, which reports why.
* **Lifetime** is ``key_cache_seconds`` (default 60 s; ``0`` turns it off), read on every call so a
  test or an operator change applies at once. At most ``key_cache_max_entries`` are kept.

:class:`LastUsedThrottle` keeps ``last_used_at`` writes to one per key per minute per process; the
UPDATE's own ``WHERE`` skips rows written in the last minute by any process.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apiome_mcp.settings import setting_or_default

__all__ = [
    "LAST_USED_INTERVAL_SECONDS",
    "CachedKey",
    "LastUsedThrottle",
    "VerifiedKeyCache",
    "secret_digest",
]

#: Shortest gap between two ``last_used_at`` writes for one key.
LAST_USED_INTERVAL_SECONDS = 60.0


def secret_digest(secret: str) -> str:
    """The cache key for a presented secret: hex SHA-256 of its UTF-8 bytes."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedKey:
    """What a successful bcrypt check proved.

    Attributes:
        key_id: The key row's id.
        key_hash: The stored hash the secret verified against, exactly as read (the re-read matches
            on it, so a regenerated key misses).
    """

    key_id: str
    key_hash: Any


class VerifiedKeyCache:
    """``sha256(secret)`` → :class:`CachedKey`, expiring after ``key_cache_seconds``.

    Used from the event loop only (no locking needed). Least recently stored entries go first.
    """

    def __init__(
        self,
        *,
        ttl_seconds: Callable[[], float] | None = None,
        max_entries: Callable[[], float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty cache.

        Args:
            ttl_seconds: Returns the current lifetime (default: the ``key_cache_seconds`` setting).
            max_entries: Returns the most entries (default: the ``key_cache_max_entries`` setting).
            clock: Monotonic clock (tests).
        """
        self._ttl = ttl_seconds or (lambda: setting_or_default("key_cache_seconds", 60.0))
        self._max = max_entries or (lambda: setting_or_default("key_cache_max_entries", 10_000))
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, CachedKey]] = OrderedDict()

    def get(self, secret: str) -> CachedKey | None:
        """The live entry for ``secret``, or ``None`` (missing, expired, or the cache is off)."""
        if float(self._ttl()) <= 0:
            return None
        digest = secret_digest(secret)
        hit = self._entries.get(digest)
        if hit is None:
            return None
        expires_at, entry = hit
        if expires_at <= self._clock():
            self._entries.pop(digest, None)
            return None
        return entry

    def put(self, secret: str, entry: CachedKey) -> None:
        """Remember that ``secret`` verified as ``entry`` (a no-op when the cache is off)."""
        ttl = float(self._ttl())
        if ttl <= 0:
            return
        digest = secret_digest(secret)
        self._entries.pop(digest, None)
        self._entries[digest] = (self._clock() + ttl, entry)
        limit = max(1, int(self._max()))
        while len(self._entries) > limit:
            self._entries.popitem(last=False)

    def invalidate(self, key_id: str) -> None:
        """Forget every entry for ``key_id`` (revoked, expired, regenerated or deleted)."""
        for digest in [d for d, (_, entry) in self._entries.items() if entry.key_id == key_id]:
            self._entries.pop(digest, None)

    def clear(self) -> None:
        """Forget everything."""
        self._entries.clear()

    def __len__(self) -> int:
        """Entries held (expired ones included until next read)."""
        return len(self._entries)


class LastUsedThrottle:
    """Decides whether a key's ``last_used_at`` is due for a write from this process."""

    def __init__(
        self,
        *,
        interval_seconds: float = LAST_USED_INTERVAL_SECONDS,
        max_entries: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty throttle.

        Args:
            interval_seconds: Shortest gap between writes for one key.
            max_entries: Keys remembered (oldest forgotten first; a forgotten key is simply due).
            clock: Monotonic clock (tests).
        """
        self._interval = interval_seconds
        self._max = max(1, max_entries)
        self._clock = clock
        self._stamped: OrderedDict[str, float] = OrderedDict()

    def due(self, key_id: str) -> bool:
        """Return ``True`` (and record the write) when ``key_id`` was not stamped recently."""
        now = self._clock()
        last = self._stamped.get(key_id)
        if last is not None and now - last < self._interval:
            return False
        self._stamped.pop(key_id, None)
        self._stamped[key_id] = now
        while len(self._stamped) > self._max:
            self._stamped.popitem(last=False)
        return True

    def clear(self) -> None:
        """Forget every stamp."""
        self._stamped.clear()
