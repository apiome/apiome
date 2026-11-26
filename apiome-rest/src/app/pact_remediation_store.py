"""Reading and writing stale-pact remediation state — PFX-6.2 (#6954).

:mod:`app.pact_remediation` decides; this module stores what it decides on and about (apiome-db
V448): the workspace's verification settings, provider-wide and per-pair overrides, the stale state
the sweep last saw per pair, re-publish requests, and each pair's last scheduled verification
attempt.

Every read and write is scoped to the caller's tenant: a pacticipant, target, override or request of
another workspace is "not found". Ids that are not UUIDs are "not found" without a query.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .consumer_contract_store import ConsumerActor
from .pact_remediation import (
    CODE_OVERRIDE_INVALID,
    CODE_OVERRIDE_NOT_FOUND,
    CODE_REQUEST_CLOSED,
    CODE_REQUEST_CURSOR_INVALID,
    CODE_REQUEST_NOT_FOUND,
    MAX_OVERRIDES,
    MAX_REQUEST_PAGE,
    OPEN_STATES,
    REQUEST_STATES,
    STATE_ACKNOWLEDGED,
    OverrideInput,
    OverrideList,
    OverrideRecord,
    OverrideValues,
    RemediationError,
    RepublishRequestPage,
    RepublishRequestRecord,
    ScheduledAttempt,
    VerificationSettings,
    VerificationSettingsInput,
    default_settings,
)
from .pacticipant_store import get_pacticipant
from .revision_deprecation import is_uuid_string

__all__ = [
    "acknowledge_request",
    "attempts_for_provider",
    "close_request",
    "delete_override",
    "get_request",
    "get_settings",
    "latest_request_at_for_sha",
    "list_overrides",
    "list_requests",
    "open_request",
    "open_requests_for_provider",
    "override_values_for_provider",
    "parse_time",
    "providers_with_pacts",
    "put_override",
    "record_attempt",
    "resolve_republished_on_publish",
    "save_settings",
    "set_escalation_status",
    "set_notification_status",
    "staleness_for_provider",
    "upsert_staleness",
]


def parse_time(value: Any) -> Optional[datetime]:
    """A timestamp column or ISO text as a timezone-aware ``datetime`` (UTC without a zone).

    Args:
        value: A ``datetime``, ISO 8601 text, or ``None``.

    Returns:
        The aware ``datetime``, or ``None``.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 text."""
    moment = parse_time(value)
    return moment.isoformat() if moment is not None else None


# =============================================================================================
# Settings
# =============================================================================================

_SETTINGS_COLUMNS = (
    "cadence, stale_threshold_hours, max_concurrent_runs, request_window_hours, "
    "republish_requests_enabled, updated_at"
)


def _settings_from_row(row: Mapping[str, Any]) -> VerificationSettings:
    """A settings row as the read model."""
    return VerificationSettings(
        cadence=row["cadence"],
        stale_threshold_hours=int(row["stale_threshold_hours"]),
        max_concurrent_runs=int(row["max_concurrent_runs"]),
        request_window_hours=int(row["request_window_hours"]),
        republish_requests_enabled=bool(row["republish_requests_enabled"]),
        customised=True,
        updated_at=_iso(row.get("updated_at")),
    )


def get_settings(db: Any, tenant_id: str) -> VerificationSettings:
    """The workspace's verification settings, or the defaults when it never saved any.

    Args:
        db: The database.
        tenant_id: The workspace.

    Returns:
        The settings.
    """
    rows = db.execute_query(
        f"SELECT {_SETTINGS_COLUMNS} FROM apiome.pact_verification_settings WHERE tenant_id = %s::uuid",
        (tenant_id,),
    )
    return _settings_from_row(rows[0]) if rows else default_settings()


def save_settings(
    db: Any, tenant_id: str, body: VerificationSettingsInput, *, actor: ConsumerActor
) -> VerificationSettings:
    """Replace the workspace's verification settings.

    Args:
        db: The database.
        tenant_id: The workspace.
        body: The new settings (validated by the model).
        actor: Who saved them.

    Returns:
        The stored settings.
    """
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.pact_verification_settings
            (tenant_id, cadence, stale_threshold_hours, max_concurrent_runs, request_window_hours,
             republish_requests_enabled, updated_by, updated_at)
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id) DO UPDATE SET
            cadence = EXCLUDED.cadence,
            stale_threshold_hours = EXCLUDED.stale_threshold_hours,
            max_concurrent_runs = EXCLUDED.max_concurrent_runs,
            request_window_hours = EXCLUDED.request_window_hours,
            republish_requests_enabled = EXCLUDED.republish_requests_enabled,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        RETURNING {_SETTINGS_COLUMNS}
        """,
        (
            tenant_id,
            body.cadence,
            body.stale_threshold_hours,
            body.max_concurrent_runs,
            body.request_window_hours,
            body.republish_requests_enabled,
            actor.user_id,
        ),
    )
    return _settings_from_row(rows[0])


