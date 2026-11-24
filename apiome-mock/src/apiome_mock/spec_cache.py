"""In-process LRU cache for compiled specs with TTL and NOTIFY invalidation."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import structlog

if TYPE_CHECKING:
    from apiome_mock.spec_loader import CompiledSpec

_log = structlog.get_logger(__name__)


@dataclass
class _CacheEntry:
    compiled: CompiledSpec
    loaded_at: float


class SpecCache:
    """Thread-safe LRU cache for :class:`CompiledSpec` with TTL expiry."""

    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[str, str, str], _CacheEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, tenant: str, project: str, version: str) -> CompiledSpec | None:
        key = (tenant, project, version)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now - entry.loaded_at > self._ttl_seconds:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return entry.compiled

    def put(self, compiled: CompiledSpec) -> None:
        key = compiled.cache_key
        with self._lock:
            self._entries[key] = _CacheEntry(compiled=compiled, loaded_at=time.monotonic())
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, tenant: str, project: str, version: str) -> None:
        key = (tenant, project, version)
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                _log.info("spec_cache_invalidated", tenant=tenant, project=project, version=version)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


ConnectFn = Callable[[str], Awaitable[Any]]
"""Opens an autocommit connection for the listener (tests inject one)."""


async def _default_connect(database_url: str) -> Any:
    import psycopg

    return await psycopg.AsyncConnection.connect(database_url, autocommit=True)


def _apply_payload(
    payload: str,
    cache: SpecCache,
    on_invalidate: Callable[[str, str, str], None] | None,
) -> None:
    payload = payload.strip()
    if not payload:
        return
    parts = payload.split("/", 2)
    if len(parts) != 3:
        _log.warning("spec_notify_invalid_payload", payload=payload)
        return
    cache.invalidate(parts[0], parts[1], parts[2])
    if on_invalidate is not None:
        on_invalidate(parts[0], parts[1], parts[2])


async def run_notify_listener(
    database_url: str,
    channel: str,
    cache: SpecCache,
    *,
    stop_event: asyncio.Event,
    on_invalidate: Callable[[str, str, str], None] | None = None,
    on_connected: Callable[[], None] | None = None,
    initial_backoff_seconds: float = 0.5,
    max_backoff_seconds: float = 30.0,
    connect: ConnectFn = _default_connect,
) -> None:
    """Listen for publish NOTIFY payloads and invalidate matching cache keys, reconnecting forever.

    Payload format: ``tenant/project/version`` (three slash-separated slugs).

    A lost connection is reopened with exponential backoff (``initial_backoff_seconds`` doubling up
    to ``max_backoff_seconds``, reset after a successful connect) until ``stop_event`` is set
    (#7207, DBP-1.24). Notifications sent while disconnected are lost, so every successful
    (re)connect flushes ``cache`` and calls ``on_connected`` to flush the caches beside it — the
    process never keeps serving entries it can no longer hear invalidations for.

    Args:
        database_url: Connection URI for the dedicated listener connection.
        channel: NOTIFY channel name.
        cache: Compiled spec cache to invalidate.
        stop_event: Set at shutdown; the loop exits instead of reconnecting.
        on_invalidate: Called with ``(tenant, project, version)`` for every valid payload.
        on_connected: Called after each successful ``LISTEN`` (flush the other caches here).
        initial_backoff_seconds: First reconnect delay.
        max_backoff_seconds: Reconnect delay ceiling.
        connect: Connection factory (tests inject one).
    """
    from psycopg import sql

    _log.info("spec_notify_listener_starting", channel=channel)
    backoff = initial_backoff_seconds
    try:
        while not stop_event.is_set():
            try:
                async with await connect(database_url) as conn:
                    await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
                    cache.clear()
                    if on_connected is not None:
                        on_connected()
                    backoff = initial_backoff_seconds
                    _log.info("spec_notify_listener_connected", channel=channel)
                    async for notify in conn.notifies():
                        if stop_event.is_set():
                            break
                        _apply_payload(notify.payload or "", cache, on_invalidate)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning("spec_notify_listener_disconnected", error=str(exc), retry_in=backoff)
            if stop_event.is_set():
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(max_backoff_seconds, backoff * 2)
    finally:
        _log.info("spec_notify_listener_stopped")
