"""Small in-process TTL cache with single-flight loading (#7207, DBP-1.24).

The mock's request path keeps its database reads (access decisions, API keys, tenant limits,
monthly usage) behind this cache so a hot version is served with no statement at all. Two
properties matter:

* **Negative entries.** A ``None`` result (unknown tenant, revoked key, missing version) is cached
  too, under its own TTL, so a stream of 404s or bad keys does not turn into a stream of queries.
* **Single flight.** When many requests miss the same key at once, exactly one loads it; the rest
  await that load instead of each taking a pooled connection.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, Hashable, TypeVar

V = TypeVar("V")


@dataclass
class _Entry(Generic[V]):
    value: V | None
    expires_at: float


class TtlCache(Generic[V]):
    """A bounded LRU of values with per-entry expiry and single-flight loads.

    Args:
        ttl_seconds: Lifetime of a cached non-``None`` value. ``0`` disables caching (every call
            loads), but concurrent callers still share one in-flight load.
        negative_ttl_seconds: Lifetime of a cached ``None``; defaults to ``ttl_seconds``.
        max_entries: LRU bound.
        clock: Monotonic clock (tests inject one).
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        negative_ttl_seconds: float | None = None,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.negative_ttl_seconds = ttl_seconds if negative_ttl_seconds is None else negative_ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[Hashable, _Entry[V]] = OrderedDict()
        self._inflight: dict[Hashable, asyncio.Future[V | None]] = {}

    def peek(self, key: Hashable) -> tuple[bool, V | None]:
        """Return ``(hit, value)`` without loading; an expired entry counts as a miss."""
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        if self._clock() >= entry.expires_at:
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, entry.value

    def put(self, key: Hashable, value: V | None) -> None:
        """Store ``value`` (``None`` is a negative entry) unless its TTL is zero."""
        ttl = self.ttl_seconds if value is not None else self.negative_ttl_seconds
        if ttl <= 0:
            self._entries.pop(key, None)
            return
        self._entries[key] = _Entry(value=value, expires_at=self._clock() + ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    async def get_or_load(self, key: Hashable, loader: Callable[[], Awaitable[V | None]]) -> V | None:
        """Return the cached value for ``key``, loading it once when absent or expired.

        Args:
            key: Cache key.
            loader: Coroutine factory that reads the value; it runs at most once per key at a time.

        Returns:
            The cached or freshly loaded value (``None`` when the loader found nothing).

        Raises:
            Exception: Whatever the loader raised; failures are not cached.
        """
        hit, value = self.peek(key)
        if hit:
            return value
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future[V | None] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await loader()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            # Mark the exception retrieved when nobody else was waiting on it.
            future.exception()
            raise
        else:
            self.put(key, value)
            future.set_result(value)
            return value
        finally:
            self._inflight.pop(key, None)

    def invalidate(self, key: Hashable) -> None:
        """Drop one key."""
        self._entries.pop(key, None)

    def invalidate_where(self, predicate: Callable[[Hashable], bool]) -> None:
        """Drop every key ``predicate`` accepts."""
        for key in [k for k in self._entries if predicate(k)]:
            del self._entries[key]

    def clear(self) -> None:
        """Drop every entry."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