# =============================================================================================
# Overrides
# =============================================================================================

_OVERRIDE_SELECT = """
    SELECT o.id::text AS id, o.provider_id::text AS provider_id, o.consumer_id::text AS consumer_id,
           p.slug AS provider_slug, p.name AS provider_name, c.slug AS consumer_slug, c.name AS consumer_name,
           o.cadence, o.stale_threshold_hours, t.slug AS target_slug, t.name AS target_name,
           (t.id IS NOT NULL AND t.deleted_at IS NOT NULL) AS target_deleted, o.updated_at
    FROM apiome.pact_verification_override o
    JOIN apiome.pacticipant p ON p.id = o.provider_id AND p.tenant_id = o.tenant_id
    LEFT JOIN apiome.pacticipant c ON c.id = o.consumer_id AND c.tenant_id = o.tenant_id
    LEFT JOIN apiome.verification_target t ON t.id = o.target_id AND t.tenant_id = o.tenant_id
"""


def _override_from_row(row: Mapping[str, Any]) -> OverrideRecord:
    """An override row as the read model."""
    return OverrideRecord(
        id=row["id"],
        provider=row["provider_slug"],
        provider_name=row["provider_name"],
        consumer=row.get("consumer_slug"),
        consumer_name=row.get("consumer_name"),
        cadence=row.get("cadence"),
        stale_threshold_hours=row.get("stale_threshold_hours"),
        target=row.get("target_slug"),
        target_name=row.get("target_name"),
        target_deleted=bool(row.get("target_deleted")),
        updated_at=_iso(row.get("updated_at")),
    )


def list_overrides(db: Any, tenant_id: str) -> OverrideList:
    """Every override of the workspace, by provider then consumer (provider-wide first).

    Args:
        db: The database.
        tenant_id: The workspace.

    Returns:
        The overrides.
    """
    rows = db.execute_query(
        _OVERRIDE_SELECT
        + " WHERE o.tenant_id = %s::uuid AND p.deleted_at IS NULL"
        + " ORDER BY p.slug, c.slug NULLS FIRST LIMIT %s",
        (tenant_id, MAX_OVERRIDES),
    )
    return OverrideList(overrides=[_override_from_row(row) for row in rows or []])


def override_values_for_provider(
    db: Any, tenant_id: str, provider_id: str
) -> Tuple[Optional[OverrideValues], Dict[str, OverrideValues]]:
    """A provider's overrides, as :func:`app.pact_remediation.resolve_settings` takes them.

    A deleted verification target counts as none, so the pair is reported as having no target.

    Args:
        db: The database.
        tenant_id: The workspace.
        provider_id: The provider.

    Returns:
        The provider-wide override (or ``None``) and each pair's, by consumer id.
    """
    rows = db.execute_query(
        _OVERRIDE_SELECT + " WHERE o.tenant_id = %s::uuid AND o.provider_id = %s::uuid",
        (tenant_id, provider_id),
    )
    provider: Optional[OverrideValues] = None
    pairs: Dict[str, OverrideValues] = {}
    for row in rows or []:
        values = OverrideValues(
            cadence=row.get("cadence"),
            stale_threshold_hours=row.get("stale_threshold_hours"),
            target=None if row.get("target_deleted") else row.get("target_slug"),
        )
        if row.get("consumer_id"):
            pairs[str(row["consumer_id"])] = values
        else:
            provider = values
    return provider, pairs


