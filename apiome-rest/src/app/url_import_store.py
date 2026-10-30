"""Storage for URL-sourced import lineages — ``apiome.url_import_specs`` (RAR-6.1, #3538).

Every function takes the database handle first and runs one statement through
``db.execute_query``. Rows come back as plain dicts. The rules that decide what to write live in
:mod:`app.url_import_refresh`; the sweep that calls these is :mod:`app.url_import_refresh_sweep`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from .url_import_refresh import STATUS_DIVERGED, STATUS_FAILED, STATUS_REFRESHED, STATUS_REFRESHING

__all__ = [
    "BACKOFF_MAX_EXPONENT",
    "get_spec",
    "get_version_for_checksum",
    "list_due",
    "list_specs",
    "record_anchors",
    "record_check",
    "record_diverged",
    "record_failure",
    "record_finished",
    "record_started",
    "tenant_slug",
    "update_settings",
    "upsert_spec",
]

#: A failing lineage waits its interval × 2^n, n capped here (×32).
BACKOFF_MAX_EXPONENT = 5

_COLUMNS = """
    s.id, s.tenant_id, s.project_id, s.url, s.source_kind, s.format_override, s.content_type,
    s.options_json, s.spec_schema_version, s.created_by, s.authenticated, s.auto_refresh_enabled,
    s.refresh_interval_seconds, s.etag, s.last_modified, s.content_checksum, s.last_version_id,
    s.post_import_checksum, s.last_checked_at, s.last_refreshed_at, s.last_status, s.last_reason,
    s.last_error, s.consecutive_failures, s.backoff_until, s.pending_job_id, s.pending_etag,
    s.pending_last_modified, s.pending_checksum, s.pending_started_at, s.created_at, s.updated_at
"""


def upsert_spec(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    url: str,
    source_kind: str,
    format_override: Optional[str],
    content_type: Optional[str],
    options: Mapping[str, Any],
    created_by: Optional[str],
    authenticated: bool,
    etag: Optional[str],
    last_modified: Optional[str],
    content_checksum: Optional[str],
    last_version_id: Optional[str],
    post_import_checksum: Optional[str],
    last_error: Optional[str] = None,
) -> Dict[str, Any]:
    """Record (or re-record) the lineage of one URL import.

    Importing the same URL into the same project again replaces the stored spec and anchors and
    clears the refresh state; the person's ``auto_refresh_enabled`` and cadence are kept.

    Returns:
        The stored row.
    """
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.url_import_specs AS s
            (tenant_id, project_id, url, source_kind, format_override, content_type, options_json,
             created_by, authenticated, etag, last_modified, content_checksum, last_version_id,
             post_import_checksum, last_error, last_status)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s::uuid, %s, %s, %s, %s, %s::uuid, %s, %s,
                CASE WHEN %s::text IS NULL THEN NULL ELSE '{STATUS_FAILED}' END)
        ON CONFLICT (project_id, url) DO UPDATE SET
            source_kind = EXCLUDED.source_kind,
            format_override = EXCLUDED.format_override,
            content_type = EXCLUDED.content_type,
            options_json = EXCLUDED.options_json,
            created_by = EXCLUDED.created_by,
            authenticated = EXCLUDED.authenticated,
            etag = EXCLUDED.etag,
            last_modified = EXCLUDED.last_modified,
            content_checksum = EXCLUDED.content_checksum,
            last_version_id = EXCLUDED.last_version_id,
            post_import_checksum = EXCLUDED.post_import_checksum,
            last_error = EXCLUDED.last_error,
            last_status = EXCLUDED.last_status,
            last_reason = NULL,
            consecutive_failures = 0,
            backoff_until = NULL,
            pending_job_id = NULL,
            pending_etag = NULL,
            pending_last_modified = NULL,
            pending_checksum = NULL,
            pending_started_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        RETURNING {_COLUMNS}
        """,
        (
            tenant_id,
            project_id,
            url,
            source_kind,
            format_override,
            content_type,
            json.dumps(dict(options or {})),
            created_by,
            bool(authenticated),
            etag,
            last_modified,
            content_checksum,
            last_version_id,
            post_import_checksum,
            last_error,
            last_error,
        ),
    )
    return dict(rows[0])


