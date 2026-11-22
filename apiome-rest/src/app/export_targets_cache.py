"""Process-local cache for the export targets list (``GET /v1/export/{tenant}/targets``).

The list pairs every registered export target with a fidelity badge predicted from the source's
canonical model. On a large spec that prediction is most of the request — every target's rule
pack walks every construct, about ten seconds for a 1 800-class OpenAPI document — and the
Export dialog and the version view ask for the same list each time they open. This module keeps
the finished list so a repeat request only pays for loading the source.

The key is content-addressed: tenant, revision, a SHA-256 of the source text the model was
rebuilt from, the source format, a digest of the API plans attached to the model, the Apiome
version (which pins every rule pack), and the registered targets with their availability. An
edit to the revision changes its source text and so its key; nothing has to be invalidated by
hand. Entries also expire after :data:`TARGETS_CACHE_TTL_SECONDS`, so a list is never served
indefinitely by a long-running worker.

Each worker keeps its own cache, capped at :data:`TARGETS_CACHE_MAX_ENTRIES` (LRU eviction).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, List, Optional, Tuple

#: How long a cached list is served (seconds).
TARGETS_CACHE_TTL_SECONDS = 600.0

#: Lists kept per worker. Each is a few hundred kilobytes of descriptors and option schemas.
TARGETS_CACHE_MAX_ENTRIES = 32

TargetsCacheKey = Tuple[str, str, str, str, str, str, str]


def build_targets_cache_key(
    *,
    tenant_id: str,
    version_record_id: str,
    source_text: Optional[str],
    source_format: Optional[str],
    plans: Any,
    apiome_version: str,
    registry: List[Tuple[str, bool]],
) -> Optional[TargetsCacheKey]:
    """Assemble the cache key for one source's targets list.

    Args:
        tenant_id: The caller's tenant; a list is never served across tenants.
        version_record_id: The revision (``versions.id``).
        source_text: The text the canonical model was rebuilt from. ``None`` means the source
            cannot be identified by content, so the list is not cached.
        source_format: The revision's source format (selects the import adapter).
        plans: The API plans attached to the model (``api.extras``), or ``None``.
        apiome_version: The running Apiome version (pins the emitters and their rule packs).
        registry: ``(target key, available)`` for every registered target, so a target
            registered at runtime, or one whose toolchain appears or goes away, misses.

    Returns:
        The key, or ``None`` when the list must not be cached.
    """
    if source_text is None:
        return None
    source_digest = hashlib.sha256(source_text.encode("utf-8", "surrogatepass")).hexdigest()
    plans_blob = json.dumps(plans, sort_keys=True, separators=(",", ":"), default=str)
    plans_digest = hashlib.sha256(plans_blob.encode("utf-8")).hexdigest()
    registry_blob = json.dumps(sorted(registry), separators=(",", ":"))
    registry_digest = hashlib.sha256(registry_blob.encode("utf-8")).hexdigest()
    return (
        str(tenant_id),
        str(version_record_id),
        source_digest,
        source_format or "",
        plans_digest,
        apiome_version,
        registry_digest,
    )


class TargetsCache:
    """A thread-safe TTL + LRU map from :data:`TargetsCacheKey` to a finished targets list."""

    def __init__(
        self,
        *,
        max_entries: int = TARGETS_CACHE_MAX_ENTRIES,
        ttl_seconds: float = TARGETS_CACHE_TTL_SECONDS,
    ) -> None:
        """Create an empty cache.

        Args:
            max_entries: Lists kept before the least recently used one is dropped.
            ttl_seconds: How long a list is served after it was stored.
        """
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: "OrderedDict[TargetsCacheKey, Tuple[float, List[Any]]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Optional[TargetsCacheKey]) -> Optional[List[Any]]:
        """Return the stored list for ``key``, or ``None`` on a miss or an expired entry.

        Args:
            key: The cache key; ``None`` always misses.

        Returns:
            A new list holding the stored entries (the entries themselves are shared and must
            not be mutated), or ``None``.
        """
        if key is None:
            return None
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                return None
            stored_at, entries = hit
            if time.monotonic() - stored_at > self._ttl_seconds:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return list(entries)

    def put(self, key: Optional[TargetsCacheKey], entries: List[Any]) -> None:
        """Store ``entries`` under ``key`` (a ``None`` key stores nothing).

        Args:
            key: The cache key.
            entries: The finished targets list.
        """
        if key is None or self._max_entries <= 0:
            return
        with self._lock:
            self._entries[key] = (time.monotonic(), list(entries))
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        """Drop every stored list."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        """Return the number of stored lists."""
        return len(self._entries)


_cache = TargetsCache()


def targets_cache() -> TargetsCache:
    """Return the process-wide targets cache."""
    return _cache