def put_override(db: Any, tenant_id: str, body: OverrideInput, *, actor: ConsumerActor) -> OverrideRecord:
    """Create or replace the override of a provider (no ``consumer``) or of a pair.

    Args:
        db: The database.
        tenant_id: The workspace.
        body: The override.
        actor: Who saved it.

    Returns:
        The stored override.

    Raises:
        RemediationError: :data:`CODE_OVERRIDE_INVALID` when it sets nothing, names the provider as
            its own consumer, or the workspace already has :data:`MAX_OVERRIDES`.
        PacticipantValidationError: ``pacticipant-not-found``.
        TargetValidationError: ``target-not-found``.
    """
    from .verification_target_store import get_target

    if body.cadence is None and body.stale_threshold_hours is None and body.target_ref is None:
        raise RemediationError(
            CODE_OVERRIDE_INVALID, "an override sets at least one of cadence, stale_threshold_hours, target_ref"
        )
    provider = get_pacticipant(db, tenant_id, body.provider)
    consumer = get_pacticipant(db, tenant_id, body.consumer) if body.consumer else None
    if consumer is not None and consumer.id == provider.id:
        raise RemediationError(CODE_OVERRIDE_INVALID, "a pacticipant cannot be its own consumer")
    target_id = get_target(tenant_id, body.target_ref).id if body.target_ref else None
    count = db.execute_query(
        "SELECT count(*) AS n FROM apiome.pact_verification_override WHERE tenant_id = %s::uuid", (tenant_id,)
    )
    existing = db.execute_query(
        "SELECT 1 FROM apiome.pact_verification_override WHERE tenant_id = %s::uuid AND provider_id = %s::uuid"
        " AND consumer_id IS NOT DISTINCT FROM %s::uuid",
        (tenant_id, provider.id, consumer.id if consumer else None),
    )
    if not existing and count and int(count[0]["n"]) >= MAX_OVERRIDES:
        raise RemediationError(
            CODE_OVERRIDE_INVALID, f"a workspace has at most {MAX_OVERRIDES} overrides; remove one first"
        )
    conflict = (
        "(tenant_id, provider_id, consumer_id) WHERE consumer_id IS NOT NULL"
        if consumer
        else ("(tenant_id, provider_id) WHERE consumer_id IS NULL")
    )
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.pact_verification_override
            (tenant_id, provider_id, consumer_id, cadence, stale_threshold_hours, target_id, created_by, updated_by)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s::uuid, %s::uuid, %s::uuid)
        ON CONFLICT {conflict} DO UPDATE SET
            cadence = EXCLUDED.cadence,
            stale_threshold_hours = EXCLUDED.stale_threshold_hours,
            target_id = EXCLUDED.target_id,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id::text AS id
        """,
        (
            tenant_id,
            provider.id,
            consumer.id if consumer else None,
            body.cadence,
            body.stale_threshold_hours,
            target_id,
            actor.user_id,
            actor.user_id,
        ),
    )
    stored = db.execute_query(_OVERRIDE_SELECT + " WHERE o.id = %s::uuid", (rows[0]["id"],))
    return _override_from_row(stored[0])


def delete_override(db: Any, tenant_id: str, override_id: str) -> None:
    """Remove one override of the workspace.

    Args:
        db: The database.
        tenant_id: The workspace.
        override_id: The override's id.

    Raises:
        RemediationError: :data:`CODE_OVERRIDE_NOT_FOUND`.
    """
    rows = []
    if is_uuid_string(override_id):
        rows = db.execute_query(
            "DELETE FROM apiome.pact_verification_override WHERE id = %s::uuid AND tenant_id = %s::uuid"
            " RETURNING id",
            (override_id, tenant_id),
        )
    if not rows:
        raise RemediationError(CODE_OVERRIDE_NOT_FOUND, f"no verification override '{override_id}' in this workspace")


# =============================================================================================
# Re-publish requests
# =============================================================================================

_REQUEST_SELECT = """
    SELECT r.id::text AS id, r.seq, r.provider_id::text AS provider_id, r.consumer_id::text AS consumer_id,
           p.slug AS provider_slug, p.name AS provider_name, c.slug AS consumer_slug, c.name AS consumer_name,
           r.sha, r.consumer_version, r.state, r.threshold_hours, r.reference_at, r.requested_at, r.expires_at,
           r.acknowledged_at, r.acknowledged_by_label, r.note, r.resolved_at, r.resolved_consumer_version,
           r.notification_status, r.escalation_status, r.webhook_deliveries
    FROM apiome.pact_republish_request r
    JOIN apiome.pacticipant p ON p.id = r.provider_id AND p.tenant_id = r.tenant_id
    JOIN apiome.pacticipant c ON c.id = r.consumer_id AND c.tenant_id = r.tenant_id
