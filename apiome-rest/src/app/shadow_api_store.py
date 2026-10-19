"""SQL for the shadow-API report and its item actions — CDG-1.6 (#5957).

Loads the rows :func:`app.shadow_api_report.build_shadow_report` works on, and writes the three
actions a person takes on a report row: **ignore** (with a reason and a snapshot of where the API
was served), **unignore**, and **link** to a catalog item or Project. Also claims the per-connector
notification throttle slot (V283), the REPO-7.2 one-per-window rule for connectors.

Every read is scoped by tenant. Nothing here links an inventory row on its own: :func:`link_item`
runs only when a person asks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .catalog_connectors import ITEM_DISCOVERED, ITEM_IGNORED, ITEM_IMPORTED

__all__ = [
    "SHADOW_EVENT_TYPE",
    "claim_connector_notification_slot",
    "get_item",
    "ignore_item",
    "link_item",
    "load_catalog_entries",
    "load_report_connectors",
    "load_report_items",
    "unignore_item",
]

#: The push-webhook event type of a new-shadow-API notification (and the throttle row's key).
SHADOW_EVENT_TYPE = "catalog.connector.shadow_api_detected"

_ITEM_COLUMNS = """
    i.id, i.connector_id, i.remote_id, i.remote_name, i.environment, i.hosts, i.base_path,
    i.remote_revision, i.remote_updated_at, i.imported_revision, i.imported_remote_updated_at,
    i.status, i.project_id, i.first_seen_at, i.last_seen_at, i.ignored_reason, i.ignored_at,
    i.ignored_by, i.ignored_hosts, i.ignored_base_path, i.linked_by, i.linked_at
"""


def load_report_connectors(db: Any, tenant_id: str, connector_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The tenant's live connectors (not `mcp-registry` ones), with the finish time of each one's last successful run.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        connector_id: Restrict to one connector (the report's ``connector`` filter).
    """
    rows = db.execute_query(
        """
        SELECT c.id, c.name, c.kind, c.status, c.last_run_at,
               (SELECT max(COALESCE(j.finished_at, j.created_at))
                  FROM apiome.tenant_repository_refresh_jobs j
                 WHERE j.connector_id = c.id AND j.status = 'succeeded') AS last_success_at
        FROM apiome.catalog_connectors c
        WHERE c.tenant_id = %s::uuid AND c.deleted_at IS NULL
          -- CDG-4.4: an MCP registry lists MCP servers, not APIs a gateway serves.
          AND c.kind <> 'mcp-registry'
          AND (%s::uuid IS NULL OR c.id = %s::uuid)
        ORDER BY lower(c.name)
        """,
        (tenant_id, connector_id, connector_id),
    )
    return [dict(r) for r in rows or []]


