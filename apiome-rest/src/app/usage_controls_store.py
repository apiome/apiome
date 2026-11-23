"""Persistence for usage export, retention and erasure — RDG-5.4 (#5789).

The only place the RDG-5.4 controls read or write the database (apiome-db V384 plus the V290 / V271
columns they expose). Every function takes the :class:`~app.database.Database` it runs on, so the
live-database tests can pass one bound to a rolled-back transaction.

* :func:`read_retention` / :func:`write_retention` — the tier caps and the workspace's own values;
* :func:`list_sources` / :func:`update_source` — a project's usage sources;
* :func:`list_toolsets` / :func:`update_toolset_body_samples` — the AGX-3.3 body-capture opt-in of
  the project's agent toolsets;
* :func:`export_day_rows` — one UTC day of ``usage_daily`` as export rows;
* :func:`erase_consumer` / :func:`delete_all_bindings` — a consumer's bindings, with or without
  erasing its counters.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .revision_deprecation import is_uuid_string
from .runtime_graph import PROVENANCE as RUNTIME_PROVENANCE
from .usage_controls import (
    AGENT_BODY_CAPTURE_MAX_RATE,
    BODY_SAMPLE_MAX_RATE,
    FREE_HOURLY_RETENTION_DAYS,
    FREE_ROLLUP_RETENTION_DAYS,
    RetentionDays,
    ToolsetBodySamplesOut,
    UsageRetentionResponse,
    UsageSourceOut,
    body_samples,
    effective_days,
)

__all__ = [
    "delete_all_bindings",
    "erase_consumer",
    "export_day_rows",
    "list_sources",
    "list_toolsets",
    "read_retention",
    "update_source",
    "update_toolset_body_samples",
    "write_retention",
]

_UNSET = object()


def _actor(user_id: Optional[str]) -> Optional[str]:
    """A user id the ``users`` foreign keys accept, or ``None``."""
    return user_id if user_id and is_uuid_string(str(user_id)) else None


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


def read_retention(db: Any, tenant_id: str) -> UsageRetentionResponse:
    """The workspace's usage retention: tier caps, its own values and what the purge applies.

    Args:
        db: The database.
        tenant_id: The tenant.

    Returns:
        The retention (Free caps when the tenant is unlicensed or the key is unset).
    """
    rows = db.execute_query(
        """
        SELECT CASE WHEN jsonb_typeof(l.seats -> 'usage_hourly_retention_days') = 'number'
                    THEN (l.seats ->> 'usage_hourly_retention_days')::numeric::integer
                    ELSE %s END AS hourly_cap,
               CASE WHEN jsonb_typeof(l.seats -> 'usage_rollup_retention_days') = 'number'
                    THEN (l.seats ->> 'usage_rollup_retention_days')::numeric::integer
                    ELSE %s END AS rollup_cap,
               s.hourly_retention_days, s.rollup_retention_days, s.updated_at
        FROM apiome.tenants t
        LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
        LEFT JOIN apiome.licenses l ON l.id = tl.license_id
        LEFT JOIN apiome.usage_retention_setting s ON s.tenant_id = t.id
        WHERE t.id = %s::uuid
        LIMIT 1
        """,
        (FREE_HOURLY_RETENTION_DAYS, FREE_ROLLUP_RETENTION_DAYS, tenant_id),
    )
    row = dict(rows[0]) if rows else {}
    hourly_cap = int(row.get("hourly_cap", FREE_HOURLY_RETENTION_DAYS))
    rollup_cap = int(row.get("rollup_cap", FREE_ROLLUP_RETENTION_DAYS))
    hourly = row.get("hourly_retention_days")
    rollup = row.get("rollup_retention_days")
    return UsageRetentionResponse(
        caps=RetentionDays(hourly_days=hourly_cap, rollup_days=rollup_cap),
        setting=RetentionDays(hourly_days=hourly, rollup_days=rollup),
        effective=RetentionDays(
            hourly_days=effective_days(hourly_cap, hourly), rollup_days=effective_days(rollup_cap, rollup)
        ),
        updated_at=row.get("updated_at"),
    )


def write_retention(
    db: Any, tenant_id: str, *, hourly_days: Optional[int], rollup_days: Optional[int], user_id: Optional[str]
) -> None:
    """Store the workspace's own retention (``None`` goes back to the tier cap).

    The caller has already checked the values against the caps
    (:func:`~app.usage_controls.check_retention`).

    Args:
        db: The database.
        tenant_id: The tenant.
        hourly_days: Days of hourly counters, or ``None``.
        rollup_days: Days of daily rollups, or ``None``.
        user_id: The user changing it.
    """
    db.execute_query(
        """
        INSERT INTO apiome.usage_retention_setting
            (tenant_id, hourly_retention_days, rollup_retention_days, updated_at, updated_by)
        VALUES (%s::uuid, %s, %s, CURRENT_TIMESTAMP, %s::uuid)
        ON CONFLICT (tenant_id) DO UPDATE SET
            hourly_retention_days = EXCLUDED.hourly_retention_days,
            rollup_retention_days = EXCLUDED.rollup_retention_days,
            updated_at = EXCLUDED.updated_at,
            updated_by = EXCLUDED.updated_by
        RETURNING tenant_id
        """,
        (tenant_id, hourly_days, rollup_days, _actor(user_id)),
    )


# ---------------------------------------------------------------------------------------------
# Sources and toolsets
# ---------------------------------------------------------------------------------------------

#: The most usage sources, and the most agent toolsets, one project's listing returns (#7196).
LIST_CAP = 1000

_SOURCE_COLUMNS = """
    id::text AS id, kind, environment, enabled, sampling_rate, field_capture, body_sample_rate,
    body_sample_until, last_received_at