def list_specs(db: Any, tenant_id: str, *, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """A tenant's URL lineages on live projects, newest first; optionally one project's."""
    clause, params = ("AND s.project_id = %s::uuid", (tenant_id, project_id)) if project_id else ("", (tenant_id,))
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}, p.name AS project_name, p.slug AS project_slug
        FROM apiome.url_import_specs s
        JOIN apiome.projects p ON p.id = s.project_id AND p.deleted_at IS NULL
        WHERE s.tenant_id = %s::uuid {clause}
        ORDER BY s.updated_at DESC, s.id
        """,
        params,
    )
    return [dict(row) for row in rows]


def get_spec(db: Any, tenant_id: str, spec_id: str) -> Optional[Dict[str, Any]]:
    """One lineage of the tenant, or ``None``."""
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}, p.name AS project_name, p.slug AS project_slug
        FROM apiome.url_import_specs s
        JOIN apiome.projects p ON p.id = s.project_id AND p.deleted_at IS NULL
        WHERE s.tenant_id = %s::uuid AND s.id = %s::uuid
        """,
        (tenant_id, spec_id),
    )
    return dict(rows[0]) if rows else None


def update_settings(
    db: Any,
    tenant_id: str,
    spec_id: str,
    *,
    auto_refresh_enabled: Optional[bool],
    refresh_interval_seconds: Optional[int],
    clear_interval: bool = False,
) -> Optional[Dict[str, Any]]:
    """Turn a lineage's refresh on or off and set its cadence; ``None`` leaves a field as it is.

    Args:
        clear_interval: Reset the cadence to the deployment default.

    Returns:
        The updated row, or ``None`` when the lineage is not the tenant's.
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.url_import_specs AS s SET
            auto_refresh_enabled = COALESCE(%s, s.auto_refresh_enabled),
            refresh_interval_seconds = CASE WHEN %s THEN NULL ELSE COALESCE(%s, s.refresh_interval_seconds) END,
            backoff_until = CASE WHEN %s IS TRUE THEN NULL ELSE s.backoff_until END,
            consecutive_failures = CASE WHEN %s IS TRUE THEN 0 ELSE s.consecutive_failures END,
            updated_at = CURRENT_TIMESTAMP
        WHERE s.tenant_id = %s::uuid AND s.id = %s::uuid
        RETURNING {_COLUMNS}
        """,
        (
            auto_refresh_enabled,
            bool(clear_interval),
            refresh_interval_seconds,
            auto_refresh_enabled,
            auto_refresh_enabled,
            tenant_id,
            spec_id,
        ),
    )
    return dict(rows[0]) if rows else None


