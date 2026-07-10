"""In-process LRU cache for compiled canonical mock specs."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from apiome_mock.canonical_compiler import CompiledCanonicalSpec

_log = structlog.get_logger(__name__)


@dataclass
class _CacheEntry:
    compiled: CompiledCanonicalSpec
    loaded_at: float


class CanonicalSpecCache:
    """Thread-safe LRU cache for :class:`CompiledCanonicalSpec` with TTL expiry."""

    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[str, str, str], _CacheEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, tenant: str, project: str, version: str) -> CompiledCanonicalSpec | None:
        key = (tenant, project, version)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now - entry.loaded_at > self._ttl_seconds:
                del self._entries[key]
                return None
            self._move_to_end(key)
            return entry.compiled

    def put(self, compiled: CompiledCanonicalSpec) -> None:
        key = compiled.cache_key
        with self._lock:
            self._entries[key] = _CacheEntry(compiled=compiled, loaded_at=time.monotonic())
            self._move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, tenant: str, project: str, version: str) -> None:
        key = (tenant, project, version)
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                _log.info("canonical_spec_cache_invalidated", tenant=tenant, project=project, version=version)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _move_to_end(self, key: tuple[str, str, str]) -> None:
        self._entries.move_to_end(key)