"""


def _request_from_row(row: Mapping[str, Any]) -> RepublishRequestRecord:
    """A request row as the read model."""
    return RepublishRequestRecord(
        id=row["id"],
        provider=row["provider_slug"],
        provider_name=row["provider_name"],
        consumer=row["consumer_slug"],
        consumer_name=row["consumer_name"],
        pact_version_sha=str(row["sha"]).strip(),
        consumer_version=row["consumer_version"],
        state=row["state"],
        threshold_hours=int(row["threshold_hours"]),
        reference_at=_iso(row.get("reference_at")),
        requested_at=_iso(row.get("requested_at")),
        expires_at=_iso(row.get("expires_at")),
        acknowledged_at=_iso(row.get("acknowledged_at")),
        acknowledged_by=row.get("acknowledged_by_label"),
        note=row.get("note"),
        resolved_at=_iso(row.get("resolved_at")),
        resolved_consumer_version=row.get("resolved_consumer_version"),
        notification_status=row.get("notification_status"),
        escalation_status=row.get("escalation_status"),
        webhook_deliveries=int(row.get("webhook_deliveries") or 0),
    )


def _decode_cursor(cursor: Optional[str]) -> Optional[int]:
    """The list position a cursor names, or ``None`` for the first page.

    Raises:
        RemediationError: :data:`CODE_REQUEST_CURSOR_INVALID`.
    """
    if not cursor:
        return None
    text = cursor.strip()
    if not text.isdigit() or len(text) > 19 or int(text) < 1:
        raise RemediationError(CODE_REQUEST_CURSOR_INVALID, f"cursor '{cursor}' is not one this API handed out")
    return int(text)


def list_requests(
    db: Any,
    tenant_id: str,
    *,
    provider_ref: Optional[str] = None,
    consumer_ref: Optional[str] = None,
    state: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = MAX_REQUEST_PAGE,
) -> RepublishRequestPage:
    """One page of the workspace's re-publish requests, newest first.

    Args:
        db: The database.
        tenant_id: The workspace.
        provider_ref: Only this provider's.
        consumer_ref: Only this consumer's.
        state: Only requests in this state, or ``open`` for requested and acknowledged ones.
        cursor: The previous page's ``next_cursor``.
        limit: Page size (1 … 50).

    Returns:
        The page.

    Raises:
        RemediationError: :data:`CODE_REQUEST_CURSOR_INVALID`.
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    before = _decode_cursor(cursor)
    clauses = ["r.tenant_id = %s::uuid"]
    params: List[Any] = [tenant_id]
    if provider_ref:
        clauses.append("r.provider_id = %s::uuid")
        params.append(get_pacticipant(db, tenant_id, provider_ref).id)
    if consumer_ref:
        clauses.append("r.consumer_id = %s::uuid")
        params.append(get_pacticipant(db, tenant_id, consumer_ref).id)
    if state == "open":
        clauses.append("r.state = ANY(%s)")
        params.append(list(OPEN_STATES))
    elif state:
        clauses.append("r.state = %s")
        params.append(state)
    if before is not None:
        clauses.append("r.seq < %s")
        params.append(before)
    size = max(1, min(int(limit), MAX_REQUEST_PAGE))
    params.append(size + 1)
    rows = (
        db.execute_query(
            _REQUEST_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY r.seq DESC LIMIT %s", tuple(params)
        )
        or []
    )
    page = rows[:size]
    return RepublishRequestPage(
        requests=[_request_from_row(row) for row in page],
        next_cursor=str(page[-1]["seq"]) if len(rows) > size else None,
    )


