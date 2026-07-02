"""Outbound push webhook delivery with bounded backoff and persisted attempts (#2588)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from .config import WEBHOOK_MAX_DELIVERY_ATTEMPTS
from .database import Database
from .push_webhook_crypto import decrypt_signing_secret

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = WEBHOOK_MAX_DELIVERY_ATTEMPTS
# After attempts 1–3 fail, wait before attempts 2–4 (bounded backoff).
BACKOFF_AFTER_FAILURE_SEC = (10, 60, 300)
_RESPONSE_PREVIEW_LEN = 1024


def _stable_body(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _truncate(s: Optional[str], max_len: int) -> Optional[str]:
    if s is None:
        return None
    if len(s) <= max_len:
        return s
    return s[:max_len]


def _deliver_one_http(
    url: str,
    event_type: str,
    body: bytes,
    signature: str,
) -> tuple[Optional[int], Optional[str], Optional[str], int]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Apiome-Event": event_type,
        "X-Apiome-Signature": signature,
        "User-Agent": "Apiome-Webhooks/1.0",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            t0 = time.perf_counter()
            r = client.post(url, content=body, headers=headers)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            preview = _truncate(r.text, _RESPONSE_PREVIEW_LEN)
            ok = 200 <= r.status_code < 300
            err = None if ok else f"HTTP {r.status_code}"
            return r.status_code, preview, err, latency_ms
    except httpx.HTTPError as e:
        return None, None, str(e), 0


def _finalize_dead_letter(
    database: Database,
    event_id: str,
    attempt_number: int,
    *,
    http_status: Optional[int],
    response_body_preview: Optional[str],
    error_message: Optional[str],
    latency_ms: int,
    reason: str,
) -> None:
    database.finalize_push_webhook_delivery_attempt(
        event_id,
        attempt_number=attempt_number,
        http_status=http_status,
        response_body_preview=response_body_preview,
        error_message=error_message,
        latency_ms=latency_ms,
        new_status="dead_letter",
        new_attempt_count=attempt_number,
        next_retry_at=None,
        last_error=_truncate(reason, 2000),
    )


def deliver_one_due_event(database: Database, row: Dict[str, Any]) -> None:
    """Execute one HTTP attempt for a queued event and persist outcome."""
    event_id = str(row["event_id"])
    prev_attempt_count = int(row["attempt_count"])
    attempt_number = prev_attempt_count + 1
    payload = row["payload"]
    event_type = row["event_type"]
    url = row["subscription_url"]

    if not row["subscription_active"]:
        _finalize_dead_letter(
            database,
            event_id,
            attempt_number,
            http_status=None,
            response_body_preview=None,
            error_message="subscription inactive",
            latency_ms=0,
            reason="subscription inactive",
        )
        return

    secret = decrypt_signing_secret(row["signing_secret_encrypted"])
    if not secret:
        msg = (
            "signing secret not available for delivery "
            "(configure APIOME_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY or rotate signing secret)"
        )
        if attempt_number >= MAX_DELIVERY_ATTEMPTS:
            _finalize_dead_letter(
                database,
                event_id,
                attempt_number,
                http_status=None,
                response_body_preview=None,
                error_message=msg,
                latency_ms=0,
                reason=msg,
            )
        else:
            database.finalize_push_webhook_delivery_attempt(
                event_id,
                attempt_number=attempt_number,
                http_status=None,
                response_body_preview=None,
                error_message=msg,
                latency_ms=0,
                new_status="retrying",
                new_attempt_count=attempt_number,
                next_retry_at=_next_retry_utc(attempt_number),
                last_error="signing secret not available for delivery",
            )
        return

    body = _stable_body(payload)
    signature = _sign_payload(secret, body)
    http_status, preview, err, latency_ms = _deliver_one_http(url, event_type, body, signature)

    if http_status is not None and 200 <= http_status < 300:
        database.finalize_push_webhook_delivery_attempt(
            event_id,
            attempt_number=attempt_number,
            http_status=http_status,
            response_body_preview=preview,
            error_message=None,
            latency_ms=latency_ms,
            new_status="delivered",
            new_attempt_count=attempt_number,
            next_retry_at=None,
            last_error=None,
        )
        return

    err_msg = err or "delivery failed"
    if attempt_number >= MAX_DELIVERY_ATTEMPTS:
        _finalize_dead_letter(
            database,
            event_id,
            attempt_number,
            http_status=http_status,
            response_body_preview=preview,
            error_message=err_msg,
            latency_ms=latency_ms,
            reason=err_msg,
        )
        return

    next_at = _next_retry_utc(attempt_number)
    database.finalize_push_webhook_delivery_attempt(
        event_id,
        attempt_number=attempt_number,
        http_status=http_status,
        response_body_preview=preview,
        error_message=err_msg,
        latency_ms=latency_ms,
        new_status="retrying",
        new_attempt_count=attempt_number,
        next_retry_at=next_at,
        last_error=_truncate(err_msg, 2000),
    )


def _next_retry_utc(failed_attempt_number: int) -> datetime:
    """failed_attempt_number is 1..3 when scheduling attempts 2..4."""
    delay = BACKOFF_AFTER_FAILURE_SEC[failed_attempt_number - 1]
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


def process_due_push_webhook_deliveries(database: Database, max_events: int = 10) -> int:
    """Process up to max_events due deliveries. Returns count attempted."""
    n = 0
    for _ in range(max_events):
        row = database.get_next_due_push_webhook_delivery()
        if not row:
            break
        try:
            deliver_one_due_event(database, row)
        except Exception as exc:
            logger.exception("push webhook delivery failed for event %s", row.get("event_id"))
            # Persist a failed attempt so the event is not stuck in 'processing' and
            # backoff / dead-letter logic still applies.
            try:
                prev_attempt_count = int(row.get("attempt_count", 0))
                attempt_number = prev_attempt_count + 1
                err_msg = f"internal delivery error: {type(exc).__name__}: {exc}"
                if attempt_number >= MAX_DELIVERY_ATTEMPTS:
                    _finalize_dead_letter(
                        database,
                        str(row.get("event_id", "")),
                        attempt_number,
                        http_status=None,
                        response_body_preview=None,
                        error_message=err_msg,
                        latency_ms=0,
                        reason=err_msg,
                    )
                else:
                    database.finalize_push_webhook_delivery_attempt(
                        str(row.get("event_id", "")),
                        attempt_number=attempt_number,
                        http_status=None,
                        response_body_preview=None,
                        error_message=err_msg,
                        latency_ms=0,
                        new_status="retrying",
                        new_attempt_count=attempt_number,
                        next_retry_at=_next_retry_utc(attempt_number),
                        last_error=_truncate(err_msg, 2000),
                    )
            except Exception:
                logger.exception(
                    "failed to persist internal-error attempt for event %s", row.get("event_id")
                )
        n += 1
    return n
