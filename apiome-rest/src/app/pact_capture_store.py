"""Reads and writes of consumer-tagged mock captures — PFX-9.1 (#7319).

The mock runtime writes the captures (``apiome_mock.consumer_capture``); this module is the REST
side: reading sessions and their calls back, private capture URLs, and the retention setting.

Every statement is bound to the caller's ``tenant_id``, so nothing crosses a workspace, and every
read of a session or call also requires ``expires_at > CURRENT_TIMESTAMP``: an expired capture is
never shown, even before the runtime's sweeper deletes it. Writes run in one transaction with their
``access_audit`` row (:func:`app.pact_cleanup_store.audit_tx`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from .config import settings
from .consumer_contract_store import ConsumerActor
from .keyset_lists import ListOrder, SortColumn, newest_first
from .pact_capture import (
    CAPTURE_URL_SEGMENT,
    DEFAULT_RETENTION_DAYS,
    new_link_token,
)
from .pact_cleanup_store import audit_tx
from .revision_deprecation import is_uuid_string

__all__ = [
    "CALLS_ORDER",
    "LINKS_ORDER",
    "SESSIONS_ORDER",
    "CaptureNotFoundError",
    "create_link",
    "delete_session",
    "list_calls",
    "list_links",
    "list_sessions",
    "read_session",
    "read_settings",
    "revoke_link",
    "save_retention",
]

#: Sessions newest activity first.
SESSIONS_ORDER = newest_first("pact-capture-sessions", "s.last_call_at", "s.id", timestamp_field="last_call_at")

#: A session's calls in the order they were made.
CALLS_ORDER = ListOrder("pact-capture-calls", (SortColumn("c.id", "int", ("id",)),))

#: Capture URLs newest first.
LINKS_ORDER = newest_first("pact-capture-links", "l.created_at", "l.id")


class CaptureNotFoundError(LookupError):
    """The session, link, project or version does not exist in the caller's workspace (or expired).

    Attributes:
        code: A stable error code for the 404 body.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _user_id(actor: ConsumerActor) -> Optional[str]:
    return str(actor.user_id) if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------


def read_settings(execute_query: Any, tenant_id: str) -> Dict[str, Any]:
    """The tenant's capture settings, with the defaults when it has none.

    Args:
        execute_query: ``db.execute_query``.
        tenant_id: The caller's tenant.

    Returns:
        ``retention_days``, ``configured``, ``refused_calls``, ``last_refused_reason``,
        ``last_refused_at``, ``updated_by_label``, ``updated_at``.
    """
    rows = (
        execute_query(
            """
        SELECT retention_days, refused_calls, last_refused_reason, last_refused_at, updated_by_label, updated_at
        FROM apiome.mock_consumer_capture_settings
        WHERE tenant_id = %s::uuid
        """,
            (tenant_id,),
        )
        or []
    )
    if not rows:
        return {
            "retention_days": DEFAULT_RETENTION_DAYS,
            "configured": False,
            "refused_calls": 0,
            "last_refused_reason": None,
            "last_refused_at": None,
            "updated_by_label": None,
            "updated_at": None,
        }
    row = dict(rows[0])
    return {
        "retention_days": int(row["retention_days"]),
        # A row the runtime opened only to count refusals has no editor and still holds the default.
        "configured": row.get("updated_by_label") is not None,
        "refused_calls": int(row["refused_calls"]),
        "last_refused_reason": row.get("last_refused_reason"),
        "last_refused_at": row.get("last_refused_at"),
        "updated_by_label": row.get("updated_by_label"),
        "updated_at": row.get("updated_at"),
    }


def save_retention(db: Any, tenant_id: str, retention_days: int, *, actor: ConsumerActor) -> Dict[str, Any]:
    """Set how many days captures are kept, audited as ``pacts.capture.settings``.

    The new value applies to calls recorded from now on; captures already stored keep the expiry
    they were written with.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        retention_days: Days (already validated by the request model).
        actor: Who is saving.

    Returns:
        The settings as stored.
    """

    def work(cursor: Any) -> None:
        cursor.execute(
            """
            INSERT INTO apiome.mock_consumer_capture_settings
              (tenant_id, retention_days, updated_by, updated_by_label, updated_at)
            VALUES (%s::uuid, %s, %s::uuid, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (tenant_id) DO UPDATE SET
              retention_days = EXCLUDED.retention_days,
              updated_by = EXCLUDED.updated_by,
              updated_by_label = EXCLUDED.updated_by_label,
              updated_at = CURRENT_TIMESTAMP
            """,
            (tenant_id, retention_days, _user_id(actor), actor.label or "unknown"),
        )
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.capture.settings",
            actor,
            "pact-captures/settings",
            {"retention_days": retention_days},
        )

    db._guarded_tx(work)
    return read_settings(db.execute_query, tenant_id)


