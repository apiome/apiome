"""Persistence for a project's external ``$ref`` state — COA-2.8 (#7051).

One ``apiome.project_external_refs`` row (V398) per project and URL: the last refresh's status,
the last fetched snapshot, an optional pinned snapshot and the last change a refresh detected.
:mod:`app.project_references_routes` decides *what* to write; this module only reads and writes.

Every function takes the tenant id and filters on it, so a row can never be read or changed
across tenants.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .database import db

__all__ = [
    "STATUSES",
    "clear_pin",
    "list_refs",
    "record_check",
    "set_pin",
]

#: The statuses the table accepts (V398's CHECK).
STATUSES = ("ok", "changed", "unreachable", "blocked")

_COLUMNS = """
    url, status, reason, detail, content_digest, document, fetched_at, diff,
    checked_at, checked_by, pinned_digest, pinned_document, pinned_at, pinned_by
"""


def _json(value: Any) -> Optional[str]:
    """Serialize a JSONB parameter (``None`` stays SQL NULL)."""
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def list_refs(tenant_id: str, project_id: str) -> Dict[str, Dict[str, Any]]:
    """Every stored reference of a project, keyed by URL.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.

    Returns:
        ``url → row`` (all columns of :data:`_COLUMNS`).
    """
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}
        FROM apiome.project_external_refs
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid
        """,
        (tenant_id, project_id),
    )
    return {str(row["url"]): dict(row) for row in rows}


def record_check(
    *,
    tenant_id: str,
    project_id: str,
    url: str,
    status: str,
    actor_id: Optional[str],
    reason: Optional[str] = None,
    detail: Optional[str] = None,
    digest: Optional[str] = None,
    document: Any = None,
    diff: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record one refresh of one reference (insert or update its row).

    A successful fetch (``digest`` given) replaces the snapshot and its ``fetched_at``; a failed
    or refused one keeps the previous snapshot, so the panel still knows what was last seen and
    when. The pin is never touched here.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        url: The reference's URL (fragment stripped).
        status: One of :data:`STATUSES`.
        actor_id: Who refreshed.
        reason: Machine reason for a refusal or failure.
        detail: Human explanation for a refusal or failure.
        digest: The fetched document's sha-256, when the fetch succeeded.
        document: The fetched document, when the fetch succeeded.
        diff: The change detected, or ``None``.

    Returns:
        The stored row.

    Raises:
        ValueError: When ``status`` is not one of :data:`STATUSES`.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown external $ref status {status!r}")
    fetched = digest is not None
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.project_external_refs AS r
            (tenant_id, project_id, url, status, reason, detail, content_digest, document,
             fetched_at, diff, checked_at, checked_by)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb,
                CASE WHEN %s THEN CURRENT_TIMESTAMP END, %s::jsonb, CURRENT_TIMESTAMP, %s::uuid)
        ON CONFLICT (project_id, url) DO UPDATE SET
            status = EXCLUDED.status,
            reason = EXCLUDED.reason,
            detail = EXCLUDED.detail,
            content_digest = CASE WHEN %s THEN EXCLUDED.content_digest ELSE r.content_digest END,
            document = CASE WHEN %s THEN EXCLUDED.document ELSE r.document END,
            fetched_at = CASE WHEN %s THEN EXCLUDED.fetched_at ELSE r.fetched_at END,
            diff = EXCLUDED.diff,
            checked_at = EXCLUDED.checked_at,
            checked_by = EXCLUDED.checked_by
        WHERE r.tenant_id = EXCLUDED.tenant_id
        RETURNING {_COLUMNS}
        """,
        (
            tenant_id,
            project_id,
            url,
            status,
            reason,
            detail,
            digest,
            _json(document),
            fetched,
            _json(diff),
            actor_id,
            fetched,
            fetched,
            fetched,
        ),
    )
    return dict(rows[0]) if rows else {}


def set_pin(*, tenant_id: str, project_id: str, url: str, actor_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pin a reference's last fetched snapshot as the accepted one.

    The reference then reads ``ok`` with no diff: it matches its pin by definition.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        url: The reference's URL.
        actor_id: Who pinned.

    Returns:
        The updated row, or ``None`` when the reference has no fetched snapshot to pin.
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.project_external_refs
        SET pinned_digest = content_digest,
            pinned_document = document,
            pinned_at = CURRENT_TIMESTAMP,
            pinned_by = %s::uuid,
            status = CASE WHEN status = 'changed' THEN 'ok' ELSE status END,
            diff = CASE WHEN status = 'changed' THEN NULL ELSE diff END
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND url = %s
          AND content_digest IS NOT NULL AND document IS NOT NULL
        RETURNING {_COLUMNS}
        """,
        (actor_id, tenant_id, project_id, url),
    )
    return dict(rows[0]) if rows else None


def clear_pin(*, tenant_id: str, project_id: str, url: str) -> Optional[Dict[str, Any]]:
    """Remove a reference's pin; later refreshes compare against the previous snapshot again.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        url: The reference's URL.

    Returns:
        The updated row, or ``None`` when the reference is not stored.
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.project_external_refs
        SET pinned_digest = NULL, pinned_document = NULL, pinned_at = NULL, pinned_by = NULL
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND url = %s
        RETURNING {_COLUMNS}
        """,
        (tenant_id, project_id, url),
    )
    return dict(rows[0]) if rows else None
