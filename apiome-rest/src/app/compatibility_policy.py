"""Compatibility mode policy vocabulary and resolution (XPC-4.5, #5749).

XPC-4.1–4.4 made the Avro, JSON Schema, Protobuf and AsyncAPI classifiers grade a change by
**compatibility mode** and, for Protobuf, by **buf breaking category**. This module is the one
place that says which values exist, what a tenant gets by default, and how a request's explicit
values combine with the project's policy:

=============================  =======================================  ==============
Setting                        Values                                   Default
=============================  =======================================  ==============
``compatibility_mode``         ``BACKWARD`` ``FORWARD`` ``FULL`` ``NONE``  ``BACKWARD``
``compatibility_transitive``   ``true`` / ``false``                     ``false``
``protobuf_breaking_category`` ``WIRE`` ``WIRE_JSON`` ``PACKAGE`` ``FILE``  ``WIRE_JSON``
=============================  =======================================  ==============

The policy is a style-guide setting (V382), resolved through the GOV-1.4 guide chain (project
assignment → tenant assignment → tenant default) beside the CTG-3.4 breaking-publish level, and
frozen into ``style_guide_revisions.policy`` on every guide edit.

``NONE`` is Confluent's "no compatibility checking": changes are still listed with their rule
ids, but none of them fails the mode. The ``_TRANSITIVE`` mode names (``FULL_TRANSITIVE``) are
accepted as input and split into the mode and ``transitive=True``.

Deliberately dependency-free apart from the database handle used by :func:`resolve_policy`, so
the style-guide editor can normalize values without importing the classifiers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "MODE_BACKWARD",
    "MODE_FORWARD",
    "MODE_FULL",
    "MODE_NONE",
    "COMPATIBILITY_MODES",
    "PROTOBUF_CATEGORIES",
    "DEFAULT_COMPATIBILITY_MODE",
    "DEFAULT_COMPATIBILITY_TRANSITIVE",
    "DEFAULT_PROTOBUF_CATEGORY",
    "CompatibilityPolicy",
    "PolicyValueError",
    "normalize_compatibility_mode",
    "normalize_protobuf_category",
    "parse_mode",
    "parse_category",
    "policy_from_guide",
    "resolve_policy",
    "effective_policy",
    "requested_settings",
]

logger = logging.getLogger(__name__)

MODE_BACKWARD = "BACKWARD"
MODE_FORWARD = "FORWARD"
MODE_FULL = "FULL"
MODE_NONE = "NONE"

#: Closed vocabulary, mirroring the V382 ``style_guides_compatibility_mode_ck`` check.
COMPATIBILITY_MODES: Tuple[str, ...] = (MODE_BACKWARD, MODE_FORWARD, MODE_FULL, MODE_NONE)

#: The four ``buf breaking`` categories, least strict first, mirroring the V382
#: ``style_guides_protobuf_breaking_category_ck`` check.
PROTOBUF_CATEGORIES: Tuple[str, ...] = ("WIRE", "WIRE_JSON", "PACKAGE", "FILE")

#: Confluent's default level, and the line the classifiers grade at without a policy.
DEFAULT_COMPATIBILITY_MODE = MODE_BACKWARD
DEFAULT_COMPATIBILITY_TRANSITIVE = False
#: gRPC services carry binary and transcoded JSON traffic, so JSON keys count by default.
DEFAULT_PROTOBUF_CATEGORY = "WIRE_JSON"

_TRANSITIVE_SUFFIX = "_TRANSITIVE"


class PolicyValueError(ValueError):
    """A request named a mode or category outside the closed vocabulary."""


@dataclass(frozen=True)
class CompatibilityPolicy:
    """The mode, transitivity and Protobuf category a comparison is graded under.

    Attributes:
        mode: One of :data:`COMPATIBILITY_MODES`.
        transitive: Whether earlier revisions are checked too, not only the base.
        category: One of :data:`PROTOBUF_CATEGORIES`.
    """

    mode: str = DEFAULT_COMPATIBILITY_MODE
    transitive: bool = DEFAULT_COMPATIBILITY_TRANSITIVE
    category: str = DEFAULT_PROTOBUF_CATEGORY

    @property
    def mode_name(self) -> str:
        """The Confluent level name, e.g. ``FULL_TRANSITIVE`` (``NONE`` has no transitive form)."""
        if self.transitive and self.mode != MODE_NONE:
            return f"{self.mode}{_TRANSITIVE_SUFFIX}"
        return self.mode

    def as_settings(self) -> Dict[str, Any]:
        """Serialize to the camelCase style-guide settings shape."""
        return {
            "compatibilityMode": self.mode,
            "compatibilityTransitive": self.transitive,
            "protobufBreakingCategory": self.category,
        }


def parse_mode(raw: Any) -> Tuple[Optional[str], Optional[bool]]:
    """Parse a requested mode, splitting a ``_TRANSITIVE`` suffix off.

    Args:
        raw: A mode name in any case (``forward``, ``FULL_TRANSITIVE``), or ``None`` / blank.

    Returns:
        ``(mode, transitive)``: the plain mode (``None`` when ``raw`` is blank) and ``True`` when
        the name carried ``_TRANSITIVE`` (``None`` otherwise, so the caller's own value stands).

    Raises:
        PolicyValueError: If ``raw`` names no mode, or is ``NONE_TRANSITIVE``.
    """
    value = str(raw or "").strip().upper()
    if not value:
        return None, None
    transitive: Optional[bool] = None
    if value.endswith(_TRANSITIVE_SUFFIX):
        value = value[: -len(_TRANSITIVE_SUFFIX)]
        transitive = True
    if value not in COMPATIBILITY_MODES or (transitive and value == MODE_NONE):
        raise PolicyValueError(
            f"Unknown compatibility mode {raw!r}; expected one of "
            f"{', '.join(COMPATIBILITY_MODES)} (optionally with {_TRANSITIVE_SUFFIX})"
        )
    return value, transitive


def parse_category(raw: Any) -> Optional[str]:
    """Parse a requested Protobuf category.

    Args:
        raw: A category name in any case, or ``None`` / blank.

    Returns:
        The upper-cased category, or ``None`` when ``raw`` is blank.

    Raises:
        PolicyValueError: If ``raw`` names no category.
    """
    value = str(raw or "").strip().upper()
    if not value:
        return None
    if value not in PROTOBUF_CATEGORIES:
        raise PolicyValueError(
            f"Unknown Protobuf breaking category {raw!r}; expected one of "
            f"{', '.join(PROTOBUF_CATEGORIES)}"
        )
    return value


def normalize_compatibility_mode(raw: Any) -> str:
    """Coerce a stored mode into the closed vocabulary, falling back to the default.

    Args:
        raw: A DB column value or ``None``.

    Returns:
        One of :data:`COMPATIBILITY_MODES`; unknown values yield :data:`DEFAULT_COMPATIBILITY_MODE`.
    """
    try:
        mode, _ = parse_mode(raw)
    except PolicyValueError:
        return DEFAULT_COMPATIBILITY_MODE
    return mode or DEFAULT_COMPATIBILITY_MODE


def normalize_protobuf_category(raw: Any) -> str:
    """Coerce a stored category into the closed vocabulary, falling back to the default.

    Args:
        raw: A DB column value or ``None``.

    Returns:
        One of :data:`PROTOBUF_CATEGORIES`; unknown values yield :data:`DEFAULT_PROTOBUF_CATEGORY`.
    """
    try:
        return parse_category(raw) or DEFAULT_PROTOBUF_CATEGORY
    except PolicyValueError:
        return DEFAULT_PROTOBUF_CATEGORY


def policy_from_guide(guide: Optional[Dict[str, Any]]) -> CompatibilityPolicy:
    """Read the policy off a style-guide row.

    Args:
        guide: A ``style_guides`` row (or ``None``).

    Returns:
        The guide's :class:`CompatibilityPolicy`; defaults for a missing guide or column.
    """
    if not isinstance(guide, dict):
        return CompatibilityPolicy()
    return CompatibilityPolicy(
        mode=normalize_compatibility_mode(guide.get("compatibility_mode")),
        transitive=bool(guide.get("compatibility_transitive") or False),
        category=normalize_protobuf_category(guide.get("protobuf_breaking_category")),
    )


def resolve_policy(db: Any, tenant_id: str, project_id: Optional[str]) -> CompatibilityPolicy:
    """Resolve a project's policy from its assigned style guide (GOV-1.4 chain). Never raises.

    Args:
        db: Database handle exposing ``get_assigned_style_guide``.
        tenant_id: The tenant whose guide chain applies.
        project_id: The owning project, enabling a project-level guide to win.

    Returns:
        The policy; the defaults when there is no guide or the lookup fails, so a broken lookup
        never makes a check stricter.
    """
    try:
        return policy_from_guide(db.get_assigned_style_guide(tenant_id, project_id))
    except Exception:  # noqa: BLE001 - policy resolution must never break a diff or publish
        logger.warning(
            "Compatibility policy resolution failed for tenant %s (project %s); using defaults",
            tenant_id,
            project_id,
            exc_info=True,
        )
        return CompatibilityPolicy()


def effective_policy(
    policy: CompatibilityPolicy,
    *,
    mode: Any = None,
    transitive: Optional[bool] = None,
    category: Any = None,
) -> CompatibilityPolicy:
    """Overlay a request's explicit values on the project's policy.

    Args:
        policy: The resolved project policy (the defaults).
        mode: The requested mode, or ``None`` to keep the policy's. A ``_TRANSITIVE`` name also
            sets ``transitive`` unless ``transitive`` is given explicitly.
        transitive: The requested transitivity, or ``None`` to keep the policy's.
        category: The requested Protobuf category, or ``None`` to keep the policy's.

    Returns:
        The policy the comparison runs under.

    Raises:
        PolicyValueError: For a mode or category outside the vocabulary.
    """
    parsed_mode, implied_transitive = parse_mode(mode)
    parsed_category = parse_category(category)
    if transitive is None:
        transitive = implied_transitive
    return CompatibilityPolicy(
        mode=parsed_mode or policy.mode,
        transitive=policy.transitive if transitive is None else bool(transitive),
        category=parsed_category or policy.category,
    )


def requested_settings(*, mode: Any = None, transitive: Optional[bool] = None, category: Any = None) -> Dict[str, bool]:
    """Say which settings a request named, for ``evaluatedUnder.source``.

    Args:
        mode: The requested mode (a ``_TRANSITIVE`` name also names ``transitive``).
        transitive: The requested transitivity.
        category: The requested Protobuf category.

    Returns:
        ``{"mode": bool, "transitive": bool, "category": bool}``.
    """
    mode_text = str(mode or "").strip().upper()
    return {
        "mode": bool(mode_text),
        "transitive": transitive is not None or mode_text.endswith(_TRANSITIVE_SUFFIX),
        "category": bool(str(category or "").strip()),
    }
