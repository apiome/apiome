"""Sunset readiness — the reads and the weekly claim (RDG-5.3, #5788).

The SQL half of :mod:`app.sunset_readiness`:

* :func:`usage_for_revisions` reads each revision's 7-day ``prod`` calls from ``usage_daily``, per
  consumer (through the RDG-1.8 binding, deleted or not, so history stays attributed) and for
  anonymous traffic;
* :func:`readiness_for_entries` turns that into the :class:`~app.sunset_readiness.SunsetUsage`
  block per sunset-timeline row — ``None`` for a project with no usage source, which has no
  evidence either way and so draws no line;
* :func:`alert_candidates` lists the revisions the sweep should look at: a sunset is set, bound
  consumers called it in the window, and no alert went out in the last 7 days;
* :func:`claim_and_notify` is the stored "once per version per week" rule: one upsert on
  ``sunset_still_used_alert`` that only succeeds when the last alert is at least 7 days old, with
  the inbox rows written in the same transaction.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .revision_deprecation import is_uuid_string
from .sunset_readiness import ENVIRONMENT, RENOTIFY_AFTER, SunsetUsage, UsageRow, summarize_usage, usage_window

__all__ = [
    "MAX_CANDIDATES",
    "alert_candidates",
    "candidate_project",
    "claim_and_notify",
    "projects_with_usage_sources",
    "readiness_for_entries",
    "usage_for_revisions",
]

#: Most revisions one sweep tick looks at. The rest wait for the next tick.
MAX_CANDIDATES = 500


def _uuids(values: Iterable[Any]) -> List[str]:
    """The distinct values that are UUIDs, in first-seen order."""
    seen: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if is_uuid_string(text) and text not in seen:
            seen.append(text)
    return seen


def usage_for_revisions(
    db: Any,
    tenant_id: str,
    revisions: Sequence[Tuple[str, str]],
    *,
    today: date,
) -> Dict[str, List[UsageRow]]:
    """Each revision's window calls, per consumer and for anonymous traffic.

    Args:
        db: The database (``execute_query``).
        tenant_id: The tenant.
        revisions: ``(revision_id, project_id)`` pairs.
        today: The current UTC day; the window is the 7 days ending today.

    Returns:
        ``{revision_id: [UsageRow, …]}``; a revision with no traffic is absent.
    """
    revision_ids = _uuids(revision for revision, _ in revisions)
    project_ids = _uuids(project for _, project in revisions)
    if not is_uuid_string(str(tenant_id or "")) or not revision_ids or not project_ids:
        return {}
    since, until = usage_window(today)
    rows = db.execute_query(
        """
        SELECT d.version_record_id::text AS revision_id, b.consumer_id::text AS consumer_id,
               c.slug AS consumer_slug, c.name AS consumer_name, sum(d.calls)::bigint AS calls
        FROM apiome.usage_daily d
        LEFT JOIN apiome.usage_consumer_binding b ON b.id = d.consumer_binding_id
        LEFT JOIN apiome.consumer c ON c.id = b.consumer_id
        WHERE d.tenant_id = %s::uuid AND d.project_id = ANY (%s::uuid[])
          AND d.version_record_id = ANY (%s::uuid[])
          AND d.environment = %s AND d.day BETWEEN %s AND %s
        GROUP BY d.version_record_id, b.consumer_id, c.slug, c.name
        HAVING sum(d.calls) > 0
        ORDER BY d.version_record_id, b.consumer_id NULLS LAST
        """,
        (tenant_id, project_ids, revision_ids, ENVIRONMENT, since, until),
    )
    by_revision: Dict[str, List[UsageRow]] = {}
    for row in rows:
        by_revision.setdefault(str(row["revision_id"]), []).append(
            UsageRow(
                consumer_id=row.get("consumer_id"),
                slug=row.get("consumer_slug"),
                name=row.get("consumer_name"),
                calls=int(row.get("calls") or 0),
            )
        )
    return by_revision


def projects_with_usage_sources(db: Any, tenant_id: str, project_ids: Iterable[Any]) -> Set[str]:
    """The projects that have a usage source other than the mock runtime's.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_ids: The projects to check.

    Returns:
        The ids of those that have one.
    """
    ids = _uuids(project_ids)
    if not is_uuid_string(str(tenant_id or "")) or not ids:
        return set()
    rows = db.execute_query(
        """
        SELECT DISTINCT s.project_id::text AS project_id
        FROM apiome.usage_source s
        WHERE s.tenant_id = %s::uuid AND s.project_id = ANY (%s::uuid[]) AND s.kind <> 'mock'
        """,
        (tenant_id, ids),
    )
    return {str(row["project_id"]) for row in rows}


def readiness_for_entries(
    db: Any,
    tenant_id: str,
    revisions: Sequence[Tuple[str, str]],
    *,
    consumers_visible: bool,
    today: date,
) -> Dict[str, Optional[SunsetUsage]]:
    """The usage block for each sunset-timeline row.

    Args:
        db: The database.
        tenant_id: The tenant.
        revisions: ``(revision_id, project_id)`` pairs.
        consumers_visible: Whether the reader holds ``consumer_contracts:view``.
        today: The current UTC day.

    Returns:
        ``{revision_id: SunsetUsage | None}`` — ``None`` when the revision's project has no usage
        source, so the page says nothing rather than "No traffic".
    """
    if not revisions:
        return {}
    sourced = projects_with_usage_sources(db, tenant_id, (project for _, project in revisions))
    usage = usage_for_revisions(
        db, tenant_id, [pair for pair in revisions if pair[1] in sourced], today=today
    )
    return {
        revision: (
            summarize_usage(usage.get(revision, []), project_id=project, consumers_visible=consumers_visible)
            if project in sourced
            else None
        )
        for revision, project in revisions
    }


def alert_candidates(db: Any, *, today: date, limit: int = MAX_CANDIDATES) -> List[Dict[str, Any]]:
    """Revisions the sweep should look at this tick.

    A revision qualifies when it has a sunset set, bound consumers called it in the window, and no
    alert went out for it in the last 7 days. Whether the sunset is close enough is decided in
    Python (:func:`app.sunset_readiness.is_alert_due`), because a stored sunset is free text.

    Args:
        db: The database.
        today: The current UTC day.
        limit: Most rows returned.

    Returns:
        Rows with ``tenant_id``, ``project_id``, ``project_slug``, ``project_name``, ``revision_id``,
        ``version_label`` and ``metadata``.
    """
    since, until = usage_window(today)
    return db.execute_query(
        """
        SELECT p.tenant_id::text AS tenant_id, p.id::text AS project_id, p.slug AS project_slug,
               p.name AS project_name, v.id::text AS revision_id, v.version_id AS version_label,
               v.metadata
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        JOIN apiome.tenants t ON t.id = p.tenant_id
        WHERE v.deleted_at IS NULL AND p.deleted_at IS NULL AND t.deleted_at IS NULL
          AND NULLIF(trim(COALESCE(v.metadata->>'sunsetAt', v.metadata->>'sunsetDate',
                                   v.metadata->>'sunset_date', '')), '') IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM apiome.usage_daily d
              WHERE d.tenant_id = p.tenant_id AND d.project_id = p.id AND d.version_record_id = v.id
                AND d.environment = %s AND d.day BETWEEN %s AND %s
                AND d.consumer_binding_id IS NOT NULL AND d.calls > 0
          )
          AND NOT EXISTS (
              SELECT 1 FROM apiome.sunset_still_used_alert a
              WHERE a.version_record_id = v.id AND a.last_notified_at > CURRENT_TIMESTAMP - %s
          )
        ORDER BY p.tenant_id, p.id, v.id
        LIMIT %s
        """,
        (ENVIRONMENT, since, until, RENOTIFY_AFTER, max(1, int(limit))),
    )


def claim_and_notify(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    revision_id: str,
    sunset_at: Optional[str],
    usage: SunsetUsage,
    drafts: Sequence[Any],
) -> bool:
    """Claim this week's alert for a revision and write its inbox rows, in one transaction.

    The upsert succeeds for a revision never alerted, or one whose last alert is at least
    :data:`~app.sunset_readiness.RENOTIFY_AFTER` old; otherwise it changes nothing and no row is
    written. Two replicas racing on the same revision therefore send one alert between them.

    Args:
        db: The database (``connect`` and ``_insert_notifications``).
        tenant_id: The tenant.
        project_id: The project.
        revision_id: The revision.
        sunset_at: The sunset the alert warns about.
        usage: The window usage the alert counted.
        drafts: The ``sunset_still_used`` notification drafts.

    Returns:
        True when this call claimed the week (and the alert should be sent), False when another
        alert went out less than 7 days ago.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.sunset_still_used_alert AS a
                    (version_record_id, tenant_id, project_id, last_notified_at, sunset_at,
                     consumer_count, calls)
                VALUES (%s::uuid, %s::uuid, %s::uuid, CURRENT_TIMESTAMP, %s, %s, %s)
                ON CONFLICT (version_record_id) DO UPDATE
                    SET last_notified_at = EXCLUDED.last_notified_at,
                        sunset_at = EXCLUDED.sunset_at,
                        consumer_count = EXCLUDED.consumer_count,
                        calls = EXCLUDED.calls,
                        alert_count = a.alert_count + 1
                    WHERE a.last_notified_at <= EXCLUDED.last_notified_at - %s
                RETURNING a.version_record_id
                """,
                (
                    revision_id,
                    tenant_id,
                    project_id,
                    sunset_at,
                    usage.consumer_count,
                    usage.bound_calls,
                    RENOTIFY_AFTER,
                ),
            )
            claimed = cursor.fetchone() is not None
            if claimed:
                db._insert_notifications(cursor, tenant_id=tenant_id, notify=lambda _produced: list(drafts))
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise


def candidate_project(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The project row a candidate names, in the shape the payload builders read.

    Args:
        row: An :func:`alert_candidates` row.

    Returns:
        ``{"id", "slug", "name"}``.
    """
    return {"id": row.get("project_id"), "slug": row.get("project_slug"), "name": row.get("project_name")}
