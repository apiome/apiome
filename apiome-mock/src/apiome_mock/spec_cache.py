"""In-process LRU cache for compiled specs with TTL and NOTIFY invalidation."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Callable

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


async def run_notify_listener(
    database_url: str,
    channel: str,
    cache: SpecCache,
    *,
    stop_event: asyncio.Event,
    on_invalidate: Callable[[str, str, str], None] | None = None,
) -> None:
    """Listen for publish NOTIFY payloads and invalidate matching cache keys.

    Payload format: ``tenant/project/version`` (three slash-separated slugs).
    """
    import psycopg
    from psycopg import sql

    _log.info("spec_notify_listener_starting", channel=channel)
    try:
        async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as conn:
            await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
            async for notify in conn.notifies():
                if stop_event.is_set():
                    break
                payload = (notify.payload or "").strip()
                if not payload:
                    continue
                parts = payload.split("/", 2)
                if len(parts) != 3:
                    _log.warning("spec_notify_invalid_payload", payload=payload)
                    continue
                cache.invalidate(parts[0], parts[1], parts[2])
                if on_invalidate is not None:
                    on_invalidate(parts[0], parts[1], parts[2])
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.warning("spec_notify_listener_stopped", error=str(exc))
    finally:
        _log.info("spec_notify_listener_stopped")
