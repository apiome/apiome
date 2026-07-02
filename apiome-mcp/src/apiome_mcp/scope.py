"""MCP API key read scope stored in ``apiome.mcp_api_keys.scope_json`` (#3001).

Persisted JSON shape::

    {"tenants": ["<tenant_uuid>", ...], "projects": ["<project_uuid>", ...]}

Each list holds string identifiers (typically UUIDs as stored by the platform).

**Semantics**

- **Public** — both lists empty: :meth:`Scope.allows` permits any tenant/project
  pair passed in (subject to other product rules such as row visibility).
- **Tenant-limited** — ``tenants`` non-empty: the resource tenant id must be a
  member of ``tenants``.
- **Project-limited** — ``projects`` non-empty: the resource project id must be
  provided and be a member of ``projects``.

Unknown JSON keys are ignored. Missing ``tenants`` / ``projects`` keys behave
like empty lists. Non-dict or structurally invalid ``scope_json`` values yield a
**deny-all** scope (``deny_all=True``) and emit a ``WARNING`` log entry so that
mis-scoped keys are detected promptly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


def _coerce_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


@dataclass(frozen=True)
class Scope:
    """Declared read scope for an MCP API key (mirrors ``scope_json``).

    ``tenants`` and ``projects`` are stored as immutable tuples.  Pass lists at
    construction time — they are coerced to tuples automatically.  This prevents
    accidental in-place mutation of a ``frozen=True`` dataclass whose fields
    would otherwise be mutable lists.
    """

    tenants: tuple[str, ...] = field(default_factory=tuple)
    projects: tuple[str, ...] = field(default_factory=tuple)
    deny_all: bool = False

    def __post_init__(self) -> None:
        """Coerce list inputs to tuples so instances are truly immutable."""
        if isinstance(self.tenants, list):
            object.__setattr__(self, "tenants", tuple(self.tenants))
        if isinstance(self.projects, list):
            object.__setattr__(self, "projects", tuple(self.projects))

    def allows(self, tenant: str, project: str | None = None) -> bool:
        """Return True if reading *tenant* / *project* is allowed by this scope."""
        if self.deny_all:
            return False
        if self.tenants and tenant not in self.tenants:
            return False
        if self.projects:
            if project is None or project not in self.projects:
                return False
        return True

    def to_json_dict(self) -> dict[str, list[str]]:
        """Serialize for JSONB (stable keys for issuance and migrations)."""
        return {"tenants": list(self.tenants), "projects": list(self.projects)}


def parse_scope_json(raw: Any) -> Scope:
    """Build a :class:`Scope` from ``scope_json`` (database value or plain dict).

    Returns a **deny-all** :class:`Scope` (``deny_all=True``) and logs a
    ``WARNING`` for any structurally invalid payload (non-dict, or ``tenants``/
    ``projects`` present but not a list).  ``None`` and ``{}`` both yield a
    public (allow-all) scope — they are valid "no restriction" shapes.
    """
    if raw is None:
        return Scope()
    if isinstance(raw, Scope):
        return raw
    if not isinstance(raw, dict):
        _log.warning(
            "scope_json has unexpected type %s; denying all access",
            type(raw).__name__,
        )
        return Scope(deny_all=True)

    tenants_raw = raw.get("tenants")
    projects_raw = raw.get("projects")

    if tenants_raw is not None and not isinstance(tenants_raw, list):
        _log.warning(
            "scope_json 'tenants' field is %s, expected list; denying all access",
            type(tenants_raw).__name__,
        )
        return Scope(deny_all=True)

    if projects_raw is not None and not isinstance(projects_raw, list):
        _log.warning(
            "scope_json 'projects' field is %s, expected list; denying all access",
            type(projects_raw).__name__,
        )
        return Scope(deny_all=True)

    return Scope(
        tenants=_coerce_str_tuple(tenants_raw) if tenants_raw is not None else (),
        projects=_coerce_str_tuple(projects_raw) if projects_raw is not None else (),
    )
