"""
Configurable refresh cadence for repository auto-refresh (RAR-3.1, #3522).

The auto-refresh sweep used a hardcoded, global ``await asyncio.sleep(5)``
(``main.py:179``); "refresh after a few minutes" could not be expressed per
repository. RAR-3.1 stores a per-repo ``refresh_interval_seconds`` (default 300)
on ``apiome.tenant_repositories`` and adds a ``last_refreshed_at`` anchor, gated by a
global floor (``APIOME_REFRESH_MIN_INTERVAL``, default 60s).

This module is the pure, side-effect-free policy layer the DAO and the sweep
(RAR-3.2) build on:

* :func:`resolve_refresh_interval` applies the default and clamps sub-floor
  values to the floor, logging a warning when it clamps.
* :func:`is_repository_due` decides whether a repo is due for a refresh from its
  ``last_refreshed_at`` and effective interval.

Keeping the policy here (rather than inline in SQL or the sweep loop) means the
clamping and due rules are deterministic and unit-testable, and the floor can be
tuned per environment without a migration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

#: Default per-repo cadence when a repository has no explicit interval (~5 min).
DEFAULT_REFRESH_INTERVAL_SECONDS = 300
#: Default global floor below which a configured interval is clamped.
DEFAULT_MIN_REFRESH_INTERVAL_SECONDS = 60

_log = logging.getLogger(__name__)


def resolve_refresh_interval(
    configured_seconds: Optional[int],
    *,
    floor_seconds: int = DEFAULT_MIN_REFRESH_INTERVAL_SECONDS,
    default_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS,
) -> int:
    """Resolve a repository's effective refresh interval in seconds (RAR-3.1).

    Applies the default when no per-repo value is configured, then clamps the
    result up to the floor so a too-aggressive cadence cannot hammer providers.
    A clamp (or a non-positive configured value, which is treated as "unset")
    is logged at WARNING so operators can see it took effect.

    The floor itself is clamped to at least 1 second so a misconfigured
    ``floor_seconds`` of 0 or negative can never disable the guard entirely.

    Args:
        configured_seconds: The per-repo ``refresh_interval_seconds`` value, or
            None when the repository has no explicit cadence. Non-positive values
            are treated as unset and fall back to ``default_seconds``.
        floor_seconds: The global minimum interval; results below it are clamped.
        default_seconds: The interval used when ``configured_seconds`` is unset.

    Returns:
        The effective interval in seconds (always >= max(floor, 1)).
    """
    floor = floor_seconds if floor_seconds >= 1 else 1

    if configured_seconds is None or configured_seconds <= 0:
        interval = default_seconds
    else:
        interval = configured_seconds

    if interval < floor:
        _log.warning(
            "refresh interval %ss is below the floor %ss; clamping to %ss",
            interval,
            floor,
            floor,
        )
        return floor
    return interval


def _as_utc(value: Optional[object]) -> Optional[datetime]:
    """Coerce a timestamp to a timezone-aware UTC ``datetime`` or ``None``.

    Accepts an aware/naive :class:`datetime` or an ISO-8601 string (including a
    trailing ``Z``). Naive datetimes are assumed UTC. Anything unparseable yields
    ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_repository_due(
    *,
    last_refreshed_at: Optional[object],
    interval_seconds: int,
    now: Optional[object] = None,
) -> bool:
    """Return True when a repository is due for an auto-refresh (RAR-3.1).

    A repository is due when it has never been refreshed
    (``last_refreshed_at is None``) or when at least ``interval_seconds`` have
    elapsed since its last refresh, i.e. ``now - last_refreshed_at >= interval``.

    Args:
        last_refreshed_at: The repository's ``last_refreshed_at`` (datetime / ISO
            string / None). None means never refreshed -> due.
        interval_seconds: The effective interval from
            :func:`resolve_refresh_interval`.
        now: The reference "current" time (datetime / ISO string); defaults to the
            current UTC time when omitted.

    Returns:
        True when the repository should be refreshed now.
    """
    last = _as_utc(last_refreshed_at)
    if last is None:
        return True
    current = _as_utc(now) or datetime.now(timezone.utc)
    elapsed = (current - last).total_seconds()
    return elapsed >= interval_seconds