def get_request(db: Any, tenant_id: str, request_id: str) -> RepublishRequestRecord:
    """One re-publish request of the workspace.

    Raises:
        RemediationError: :data:`CODE_REQUEST_NOT_FOUND`.
    """
    rows = []
    if is_uuid_string(request_id):
        rows = db.execute_query(
            _REQUEST_SELECT + " WHERE r.id = %s::uuid AND r.tenant_id = %s::uuid", (request_id, tenant_id)
        )
    if not rows:
        raise RemediationError(CODE_REQUEST_NOT_FOUND, f"no re-publish request '{request_id}' in this workspace")
    return _request_from_row(rows[0])


def acknowledge_request(
    db: Any, tenant_id: str, request_id: str, note: Optional[str], *, actor: ConsumerActor
) -> RepublishRequestRecord:
    """The consumer acknowledges an open request (acknowledging again updates the note).

    Args:
        db: The database.
        tenant_id: The workspace.
        request_id: The request.
        note: What the consumer will do.
        actor: Who acknowledged it.

    Returns:
        The request.

    Raises:
        RemediationError: :data:`CODE_REQUEST_NOT_FOUND`; :data:`CODE_REQUEST_CLOSED` when it is no
            longer open.
    """
    current = get_request(db, tenant_id, request_id)
    if current.state not in OPEN_STATES:
        raise RemediationError(
            CODE_REQUEST_CLOSED, f"the re-publish request is {current.state}; only an open request can be acknowledged"
        )
    rows = db.execute_query(
        """
        UPDATE apiome.pact_republish_request
        SET state = %s, acknowledged_at = COALESCE(acknowledged_at, CURRENT_TIMESTAMP),
            acknowledged_by = %s::uuid, acknowledged_by_label = %s, note = %s
        WHERE id = %s::uuid AND tenant_id = %s::uuid AND state = ANY(%s)
        RETURNING id
        """,
        (
            STATE_ACKNOWLEDGED,
            actor.user_id,
            (actor.label or "")[:320] or None,
            note,
            request_id,
            tenant_id,
            list(OPEN_STATES),
        ),
    )
    if not rows:
        raise RemediationError(CODE_REQUEST_CLOSED, "the re-publish request closed meanwhile")
    return get_request(db, tenant_id, request_id)


def open_requests_for_provider(db: Any, tenant_id: str, provider_id: str) -> Dict[str, RepublishRequestRecord]:
    """Each consumer's open request for the provider, by consumer id."""
    rows = db.execute_query(
        _REQUEST_SELECT + " WHERE r.tenant_id = %s::uuid AND r.provider_id = %s::uuid AND r.state = ANY(%s)",
        (tenant_id, provider_id, list(OPEN_STATES)),
    )
    return {str(row["consumer_id"]): _request_from_row(row) for row in rows or []}


def latest_request_at_for_sha(
    db: Any, tenant_id: str, provider_id: str, consumer_id: str, sha: str
) -> Optional[datetime]:
    """When the newest request for one pact version of a pair was opened, if any."""
    rows = db.execute_query(
        "SELECT max(requested_at) AS at FROM apiome.pact_republish_request"
        " WHERE tenant_id = %s::uuid AND provider_id = %s::uuid AND consumer_id = %s::uuid AND sha = %s",
        (tenant_id, provider_id, consumer_id, sha),
    )
    return parse_time(rows[0]["at"]) if rows else None


