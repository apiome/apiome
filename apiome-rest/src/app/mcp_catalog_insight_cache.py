"""Short per-tenant cache of the MCP catalog insight (DBP-1.17, #7200).

``GET /v1/mcp/{tenant}/insight/catalog`` aggregates a tenant's whole catalog. The dashboard that
reads it is opened, tabbed away from and reloaded far more often than the catalog changes, so each
API instance keeps a tenant's answer for ``MCP_CATALOG_INSIGHT_CACHE_TTL_SECONDS`` (default 30,
at most 300; ``0`` turns the cache off).

* The key is the tenant id, so one tenant never sees another's numbers.
* Only a successful read is stored; a database error propagates and the next request reads again.
* Nothing invalidates an entry early: a discovery, publish or delete shows on the dashboard within
  one interval. The catalog grid, the facets and every endpoint page are not cached.
* A stored value is copied on the way in and on the way out, so a caller that changes the dict it
  was given cannot change what the next caller gets.

It reuses :class:`app.authz_cache.TtlCache` (a thread-safe map whose entries expire).
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict

from .authz_cache import TtlCache
from .config import settings

#: Longest interval the setting may ask for, in seconds.
MAX_TTL_SECONDS = 300.0


def ttl_seconds() -> float:
    """The cache interval in seconds: the setting, clamped to ``0`` … :data:`MAX_TTL_SECONDS`.

    Returns:
        ``0.0`` when the cache is off (a setting of ``0`` or less, or one that is not a number).
    """
    try:
        value = float(settings.mcp_catalog_insight_cache_ttl_seconds or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(value, MAX_TTL_SECONDS))


_cache = TtlCache(
    ttl_seconds=ttl_seconds,
    max_entries=lambda: settings.mcp_catalog_insight_cache_max_entries,
)


def cached_insight(tenant_id: str, load: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Return a tenant's catalog insight, reading it on a miss.

    Args:
        tenant_id: The tenant whose catalog the insight describes; the cache key.
        load: Reads the insight from the database
            (:meth:`app.database.Database.get_mcp_catalog_insight`). Its exception propagates and
            nothing is stored.

    Returns:
        The insight — the caller's own copy.
    """
    key = str(tenant_id)
    hit = _cache.get(key)
    if hit is not None:
        return copy.deepcopy(hit)
    value = load()
    _cache.put(key, copy.deepcopy(value))
    return value


def invalidate_all() -> None:
    """Drop every cached insight (tests; an operator-triggered reset)."""
    _cache.clear()


def cache_size() -> int:
    """How many tenants' insights are cached (for tests)."""
    return len(_cache)


__all__ = ["MAX_TTL_SECONDS", "cache_size", "cached_insight", "invalidate_all", "ttl_seconds"]
