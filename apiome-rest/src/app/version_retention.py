"""Version retention for live refresh — MFI-31.5 (#4402).

A daily refresh of a churning endpoint (MFI-31.2) adds a version every day. Each catalog item's
refresh setting keeps the newest ``keep_versions`` (default :data:`DEFAULT_KEEP_VERSIONS`) of the
versions a live refresh created; older ones are **pruned** — soft-deleted (``deleted_at``) and
stamped ``pruned_at`` (V336) — after each refresh-created version, unless they are **protected**:

* tagged (``version_tags``);
* the source of a conversion (``conversion_provenance.source_version_id``);
* a version whose drift was graded **breaking** (MFI-31.3), and the version it was compared with;
* a locked revision (``revision_locked``);
* the item's newest version.

Only versions a live refresh created count (their provenance carries ``refreshTrigger``, sweep or
manual); a version imported by hand is never pruned and does not count toward the N.

**Gaps.** A read or diff of a pruned version answers HTTP 410 with code ``version-pruned``
(:func:`raise_if_pruned`) instead of a bare 404, and :func:`nearest_live_earlier_version` gives the
version a diff can fall back to — the drift "What changed" panel compares against it.

Pruning is best-effort (:func:`prune_refresh_versions_safely`): a retention failure never fails the
refresh that triggered it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

_logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_PRUNED",
    "CODE_VERSION_PRUNED",
    "DEFAULT_KEEP_VERSIONS",
    "MAX_KEEP_VERSIONS",
    "MIN_KEEP_VERSIONS",
    "nearest_live_earlier_version",
    "plan_pruning",
    "protected_version_ids",
    "prune_refresh_versions",
    "prune_refresh_versions_safely",
    "pruned_version",
    "raise_if_pruned",
]

#: Refresh-created versions kept per item, by default and at the extremes.
DEFAULT_KEEP_VERSIONS = 50
MIN_KEEP_VERSIONS = 1
MAX_KEEP_VERSIONS = 1000

#: The refusal code of a read or diff of a pruned version (HTTP 410).
CODE_VERSION_PRUNED = "version-pruned"

#: Workflow-audit action for one pruning pass.
AUDIT_PRUNED = "catalog.refresh.versions_pruned"


def plan_pruning(refresh_versions: Sequence[Mapping[str, Any]], keep: int, protected: Iterable[str]) -> List[str]:
    """Which refresh-created versions to prune.

    Pure: the newest ``keep`` refresh-created versions stay; every older one goes unless it is
    protected. Protected versions do not extend the N — a tagged version among the newest N is one
    of them.

    Args:
        refresh_versions: The item's live refresh-created versions, newest first (``id``).
        keep: How many to keep (clamped to 1–1000).
        protected: Version ids that are always kept.

    Returns:
        The version ids to prune, newest first.
    """
    keep = max(MIN_KEEP_VERSIONS, min(MAX_KEEP_VERSIONS, int(keep)))
    guard: Set[str] = {str(v) for v in protected}
    return [str(row["id"]) for row in list(refresh_versions)[keep:] if str(row["id"]) not in guard]


def _refresh_versions(db: Any, tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    """The item's live versions a live refresh created, newest first."""
    rows = db.execute_query(
        """
        SELECT v.id, v.version_id, v.created_at
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.project_id = %s::uuid AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
          AND v.format_metadata ? 'refreshTrigger'
        ORDER BY v.created_at DESC, v.id DESC
        """,
        (project_id, tenant_id),
    )
    return [dict(row) for row in rows]


def protected_version_ids(db: Any, project_id: str) -> Set[str]:
    """The item's versions that are always kept (see the module docstring)."""
    rows = db.execute_query(
        """
        SELECT t.version_id AS id FROM apiome.version_tags t WHERE t.project_id = %s::uuid
        UNION
        SELECT c.source_version_id FROM apiome.conversion_provenance c
        WHERE c.source_project_id = %s::uuid AND c.source_version_id IS NOT NULL
        UNION
        SELECT e.version_id FROM apiome.catalog_drift_events e
        WHERE e.project_id = %s::uuid AND e.severity = 'breaking'
        UNION
        SELECT e.parent_version_id FROM apiome.catalog_drift_events e
        WHERE e.project_id = %s::uuid AND e.severity = 'breaking' AND e.parent_version_id IS NOT NULL
        UNION
        SELECT v.id FROM apiome.versions v
        WHERE v.project_id = %s::uuid AND v.revision_locked IS TRUE
        UNION
        (SELECT v.id FROM apiome.versions v
         WHERE v.project_id = %s::uuid AND v.deleted_at IS NULL
         ORDER BY v.created_at DESC, v.id DESC LIMIT 1)
        """,
        (project_id,) * 6,
    )
    return {str(row["id"]) for row in rows if row.get("id") is not None}


