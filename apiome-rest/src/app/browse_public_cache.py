"""Process cache for the public Browse directory (DBP-1.16, #7199).

``GET /v1/browse/tenants`` is anonymous, and every call counted the whole public catalog
(:meth:`Database.get_public_browse_directory_stats`) and aggregated every published public version
by tenant (:meth:`Database.list_public_browse_tenants`,
:meth:`Database.get_public_browse_tenant_facets`). None of that depends on who asks, so each API
instance keeps the answers for ``BROWSE_PUBLIC_CACHE_TTL_SECONDS``:

* the directory statistics, under one key;
* each tenant-list window and each facet count, keyed by the query's own parameters.

Only successful reads are stored: a database error propagates and the next request reads again.
A publish, unpublish or delete shows up within one interval; ``0`` turns the cache off. The route
states the same interval in its ``Cache-Control`` header (:func:`cache_control_header`), so a
client or proxy in front of the API may reuse a response for as long as this instance would.

The cache is per process. It reuses :class:`app.authz_cache.TtlCache`, a thread-safe map whose
entries expire; values are returned by reference and must not be mutated by callers.
"""

from __future__ import annotations

from typing import Callable, Hashable, TypeVar

from .authz_cache import TtlCache
from .config import settings

T = TypeVar("T")

#: Longest interval the setting may ask for, in seconds. The directory is public and changes when
#: someone publishes; five minutes is the oldest answer the ticket allows.
MAX_TTL_SECONDS = 300.0


def ttl_seconds() -> float:
    """The cache interval in seconds: the setting, clamped to ``0`` … :data:`MAX_TTL_SECONDS`.

    Returns:
        ``0.0`` when the cache is off (a setting of ``0`` or less, or one that is not a number).
    """
    try:
        value = float(settings.browse_public_cache_ttl_seconds or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(value, MAX_TTL_SECONDS))


_cache = TtlCache(
    ttl_seconds=ttl_seconds,
    max_entries=lambda: settings.browse_public_cache_max_entries,
)


def cached(key: Hashable, load: Callable[[], T]) -> T:
    """Return the value cached under ``key``, loading and storing it on a miss.

    Two requests that miss at the same moment both load; the read is idempotent, so the only cost
    is one extra query per interval, and no lock is held across a database call.

    Args:
        key: Identifies the read and its arguments. It must be hashable.
        load: Reads the value from the database. Its exception propagates and nothing is stored.

    Returns:
        The cached or freshly loaded value.
    """
    hit = _cache.get(key)
    if hit is not None:
        value = hit[0]
        return value  # type: ignore[no-any-return]
    value = load()
    # Stored in a one-item tuple so that a legitimately empty or ``None`` value is a hit too
    # (``TtlCache.get`` returns ``None`` for "missing").
    _cache.put(key, (value,))
    return value


def cache_control_header() -> str:
    """The ``Cache-Control`` value for an anonymous directory response.

    Returns:
        ``public, max-age=<interval>`` while the cache is on, so a shared cache may reuse the
        response for as long as this instance would; ``no-store`` when the cache is off, because
        the operator has asked for every read to be current.
    """
    ttl = int(ttl_seconds())
    return f"public, max-age={ttl}" if ttl > 0 else "no-store"


def invalidate_all() -> None:
    """Drop every cached directory value (tests; an operator-triggered reset)."""
    _cache.clear()


def cache_size() -> int:
    """How many values are cached (for tests)."""
    return len(_cache)


__all__ = [
    "MAX_TTL_SECONDS",
    "cache_control_header",
    "cache_size",
    "cached",
    "invalidate_all",
    "ttl_seconds",
]
