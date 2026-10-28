"""Catalog drift storage — MFI-31.3 (#4400).

SQL over ``apiome.catalog_drift_events`` and ``apiome.catalog_drift_settings`` (V334). Every function
takes the :class:`~app.database.Database` it runs on, so the refresh sweep can pass its per-tick
connection and tests can pass a recording fake. Reads for the API are scoped by tenant.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .catalog_drift import (
    NOTIFICATION_DIGESTED,
    NOTIFICATION_PENDING_DIGEST,
    DriftClassification,
    DriftSettings,
)

__all__ = [
    "dismiss_event",
    "get_settings_row",
    "insert_event",
    "latest_open_events",
    "list_events",
    "mark_digested",
    "pending_digest_events",
    "put_settings",
    "settings_payload",
    "tenants_due_for_digest",
]

_EVENT_COLUMNS = """
    e.id, e.tenant_id, e.project_id, e.version_id, e.parent_version_id, e.version_label,
    e.parent_version_label, e.trigger, e.severity, e.counts, e.change_count, e.changes,
    e.notification, e.notified_at, e.dismissed_at, e.dismissed_by, e.created_at
"""


def get_settings_row(db: Any, tenant_id: str) -> Optional[Dict[str, Any]]:
    """The tenant's stored settings row, or ``None`` when it uses the defaults."""
    rows = db.execute_query(
        "SELECT * FROM apiome.catalog_drift_settings WHERE tenant_id = %s::uuid",
        (tenant_id,),
    )
    return dict(rows[0]) if rows else None


def put_settings(db: Any, tenant_id: str, settings: DriftSettings, *, actor_id: Optional[str]) -> Dict[str, Any]:
    """Create or replace the tenant's settings (``last_digest_at`` is kept) and return the row."""
    rows = db.execute_query(
        """
        INSERT INTO apiome.catalog_drift_settings
            (tenant_id, notify_breaking, notify_dangerous, notify_safe, delivery, breaking_immediate,
             email_enabled, updated_by, updated_at)
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::uuid, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id) DO UPDATE SET
            notify_breaking = EXCLUDED.notify_breaking,
            notify_dangerous = EXCLUDED.notify_dangerous,
            notify_safe = EXCLUDED.notify_safe,
            delivery = EXCLUDED.delivery,
            breaking_immediate = EXCLUDED.breaking_immediate,
            email_enabled = EXCLUDED.email_enabled,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
        """,
        (
            tenant_id,
            settings.notify_breaking,
            settings.notify_dangerous,
            settings.notify_safe,
            settings.delivery,
            settings.breaking_immediate,
            settings.email_enabled,
            actor_id,
        ),
    )
    return dict(rows[0]) if rows else {}


def insert_event(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    version_id: str,
    parent_version_id: Optional[str],
    version_label: str,
    parent_version_label: Optional[str],
    trigger: str,
    classification: DriftClassification,
    notification: str,
) -> Dict[str, Any]:
    """Record one drift event and return the stored row.

    ``notified_at`` is stamped when ``notification`` is ``sent``. A second event for the same
    version is ignored (``uq_catalog_drift_events_version``) and the existing row is returned.
    """
    rows = db.execute_query(
        f"""
        WITH inserted AS (
            INSERT INTO apiome.catalog_drift_events AS e
                (tenant_id, project_id, version_id, parent_version_id, version_label,
                 parent_version_label, trigger, severity, counts, change_count, changes,
                 notification, notified_at)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s,
                    CASE WHEN %s = 'sent' THEN CURRENT_TIMESTAMP END)
            ON CONFLICT (version_id) DO NOTHING
            RETURNING {_EVENT_COLUMNS}
        )
        SELECT * FROM inserted
        UNION ALL
        SELECT {_EVENT_COLUMNS} FROM apiome.catalog_drift_events e
        WHERE e.version_id = %s::uuid AND NOT EXISTS (SELECT 1 FROM inserted)
        """,
        (
            tenant_id,
            project_id,
            version_id,
            parent_version_id,
            version_label,
            parent_version_label,
            trigger,
            classification.severity,
            json.dumps(classification.counts),
            classification.change_count,
            json.dumps(classification.changes),
            notification,
            notification,
            version_id,
        ),
    )
    return dict(rows[0]) if rows else {}