def load_report_items(db: Any, connector_ids: List[str], environment: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every inventory row of ``connector_ids`` that is still served (not ``missing``).

    Args:
        db: Database handle.
        connector_ids: The connectors in scope (already tenant-checked).
        environment: Restrict to one environment (the report's ``environment`` filter).
    """
    if not connector_ids:
        return []
    rows = db.execute_query(
        f"""
        SELECT {_ITEM_COLUMNS}
        FROM apiome.catalog_connector_items i
        WHERE i.connector_id = ANY(%s::uuid[]) AND i.status <> 'missing'
          AND (%s::text IS NULL OR i.environment = %s)
        ORDER BY i.remote_name NULLS LAST, i.remote_id
        """,
        (connector_ids, environment, environment),
    )
    return [dict(r) for r in rows or []]


def load_catalog_entries(db: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """The catalog side of the report: one entry per live catalog item and published Project.

    A catalog item contributes its latest revision; a Project contributes its latest **published**
    version (a Project with none is not described to anyone yet, so it is not an entry). Servers come
    from the revision's canonical model (``api_artifacts.servers``) and, for a Project, from its
    OpenAPI server list (``version_server``). ``remote_ids`` and ``remote_revision`` come from the
    revision's connector provenance (``format_metadata.remoteId`` / ``remoteRevision``).
    """
    rows = db.execute_query(
        """
        SELECT p.id AS project_id, p.name, p.publishable,
               lv.id AS version_id, lv.version_id AS version_label,
               lv.format_metadata ->> 'remoteId' AS remote_id,
               lv.format_metadata ->> 'remoteRevision' AS remote_revision,
               COALESCE((
                   SELECT array_agg(s ->> 'url') FROM apiome.api_artifacts a,
                          jsonb_array_elements(CASE WHEN jsonb_typeof(a.servers) = 'array'
                                                    THEN a.servers ELSE '[]'::jsonb END) s
                    WHERE a.version_id = lv.id AND a.deleted_at IS NULL AND s ? 'url'
               ), '{}') AS artifact_servers,
               COALESCE((
                   SELECT array_agg(vs.url ORDER BY vs.sort_order) FROM apiome.version_server vs
                    WHERE vs.version_id = lv.id
               ), '{}') AS project_servers
        FROM apiome.projects p
        JOIN LATERAL (
            SELECT v.id, v.version_id, v.format_metadata
            FROM apiome.versions v
            WHERE v.project_id = p.id AND v.deleted_at IS NULL
              AND (p.publishable = false OR v.published = true)
            ORDER BY v.created_at DESC NULLS LAST, v.id DESC
            LIMIT 1
        ) lv ON TRUE
        WHERE p.tenant_id = %s::uuid AND p.deleted_at IS NULL
        """,
        (tenant_id,),
    )
    entries: List[Dict[str, Any]] = []
    for row in rows or []:
        servers: List[str] = []
        for url in list(row.get("project_servers") or []) + list(row.get("artifact_servers") or []):
            if url and url not in servers:
                servers.append(str(url))
        entries.append(
            {
                "project_id": str(row["project_id"]),
                "name": row.get("name"),
                "publishable": bool(row.get("publishable")),
                "version_id": str(row["version_id"]) if row.get("version_id") else None,
                "version_label": row.get("version_label"),
                "servers": servers,
                "remote_ids": [row["remote_id"]] if row.get("remote_id") else [],
                "remote_revision": row.get("remote_revision"),
            }
        )
    return entries


def get_item(db: Any, tenant_id: str, connector_id: str, item_id: str) -> Optional[Dict[str, Any]]:
    """One inventory row of a live connector of the tenant, or ``None``."""
    rows = db.execute_query(
        f"""
        SELECT {_ITEM_COLUMNS}
        FROM apiome.catalog_connector_items i
        JOIN apiome.catalog_connectors c ON c.id = i.connector_id
        WHERE i.id = %s::uuid AND i.connector_id = %s::uuid
          AND c.tenant_id = %s::uuid AND c.deleted_at IS NULL
        """,
        (item_id, connector_id, tenant_id),
    )
    return dict(rows[0]) if rows else None


def ignore_item(db: Any, item_id: str, *, reason: str, actor_id: Optional[str]) -> None:
    """Ignore a row: keep the reason, who and when, and where it is served now.

    The hosts and base path are snapshotted so the report can show the row again when the
    gateway starts serving it somewhere else.
    """
    db._execute_write(
        """
        UPDATE apiome.catalog_connector_items
        SET status = %s, ignored_reason = %s, ignored_at = now(), ignored_by = %s::uuid,
            ignored_hosts = hosts, ignored_base_path = base_path
        WHERE id = %s::uuid
        """,
        (ITEM_IGNORED, reason, actor_id, item_id),
    )


def unignore_item(db: Any, item_id: str) -> None:
    """Stop ignoring a row: it returns to ``imported`` (when linked) or ``discovered``."""
    db._execute_write(
        """
        UPDATE apiome.catalog_connector_items
        SET status = CASE WHEN project_id IS NULL THEN %s ELSE %s END,
            ignored_reason = NULL, ignored_at = NULL, ignored_by = NULL,
            ignored_hosts = NULL, ignored_base_path = NULL
        WHERE id = %s::uuid
        """,
        (ITEM_DISCOVERED, ITEM_IMPORTED, item_id),
    )


def link_item(db: Any, item_id: str, *, project_id: str, actor_id: Optional[str]) -> None:
    """Link a row to a catalog item or Project, as a person asked ("Link to item").

    The row becomes ``imported`` and its freshness anchor is set to what the gateway serves now, so
    the next sync does not re-import an unchanged API and drift is measured from the link.
    """
    db._execute_write(
        """
        UPDATE apiome.catalog_connector_items
        SET status = %s, project_id = %s::uuid, linked_by = %s::uuid, linked_at = now(),
            imported_revision = remote_revision, imported_remote_updated_at = remote_updated_at,
            ignored_reason = NULL, ignored_at = NULL, ignored_by = NULL,
            ignored_hosts = NULL, ignored_base_path = NULL
        WHERE id = %s::uuid
        """,
        (ITEM_IMPORTED, project_id, actor_id, item_id),
    )


def claim_connector_notification_slot(
    db: Any, tenant_id: str, connector_id: str, event_type: str = SHADOW_EVENT_TYPE, window_seconds: int = 3600
) -> bool:
    """Atomically claim the (connector, event type) notification slot for the current window.

    One conditional upsert, as REPO-7.2's repository throttle: the first claim inserts, a later
    one wins only when the last notification is outside the window; a losing claim bumps the
    suppression counter.

    Returns:
        ``True`` when the notification may be delivered.
    """
    won = db.execute_query(
        """
        INSERT INTO apiome.catalog_connector_notification_throttle AS t
          (tenant_id, connector_id, event_type, last_notified_at)
        VALUES (%s::uuid, %s::uuid, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (connector_id, event_type) DO UPDATE
          SET last_notified_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
          WHERE %s <= 0 OR t.last_notified_at <= CURRENT_TIMESTAMP - make_interval(secs => %s)
        RETURNING id
        """,
        (tenant_id, connector_id, event_type, int(window_seconds), int(window_seconds)),
    )
    if won:
        return True
    db._execute_write(
        """
        UPDATE apiome.catalog_connector_notification_throttle
        SET suppressed_count = suppressed_count + 1, updated_at = CURRENT_TIMESTAMP
        WHERE connector_id = %s::uuid AND event_type = %s
        """,
        (connector_id, event_type),
    )
    return False
