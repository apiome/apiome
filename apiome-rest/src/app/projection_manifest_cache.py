"""TTL/LRU cache for built projection manifests — EFP-3.2 (#4817).

Evidence pages are cheap once a :class:`~app.export_projection.ProjectionManifest`
exists; rebuilding the graph for every cursor hop is the expensive step. This
module caches **manifests only** (never pages) behind a tenant-scoped key so
pagination reuses work without leaking one tenant's graph into another.

Cache keys fold tenant identity, source revision coordinates, target, normalized
options digest, and the version provenance that already participates in the
snapshot hash (emitter / registry / apiome). Entries expire after
:data:`MANIFEST_CACHE_TTL_SECONDS` and the store is capped at
:data:`MANIFEST_CACHE_MAX_ENTRIES` (LRU eviction).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

from .export_projection import ProjectionManifest

#: Soft wall-clock TTL for a cached manifest (seconds).
MANIFEST_CACHE_TTL_SECONDS = 60.0

#: Hard cap on resident entries (process-local).
MANIFEST_CACHE_MAX_ENTRIES = 64

ManifestCacheKey = Tuple[str, str, str, str, str, str, str, str]


def options_digest(options: Optional[Dict[str, Any]]) -> str:
    """Return a stable digest of emit options for use in a cache key.

    Args:
        options: Normalized or raw option mapping (``None`` → empty object).

    Returns:
        Hex SHA-256 of the canonical JSON encoding.
    """
    blob = json.dumps(options or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_manifest_cache_key(
    *,
    tenant_id: str,
    artifact_id: str,
    version_record_id: str,
    target: str,
    options: Optional[Dict[str, Any]],
    emitter_version: str,
    registry_version: str,
    apiome_version: str,
) -> ManifestCacheKey:
    """Assemble the tenant-scoped cache key for one projection manifest.

    Args:
        tenant_id: Authenticated tenant UUID (never a slug alone — keys are not
            interchangeable across tenants).
        artifact_id: Resolved project/artifact id.
        version_record_id: Resolved revision UUID.
        target: Requested emitter/format key.
        options: Normalized emit options folded into the snapshot.
        emitter_version: Target emitter implementation version.
        registry_version: Capability-registry contract version.
        apiome_version: Apiome package version folded into the snapshot.

    Returns:
        An immutable tuple suitable as an :class:`OrderedDict` key.
    """
    return (
        tenant_id,
        artifact_id,
        version_record_id,
        target,
        options_digest(options),
        emitter_version,
        registry_version,
        apiome_version,
    )


class ManifestCache:
    """Thread-safe TTL + LRU cache of :class:`ProjectionManifest` values."""

    def __init__(
        self,
        *,
        ttl_seconds: float = MANIFEST_CACHE_TTL_SECONDS,
        max_entries: int = MANIFEST_CACHE_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._store: OrderedDict[ManifestCacheKey, tuple[float, ProjectionManifest]] = OrderedDict()

    def get(self, key: ManifestCacheKey) -> Optional[ProjectionManifest]:
        """Return a cached manifest when present and unexpired; otherwise ``None``."""
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, manifest = entry
            if expires_at <= now:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return manifest

    def put(self, key: ManifestCacheKey, manifest: ProjectionManifest) -> None:
        """Insert or refresh ``manifest`` under ``key``, enforcing TTL and LRU caps."""
        expires_at = time.monotonic() + self._ttl
        with self._lock:
            if key in self._store:
                del self._store[key]
            self._store[key] = (expires_at, manifest)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """Drop every entry (tests reset process state between cases)."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


#: Process-wide manifest cache used by the evidence route.
manifest_cache = ManifestCache()