def open_request(
    db: Any,
    tenant_id: str,
    provider_id: str,
    consumer_id: str,
    *,
    sha: str,
    consumer_version: str,
    threshold_hours: int,
    reference_at: datetime,
    window_hours: int,
) -> Optional[str]:
    """Open a re-publish request for a pair, unless one is open already.

    Returns:
        The new request's id, or ``None`` when the pair already had an open one.
    """
    rows = db.execute_query(
        """
        INSERT INTO apiome.pact_republish_request
            (tenant_id, provider_id, consumer_id, sha, consumer_version, threshold_hours, reference_at, expires_at)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
                CURRENT_TIMESTAMP + make_interval(hours => %s))
        ON CONFLICT (tenant_id, provider_id, consumer_id) WHERE state IN ('requested', 'acknowledged')
        DO NOTHING
        RETURNING id::text AS id
        """,
        (tenant_id, provider_id, consumer_id, sha, consumer_version[:255], threshold_hours, reference_at, window_hours),
    )
    return rows[0]["id"] if rows else None


def close_request(
    db: Any,
    tenant_id: str,
    request_id: str,
    state: str,
    *,
    resolved_consumer_version: Optional[str] = None,
) -> bool:
    """Move an open request to ``republished``, ``cleared`` or ``expired``.

    Returns:
        True when it was still open and is now closed.
    """
    if state not in REQUEST_STATES or state in OPEN_STATES:
        raise ValueError(f"not a closing state: {state}")
    rows = db.execute_query(
        """
        UPDATE apiome.pact_republish_request
        SET state = %s, resolved_at = CURRENT_TIMESTAMP, resolved_consumer_version = %s
        WHERE id = %s::uuid AND tenant_id = %s::uuid AND state = ANY(%s)
        RETURNING id
        """,
        (state, resolved_consumer_version, request_id, tenant_id, list(OPEN_STATES)),
    )
    return bool(rows)


def set_notification_status(db: Any, tenant_id: str, request_id: str, status: Optional[str], deliveries: int) -> None:
    """Record what notifying the consumer of a new request did."""
    db.execute_query(
        "UPDATE apiome.pact_republish_request SET notification_status = %s,"
        " webhook_deliveries = webhook_deliveries + %s WHERE id = %s::uuid AND tenant_id = %s::uuid RETURNING id",
        (status, deliveries, request_id, tenant_id),
    )


def set_escalation_status(db: Any, tenant_id: str, request_id: str, status: Optional[str], deliveries: int) -> None:
    """Record what escalating an expired request did."""
    db.execute_query(
        "UPDATE apiome.pact_republish_request SET escalation_status = %s,"
        " webhook_deliveries = webhook_deliveries + %s WHERE id = %s::uuid AND tenant_id = %s::uuid RETURNING id",
        (status, deliveries, request_id, tenant_id),
    )


def resolve_republished_on_publish(
    db: Any, tenant_id: str, consumer_id: str, provider_id: str, consumer_version: str
) -> int:
    """Close the pair's open request as ``republished`` right after the consumer published again.

    The sweep would close it on its next tick; this makes the answer immediate. Never raises.

    Returns:
        The number of requests closed (0 or 1).
    """
    try:
        rows = db.execute_query(
            """
            UPDATE apiome.pact_republish_request
            SET state = 'republished', resolved_at = CURRENT_TIMESTAMP, resolved_consumer_version = %s
            WHERE tenant_id = %s::uuid AND provider_id = %s::uuid AND consumer_id = %s::uuid
              AND state IN ('requested', 'acknowledged')
            RETURNING id
            """,
            (consumer_version[:255], tenant_id, provider_id, consumer_id),
        )
        return len(rows or [])
    except Exception:  # noqa: BLE001 - a publish never fails because of remediation bookkeeping
        import logging

        logging.getLogger(__name__).exception("re-publish request resolution failed for tenant %s", tenant_id)
        return 0


# =============================================================================================
# Staleness and scheduled attempts
# =============================================================================================


