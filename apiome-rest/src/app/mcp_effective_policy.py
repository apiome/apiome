"""MCP effective policy resolver — MTG-1.4 (#4768).

Pure function used by the MCP call-time gate (MTG-2.2) and REST
“preview effective” (MTG-3.3). Both surfaces must call this module so
admin UX and runtime never diverge.

Precedence (no ambiguity)
-------------------------

::

    effective(tool) =
        tool ∈ registry
        AND tool ∈ tenant.ceiling
        AND (
              key.mode == inherit  → tool ∈ tenant.default_enable_set
              OR key.mode == explicit → tool ∈ key.enabled_tools
            )

Checks are short-circuit AND in that order. Ceiling always applies —
an explicit key grant cannot exceed the tenant ceiling even if write-
time validation later drifts.

Tenant ``default_mode`` (how missing tool rows resolve)
-------------------------------------------------------

* ``all`` — ceiling and default enable-set are the full registry; tool
  rows are **ignored** at resolve time.
* ``inherit_registry`` — absent tool rows track the registry (in ceiling
  and default-enabled); present rows refine via ``in_ceiling`` /
  ``default_enabled``.
* ``explicit`` — only tool rows with the corresponding flag set are
  members; absent rows mean out.

Legacy / unseeded tenants
-------------------------

A missing policy snapshot (``tenant is None``) is treated as
``default_mode='all'`` — full registry ceiling and defaults — matching
V162 write-time semantics and MTG-1.5 seed expectations so live clients
are not broken before backfill.

Call flow
---------

.. code-block:: mermaid

    flowchart TD
      REQ[tools/call tool=T] --> AUTH{MCP API key?}
      AUTH -->|no| ANON[MTG-2.3 anonymous policy]
      AUTH -->|yes| LOAD[Load tenant policy + key grants]
      LOAD --> RES[MTG-1.4 effective resolver]
      RES -->|T enabled| RUN[Execute tool handler]
      RES -->|T disabled| DENY[MCP error + MTG-2.4 audit]
      LIST[tools/list] --> FULL[Return full registry — MTG-2.1]
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet, FrozenSet, List, Literal, Mapping, Optional, Sequence

from .mcp_tool_registry import mcp_tool_ids

__all__ = [
    "CapabilityMode",
    "DenyReason",
    "EffectiveToolPreview",
    "KeyCapabilitySnapshot",
    "TenantDefaultMode",
    "TenantMcpPolicySnapshot",
    "TenantToolFlags",
    "is_tool_effectively_enabled",
    "preview_effective_tools",
    "resolve_tool_effective",
    "tool_in_ceiling",
    "tool_in_default_enable_set",
]

TenantDefaultMode = Literal["all", "inherit_registry", "explicit"]
CapabilityMode = Literal["inherit", "explicit"]


class DenyReason(str, Enum):
    """Why a tool is not effectively enabled (first failing check)."""

    NOT_IN_REGISTRY = "not_in_registry"
    NOT_IN_CEILING = "not_in_ceiling"
    NOT_IN_DEFAULT_ENABLE_SET = "not_in_default_enable_set"
    NOT_IN_KEY_ENABLE_SET = "not_in_key_enable_set"
    INVALID_KEY_MODE = "invalid_key_mode"


@dataclass(frozen=True)
class TenantToolFlags:
    """Per-tool ceiling / default flags from ``tenant_mcp_policy_tools``."""

    in_ceiling: bool
    default_enabled: bool


@dataclass(frozen=True)
class TenantMcpPolicySnapshot:
    """Loaded tenant MCP policy used at resolve time.

    :param default_mode: ``tenant_mcp_policies.default_mode``.
    :param tools: Map of tool_id → flags; may be empty under ``all``.
    """

    default_mode: TenantDefaultMode
    tools: Mapping[str, TenantToolFlags]


@dataclass(frozen=True)
class KeyCapabilitySnapshot:
    """Per-key capability grants from ``mcp_api_keys``.

    :param capability_mode: ``inherit`` or ``explicit``.
    :param enabled_tools: Tool ids when mode is ``explicit``; empty under inherit.
    """

    capability_mode: CapabilityMode
    enabled_tools: AbstractSet[str]


@dataclass(frozen=True)
class EffectiveToolPreview:
    """One row of a REST/MCP effective enable-set preview."""

    tool_id: str
    enabled: bool
    deny_reason: Optional[DenyReason]


def _registry_set(registry: Optional[AbstractSet[str]]) -> FrozenSet[str]:
    if registry is None:
        return frozenset(mcp_tool_ids())
    return frozenset(registry)


def _effective_default_mode(tenant: Optional[TenantMcpPolicySnapshot]) -> TenantDefaultMode:
    if tenant is None:
        return "all"
    return tenant.default_mode


def tool_in_ceiling(
    tool_id: str,
    tenant: Optional[TenantMcpPolicySnapshot],
    *,
    registry: Optional[AbstractSet[str]] = None,
) -> bool:
    """Return True when ``tool_id`` is in the tenant ceiling (registry ∩ policy).

    Tools absent from the registry are never in the ceiling.
    """
    ids = _registry_set(registry)
    if tool_id not in ids:
        return False

    mode = _effective_default_mode(tenant)
    if mode == "all":
        return True

    flags = None if tenant is None else tenant.tools.get(tool_id)
    if mode == "inherit_registry":
        if flags is None:
            return True
        return bool(flags.in_ceiling)

    # explicit — rows are authoritative
    if flags is None:
        return False
    return bool(flags.in_ceiling)


def tool_in_default_enable_set(
    tool_id: str,
    tenant: Optional[TenantMcpPolicySnapshot],
    *,
    registry: Optional[AbstractSet[str]] = None,
) -> bool:
    """Return True when ``tool_id`` is in the tenant default enable-set.

    Does not re-check ceiling; callers AND separately (formula / DB
    already enforce defaults ⊆ ceiling).
    """
    ids = _registry_set(registry)
    if tool_id not in ids:
        return False

    mode = _effective_default_mode(tenant)
    if mode == "all":
        return True

    flags = None if tenant is None else tenant.tools.get(tool_id)
    if mode == "inherit_registry":
        if flags is None:
            return True
        return bool(flags.default_enabled)

    if flags is None:
        return False
    return bool(flags.default_enabled)


def resolve_tool_effective(
    tool_id: str,
    *,
    key: KeyCapabilitySnapshot,
    tenant: Optional[TenantMcpPolicySnapshot] = None,
    registry: Optional[AbstractSet[str]] = None,
) -> tuple[bool, Optional[DenyReason]]:
    """Resolve whether ``tool_id`` is effectively enabled for ``key``.

    :returns: ``(True, None)`` when enabled; ``(False, reason)`` otherwise.
    """
    ids = _registry_set(registry)
    if tool_id not in ids:
        return False, DenyReason.NOT_IN_REGISTRY

    if not tool_in_ceiling(tool_id, tenant, registry=ids):
        return False, DenyReason.NOT_IN_CEILING

    mode = key.capability_mode
    if mode == "inherit":
        if not tool_in_default_enable_set(tool_id, tenant, registry=ids):
            return False, DenyReason.NOT_IN_DEFAULT_ENABLE_SET
        return True, None

    if mode == "explicit":
        if tool_id not in key.enabled_tools:
            return False, DenyReason.NOT_IN_KEY_ENABLE_SET
        return True, None

    return False, DenyReason.INVALID_KEY_MODE


def is_tool_effectively_enabled(
    tool_id: str,
    *,
    key: KeyCapabilitySnapshot,
    tenant: Optional[TenantMcpPolicySnapshot] = None,
    registry: Optional[AbstractSet[str]] = None,
) -> bool:
    """Boolean gate used by MCP ``tools/call`` middleware (MTG-2.2)."""
    enabled, _ = resolve_tool_effective(
        tool_id, key=key, tenant=tenant, registry=registry
    )
    return enabled


def preview_effective_tools(
    *,
    key: KeyCapabilitySnapshot,
    tenant: Optional[TenantMcpPolicySnapshot] = None,
    registry: Optional[Sequence[str]] = None,
) -> List[EffectiveToolPreview]:
    """REST/admin preview: effective enabled flag for every registry tool.

    Uses the same resolver as ``is_tool_effectively_enabled`` so preview
    rows match MCP gate decisions bit-for-bit.
    """
    order: Sequence[str] = (
        tuple(registry) if registry is not None else tuple(mcp_tool_ids())
    )
    ids = frozenset(order)
    rows: List[EffectiveToolPreview] = []
    for tool_id in order:
        enabled, reason = resolve_tool_effective(
            tool_id, key=key, tenant=tenant, registry=ids
        )
        rows.append(
            EffectiveToolPreview(
                tool_id=tool_id,
                enabled=enabled,
                deny_reason=reason,
            )
        )
    return rows