def prune_refresh_versions(
    db: Any, *, tenant_id: str, project_id: str, keep: int, actor_id: Optional[str] = None
) -> List[str]:
    """Prune the item's refresh-created versions beyond the newest ``keep``.

    Args:
        db: Database handle.
        tenant_id: The item's tenant.
        project_id: The catalog item.
        keep: The item's ``keep_versions``.
        actor_id: Who the audit row is attributed to.

    Returns:
        The pruned version ids (empty when nothing was over the limit).
    """
    candidates = _refresh_versions(db, tenant_id, project_id)
    if len(candidates) <= keep:
        return []
    to_prune = plan_pruning(candidates, keep, protected_version_ids(db, project_id))
    if not to_prune:
        return []
    rows = db.execute_query(
        """
        UPDATE apiome.versions v
        SET deleted_at = CURRENT_TIMESTAMP, pruned_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        FROM apiome.projects p
        WHERE v.id = ANY(%s::uuid[]) AND v.project_id = %s::uuid AND p.id = v.project_id
          AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
        RETURNING v.id, v.version_id
        """,
        (to_prune, project_id, tenant_id),
    )
    pruned = [str(row["id"]) for row in rows]
    if pruned:
        try:
            db.insert_workflow_audit(
                tenant_id,
                project_id,
                None,
                AUDIT_PRUNED,
                "success",
                actor_id,
                {"keep": int(keep), "pruned": [str(row["version_id"]) for row in rows]},
            )
        except Exception:  # noqa: BLE001 - the audit is best-effort
            _logger.warning("version retention audit failed project_id=%s", project_id, exc_info=True)
    return pruned


def prune_refresh_versions_safely(db: Any, **kwargs: Any) -> List[str]:
    """:func:`prune_refresh_versions` that never raises (retention never fails a refresh)."""
    try:
        return prune_refresh_versions(db, **kwargs)
    except Exception:  # noqa: BLE001
        _logger.warning("version retention failed project_id=%s", kwargs.get("project_id"), exc_info=True)
        return []


def pruned_version(
    db: Any, tenant_id: str, version_ref: str, project_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """The pruned version ``version_ref`` names (a revision id, or a label within ``project_id``), if any.

    Returns:
        ``{id, version_id, project_id, pruned_at}``, or ``None`` when no pruned version matches.
    """
    from .revision_deprecation import is_uuid_string

    ref = str(version_ref or "").strip()
    if not ref:
        return None
    if is_uuid_string(ref):
        where, params = "v.id = %s::uuid", [ref]
    elif project_id and is_uuid_string(str(project_id)):
        where, params = "v.project_id = %s::uuid AND v.version_id = %s", [str(project_id), ref]
    else:
        return None
    if not is_uuid_string(str(tenant_id)):
        return None
    rows = db.execute_query(
        f"""
        SELECT v.id, v.version_id, v.project_id, v.pruned_at
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE {where} AND p.tenant_id = %s::uuid AND v.pruned_at IS NOT NULL
        ORDER BY v.pruned_at DESC
        LIMIT 1
        """,
        tuple(params + [str(tenant_id)]),
    )
    return dict(rows[0]) if rows else None


def raise_if_pruned(db: Any, tenant_id: str, version_ref: str, project_id: Optional[str] = None) -> None:
    """Raise HTTP 410 ``version-pruned`` when ``version_ref`` names a pruned version.

    Callers use it where they would answer 404 for a missing version, so a reader learns the version
    existed and was pruned by retention. A lookup failure is ignored (the caller's 404 stands).

    Raises:
        HTTPException: 410 with ``{code, message, versionId, versionLabel, prunedAt}``.
    """
    from fastapi import HTTPException

    try:
        row = pruned_version(db, tenant_id, version_ref, project_id)
    except Exception:  # noqa: BLE001 - never turn a 404 into a 500
        _logger.warning("pruned-version lookup failed ref=%s", version_ref, exc_info=True)
        return
    if row is None:
        return
    pruned_at = row.get("pruned_at")
    raise HTTPException(
        status_code=410,
        detail={
            "code": CODE_VERSION_PRUNED,
            "message": (
                f"Version {row.get('version_id')} was pruned by the item's version retention; "
                "compare with a version that is still kept."
            ),
            "versionId": str(row["id"]),
            "versionLabel": row.get("version_id"),
            "prunedAt": pruned_at.isoformat() if hasattr(pruned_at, "isoformat") else pruned_at,
        },
    )


def nearest_live_earlier_version(db: Any, project_id: str, version_id: str) -> Optional[Dict[str, Any]]:
    """The newest live version of the item created before ``version_id`` (a diff's fallback baseline).

    Returns:
        ``{id, version_id}``, or ``None`` when there is none.
    """
    rows = db.execute_query(
        """
        SELECT v.id, v.version_id
        FROM apiome.versions v
        JOIN apiome.versions anchor ON anchor.id = %s::uuid
        WHERE v.project_id = %s::uuid AND v.deleted_at IS NULL AND v.id <> anchor.id
          AND (v.created_at, v.id) < (anchor.created_at, anchor.id)
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT 1
        """,
        (version_id, project_id),
    )
    return dict(rows[0]) if rows else None