def list_due(db: Any, *, default_interval_seconds: int, min_interval_seconds: int, limit: int) -> List[Dict[str, Any]]:
    """Lineages a sweep tick should look at, least recently checked first.

    A lineage is due when refresh is on, it was not imported with credentials, its project is
    live, and either an import it started is in flight (to follow it) or its cadence has elapsed
    and it is not backing off. The cadence is the lineage's own interval (at least
    ``min_interval_seconds``) or ``default_interval_seconds``.
    """
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}, p.name AS project_name, p.slug AS project_slug
        FROM apiome.url_import_specs s
        JOIN apiome.projects p ON p.id = s.project_id AND p.deleted_at IS NULL
        WHERE s.auto_refresh_enabled AND NOT s.authenticated
          AND (
            s.pending_job_id IS NOT NULL
            OR (
              (s.backoff_until IS NULL OR s.backoff_until <= CURRENT_TIMESTAMP)
              AND (s.last_checked_at IS NULL
                   OR s.last_checked_at <= CURRENT_TIMESTAMP - make_interval(
                        secs => GREATEST(COALESCE(s.refresh_interval_seconds, %s), %s)))
            )
          )
        ORDER BY s.last_checked_at NULLS FIRST, s.id
        LIMIT %s
        """,
        (int(default_interval_seconds), int(min_interval_seconds), int(limit)),
    )
    return [dict(row) for row in rows]


def tenant_slug(db: Any, tenant_id: str) -> Optional[str]:
    """The tenant's slug (the spec-import job is scoped by it)."""
    rows = db.execute_query("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (tenant_id,))
    return str(rows[0]["slug"]) if rows else None


def get_version_for_checksum(db: Any, tenant_id: str, version_id: str) -> Optional[Dict[str, Any]]:
    """The live version row :func:`app.spec_snapshot.build_live_spec` needs, or ``None``."""
    rows = db.execute_query(
        """
        SELECT v.id, v.version_id, v.metadata,
               p.description AS project_description, p.metadata AS project_metadata
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
        WHERE v.id = %s::uuid AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
        """,
        (version_id, tenant_id),
    )
    return dict(rows[0]) if rows else None


def record_check(db: Any, spec_id: str, *, status: str, reason: Optional[str]) -> None:
    """A check that ended without importing (up to date, or held as diverged): no failure."""
    db.execute_query(
        """
        UPDATE apiome.url_import_specs SET
            last_checked_at = CURRENT_TIMESTAMP, last_status = %s, last_reason = %s, last_error = NULL,
            consecutive_failures = 0, backoff_until = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid
        RETURNING id
        """,
        (status, reason, spec_id),
    )


def record_anchors(
    db: Any, spec_id: str, *, etag: Optional[str], last_modified: Optional[str], checksum: Optional[str], reason: str
) -> None:
    """Store the validators and checksum a check fetched, without importing (a ``baseline``)."""
    db.execute_query(
        """
        UPDATE apiome.url_import_specs SET
            etag = %s, last_modified = %s, content_checksum = %s,
            last_checked_at = CURRENT_TIMESTAMP, last_status = 'up-to-date', last_reason = %s, last_error = NULL,
            consecutive_failures = 0, backoff_until = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid
        RETURNING id
        """,
        (etag, last_modified, checksum, reason, spec_id),
    )


def record_failure(db: Any, spec_id: str, *, reason: str, error: str, default_interval_seconds: int) -> None:
    """A failed check or import: count it and back off for the interval × 2^failures (capped)."""
    db.execute_query(
        f"""
        UPDATE apiome.url_import_specs AS s SET
            last_checked_at = CURRENT_TIMESTAMP, last_status = '{STATUS_FAILED}', last_reason = %s,
            last_error = %s, consecutive_failures = s.consecutive_failures + 1,
            backoff_until = CURRENT_TIMESTAMP + make_interval(
                secs => COALESCE(s.refresh_interval_seconds, %s) * power(2, LEAST(s.consecutive_failures + 1, %s))),
            pending_job_id = NULL, pending_etag = NULL, pending_last_modified = NULL,
            pending_checksum = NULL, pending_started_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE s.id = %s::uuid
        RETURNING s.id
        """,
        (reason, error[:2000], int(default_interval_seconds), BACKOFF_MAX_EXPONENT, spec_id),
    )


def record_started(
    db: Any,
    spec_id: str,
    *,
    job_id: str,
    etag: Optional[str],
    last_modified: Optional[str],
    checksum: Optional[str],
    reason: str,
) -> None:
    """A refresh import started; its validators become the anchors once it succeeds."""
    db.execute_query(
        f"""
        UPDATE apiome.url_import_specs SET
            last_checked_at = CURRENT_TIMESTAMP, last_status = '{STATUS_REFRESHING}', last_reason = %s,
            last_error = NULL, pending_job_id = %s, pending_etag = %s, pending_last_modified = %s,
            pending_checksum = %s, pending_started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid
        RETURNING id
        """,
        (reason, job_id, etag, last_modified, checksum, spec_id),
    )


def record_diverged(db: Any, spec_id: str, *, reason: str) -> None:
    """A newer document was held because the version was edited in Apiome (RAR-4.4)."""
    record_check(db, spec_id, status=STATUS_DIVERGED, reason=reason)


def record_finished(db: Any, spec_id: str, *, version_id: Optional[str], post_import_checksum: Optional[str]) -> None:
    """The refresh import succeeded: its validators and version become the lineage's anchors."""
    db.execute_query(
        f"""
        UPDATE apiome.url_import_specs SET
            etag = pending_etag, last_modified = pending_last_modified, content_checksum = pending_checksum,
            last_version_id = COALESCE(%s::uuid, last_version_id), post_import_checksum = %s,
            last_refreshed_at = CURRENT_TIMESTAMP, last_status = '{STATUS_REFRESHED}', last_error = NULL,
            consecutive_failures = 0, backoff_until = NULL,
            pending_job_id = NULL, pending_etag = NULL, pending_last_modified = NULL,
            pending_checksum = NULL, pending_started_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid
        RETURNING id
        """,
        (version_id, post_import_checksum, spec_id),
    )