"""


def _source_out(row: Dict[str, Any]) -> UsageSourceOut:
    """Adapt one ``usage_source`` row."""
    return UsageSourceOut(
        id=row["id"],
        kind=row["kind"],
        environment=row["environment"],
        enabled=bool(row["enabled"]),
        sampling_rate=float(row["sampling_rate"]),
        field_capture=bool(row["field_capture"]),
        body_samples=body_samples(row["body_sample_rate"], row["body_sample_until"], max_rate=BODY_SAMPLE_MAX_RATE),
        last_received_at=row.get("last_received_at"),
    )


def list_sources(db: Any, tenant_id: str, project_id: str) -> List[UsageSourceOut]:
    """A project's usage sources, oldest first.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.

    Returns:
        The sources (the first :data:`LIST_CAP`).
    """
    rows = db.execute_query(
        f"""
        SELECT {_SOURCE_COLUMNS}
        FROM apiome.usage_source
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid
        ORDER BY created_at, id
        LIMIT {LIST_CAP}
        """,
        (tenant_id, project_id),
    )
    return [_source_out(dict(row)) for row in rows or []]


def get_source(db: Any, tenant_id: str, project_id: str, source_id: str) -> Optional[UsageSourceOut]:
    """One source of the project, or ``None``.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.
        source_id: The source.

    Returns:
        The source, or ``None`` when the project has no such source.
    """
    if not is_uuid_string(source_id):
        return None
    rows = db.execute_query(
        f"""
        SELECT {_SOURCE_COLUMNS}
        FROM apiome.usage_source
        WHERE id = %s::uuid AND tenant_id = %s::uuid AND project_id = %s::uuid
        """,
        (source_id, tenant_id, project_id),
    )
    return _source_out(dict(rows[0])) if rows else None


def update_source(
    db: Any,
    tenant_id: str,
    project_id: str,
    source_id: str,
    *,
    sampling_rate: Optional[float] = None,
    field_capture: Optional[bool] = None,
    body_sample_rate: Optional[float] = None,
    body_sample_until: Any = _UNSET,
) -> Optional[UsageSourceOut]:
    """Change what a source captures. ``None`` (or unset) keeps a value.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.
        source_id: The source.
        sampling_rate: Head sampling in (0, 1].
        field_capture: Whether field presence is counted.
        body_sample_rate: The body-sample rate (already checked against the caps).
        body_sample_until: The end of the window (``None`` closes it); leave unset to keep it.

    Returns:
        The source after the change, or ``None`` when the project has no such source.
    """
    if not is_uuid_string(source_id):
        return None
    set_until = body_sample_until is not _UNSET
    rows = db.execute_query(
        f"""
        UPDATE apiome.usage_source
        SET sampling_rate = COALESCE(%s, sampling_rate),
            field_capture = COALESCE(%s, field_capture),
            body_sample_rate = COALESCE(%s, body_sample_rate),
            body_sample_until = CASE WHEN %s THEN %s::timestamptz ELSE body_sample_until END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid AND tenant_id = %s::uuid AND project_id = %s::uuid
        RETURNING {_SOURCE_COLUMNS}
        """,
        (
            sampling_rate,
            field_capture,
            body_sample_rate,
            set_until,
            body_sample_until if set_until else None,
            source_id,
            tenant_id,
            project_id,
        ),
    )
    return _source_out(dict(rows[0])) if rows else None


_TOOLSET_COLUMNS = """
    ts.id::text AS id, ts.version_id::text AS version_id, v.version_id AS version_label, ts.enabled,
    ts.body_capture_rate, ts.body_capture_until
