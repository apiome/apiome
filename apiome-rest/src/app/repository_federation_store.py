"""Federation storage — V2-REPO-8.2 (#2806).

Reads and writes over ``projects.repository_federation`` and ``project_federation_merges``
(apiome-db V303). A history row and its ``apiome.access_audit`` row are written in **one
transaction** (``db._guarded_tx``), so a merge is never recorded without its audit trail — the
ticket's "audit row ``repository.federation_merged`` per merge". The rules are
:mod:`app.repository_federation`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .database import db
from .repository_federation import AUDIT_BY_STATUS, AUDIT_TOGGLED, FederationMergeCreate
from .revision_deprecation import is_uuid_string

__all__ = [
    "MAX_HISTORY_LIMIT",
    "get_federation_enabled",
    "insert_merge",
    "list_project_merges",
    "list_repository_merges",
    "set_federation_enabled",
]

#: Largest history page.
MAX_HISTORY_LIMIT = 200

_COLUMNS = """
    m.id, m.project_id, p.name AS project_name, m.status, m.version_id, v.version_id AS version_label,
    m.parent_version_id, m.repository_id, m.repository_full_name, m.branch, m.path, m.source_count,
    m.classes_carried, m.paths_carried, m.removed_count, m.conflict_count, m.sources, m.conflicts,
    m.actor_id, m.created_at
"""

_FROM = """
      FROM apiome.project_federation_merges m
      JOIN apiome.projects p ON p.id = m.project_id
      LEFT JOIN apiome.versions v ON v.id = m.version_id
"""

_INSERT_SQL = """
    INSERT INTO apiome.project_federation_merges
           (tenant_id, project_id, status, version_id, parent_version_id, repository_id,
            repository_full_name, branch, path, source_count, classes_carried, paths_carried,
            removed_count, conflict_count, sources, conflicts, actor_id)
    SELECT %s::uuid, p.id, %s, %s::uuid, %s::uuid,
           (SELECT r.id FROM apiome.tenant_repositories r WHERE r.id = %s::uuid AND r.tenant_id = p.tenant_id),
           %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::uuid
      FROM apiome.projects p
     WHERE p.id = %s::uuid AND p.tenant_id = %s::uuid
    RETURNING id
"""


def _uuid_or_none(value: Optional[str]) -> Optional[str]:
    """Keep a UUID-shaped id, drop anything else (an id from another shape is never trusted)."""
    text = (value or "").strip()
    return text if text and is_uuid_string(text) else None


def get_federation_enabled(tenant_id: str, project_id: str) -> Optional[bool]:
    """Read a project's federation switch.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.

    Returns:
        The switch, or ``None`` when the project is not in the tenant.
    """
    rows = db.execute_query(
        "SELECT repository_federation FROM apiome.projects WHERE id = %s::uuid AND tenant_id = %s::uuid",
        (project_id, tenant_id),
    )
    return bool(rows[0]["repository_federation"]) if rows else None


def set_federation_enabled(
    tenant_id: str,
    project_id: str,
    enabled: bool,
    *,
    actor_id: Optional[str],
    actor_label: Optional[str],
) -> Optional[bool]:
    """Switch a project's federation on or off, audited as ``repository.federation_toggled``.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        enabled: The new value.
        actor_id: Who switched it.
        actor_label: Their email or name, for the audit row.

    Returns:
        The stored value, or ``None`` when the project is not in the tenant.
    """

    def work(cursor: Any) -> Optional[bool]:
        cursor.execute(
            """
            UPDATE apiome.projects SET repository_federation = %s
             WHERE id = %s::uuid AND tenant_id = %s::uuid
            RETURNING repository_federation
            """,
            (bool(enabled), project_id, tenant_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        db._append_access_audit(
            cursor,
            tenant_id=tenant_id,
            action=AUDIT_TOGGLED,
            actor_id=actor_id,
            actor_label=actor_label,
            target=project_id,
            source="api",
            detail={"projectId": project_id, "enabled": bool(enabled)},
        )
        return bool(row["repository_federation"])

    return db._guarded_tx(work)


def insert_merge(
    tenant_id: str,
    project_id: str,
    report: FederationMergeCreate,
    conflicts: List[Dict[str, Any]],
    *,
    actor_id: Optional[str],
    actor_label: Optional[str],
) -> Optional[str]:
    """Record one merge and its audit row in one transaction.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project (must be in the tenant).
        report: What the import reported.
        conflicts: The conflicts as stored (:func:`app.repository_federation.with_existing_definitions`).
        actor_id: Who imported.
        actor_label: Their email or name.

    Returns:
        The new row's id, or ``None`` when the project is not in the tenant (nothing written).
    """
    version_id = None if report.status == "conflicted" else _uuid_or_none(report.version_id)
    sources = [s.model_dump(by_alias=True) for s in report.sources]
    conflict_count = max(report.conflict_count or 0, len(conflicts))

    def work(cursor: Any) -> Optional[str]:
        cursor.execute(
            _INSERT_SQL,
            (
                tenant_id,
                report.status,
                version_id,
                _uuid_or_none(report.parent_version_id),
                _uuid_or_none(report.repository_id),
                report.repository_full_name,
                report.branch,
                report.path,
                report.source_count,
                report.classes_carried,
                report.paths_carried,
                report.removed_count,
                conflict_count,
                json.dumps(sources),
                json.dumps(conflicts, default=str),
                actor_id,
                project_id,
                tenant_id,
            ),
        )
        row = cursor.fetchone()
        if not row:
            return None
        merge_id = str(row["id"])
        db._append_access_audit(
            cursor,
            tenant_id=tenant_id,
            action=AUDIT_BY_STATUS[report.status],
            actor_id=actor_id,
            actor_label=actor_label,
            target=project_id,
            source="api",
            detail={
                "mergeId": merge_id,
                "projectId": project_id,
                "status": report.status,
                "versionId": version_id,
                "repositoryFullName": report.repository_full_name,
                "branch": report.branch,
                "path": report.path,
                "sourceCount": report.source_count,
                "conflictCount": conflict_count,
                "conflicts": [f"{c['kind']} {c['key']}" for c in conflicts][:20],
            },
        )
        return merge_id

    return db._guarded_tx(work)


def _row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a history row (ids to strings, JSON columns to lists)."""
    out = dict(row)
    for key in ("id", "project_id", "version_id", "parent_version_id", "repository_id", "actor_id"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("sources", "conflicts"):
        value = out.get(key)
        if isinstance(value, str):
            value = json.loads(value)
        out[key] = value if isinstance(value, list) else []
    return out


def _limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_HISTORY_LIMIT))


def list_project_merges(tenant_id: str, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """A project's merge history, newest first.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        limit: Rows (clamped to 1–200).

    Returns:
        History rows.
    """
    rows = db.execute_query(
        f"SELECT {_COLUMNS} {_FROM} WHERE m.project_id = %s::uuid AND m.tenant_id = %s::uuid "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT %s",
        (project_id, tenant_id, _limit(limit)),
    )
    return [_row(r) for r in rows]


def list_repository_merges(tenant_id: str, repository_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """The merges a repository's files took part in as the imported file, newest first.

    Args:
        tenant_id: The caller's tenant.
        repository_id: The registered repository.
        limit: Rows (clamped to 1–200).

    Returns:
        History rows.
    """
    rows = db.execute_query(
        f"SELECT {_COLUMNS} {_FROM} WHERE m.repository_id = %s::uuid AND m.tenant_id = %s::uuid "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT %s",
        (repository_id, tenant_id, _limit(limit)),
    )
    return [_row(r) for r in rows]
