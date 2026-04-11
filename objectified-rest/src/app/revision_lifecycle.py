"""
Schema **revision lifecycle** tags (#739): semantic classification vs named release pointers (#501).

Stored in ``odb.versions.metadata.lifecycle`` (API camelCase ``lifecycle``) with values:
``stable``, ``beta``, ``deprecated``, ``archived``. Aligns deprecation with ``#507`` when
lifecycle is ``deprecated``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .revision_deprecation import coerce_metadata, is_revision_deprecated, merge_version_metadata

LIFECYCLE_STABLE = "stable"
LIFECYCLE_BETA = "beta"
LIFECYCLE_DEPRECATED = "deprecated"
LIFECYCLE_ARCHIVED = "archived"

LIFECYCLE_VALUES = frozenset(
    {
        LIFECYCLE_STABLE,
        LIFECYCLE_BETA,
        LIFECYCLE_DEPRECATED,
        LIFECYCLE_ARCHIVED,
    }
)

# Allowed transitions (excluding same-state). Archived is terminal unless tenant admin exits explicitly.
_TRANSITIONS: Dict[str, frozenset[str]] = {
    LIFECYCLE_STABLE: frozenset({LIFECYCLE_BETA, LIFECYCLE_DEPRECATED, LIFECYCLE_ARCHIVED}),
    LIFECYCLE_BETA: frozenset({LIFECYCLE_STABLE, LIFECYCLE_DEPRECATED, LIFECYCLE_ARCHIVED}),
    LIFECYCLE_DEPRECATED: frozenset({LIFECYCLE_STABLE, LIFECYCLE_BETA, LIFECYCLE_ARCHIVED}),
    LIFECYCLE_ARCHIVED: frozenset(),
}


def normalize_lifecycle_token(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    t = raw.strip().lower()
    if t in LIFECYCLE_VALUES:
        return t
    return None


def effective_lifecycle(metadata: Any) -> str:
    """Effective lifecycle for display and filtering: explicit ``metadata.lifecycle``, else infer from ``deprecated`` (#507), else stable."""
    m = coerce_metadata(metadata)
    explicit = normalize_lifecycle_token(m.get("lifecycle"))
    if explicit is not None:
        return explicit
    if is_revision_deprecated(metadata):
        return LIFECYCLE_DEPRECATED
    return LIFECYCLE_STABLE


def validate_lifecycle_transition(
    old: str,
    new: str,
    *,
    allow_exit_archived: bool = False,
) -> None:
    if old == new:
        return
    if old == LIFECYCLE_ARCHIVED:
        if allow_exit_archived and new in (
            LIFECYCLE_STABLE,
            LIFECYCLE_BETA,
            LIFECYCLE_DEPRECATED,
        ):
            return
        raise ValueError("Invalid lifecycle transition: archived revisions are terminal (tenant admins may change lifecycle to un-archive)")
    allowed = _TRANSITIONS.get(old, frozenset())
    if new not in allowed:
        raise ValueError(f"Invalid lifecycle transition: {old} -> {new}")


def prepare_version_metadata_update(
    existing: Any,
    patch: Optional[Dict[str, Any]],
    *,
    allow_exit_archived: bool = False,
) -> Dict[str, Any]:
    """
    Shallow-merge ``patch`` into ``existing`` metadata, validate lifecycle vocabulary and transitions,
    sync ``deprecated`` with ``#507`` when lifecycle is ``deprecated`` or leaving deprecated.
    """
    if patch is None:
        return coerce_metadata(existing)

    base = coerce_metadata(existing)
    old_lc = effective_lifecycle(base)

    if "lifecycle" in patch:
        token = patch.get("lifecycle")
        if token is None:
            raise ValueError("lifecycle cannot be null; omit the key to keep current effective lifecycle")
        norm = normalize_lifecycle_token(token)
        if norm is None:
            raise ValueError(
                f"Invalid lifecycle value; expected one of: {', '.join(sorted(LIFECYCLE_VALUES))}",
            )

    merged = merge_version_metadata(existing, patch)
    m = coerce_metadata(merged)

    # Clearing deprecation (#507) without a lifecycle patch should leave governance consistent.
    if patch.get("deprecated") is False and old_lc == LIFECYCLE_DEPRECATED and "lifecycle" not in patch:
        m["lifecycle"] = LIFECYCLE_STABLE

    if "lifecycle" in patch and patch.get("lifecycle") is not None:
        new_lc = normalize_lifecycle_token(m.get("lifecycle"))
        assert new_lc is not None
    else:
        new_lc = effective_lifecycle(m)

    validate_lifecycle_transition(old_lc, new_lc, allow_exit_archived=allow_exit_archived)

    m["lifecycle"] = new_lc

    if new_lc == LIFECYCLE_DEPRECATED:
        m["deprecated"] = True
    elif new_lc in (LIFECYCLE_STABLE, LIFECYCLE_BETA):
        if old_lc == LIFECYCLE_DEPRECATED:
            m["deprecated"] = False

    return m


def sql_effective_lifecycle_expr(alias: str = "v") -> str:
    """SQL expression matching :func:`effective_lifecycle` for server-side filters."""
    # Explicit lifecycle wins when set and valid; else infer deprecated from flags; else stable.
    return f"""(
      CASE
        WHEN NULLIF(trim(COALESCE({alias}.metadata->>'lifecycle', '')), '') IS NOT NULL
             AND lower(trim({alias}.metadata->>'lifecycle')) IN ('stable', 'beta', 'deprecated', 'archived')
          THEN lower(trim({alias}.metadata->>'lifecycle'))
        WHEN COALESCE({alias}.metadata->>'deprecated', '') IN ('true', '1', 'True', 'yes')
          OR ({alias}.metadata @> '{{"deprecated": true}}'::jsonb)
          THEN 'deprecated'
        ELSE 'stable'
      END
    )"""
