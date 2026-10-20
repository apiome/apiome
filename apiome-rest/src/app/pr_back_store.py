"""PR-back storage — REPO-5.8 (#2793).

The reads and writes PR-back needs, over ``apiome.repository_pr_back_settings`` (apiome-db V302)
and the REPO-5.7 provenance tables (V301):

* each repository's settings (:func:`get_settings`, :func:`save_settings`);
* the repository files a project was imported from (:func:`project_sources`) — the
  ``project_repository_sources`` rows, or, for a project last imported before REPO-5.7, its latest
  ``tenant_repository_imports`` row as its one source;
* which file defined each class and path of a version (:func:`entity_sources`).

Every read is scoped by tenant. The rules over these rows are :mod:`app.pr_back`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .database import db
from .pr_back import PrBackSettings, SourceFile

__all__ = [
    "entity_sources",
    "get_settings",
    "get_settings_row",
    "latest_version_id",
    "project_names",
    "project_sources",
    "save_settings",
    "unknown_project_ids",
]

#: ``project_ids`` is read as ``text[]``: psycopg2 has no ``uuid[]`` adapter and would return the
#: array's literal (``'{…}'``) instead of a list.
_SETTINGS_COLUMNS = """
    repository_id, tenant_id, project_policy, project_ids::text[] AS project_ids, target_branch,
    commit_message_template, reviewers, updated_by, created_at, updated_at
"""

_GET_SETTINGS_SQL = f"""
    SELECT {_SETTINGS_COLUMNS}
      FROM apiome.repository_pr_back_settings
     WHERE repository_id = %s::uuid AND tenant_id = %s::uuid
"""

_SAVE_SETTINGS_SQL = f"""
    INSERT INTO apiome.repository_pr_back_settings
           (repository_id, tenant_id, project_policy, project_ids, target_branch,
            commit_message_template, reviewers, updated_by)
    VALUES (%s::uuid, %s::uuid, %s, %s::uuid[], %s, %s, %s::text[], %s::uuid)
    ON CONFLICT (repository_id) DO UPDATE
       SET project_policy = EXCLUDED.project_policy,
           project_ids = EXCLUDED.project_ids,
           target_branch = EXCLUDED.target_branch,
           commit_message_template = EXCLUDED.commit_message_template,
           reviewers = EXCLUDED.reviewers,
           updated_by = EXCLUDED.updated_by,
           updated_at = CURRENT_TIMESTAMP
     WHERE apiome.repository_pr_back_settings.tenant_id = EXCLUDED.tenant_id
    RETURNING {_SETTINGS_COLUMNS}
"""

_PROJECTS_SQL = """
    SELECT id, name FROM apiome.projects
     WHERE tenant_id = %s::uuid AND id = ANY(%s::uuid[]) AND deleted_at IS NULL
"""

_SOURCES_SQL = """
    SELECT id, repository_id, branch, path, precedence
      FROM apiome.project_repository_sources
     WHERE project_id = %s::uuid AND tenant_id = %s::uuid
     ORDER BY precedence, created_at, id
"""

_LATEST_IMPORT_SQL = """
    SELECT repository_id, branch, path
      FROM apiome.tenant_repository_imports
     WHERE project_id = %s::uuid AND tenant_id = %s::uuid
     ORDER BY created_at DESC, id DESC
     LIMIT 1
"""

_LATEST_VERSION_SQL = """
    SELECT id FROM apiome.versions
     WHERE project_id = %s::uuid AND deleted_at IS NULL
     ORDER BY created_at DESC NULLS LAST, id DESC
     LIMIT 1
"""

_ENTITY_SOURCES_SQL = """
    SELECT entity_kind, entity_key, source_id
      FROM apiome.version_entity_sources
     WHERE version_id = %s::uuid
