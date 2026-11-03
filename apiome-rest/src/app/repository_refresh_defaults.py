"""Workspace refresh defaults for repositories (RAR-6.5, #3542).

A workspace can store the refresh settings a new repository starts from: the cadence (RAR-3.1),
the conflict policy (RAR-4.5) and the auto-refresh switch (RAR-3.3). A repository follows each
default until that one setting is changed on it (its ``inherits_*`` flag turns FALSE); changing
the defaults can re-apply them to the settings repositories still follow. Storage and the
re-apply are in :class:`app.database.Database` (``tenant_repository_refresh_defaults``, V351);
this module resolves what the defaults are when a workspace has stored none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .repository_conflict_policy import DEFAULT_CONFLICT_POLICY, parse_conflict_policy
from .repository_refresh_cadence import DEFAULT_REFRESH_INTERVAL_SECONDS

__all__ = ["BUILT_IN_REFRESH_DEFAULTS", "REFRESH_SETTINGS", "RefreshDefaults", "resolve_refresh_defaults"]

#: The settings a repository can follow the workspace default for (``use_workspace_defaults``).
REFRESH_SETTINGS = ("refresh_interval", "conflict_policy", "auto_refresh")


@dataclass(frozen=True)
class RefreshDefaults:
    """The refresh settings a new repository starts from.

    Attributes:
        refresh_interval_seconds: The cadence.
        conflict_policy: The conflict policy token (``hold-for-review`` …).
        auto_refresh_enabled: Whether auto-refresh is on.
    """

    refresh_interval_seconds: int
    conflict_policy: str
    auto_refresh_enabled: bool


#: The values a workspace without stored defaults uses — the columns' own defaults (V107, V109, V235).
BUILT_IN_REFRESH_DEFAULTS = RefreshDefaults(
    refresh_interval_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS,
    conflict_policy=DEFAULT_CONFLICT_POLICY.value,
    auto_refresh_enabled=True,
)


def resolve_refresh_defaults(row: Optional[Mapping[str, Any]]) -> RefreshDefaults:
    """The workspace's defaults from its stored row, or the built-in values when it has none.

    Args:
        row: The ``tenant_repository_refresh_defaults`` row, or ``None``.

    Returns:
        The defaults; a missing or unreadable field falls back to its built-in value.
    """
    if not row:
        return BUILT_IN_REFRESH_DEFAULTS
    interval = row.get("refresh_interval_seconds")
    policy = parse_conflict_policy(row.get("refresh_conflict_policy"), default=DEFAULT_CONFLICT_POLICY)
    enabled = row.get("auto_refresh_enabled")
    return RefreshDefaults(
        refresh_interval_seconds=int(interval) if isinstance(interval, int) and interval > 0
        else BUILT_IN_REFRESH_DEFAULTS.refresh_interval_seconds,
        conflict_policy=policy.value,
        auto_refresh_enabled=bool(enabled) if enabled is not None else True,
    )
