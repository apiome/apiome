"""
Push webhook subscription CRUD for downstream integrations (CI, catalogs) — #2587.

Secrets are stored hashed; API responses expose signingSecretRef only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

import psycopg2.errors
from fastapi import APIRouter, Depends, HTTPException
from pydantic import HttpUrl, TypeAdapter

from .auth import validate_authentication
from .database import db
from .permissions import enforce_permission, Resource, Action
from .models import (
    PushWebhookDeadLetterItem,
    PushWebhookDeliveryAttemptItem,
    PushWebhookDeliveryEventDetailResponse,
    PushWebhookSubscriptionCreateRequest,
    PushWebhookSubscriptionResponse,
    PushWebhookSubscriptionUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/push-webhook-subscriptions", tags=["webhooks"])

_https_url_adapter = TypeAdapter(HttpUrl)


def normalize_push_webhook_url(raw: str) -> str:
    """
    Canonical form for duplicate detection: https, lower host, trim trailing slash on path,
    strip fragment, disallow userinfo.
    """
    raw = raw.strip()
    try:
        _https_url_adapter.validate_python(raw)
    except Exception:
        raise ValueError("Invalid HTTPS URL") from None

    p = urlparse(raw)
    if p.scheme.lower() != "https":
        raise ValueError("Webhook URL must use https")
    if not p.hostname:
        raise ValueError("Webhook URL must include a host")
    if p.username is not None or p.password is not None:
        raise ValueError("Webhook URL must not embed credentials")

    netloc = p.netloc.lower()
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse(("https", netloc, path, "", p.query, ""))


def _row_to_response(row: Dict[str, Any]) -> PushWebhookSubscriptionResponse:
    return PushWebhookSubscriptionResponse(
        id=str(row["id"]),
        url=row["url"],
        active=bool(row["active"]),
        signing_secret_ref=str(row["signing_secret_ref"]),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _duplicate_http() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "WEBHOOK_URL_DUPLICATE",
            "message": "A push webhook subscription with this normalized URL already exists for this tenant.",
        },
    )


@router.get("/{tenant_slug}/deliveries/dead-letter", response_model=List[PushWebhookDeadLetterItem])
async def list_push_webhook_dead_letter_deliveries(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[PushWebhookDeadLetterItem]:
    """List terminal dead-letter webhook deliveries for the tenant (#2588)."""
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    rows = db.list_push_webhook_dead_letter_events(tenant_id)
    return [
        PushWebhookDeadLetterItem(
            id=str(r["id"]),
            subscription_id=str(r["subscription_id"]),
            event_type=r["event_type"],
            payload=dict(r["payload"]) if r.get("payload") is not None else {},
            attempt_count=int(r["attempt_count"]),
            last_error=r.get("last_error"),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in rows
    ]


@router.get("/{tenant_slug}/deliveries/{event_id}", response_model=PushWebhookDeliveryEventDetailResponse)
async def get_push_webhook_delivery_detail(
    tenant_slug: str,
    event_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PushWebhookDeliveryEventDetailResponse:
    """Delivery event with full attempt history (#2588)."""
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    ev = db.get_push_webhook_delivery_event(tenant_id, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Webhook delivery event not found")
    attempts_raw = db.list_push_webhook_delivery_attempts(event_id)
    attempts = [
        PushWebhookDeliveryAttemptItem(
            attempt_number=int(a["attempt_number"]),
            http_status=a.get("http_status"),
            response_body_preview=a.get("response_body_preview"),
            error_message=a.get("error_message"),
            latency_ms=a.get("latency_ms"),
            attempted_at=a.get("attempted_at"),
        )
        for a in attempts_raw
    ]
    return PushWebhookDeliveryEventDetailResponse(
        id=str(ev["id"]),
        subscription_id=str(ev["subscription_id"]),
        event_type=ev["event_type"],
        status=str(ev["status"]),
        payload=dict(ev["payload"]) if ev.get("payload") is not None else {},
        attempt_count=int(ev["attempt_count"]),
        next_retry_at=ev.get("next_retry_at"),
        last_error=ev.get("last_error"),
        created_at=ev.get("created_at"),
        updated_at=ev.get("updated_at"),
        attempts=attempts,
    )


@router.get("/{tenant_slug}", response_model=List[PushWebhookSubscriptionResponse])
async def list_push_webhook_subscriptions(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[PushWebhookSubscriptionResponse]:
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    rows = db.list_push_webhook_subscriptions(tenant_id)
    return [_row_to_response(r) for r in rows]


@router.post("/{tenant_slug}", response_model=PushWebhookSubscriptionResponse)
async def create_push_webhook_subscription(
    tenant_slug: str,
    body: PushWebhookSubscriptionCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PushWebhookSubscriptionResponse:
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.CREATE)
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    try:
        norm = normalize_push_webhook_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        row = db.create_push_webhook_subscription(
            tenant_id,
            body.url,
            norm,
            body.signing_secret,
            active=body.active,
        )
    except psycopg2.errors.UniqueViolation:
        raise _duplicate_http() from None
    except Exception:
        logger.exception("create_push_webhook_subscription")
        raise HTTPException(status_code=500, detail="Failed to create push webhook subscription") from None

    return _row_to_response(row)


@router.get("/{tenant_slug}/{subscription_id}", response_model=PushWebhookSubscriptionResponse)
async def get_push_webhook_subscription(
    tenant_slug: str,
    subscription_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PushWebhookSubscriptionResponse:
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    row = db.get_push_webhook_subscription(tenant_id, subscription_id)
    if not row:
        raise HTTPException(status_code=404, detail="Push webhook subscription not found")
    return _row_to_response(row)


@router.patch("/{tenant_slug}/{subscription_id}", response_model=PushWebhookSubscriptionResponse)
async def update_push_webhook_subscription(
    tenant_slug: str,
    subscription_id: str,
    body: PushWebhookSubscriptionUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PushWebhookSubscriptionResponse:
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]

    if body.url is None and body.active is None and body.signing_secret is None:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: url, active, signingSecret",
        )

    url_val: str | None = None
    norm_val: str | None = None
    if body.url is not None:
        try:
            norm_val = normalize_push_webhook_url(body.url)
            url_val = body.url
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        row = db.update_push_webhook_subscription(
            tenant_id,
            subscription_id,
            url=url_val,
            url_normalized=norm_val,
            active=body.active,
            signing_secret_plain=body.signing_secret,
        )
    except ValueError as e:
        if str(e) == "no_updates":
            raise HTTPException(
                status_code=400,
                detail="Provide at least one of: url, active, signingSecret",
            ) from e
        raise HTTPException(status_code=500, detail="Invalid update request") from e
    except psycopg2.errors.UniqueViolation:
        raise _duplicate_http() from None
    except Exception:
        logger.exception("update_push_webhook_subscription")
        raise HTTPException(status_code=500, detail="Failed to update push webhook subscription") from None

    if not row:
        raise HTTPException(status_code=404, detail="Push webhook subscription not found")
    return _row_to_response(row)