def staleness_for_provider(db: Any, tenant_id: str, provider_id: str) -> Dict[str, Mapping[str, Any]]:
    """The stale state the sweep last saw for each of a provider's pairs, by consumer id."""
    rows = db.execute_query(
        "SELECT consumer_id::text AS consumer_id, sha, stale, reference_at, changed_at"
        " FROM apiome.pact_staleness WHERE tenant_id = %s::uuid AND provider_id = %s::uuid",
        (tenant_id, provider_id),
    )
    return {str(row["consumer_id"]): row for row in rows or []}


def upsert_staleness(
    db: Any,
    tenant_id: str,
    provider_id: str,
    consumer_id: str,
    *,
    sha: str,
    stale: bool,
    reference_at: datetime,
    threshold_hours: int,
) -> None:
    """Record the stale state of a pair (``changed_at`` moves only when ``stale`` changes)."""
    db.execute_query(
        """
        INSERT INTO apiome.pact_staleness
            (tenant_id, provider_id, consumer_id, sha, stale, reference_at, threshold_hours)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, provider_id, consumer_id) DO UPDATE SET
            changed_at = CASE WHEN pact_staleness.stale = EXCLUDED.stale
                              THEN pact_staleness.changed_at ELSE CURRENT_TIMESTAMP END,
            sha = EXCLUDED.sha, stale = EXCLUDED.stale, reference_at = EXCLUDED.reference_at,
            threshold_hours = EXCLUDED.threshold_hours, checked_at = CURRENT_TIMESTAMP
        RETURNING consumer_id
        """,
        (tenant_id, provider_id, consumer_id, sha, stale, reference_at, threshold_hours),
    )


def attempts_for_provider(db: Any, tenant_id: str, provider_id: str) -> Dict[str, ScheduledAttempt]:
    """Each pair's last scheduled verification attempt, by consumer id."""
    rows = db.execute_query(
        "SELECT consumer_id::text AS consumer_id, sha, attempted_at, status, code, reason"
        " FROM apiome.pact_scheduled_verification WHERE tenant_id = %s::uuid AND provider_id = %s::uuid",
        (tenant_id, provider_id),
    )
    return {
        str(row["consumer_id"]): ScheduledAttempt(
            pact_version_sha=str(row["sha"]).strip(),
            attempted_at=_iso(row.get("attempted_at")),
            status=row["status"],
            code=row.get("code"),
            reason=row.get("reason"),
        )
        for row in rows or []
    }


def record_attempt(
    db: Any,
    tenant_id: str,
    provider_id: str,
    consumer_id: str,
    *,
    sha: str,
    status: str,
    code: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Record a pair's scheduled verification attempt (replacing the previous one)."""
    db.execute_query(
        """
        INSERT INTO apiome.pact_scheduled_verification
            (tenant_id, provider_id, consumer_id, sha, status, code, reason)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, provider_id, consumer_id) DO UPDATE SET
            sha = EXCLUDED.sha, status = EXCLUDED.status, code = EXCLUDED.code, reason = EXCLUDED.reason,
            attempted_at = CURRENT_TIMESTAMP
        RETURNING consumer_id
        """,
        (
            tenant_id,
            provider_id,
            consumer_id,
            sha,
            status,
            (code or None) and code[:64],
            (reason or None) and reason[:1000],
        ),
    )


def providers_with_pacts(db: Any, *, limit: int) -> List[Tuple[str, str, str]]:
    """Every live provider that has a pact, with its workspace, oldest workspace first.

    Args:
        db: The database.
        limit: The most providers to return.

    Returns:
        ``(tenant_id, tenant_slug, provider_id)`` triples.
    """
    rows = db.execute_query(
        """
        SELECT DISTINCT p.tenant_id::text AS tenant_id, t.slug AS tenant_slug, p.id::text AS provider_id
        FROM apiome.pacticipant p
        JOIN apiome.tenants t ON t.id = p.tenant_id
        WHERE p.deleted_at IS NULL
          AND EXISTS (SELECT 1 FROM apiome.pact_publication pub WHERE pub.provider_id = p.id)
        ORDER BY 1, 3
        LIMIT %s
        """,
        (limit,),
    )
    return [(row["tenant_id"], row["tenant_slug"], row["provider_id"]) for row in rows or []]