# ---------------------------------------------------------------------------------------------
# Sessions and calls
# ---------------------------------------------------------------------------------------------

_SESSION_COLUMNS = """
    s.id, s.project_slug, s.version_label, s.consumer, s.consumer_version, s.first_call_at,
    s.last_call_at, s.call_count, s.refused_count, s.refused, s.expires_at
"""


def _session(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "project": row["project_slug"],
        "version": row["version_label"],
        "consumer": row["consumer"],
        "consumer_version": row["consumer_version"],
        "first_call_at": row["first_call_at"],
        "last_call_at": row["last_call_at"],
        "call_count": int(row["call_count"]),
        "refused_count": int(row["refused_count"]),
        "refused": {str(k): int(v) for k, v in _json(row["refused"], {}).items()},
        "expires_at": row["expires_at"],
    }


def list_sessions(
    execute_query: Any,
    tenant_id: str,
    *,
    project: Optional[str] = None,
    version: Optional[str] = None,
    consumer: Optional[str] = None,
    limit: int,
    cursor: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """The tenant's live capture sessions, newest activity first.

    Args:
        execute_query: ``db.execute_query``.
        tenant_id: The caller's tenant.
        project: Only this project slug.
        version: Only this version label.
        consumer: Only this consumer (exact).
        limit: Rows to read (the route passes ``limit + 1``).
        cursor: :data:`SESSIONS_ORDER` values of the last session already seen.

    Returns:
        Session dictionaries (with ``last_call_at`` and ``id`` for the cursor).
    """
    filters: List[str] = []
    params: List[Any] = [tenant_id]
    for column, value in (("s.project_slug", project), ("s.version_label", version), ("s.consumer", consumer)):
        if value is not None:
            filters.append(f" AND {column} = %s")
            params.append(value)
    after_sql, after_params, limit_sql, limit_params = SESSIONS_ORDER.window(limit, cursor)
    rows = (
        execute_query(
            f"""
        SELECT {_SESSION_COLUMNS}
        FROM apiome.mock_consumer_capture_session s
        WHERE s.tenant_id = %s::uuid AND s.expires_at > CURRENT_TIMESTAMP{"".join(filters)}{after_sql}
        ORDER BY {SESSIONS_ORDER.order_by}{limit_sql}
        """,
            (*params, *after_params, *limit_params),
        )
        or []
    )
    return [_session(dict(row)) for row in rows]


def read_session(execute_query: Any, tenant_id: str, session_id: str) -> Dict[str, Any]:
    """One live session of the tenant.

    Raises:
        CaptureNotFoundError: ``capture-session-not-found`` — unknown, another tenant's, or expired.
    """
    rows = (
        execute_query(
            f"""
            SELECT {_SESSION_COLUMNS}
            FROM apiome.mock_consumer_capture_session s
            WHERE s.id = %s::uuid AND s.tenant_id = %s::uuid AND s.expires_at > CURRENT_TIMESTAMP
            """,
            (session_id, tenant_id),
        )
        if is_uuid_string(session_id)
        else []
    ) or []
    if not rows:
        retention = read_settings(execute_query, tenant_id)["retention_days"]
        raise CaptureNotFoundError(
            "capture-session-not-found",
            f"No capture session {session_id}. Its calls may be gone: captures are kept {retention} days.",
        )
    return _session(dict(rows[0]))


def list_calls(
    execute_query: Any,
    tenant_id: str,
    session_id: str,
    *,
    limit: int,
    cursor: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """A session's live calls in the order they were made.

    Args:
        execute_query: ``db.execute_query``.
        tenant_id: The caller's tenant (checked on the call row itself, too).
        session_id: The session (already read with :func:`read_session`).
        limit: Rows to read (the route passes ``limit + 1``).
        cursor: :data:`CALLS_ORDER` values of the last call already seen.

    Returns:
        Call dictionaries; ``id`` is an integer (stringified by the route model).
    """
    after_sql, after_params, limit_sql, limit_params = CALLS_ORDER.window(limit, cursor)
    rows = (
        execute_query(
            f"""
        SELECT c.id, c.captured_at, c.via, c.link_id, c.method, c.path, c.path_template, c.operation_key,
               c.status, c.origin, c.origin_detail, c.scenario, c.mock_session, c.request, c.response,
               c.redactions, c.redaction_count
        FROM apiome.mock_consumer_capture_call c
        WHERE c.session_id = %s::uuid AND c.tenant_id = %s::uuid
          AND c.expires_at > CURRENT_TIMESTAMP{after_sql}
        ORDER BY {CALLS_ORDER.order_by}{limit_sql}
        """,
            (session_id, tenant_id, *after_params, *limit_params),
        )
        or []
    )
    calls = []
    for raw in rows:
        row = dict(raw)
        calls.append(
            {
                **row,
                "id": int(row["id"]),
                "link_id": str(row["link_id"]) if row.get("link_id") else None,
                "request": _json(row["request"], {}),
                "response": _json(row["response"], {}),
                "redactions": _json(row["redactions"], []),
            }
        )
    return calls


def delete_session(db: Any, tenant_id: str, session_id: str, *, actor: ConsumerActor) -> None:
    """Delete a session and its calls, audited as ``pacts.capture.session.delete``.

    Raises:
        CaptureNotFoundError: ``capture-session-not-found`` when it is not the tenant's.
    """
    session = read_session(db.execute_query, tenant_id, session_id)

    def work(cursor: Any) -> int:
        cursor.execute(
            "DELETE FROM apiome.mock_consumer_capture_session WHERE id = %s::uuid AND tenant_id = %s::uuid",
            (session_id, tenant_id),
        )
        deleted = int(cursor.rowcount or 0)
        if deleted:
            audit_tx(
                db,
                cursor,
                tenant_id,
                "pacts.capture.session.delete",
                actor,
                f"pact-captures/sessions/{session_id}",
                {
                    "consumer": session["consumer"],
                    "consumer_version": session["consumer_version"],
                    "project": session["project"],
                    "version": session["version"],
                    "calls": session["call_count"],
                },
            )
        return deleted

    if not db._guarded_tx(work):
        raise CaptureNotFoundError("capture-session-not-found", f"No capture session {session_id}.")


# ---------------------------------------------------------------------------------------------
# Private capture URLs
# ---------------------------------------------------------------------------------------------


def _link_path(tenant_slug: str, project: str, version: str, token: str) -> str:
    return f"/{tenant_slug}/{project}/{version}/{CAPTURE_URL_SEGMENT}/{token}"


def _link(row: Dict[str, Any], *, now: datetime) -> Dict[str, Any]:
    if row.get("revoked_at") is not None:
        state = "revoked"
    elif row["expires_at"] <= now:
        state = "expired"
    else:
        state = "live"
    return {
        "id": str(row["id"]),
        "project": row["project_slug"],
        "version": row["version_label"],
        "consumer": row["consumer"],
        "consumer_version": row["consumer_version"],
        "token_prefix": row["token_prefix"],
        "state": state,
        "created_by_label": row.get("created_by_label"),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "revoked_at": row.get("revoked_at"),
    }


_LINK_SELECT = """
    SELECT l.id, p.slug AS project_slug, v.version_id AS version_label, l.consumer, l.consumer_version,
           l.token_prefix, l.created_by_label, l.created_at, l.expires_at, l.revoked_at
    FROM apiome.mock_consumer_capture_link l
    INNER JOIN apiome.versions v ON v.id = l.version_id
    INNER JOIN apiome.projects p ON p.id = v.project_id
"""


def list_links(
    execute_query: Any, tenant_id: str, *, limit: int, cursor: Optional[Sequence[Any]] = None
) -> List[Dict[str, Any]]:
    """The tenant's capture URLs, newest first (live, revoked and expired), never their tokens."""
    after_sql, after_params, limit_sql, limit_params = LINKS_ORDER.window(limit, cursor)
    rows = (
        execute_query(
            f"""
        {_LINK_SELECT}
        WHERE l.tenant_id = %s::uuid{after_sql}
        ORDER BY {LINKS_ORDER.order_by}{limit_sql}
        """,
            (tenant_id, *after_params, *limit_params),
        )
        or []
    )
    now = datetime.now(timezone.utc)
    return [_link(dict(row), now=now) for row in rows]


def create_link(
    db: Any,
    tenant_id: str,
    *,
    project: str,
    version: str,
    consumer: str,
    consumer_version: str,
    expires_in_days: int,
    actor: ConsumerActor,
) -> Dict[str, Any]:
    """Create a private capture URL, audited as ``pacts.capture.link.create``.

    The token is returned here once and never again: only its SHA-256 digest is stored.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        project: Project slug.
        version: Version label.
        consumer: Consumer the calls are recorded for.
        consumer_version: That consumer's version.
        expires_in_days: Days until the link stops working (validated by the request model).
        actor: Who is creating it.

    Returns:
        The link, with ``token``, ``path`` and ``url``.

    Raises:
        CaptureNotFoundError: ``capture-version-not-found`` when the version is not the tenant's.
    """
    versions = (
        db.execute_query(
            """
        SELECT v.id, t.slug AS tenant_slug
        FROM apiome.versions v
        INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
        INNER JOIN apiome.tenants t ON t.id = p.tenant_id
        WHERE p.tenant_id = %s::uuid AND p.slug = %s AND v.version_id = %s AND v.deleted_at IS NULL
        """,
            (tenant_id, project, version),
        )
        or []
    )
    if not versions:
        raise CaptureNotFoundError("capture-version-not-found", f"No version {version!r} of project {project!r}.")
    version_row = dict(versions[0])
    token, token_hash, token_prefix = new_link_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO apiome.mock_consumer_capture_link
              (tenant_id, version_id, consumer, consumer_version, token_hash, token_prefix,
               created_by, created_by_label, expires_at)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::uuid, %s, %s)
            RETURNING id, consumer, consumer_version, token_prefix, created_by_label, created_at, expires_at,
                      revoked_at
            """,
            (
                tenant_id,
                str(version_row["id"]),
                consumer,
                consumer_version,
                token_hash,
                token_prefix,
                _user_id(actor),
                actor.label,
                expires_at,
            ),
        )
        row = dict(cursor.fetchone())
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.capture.link.create",
            actor,
            f"pact-captures/links/{row['id']}",
            {
                "project": project,
                "version": version,
                "consumer": consumer,
                "consumer_version": consumer_version,
                "token_prefix": token_prefix,
                "expires_at": expires_at.isoformat(),
            },
        )
        return row

    row = db._guarded_tx(work)
    link = _link({**row, "project_slug": project, "version_label": version}, now=datetime.now(timezone.utc))
    path = _link_path(str(version_row["tenant_slug"]), project, version, token)
    return {**link, "token": token, "path": path, "url": f"{settings.mock_public_base_url.rstrip('/')}{path}"}


def revoke_link(db: Any, tenant_id: str, link_id: str, *, actor: ConsumerActor) -> Dict[str, Any]:
    """Revoke a capture URL, audited as ``pacts.capture.link.revoke``.

    Revoking twice is a no-op that answers the link as it is. The mock stops recording through it
    within its link cache's lifetime (30 seconds by default).

    Raises:
        CaptureNotFoundError: ``capture-link-not-found`` when it is not the tenant's.
    """
    if not is_uuid_string(link_id):
        raise CaptureNotFoundError("capture-link-not-found", f"No capture URL {link_id}.")

    def work(cursor: Any) -> int:
        cursor.execute(
            """
            UPDATE apiome.mock_consumer_capture_link SET revoked_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND revoked_at IS NULL
            """,
            (link_id, tenant_id),
        )
        changed = int(cursor.rowcount or 0)
        if changed:
            audit_tx(db, cursor, tenant_id, "pacts.capture.link.revoke", actor, f"pact-captures/links/{link_id}", {})
        return changed

    db._guarded_tx(work)
    rows = (
        db.execute_query(f"{_LINK_SELECT} WHERE l.id = %s::uuid AND l.tenant_id = %s::uuid", (link_id, tenant_id)) or []
    )
    if not rows:
        raise CaptureNotFoundError("capture-link-not-found", f"No capture URL {link_id}.")
    return _link(dict(rows[0]), now=datetime.now(timezone.utc))