"""


def _toolset_out(row: Dict[str, Any]) -> ToolsetBodySamplesOut:
    """Adapt one ``agent_toolsets`` row."""
    return ToolsetBodySamplesOut(
        id=row["id"],
        version_id=row["version_id"],
        version_label=row.get("version_label"),
        enabled=bool(row["enabled"]),
        body_samples=body_samples(
            row["body_capture_rate"], row["body_capture_until"], max_rate=AGENT_BODY_CAPTURE_MAX_RATE
        ),
    )


def list_toolsets(db: Any, tenant_id: str, project_id: str) -> List[ToolsetBodySamplesOut]:
    """The agent toolsets of a project's versions, with their body-capture opt-in.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.

    Returns:
        The toolsets, newest version first (the newest :data:`LIST_CAP`).
    """
    rows = db.execute_query(
        f"""
        SELECT {_TOOLSET_COLUMNS}
        FROM apiome.agent_toolsets ts
        JOIN apiome.versions v ON v.id = ts.version_id
        WHERE ts.tenant_id = %s::uuid AND v.project_id = %s::uuid
        ORDER BY ts.created_at DESC, ts.id
        LIMIT {LIST_CAP}
        """,
        (tenant_id, project_id),
    )
    return [_toolset_out(dict(row)) for row in rows or []]


def get_toolset(db: Any, tenant_id: str, toolset_id: str) -> Optional[ToolsetBodySamplesOut]:
    """One of the tenant's toolsets with its body-capture opt-in, or ``None``.

    Args:
        db: The database.
        tenant_id: The tenant.
        toolset_id: The toolset.

    Returns:
        The toolset, or ``None``.
    """
    if not is_uuid_string(toolset_id):
        return None
    rows = db.execute_query(
        f"""
        SELECT {_TOOLSET_COLUMNS}
        FROM apiome.agent_toolsets ts
        JOIN apiome.versions v ON v.id = ts.version_id
        WHERE ts.id = %s::uuid AND ts.tenant_id = %s::uuid
        """,
        (toolset_id, tenant_id),
    )
    return _toolset_out(dict(rows[0])) if rows else None


def update_toolset_body_samples(
    db: Any, tenant_id: str, toolset_id: str, *, rate: float, until: Optional[datetime], user_id: Optional[str]
) -> Optional[ToolsetBodySamplesOut]:
    """Open, change or close a toolset's body-capture window (AGX-3.3 columns).

    Args:
        db: The database.
        tenant_id: The tenant.
        toolset_id: The toolset.
        rate: The rate (already checked); ``0`` closes the window.
        until: The end of the window (``None`` when closing).
        user_id: The user changing it.

    Returns:
        The toolset after the change, or ``None`` when the tenant has no such toolset.
    """
    if not is_uuid_string(toolset_id):
        return None
    rows = db.execute_query(
        """
        UPDATE apiome.agent_toolsets
        SET body_capture_rate = %s, body_capture_until = %s::timestamptz,
            updated_by = %s::uuid, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid AND tenant_id = %s::uuid
        RETURNING id
        """,
        (rate, until, _actor(user_id), toolset_id, tenant_id),
    )
    return get_toolset(db, tenant_id, toolset_id) if rows else None


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------


def export_day_rows(db: Any, tenant_id: str, project_id: str, day: date) -> List[Dict[str, Any]]:
    """One UTC day of the project's ``usage_daily`` rows, with the consumer as a slug.

    A row no binding attributes (or whose consumer was erased) reads ``anonymous``. A binding's
    name or hash is never selected.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.
        day: The UTC day.

    Returns:
        The rows, in a stable order.
    """
    rows = db.execute_query(
        """
        SELECT d.day, d.environment, d.source_id::text AS source_id, s.kind AS source_kind,
               d.version_record_id::text AS version_id, v.version_id AS version_label,
               d.operation_key, d.status_code, COALESCE(c.slug, 'anonymous') AS consumer,
               d.calls, d.errors, d.latency_sum_ms, d.latency_max_ms, d.request_bytes, d.response_bytes
        FROM apiome.usage_daily d
        JOIN apiome.usage_source s ON s.id = d.source_id
        LEFT JOIN apiome.versions v ON v.id = d.version_record_id
        LEFT JOIN apiome.usage_consumer_binding b ON b.id = d.consumer_binding_id
        LEFT JOIN apiome.consumer c ON c.id = b.consumer_id
        WHERE d.tenant_id = %s::uuid AND d.project_id = %s::uuid AND d.day = %s
        ORDER BY d.environment, d.operation_key, d.status_code, consumer, d.source_id, version_id
        """,
        (tenant_id, project_id, day),
    )
    return [dict(row) for row in rows or []]


# ---------------------------------------------------------------------------------------------
# Bindings: delete, or erase
# ---------------------------------------------------------------------------------------------


def delete_all_bindings(db: Any, tenant_id: str, consumer_id: str, *, user_id: Optional[str]) -> int:
    """Stamp every live binding of a consumer deleted; attributed history is kept (RDG-1.8 rule).

    Args:
        db: The database.
        tenant_id: The tenant.
        consumer_id: The consumer.
        user_id: The deleting user.

    Returns:
        How many bindings were deleted.
    """
    rows = db.execute_query(
        """
        UPDATE apiome.usage_consumer_binding
        SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s::uuid
        WHERE tenant_id = %s::uuid AND consumer_id = %s::uuid AND deleted_at IS NULL
        RETURNING id
        """,
        (_actor(user_id), tenant_id, consumer_id),
    )
    return len(rows or [])


def erase_consumer(db: Any, tenant_id: str, consumer_id: str) -> Dict[str, int]:
    """Erase a consumer from the usage index, in one transaction (V384 ``erase_usage_consumer``).

    Its bindings (live and deleted) are deleted with their hashes, its counters are re-attributed to
    ``anonymous`` (totals unchanged), the unattributed-client rows carrying its hashes are deleted,
    and so are its runtime dependency-graph edges.

    Args:
        db: The database.
        tenant_id: The tenant.
        consumer_id: The consumer.

    Returns:
        ``bindings``, ``hourly_rows``, ``daily_rows``, ``calls``, ``unattributed_rows`` and
        ``edges`` — what was deleted or re-attributed.
    """

    def work(cursor: Any) -> Dict[str, int]:
        cursor.execute("SELECT apiome.erase_usage_consumer(%s::uuid, %s::uuid) AS result", (tenant_id, consumer_id))
        result = dict(cursor.fetchone()["result"] or {})
        cursor.execute(
            """
            DELETE FROM apiome.catalog_edges
            WHERE tenant_id = %s::uuid AND provenance = %s AND from_kind = 'consumer' AND from_id = %s::uuid
            """,
            (tenant_id, RUNTIME_PROVENANCE, consumer_id),
        )
        result["edges"] = int(cursor.rowcount or 0)
        return {key: int(value or 0) for key, value in result.items()}

    return db._guarded_tx(work)
