"""Compiled-spec LRU with single-flight loads and revalidation at expiry (#7208, DBP-1.25).

Both compiled-spec caches (REST :class:`~apiome_mock.spec_cache.SpecCache` and canonical
:class:`~apiome_mock.canonical_spec_cache.CanonicalSpecCache`) are this class. Three rules:

* **Single flight.** While a key is being loaded or revalidated, every other request for that key
  awaits the same future, so 100 concurrent requests for an uncached version run one load and hold
  one pooled connection, not 100.
* **Revalidate, don't drop.** An entry older than ``ttl_seconds`` is not thrown away. One cheap
  statement reads the version's freshness stamp (:func:`~apiome_mock.spec_loader.fetch_spec_stamp`)
  and, when it equals the stamp the entry was built from, the entry's lifetime is extended without
  reloading. Only a changed (or vanished) spec is reloaded.
* **Invalidation wins.** A NOTIFY (``invalidate`` / ``clear``) that lands while a load is in flight
  stops that load's result from being stored: it may have read the rows before the change, so the
  next request loads again. A changed spec is therefore served within one NOTIFY, or one TTL when
  the NOTIFY is lost.

The synchronous methods are guarded by a lock (they are cheap and may be called from any thread);
:meth:`get_or_load` is event-loop only.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from threading import Lock
from typing import Generic, Protocol, TypeVar

import structlog

_log = structlog.get_logger(__name__)

CacheKey = tuple[str, str, str]
"""``(tenant, project, version)`` slug coordinates."""


class _Cacheable(Protocol):
    @property
    def cache_key(self) -> CacheKey: ...


T = TypeVar("T", bound=_Cacheable)


@dataclass
class _Entry(Generic[T]):
    compiled: T
    loaded_at: float


class RevalidatingSpecCache(Generic[T]):
    """Bounded LRU of compiled specs keyed by slug coordinates.

    Args:
        max_entries: LRU bound (``APIOME_MOCK_SPEC_CACHE_MAX_ENTRIES``).
        ttl_seconds: How long an entry is served before it is revalidated
            (``APIOME_MOCK_SPEC_CACHE_TTL_SECONDS``).
        stamp_of: Returns the freshness stamp an entry was built from (compared with what
            ``revalidate`` reads). ``None`` means "unknown" and always reloads at expiry.
        event_prefix: Prefix for this cache's log events.
        clock: Monotonic clock (tests inject one).
    """

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        stamp_of: Callable[[T], Hashable | None],
        event_prefix: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._stamp_of = stamp_of
        self._event_prefix = event_prefix
        self._clock = clock
        self._entries: OrderedDict[CacheKey, _Entry[T]] = OrderedDict()
        self._lock = Lock()
        self._inflight: dict[CacheKey, asyncio.Future[T | None]] = {}
        self._epoch = 0
        """Bumped by every invalidate/clear; a load started under an older epoch is not stored."""

    # ── synchronous API ───────────────────────────────────────────────────────

    def get(self, tenant: str, project: str, version: str) -> T | None:
        """Return the entry when it is within its TTL (no load, no revalidation)."""
        key = (tenant, project, version)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or self._expired(entry):
                return None
            self._entries.move_to_end(key)
            return entry.compiled

    def put(self, compiled: T) -> None:
        """Store ``compiled`` under its ``cache_key``, evicting the least recently used entry."""
        key = compiled.cache_key
        with self._lock:
            self._entries[key] = _Entry(compiled=compiled, loaded_at=self._clock())
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, tenant: str, project: str, version: str) -> None:
        """Forget one version (publish / settings NOTIFY)."""
        key = (tenant, project, version)
        with self._lock:
            self._epoch += 1
            if self._entries.pop(key, None) is not None:
                _log.info(f"{self._event_prefix}_invalidated", tenant=tenant, project=project, version=version)

    def clear(self) -> None:
        """Forget every entry (listener reconnect, tests)."""
        with self._lock:
            self._epoch += 1
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    # ── async API ─────────────────────────────────────────────────────────────

    async def get_or_load(
        self,
        tenant: str,
        project: str,
        version: str,
        *,
        load: Callable[[], Awaitable[T | None]],
        revalidate: Callable[[], Awaitable[Hashable | None]],
    ) -> T | None:
        """Return the compiled spec, loading or revalidating it at most once per key at a time.

        Args:
            tenant: Tenant slug.
            project: Project slug.
            version: Version label.
            load: Reads and compiles the spec (``None`` when it is not mockable). Runs only on a
                miss, or at expiry when the stamp changed.
            revalidate: Reads the version's current freshness stamp (one statement; ``None`` when
                the version is gone). Runs only at expiry of an existing entry.

        Returns:
            The cached, revalidated or freshly loaded spec, or ``None``.

        Raises:
            Exception: Whatever ``load`` or ``revalidate`` raised; failures are not cached, and the
                waiters of the same flight see the same exception.
        """
        key = (tenant, project, version)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and not self._expired(entry):
                self._entries.move_to_end(key)
                return entry.compiled
            epoch = self._epoch
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)

        future: asyncio.Future[T | None] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await self._refresh(key, entry, epoch, load=load, revalidate=revalidate)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # retrieved: nobody else may be waiting
            raise
        else:
            future.set_result(value)
            return value
        finally:
            self._inflight.pop(key, None)

    async def _refresh(
        self,
        key: CacheKey,
        stale: _Entry[T] | None,
        epoch: int,
        *,
        load: Callable[[], Awaitable[T | None]],
        revalidate: Callable[[], Awaitable[Hashable | None]],
    ) -> T | None:
        """Extend ``stale`` when its stamp is unchanged; otherwise load and store a new entry."""
        if stale is not None:
            known = self._stamp_of(stale.compiled)
            if known is not None and await revalidate() == known:
                with self._lock:
                    if self._epoch == epoch and self._entries.get(key) is stale:
                        stale.loaded_at = self._clock()
                        self._entries.move_to_end(key)
                        _log.debug(f"{self._event_prefix}_revalidated", key="/".join(key))
                        return stale.compiled
        value = await load()
        with self._lock:
            if self._epoch == epoch:
                if value is None:
                    self._entries.pop(key, None)
                else:
                    self._entries[key] = _Entry(compiled=value, loaded_at=self._clock())
                    self._entries.move_to_end(key)
                    while len(self._entries) > self._max_entries:
                        self._entries.popitem(last=False)
        return value

    def _expired(self, entry: _Entry[T]) -> bool:
        return self._clock() - entry.loaded_at > self._ttl_seconds