def latest_open_events(db: Any, tenant_id: str, project_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """The newest undismissed event per item, for the catalog badge.

    Args:
        db: Database handle.
        tenant_id: The caller's tenant.
        project_ids: The items on the page.

    Returns:
        ``{project_id: event row}`` without the ``changes`` list; items without an open event are
        absent.
    """
    from .revision_deprecation import is_uuid_string

    ids = [str(pid) for pid in project_ids if is_uuid_string(str(pid))]
    if not ids or not is_uuid_string(str(tenant_id)):
        return {}
    rows = db.execute_query(
        """
        SELECT DISTINCT ON (e.project_id)
               e.id, e.project_id, e.version_id, e.version_label, e.severity, e.counts,
               e.change_count, e.trigger, e.created_at
        FROM apiome.catalog_drift_events e
        WHERE e.tenant_id = %s::uuid AND e.project_id = ANY(%s::uuid[]) AND e.dismissed_at IS NULL
        ORDER BY e.project_id, e.created_at DESC, e.id DESC
        """,
        (tenant_id, ids),
    )
    return {str(row["project_id"]): dict(row) for row in rows}


def list_events(db: Any, tenant_id: str, project_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    """An item's drift events, newest first, with their changes."""
    rows = db.execute_query(
        f"""
        SELECT {_EVENT_COLUMNS}
        FROM apiome.catalog_drift_events e
        WHERE e.tenant_id = %s::uuid AND e.project_id = %s::uuid
        ORDER BY e.created_at DESC, e.id DESC
        LIMIT %s
        """,
        (tenant_id, project_id, int(limit)),
    )
    return [dict(row) for row in rows]


def dismiss_event(
    db: Any, tenant_id: str, project_id: str, event_id: str, *, actor_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Dismiss one event (idempotent: a dismissed event keeps its first dismissal).

    Returns:
        The event row, or ``None`` when no such event belongs to the item in the tenant.
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.catalog_drift_events e
        SET dismissed_at = COALESCE(e.dismissed_at, CURRENT_TIMESTAMP),
            dismissed_by = COALESCE(e.dismissed_by, %s::uuid)
        WHERE e.id = %s::uuid AND e.project_id = %s::uuid AND e.tenant_id = %s::uuid
        RETURNING {_EVENT_COLUMNS}
        """,
        (actor_id, event_id, project_id, tenant_id),
    )
    return dict(rows[0]) if rows else None


def tenants_due_for_digest(db: Any, *, interval_seconds: int) -> List[str]:
    """Tenants with waiting events whose last digest is at least ``interval_seconds`` old.

    A tenant that never sent one is due once its oldest waiting event is that old, so the first
    digest also covers a full day.
    """
    rows = db.execute_query(
        """
        SELECT e.tenant_id
        FROM apiome.catalog_drift_events e
        LEFT JOIN apiome.catalog_drift_settings s ON s.tenant_id = e.tenant_id
        WHERE e.notification = %s
        GROUP BY e.tenant_id, s.last_digest_at
        HAVING COALESCE(s.last_digest_at, MIN(e.created_at))
               <= CURRENT_TIMESTAMP - make_interval(secs => %s)
        """,
        (NOTIFICATION_PENDING_DIGEST, int(interval_seconds)),
    )
    return [str(row["tenant_id"]) for row in rows]


def pending_digest_events(db: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """A tenant's waiting events, oldest first, with the item's name and slug."""
    rows = db.execute_query(
        f"""
        SELECT {_EVENT_COLUMNS}, p.name AS item_name, p.slug AS item_slug
        FROM apiome.catalog_drift_events e
        JOIN apiome.projects p ON p.id = e.project_id
        WHERE e.tenant_id = %s::uuid AND e.notification = %s
        ORDER BY e.created_at, e.id
        """,
        (tenant_id, NOTIFICATION_PENDING_DIGEST),
    )
    return [dict(row) for row in rows]


def mark_digested(db: Any, tenant_id: str, event_ids: List[str]) -> None:
    """Mark events as sent in a digest and stamp the tenant's ``last_digest_at``."""
    db.execute_query(
        """
        WITH marked AS (
            UPDATE apiome.catalog_drift_events
            SET notification = %s, notified_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s::uuid AND id = ANY(%s::uuid[])
            RETURNING id
        )
        INSERT INTO apiome.catalog_drift_settings (tenant_id, last_digest_at)
        VALUES (%s::uuid, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id) DO UPDATE SET last_digest_at = CURRENT_TIMESTAMP
        RETURNING tenant_id
        """,
        (NOTIFICATION_DIGESTED, tenant_id, list(event_ids), tenant_id),
    )


def settings_payload(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The extra columns the API shows beside the settings: when they changed and the last digest."""
    row = row or {}
    return {key: row.get(key) for key in ("updated_at", "updated_by", "last_digest_at")}
