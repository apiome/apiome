"""``/v1/tenants/{tenant}/pact-webhook-deliveries`` — the webhook delivery log, PFX-5.6 (#6950).

What the **Webhooks** page of the Contracts workspace reads and does beside the Pact Broker's
webhook routes (PFX-1.9):

* ``GET …/pact-webhook-deliveries`` — the firings of the workspace, or of one webhook
  (``webhook``), newest first, narrowed by ``status``, one page at a time (``cursor``, ``limit``);
* ``GET …/pact-webhook-deliveries/latest`` — the newest firing of each webhook;
* ``GET …/pact-webhook-deliveries/{id}`` — one firing and the log of each attempt;
* ``POST …/pact-webhook-deliveries/{id}/redeliver`` — send a finished firing again, as a new firing.

They live beside the Pact Broker surface, not under ``…/pact-broker``, because no Pact Broker or
PactFlow client knows them; that surface stays the catalogued, PactFlow-compatible one.

Reading needs ``pacts:view``; redelivering ``pacts:edit`` (as running a saved webhook does). Only
the caller's tenant is read. No response carries a secret: the logs are the ones the sender wrote,
with every secret already removed.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .pact_audit import audited_write
from .pact_publication import PactPublicationError
from .pact_webhook import (
    CODE_TRIGGERED_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_INVALID,
    CODE_WEBHOOK_NOT_FOUND,
    validate_webhook_uuid,
)
from .pact_webhook_delivery_log import (
    CODE_DELIVERY_CURSOR_INVALID,
    CODE_DELIVERY_IN_PROGRESS,
    CODE_WEBHOOK_DISABLED,
    MAX_DELIVERY_PAGE,
    latest_deliveries,
    list_deliveries,
    redeliver,
)
from .pact_webhook_store import TriggeredWebhookRecord, get_triggered_webhook_logs
from .permissions import Action, Resource, enforce_permission

__all__ = ["delivery_document", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-webhook-deliveries"

_STATUS_BY_CODE = {
    CODE_WEBHOOK_INVALID: 400,
    CODE_DELIVERY_CURSOR_INVALID: 400,
    CODE_WEBHOOK_NOT_FOUND: 404,
    CODE_TRIGGERED_WEBHOOK_NOT_FOUND: 404,
    CODE_DELIVERY_IN_PROGRESS: 409,
    CODE_WEBHOOK_DISABLED: 409,
}

_DELIVERY_NOT_FOUND = {404: {"description": "`pact-triggered-webhook-not-found`: no such delivery in this workspace."}}


def _http_error(exc: PactPublicationError) -> HTTPException:
    """Translate a refusal into ``{"detail": {"code", "message"[, "pointer"]}}`` with its status."""
    detail: Dict[str, Any] = {"code": exc.code, "message": str(exc)}
    pointer = getattr(exc, "pointer", None)
    if pointer is not None:
        detail["pointer"] = pointer
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=detail)


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def delivery_document(item: TriggeredWebhookRecord) -> Dict[str, Any]:
    """Render one firing for the delivery log.

    Args:
        item: The firing.

    Returns:
        ``id``, ``webhookId``, ``name`` (``POST host``), ``status``, ``attemptsMade``,
        ``attemptsRemaining``, ``triggerType``, ``eventName``, ``consumer`` and ``provider``
        (``{name, slug}``), ``consumerVersionNumber``, ``pactVersionSha``, ``verificationNumber``
        and ``triggeredAt``.
    """
    return {
        "id": item.id,
        "webhookId": item.webhook_id,
        "name": item.name,
        "status": item.status,
        "attemptsMade": item.attempts_made,
        "attemptsRemaining": item.attempts_remaining,
        "triggerType": item.trigger_type,
        "eventName": item.event_name,
        "consumer": {"name": item.consumer_name, "slug": item.consumer_slug},
        "provider": {"name": item.provider_name, "slug": item.provider_slug},
        "consumerVersionNumber": item.consumer_version_number,
        "pactVersionSha": item.sha,
        "verificationNumber": item.verification_number,
        "triggeredAt": item.triggered_at,
    }


@router.get(
    _PREFIX,
    summary="List webhook deliveries",
    description=(
        "The firings of the workspace's contract webhooks, newest first: each with its status "
        "(`success`, `failure` — dead-lettered after every attempt, `retrying`, `not_run`), attempts, "
        "the event, the pact that caused it and how it was triggered (`resource_creation` or `user` "
        "for a redelivery). `webhook` narrows to one webhook, `status` to one status. Pass "
        "`nextCursor` back as `cursor` for the next page. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-webhook-delivery-cursor-invalid` or `pact-webhook-invalid` (unknown status)."},
        404: {"description": "`pact-webhook-not-found`: no such webhook in this workspace."},
    },
)
def read_deliveries(
    tenant_slug: str,
    webhook: Optional[str] = Query(None, description="Only this webhook's deliveries (its `uuid`)."),
    status: Optional[Literal["success", "failure", "retrying", "not_run"]] = Query(
        None, description="Only deliveries with this status."
    ),
    cursor: Optional[str] = Query(None, description="The `nextCursor` of the previous page."),
    limit: int = Query(25, ge=1, le=MAX_DELIVERY_PAGE, description="The page size."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """List one page of the delivery log.

    Args:
        tenant_slug: The tenant in the URL.
        webhook: Only this webhook's firings.
        status: Only firings with this status.
        cursor: Where the page starts.
        limit: The page size.
        auth_data: The authenticated principal.

    Returns:
        ``{"deliveries": [...], "nextCursor": str | None}``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        webhook_id = validate_webhook_uuid(webhook) if webhook is not None else None
        page = list_deliveries(
            db, _tenant_id(auth_data), webhook_id=webhook_id, status=status, cursor=cursor, limit=limit
        )
    except PactPublicationError as exc:
        raise _http_error(exc) from exc
    return {"deliveries": [delivery_document(item) for item in page.deliveries], "nextCursor": page.next_cursor}