"""


def get_settings_row(tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
    """Read a repository's stored settings row.

    Args:
        tenant_id: The caller's tenant.
        repository_id: The registered repository.

    Returns:
        The row, or ``None`` when the repository has no PR-back settings.
    """
    rows = db.execute_query(_GET_SETTINGS_SQL, (repository_id, tenant_id))
    return dict(rows[0]) if rows else None


def get_settings(tenant_id: str, repository_id: str) -> Optional[PrBackSettings]:
    """Read a repository's settings.

    Args:
        tenant_id: The caller's tenant.
        repository_id: The registered repository.

    Returns:
        The :class:`PrBackSettings`, or ``None`` when the repository has none (no project may PR
        back).
    """
    return PrBackSettings.from_row(get_settings_row(tenant_id, repository_id))


def save_settings(
    tenant_id: str, repository_id: str, settings: PrBackSettings, actor_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Create or replace a repository's settings.

    Args:
        tenant_id: The caller's tenant (the repository must be in it — the route checks).
        repository_id: The registered repository.
        settings: Normalized settings (:func:`app.pr_back.normalize_settings`).
        actor_id: Who saved them.

    Returns:
        The stored row, or ``None`` when a row for the repository exists in another tenant.
    """
    rows = db.execute_query(
        _SAVE_SETTINGS_SQL,
        (
            repository_id,
            tenant_id,
            settings.project_policy,
            list(settings.project_ids),
            settings.target_branch,
            settings.commit_message_template,
            list(settings.reviewers),
            actor_id,
        ),
    )
    return dict(rows[0]) if rows else None


def project_names(tenant_id: str, project_ids: Sequence[str]) -> Dict[str, str]:
    """Name the tenant's live projects among some ids.

    Args:
        tenant_id: The caller's tenant.
        project_ids: Project ids.

    Returns:
        ``id → name`` for those that exist in the tenant (lower-case ids).
    """
    if not project_ids:
        return {}
    rows = db.execute_query(_PROJECTS_SQL, (tenant_id, list(project_ids)))
    return {str(r["id"]).lower(): str(r.get("name") or "") for r in rows}


def unknown_project_ids(tenant_id: str, project_ids: Sequence[str]) -> List[str]:
    """List the ids that name no live project of the tenant.

    Args:
        tenant_id: The caller's tenant.
        project_ids: Project ids (lower-case).

    Returns:
        The ids with no project, in the order given.
    """
    known = project_names(tenant_id, project_ids)
    return [p for p in project_ids if p.lower() not in known]


def project_sources(tenant_id: str, project_id: str) -> List[SourceFile]:
    """List the repository files a project was imported from.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.

    Returns:
        The ``project_repository_sources`` rows in precedence order. A project imported only before
        REPO-5.7 has none; its latest ``tenant_repository_imports`` row is then its one source
        (``source_id`` ``None``, precedence 1), matching how the import itself falls back.
    """
    rows = db.execute_query(_SOURCES_SQL, (project_id, tenant_id))
    if rows:
        return [
            SourceFile(
                source_id=str(r["id"]),
                repository_id=str(r["repository_id"]),
                branch=str(r["branch"]),
                path=str(r["path"]),
                precedence=int(r["precedence"]),
            )
            for r in rows
        ]
    latest = db.execute_query(_LATEST_IMPORT_SQL, (project_id, tenant_id))
    if not latest:
        return []
    row = latest[0]
    return [
        SourceFile(
            source_id=None,
            repository_id=str(row["repository_id"]),
            branch=str(row["branch"]),
            path=str(row["path"]),
            precedence=1,
        )
    ]


def entity_sources(version_id: str) -> Dict[Tuple[str, str], Optional[str]]:
    """Read which source file defined each class and path of a version.

    Args:
        version_id: The revision id.

    Returns:
        ``(kind, key) → source_id`` (``None`` when the defining source was removed). A class or
        path without an entry was not defined by a repository.
    """
    rows = db.execute_query(_ENTITY_SOURCES_SQL, (version_id,))
    return {
        (str(r["entity_kind"]), str(r["entity_key"])): (
            str(r["source_id"]) if r.get("source_id") is not None else None
        )
        for r in rows
    }


def latest_version_id(project_id: str) -> Optional[str]:
    """Return the project's newest live version.

    Args:
        project_id: The project.

    Returns:
        The revision id, or ``None`` when the project has no versions.
    """
    rows = db.execute_query(_LATEST_VERSION_SQL, (project_id,))
    return str(rows[0]["id"]) if rows else None
