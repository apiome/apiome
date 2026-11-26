"""The delivery log of contract webhooks, and redelivering a firing — PFX-5.6 (#6950).

The **Webhooks** page of the Contracts workspace shows what each webhook did. The Pact Broker's
own routes (PFX-1.9) list firings by pact or by verification result only; this module reads them by
webhook and for the whole workspace, and sends one again:

* :func:`list_deliveries` — the firings of the workspace or of one webhook, newest first, narrowed
  by status, one page at a time behind an opaque cursor;
* :func:`latest_deliveries` — the newest firing of each webhook, for the list's **Last delivery**;
* :func:`redeliver` — queue a firing again. It is a new firing (``trigger_type`` ``user``) with the
  same event and template parameters; the original and its log are kept as they were.

Everything starts from the caller's tenant: an id from another tenant reads as not found. Nothing
here reads or returns a secret — a firing's queued payload holds only template parameters.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .pact_publication import PactPublicationError
from .pact_webhook import CODE_TRIGGERED_WEBHOOK_NOT_FOUND, CODE_WEBHOOK_INVALID
from .pact_webhook_store import (
    _TRIGGERED_SELECT,
    TriggeredWebhookRecord,
    _triggered,
    enqueue_triggered_webhook,
    get_webhook,
)
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_DELIVERY_CURSOR_INVALID",
    "CODE_DELIVERY_IN_PROGRESS",
    "CODE_WEBHOOK_DISABLED",
    "DELIVERY_STATUSES",
    "DeliveryPage",
    "MAX_DELIVERY_PAGE",
    "decode_cursor",
    "encode_cursor",
    "latest_deliveries",
    "list_deliveries",
    "redeliver",
]

#: The cursor is not one this API handed out (HTTP 400).
CODE_DELIVERY_CURSOR_INVALID = "pact-webhook-delivery-cursor-invalid"
#: The firing is still queued or being retried; sending it again would deliver it twice (HTTP 409).
CODE_DELIVERY_IN_PROGRESS = "pact-webhook-delivery-in-progress"
#: The webhook is disabled; a redelivery would be dead-lettered unsent (HTTP 409).
CODE_WEBHOOK_DISABLED = "pact-webhook-disabled"

#: The statuses a firing can have (:func:`app.pact_webhook_store.triggered_status`).
DELIVERY_STATUSES = ("success", "failure", "retrying", "not_run")

#: The largest page of the delivery log.
MAX_DELIVERY_PAGE = 50

#: How each status reads in the queue's terms (``push_webhook_delivery_events``).
_STATUS_SQL = {
    "success": "e.status = 'delivered'",
    "failure": "e.status = 'dead_letter'",
    "retrying": "(e.status = 'retrying' OR (e.status IN ('pending', 'processing') AND e.attempt_count > 0))",
    "not_run": "(e.status IN ('pending', 'processing') AND e.attempt_count = 0)",
}


class DeliveryPage(BaseModel):
    """One page of a delivery log.

    Attributes:
        deliveries: The firings, newest first.
        next_cursor: Pass as ``cursor`` for the next page; ``None`` at the end.
    """

    model_config = ConfigDict(extra="forbid")

    deliveries: List[TriggeredWebhookRecord] = Field(default_factory=list)
    next_cursor: Optional[str] = None


def _invalid_cursor(cursor: str) -> PactPublicationError:
    """The refusal of a cursor this API did not hand out."""
    return PactPublicationError(
        CODE_DELIVERY_CURSOR_INVALID, f"cursor '{cursor}' is not a delivery-log cursor this API handed out"
    )


def encode_cursor(created_at: str, triggered_id: str) -> str:
    """The opaque cursor that resumes a log after one firing.

    Args:
        created_at: The firing's ``triggered_at`` (ISO-8601).
        triggered_id: The firing's ``uuid``.

    Returns:
        URL-safe base64 of ``created_at|id``, without padding.
    """
    raw = f"{created_at}|{triggered_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: Optional[str]) -> Optional[Tuple[str, str]]:
    """The position a cursor names.

    Args:
        cursor: The ``next_cursor`` of an earlier page, or ``None`` / ``""`` for the first page.

    Returns:
        ``(created_at, id)``, or ``None`` for the first page.

    Raises:
        PactPublicationError: ``pact-webhook-delivery-cursor-invalid``.
    """
    if cursor is None or cursor.strip() == "":
        return None
    text = cursor.strip()
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise _invalid_cursor(cursor) from exc
    created_at, _, triggered_id = decoded.partition("|")
    try:
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise _invalid_cursor(cursor) from exc
    if not is_uuid_string(triggered_id):
        raise _invalid_cursor(cursor)
    return created_at, triggered_id


def list_deliveries(
    db: Any,
    tenant_id: str,
    *,
    webhook_id: Optional[str] = None,
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 25,
) -> DeliveryPage:
    """One page of the delivery log, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        webhook_id: Only this webhook's firings (checked to be the tenant's); every webhook when
            ``None``.
        status: Only firings with this status (one of :data:`DELIVERY_STATUSES`).
        cursor: The ``next_cursor`` of the previous page.
        limit: The page size (1 … :data:`MAX_DELIVERY_PAGE`).

    Returns:
        The page.

    Raises:
        PactPublicationError: ``pact-webhook-not-found`` for a webhook the tenant does not have;
            ``pact-webhook-delivery-cursor-invalid``; ``pact-webhook-invalid`` for an unknown status.
    """
    if status is not None and status not in _STATUS_SQL:
        raise PactPublicationError(
            CODE_WEBHOOK_INVALID,
            f"status '{status}' is not one of {', '.join(DELIVERY_STATUSES)}",
            pointer="/status",
        )
    position = decode_cursor(cursor)
    size = max(1, min(int(limit), MAX_DELIVERY_PAGE))
    where = ""
    params: List[Any] = [tenant_id]
    if webhook_id is not None:
        get_webhook(db, tenant_id, webhook_id)  # the 404 for another tenant's or a missing webhook
        where += " AND t.webhook_id = %s::uuid"
        params.append(webhook_id)
    if status is not None:
        where += " AND " + _STATUS_SQL[status]
    if position is not None:
        where += " AND (t.created_at, t.id) < (%s::timestamptz, %s::uuid)"
        params += [position[0], position[1]]
    query = _TRIGGERED_SELECT + where + " ORDER BY t.created_at DESC, t.id DESC LIMIT %s"
    params.append(size + 1)
    rows = [dict(row) for row in db.execute_query(query, tuple(params)) or []]
    deliveries = [_triggered(row) for row in rows[:size]]
    next_cursor = None
    if len(rows) > size and deliveries:
        last = deliveries[-1]
        next_cursor = encode_cursor(str(last.triggered_at), last.id)
    return DeliveryPage(deliveries=deliveries, next_cursor=next_cursor)


def latest_deliveries(db: Any, tenant_id: str) -> Dict[str, TriggeredWebhookRecord]:
    """The newest firing of each of the tenant's webhooks.

    Args:
        db: The database.
        tenant_id: The caller's tenant.

    Returns:
        ``{webhook_id: firing}``; a webhook that never fired is absent.
    """
    newest = (
        db.execute_query(
            """
            SELECT latest.id::text AS id
            FROM apiome.pact_webhook w
            CROSS JOIN LATERAL (
                SELECT t.id FROM apiome.pact_triggered_webhook t
                WHERE t.webhook_id = w.id AND t.tenant_id = w.tenant_id
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT 1
            ) latest
            WHERE w.tenant_id = %s::uuid
            """,
            (tenant_id,),
        )
        or []
    )
    ids = [str(row["id"]) for row in newest]
    if not ids:
        return {}
    rows = db.execute_query(_TRIGGERED_SELECT + " AND t.id = ANY(%s::uuid[])", (tenant_id, ids)) or []
    return {item.webhook_id: item for item in (_triggered(dict(row)) for row in rows)}


def _not_found(triggered_id: str) -> PactPublicationError:
    """The refusal of a firing the tenant does not have."""
    return PactPublicationError(
        CODE_TRIGGERED_WEBHOOK_NOT_FOUND, f"no triggered webhook '{triggered_id}' in this workspace"
    )


def redeliver(db: Any, tenant_id: str, triggered_id: str) -> TriggeredWebhookRecord:
    """Queue a firing again: a new firing of the same webhook, event and template parameters.

    Only a finished firing (``success`` or ``failure``) is sent again; the worker then makes up to
    the usual number of attempts. The original firing and its log are left as they were.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        triggered_id: The firing to send again.

    Returns:
        The new firing (status ``not_run``).

    Raises:
        PactPublicationError: ``pact-triggered-webhook-not-found``; ``pact-webhook-delivery-in-progress``
            while the firing is still queued or being retried; ``pact-webhook-disabled`` when its
            webhook is disabled.
    """
    if not is_uuid_string(str(triggered_id or "")):
        raise _not_found(triggered_id)

    def work(cursor: Any) -> str:
        cursor.execute(
            """
            SELECT t.webhook_id::text AS webhook_id, t.consumer_id::text AS consumer_id,
                   t.provider_id::text AS provider_id, t.event_name, t.consumer_version_number,
                   t.pact_version_sha, t.verification_number,
                   e.status::text AS delivery_status, e.payload, w.enabled
            FROM apiome.pact_triggered_webhook t
            JOIN apiome.push_webhook_delivery_events e ON e.id = t.delivery_event_id
            JOIN apiome.pact_webhook w ON w.id = t.webhook_id AND w.tenant_id = t.tenant_id
            WHERE t.tenant_id = %s::uuid AND t.id = %s::uuid
            FOR UPDATE OF t
            """,
            (tenant_id, triggered_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise _not_found(triggered_id)
        if row["delivery_status"] not in ("delivered", "dead_letter"):
            raise PactPublicationError(
                CODE_DELIVERY_IN_PROGRESS,
                "this delivery is still queued or being retried; redeliver it once it has succeeded or failed",
            )
        if not row["enabled"]:
            raise PactPublicationError(CODE_WEBHOOK_DISABLED, "the webhook is disabled; enable it before redelivering")
        payload = row.get("payload") or {}
        parameters = payload.get("parameters") if isinstance(payload, dict) else None
        return enqueue_triggered_webhook(
            cursor,
            tenant_id=tenant_id,
            webhook_id=row["webhook_id"],
            consumer_id=row["consumer_id"],
            provider_id=row["provider_id"],
            event_name=row["event_name"],
            parameters=parameters if isinstance(parameters, dict) else {},
            consumer_version_number=row.get("consumer_version_number"),
            sha=(row.get("pact_version_sha") or "").strip() or None,
            verification_number=row.get("verification_number"),
            trigger_type="user",
        )

    created = db._guarded_tx(work)
    rows = db.execute_query(_TRIGGERED_SELECT + " AND t.id = %s::uuid", (tenant_id, created)) or []
    if not rows:  # pragma: no cover - the row was written in the transaction above
        raise _not_found(created)
    return _triggered(dict(rows[0]))