@router.get(
    _PREFIX + "/latest",
    summary="Latest delivery of each webhook",
    description=(
        "The newest firing of each of the workspace's contract webhooks, keyed by webhook `uuid`; a "
        "webhook that never fired is absent. Requires `pacts:view`."
    ),
)
def read_latest_deliveries(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read the newest firing of each webhook.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        ``{"latest": {webhook_id: delivery}}``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    latest = latest_deliveries(db, _tenant_id(auth_data))
    return {"latest": {webhook_id: delivery_document(item) for webhook_id, item in latest.items()}}


@router.get(
    _PREFIX + "/{delivery_id}",
    summary="Read a webhook delivery",
    description=(
        "One firing and the log of each attempt (`attempt`, `success`, `status`, `logs`, "
        "`createdAt`), oldest first — what was sent and what came back, every secret removed. "
        "Requires `pacts:view`."
    ),
    responses=_DELIVERY_NOT_FOUND,
)
def read_delivery(
    tenant_slug: str,
    delivery_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read one firing and its execution log.

    Args:
        tenant_slug: The tenant in the URL.
        delivery_id: The firing's ``uuid``.
        auth_data: The authenticated principal.

    Returns:
        The delivery with ``executions``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        logs = get_triggered_webhook_logs(db, _tenant_id(auth_data), (delivery_id or "").strip().lower())
    except PactPublicationError as exc:
        raise _http_error(exc) from exc
    return {**delivery_document(logs.triggered), "executions": logs.executions}


@router.post(
    _PREFIX + "/{delivery_id}/redeliver",
    status_code=202,
    summary="Redeliver a webhook delivery",
    description=(
        "Send a finished firing (`success` or `failure`) again: a new firing of the same webhook, "
        "with the same event and template parameters, queued now and retried as any other "
        "(`triggerType` `user`). The original and its log are kept. Answers `202` with the new "
        "delivery. Requires `pacts:edit`."
    ),
    responses={
        **_DELIVERY_NOT_FOUND,
        409: {
            "description": (
                "`pact-webhook-delivery-in-progress`: the delivery is still queued or being retried; "
                "`pact-webhook-disabled`: its webhook is disabled."
            )
        },
    },
)
@audited_write("pacts.webhook.redeliver", "pact-webhook-delivery/{delivery_id}")
def post_redeliver(
    tenant_slug: str,
    delivery_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Queue a firing again.

    Args:
        tenant_slug: The tenant in the URL.
        delivery_id: The firing to send again.
        auth_data: The authenticated principal.

    Returns:
        The new delivery, ``202``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT)
    try:
        created = redeliver(db, _tenant_id(auth_data), (delivery_id or "").strip().lower())
    except PactPublicationError as exc:
        raise _http_error(exc) from exc
    return delivery_document(created)
