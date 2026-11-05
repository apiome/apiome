"""The export webhook delivery pipeline — MFX-38.2 (#4329).

A delivery is one signed body sent until the receiver takes it. The rules (body, signature, fetch
link) live in :mod:`app.export_webhook_delivery`; what lives here is sending it, what each answer
means, and the run row (``export_webhook_delivery_runs``, V355):

* :func:`start_delivery` records the run (``delivering``) and makes the **first attempt at once**, so
  the caller sees the receiver's answer in the response.
* A **retryable** failure — no answer (connection refused, timeout), ``408``, ``425``, ``429`` or any
  ``5xx`` — leaves the run ``retrying`` with a ``next_attempt_at`` on the push-webhook backoff
  (#2588: 10 s, 60 s, 5 min), or later when a ``429`` / ``503`` asks so with ``Retry-After``.
  :func:`process_due_export_webhook_deliveries`, ticked by the webhook delivery sweep, makes the
  next attempt; after :data:`MAX_ATTEMPTS` the run is ``failed`` (``…-attempts-exhausted``).
* A **final** failure fails the run at once: the SSRF guard refused the destination (it runs on every
  attempt and on every redirect hop, so a host that later resolves inward is still refused), or the
  receiver answered a ``3xx`` (redirects are not followed) or another ``4xx``.

Every attempt re-sends the **same bytes with the same signature** — the secret is not kept, so there
is nothing to re-sign with — and carries ``X-Apiome-Delivery`` (the run id) so a receiver can
de-duplicate, plus ``X-Apiome-Delivery-Attempt``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import httpx

from .database import Database
from .export_webhook_delivery import EVENT_TYPE
from .push_webhook_delivery import BACKOFF_AFTER_FAILURE_SEC, MAX_DELIVERY_ATTEMPTS, retry_after_seconds
from .ssrf_guard import build_guarded_client

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_ATTEMPTS_EXHAUSTED",
    "ERROR_DESTINATION_REFUSED",
    "ERROR_INTERNAL",
    "ERROR_RECEIVER_ERROR",
    "ERROR_REJECTED",
    "ERROR_UNREACHABLE",
    "MAX_ATTEMPTS",
    "RUN_STATUSES",
    "AttemptResult",
    "attempt_delivery",
    "process_due_export_webhook_deliveries",
    "send_attempt",
    "start_delivery",
]

RUN_STATUS_PENDING = "pending"
RUN_STATUS_DELIVERING = "delivering"
RUN_STATUS_RETRYING = "retrying"
RUN_STATUS_DELIVERED = "delivered"
RUN_STATUS_FAILED = "failed"

#: Every status, matching V355's ``export_webhook_delivery_runs_status_check``.
RUN_STATUSES = (RUN_STATUS_PENDING, RUN_STATUS_DELIVERING, RUN_STATUS_RETRYING, RUN_STATUS_DELIVERED,
                RUN_STATUS_FAILED)

#: The push-webhook attempt budget (#2588): the first attempt and three retries.
MAX_ATTEMPTS = MAX_DELIVERY_ATTEMPTS

ERROR_DESTINATION_REFUSED = "export-webhook-delivery-destination-refused"
ERROR_REJECTED = "export-webhook-delivery-rejected"
ERROR_UNREACHABLE = "export-webhook-delivery-unreachable"
ERROR_RECEIVER_ERROR = "export-webhook-delivery-receiver-error"
ERROR_ATTEMPTS_EXHAUSTED = "export-webhook-delivery-attempts-exhausted"
ERROR_INTERNAL = "export-webhook-delivery-internal-error"

#: Statuses worth trying again: the receiver is busy, rate-limiting, or broken for now.
_RETRYABLE_STATUSES = frozenset({408, 425, 429})
_REQUEST_TIMEOUT_SEC = 30.0
_RESPONSE_PREVIEW_CHARS = 512
_ERROR_MESSAGE_CHARS = 2000

ClientFactory = Callable[..., httpx.Client]


@dataclass(frozen=True)
class AttemptResult:
    """What one ``POST`` came back with.

    Attributes:
        http_status: The receiver's status code, or ``None`` when it never answered.
        latency_ms: How long the request took.
        response_preview: The start of the receiver's response body.
        error: Why the attempt did not succeed, or ``None``.
        retry_after: Seconds a ``429`` / ``503`` asked to wait (``Retry-After``).
        refused: The SSRF guard refused the destination (no request was sent to it).
    """

    http_status: Optional[int]
    latency_ms: int = 0
    response_preview: Optional[str] = None
    error: Optional[str] = None
    retry_after: Optional[int] = None
    refused: bool = False

    @property
    def delivered(self) -> bool:
        """The receiver answered ``2xx``."""
        return self.http_status is not None and 200 <= self.http_status < 300

    @property
    def retryable(self) -> bool:
        """Another attempt might succeed: no answer (not refused), ``408``/``425``/``429`` or ``5xx``."""
        if self.refused or self.delivered:
            return False
        if self.http_status is None:
            return True
        return self.http_status in _RETRYABLE_STATUSES or self.http_status >= 500


def send_attempt(
    url: str,
    body: bytes,
    signature: str,
    *,
    delivery_id: str,
    attempt_number: int,
    client_factory: ClientFactory = build_guarded_client,
) -> AttemptResult:
    """``POST`` the signed body once, through the SSRF-guarded client.

    Args:
        url: The receiver.
        body: The exact signed bytes.
        signature: ``sha256=<hex>``, sent as ``X-Apiome-Signature``.
        delivery_id: The run id, sent as ``X-Apiome-Delivery``.
        attempt_number: 1-based, sent as ``X-Apiome-Delivery-Attempt``.
        client_factory: Builds the HTTP client (tests pass a mock transport).

    Returns:
        The :class:`AttemptResult`. Never raises for a network or guard failure.
    """
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Apiome-Webhooks/1.0",
        "X-Apiome-Event": EVENT_TYPE,
        "X-Apiome-Signature": signature,
        "X-Apiome-Delivery": delivery_id,
        "X-Apiome-Delivery-Attempt": str(attempt_number),
    }
    started = time.perf_counter()
    try:
        with client_factory(timeout=_REQUEST_TIMEOUT_SEC, follow_redirects=False) as client:
            response = client.post(url, content=body, headers=headers)
    except ValueError as exc:  # SSRFError (a ValueError): the guard refused this hop
        return AttemptResult(http_status=None, error=f"destination refused: {exc}", refused=True)
    except httpx.HTTPError as exc:
        latency = int((time.perf_counter() - started) * 1000)
        return AttemptResult(http_status=None, latency_ms=latency,
                             error=f"no response: {type(exc).__name__}: {exc}"[:_ERROR_MESSAGE_CHARS])
    latency = int((time.perf_counter() - started) * 1000)
    status = response.status_code
    preview = (response.text or "")[:_RESPONSE_PREVIEW_CHARS] or None
    if 200 <= status < 300:
        return AttemptResult(http_status=status, latency_ms=latency, response_preview=preview)
    retry_after = retry_after_seconds(response.headers.get("Retry-After")) if status in (429, 503) else None
    error = f"HTTP {status}" + (" (redirects are not followed)" if 300 <= status < 400 else "")
    return AttemptResult(http_status=status, latency_ms=latency, response_preview=preview, error=error,
                         retry_after=retry_after)


def _next_attempt_at(failed_attempt: int, retry_after: Optional[int], now: datetime) -> datetime:
    """When to try again after attempt ``failed_attempt`` failed (the push-webhook backoff)."""
    delay = BACKOFF_AFTER_FAILURE_SEC[min(failed_attempt, len(BACKOFF_AFTER_FAILURE_SEC)) - 1]
    if retry_after is not None:
        delay = max(delay, retry_after)
    return now + timedelta(seconds=delay)


def _failure_code(result: AttemptResult) -> str:
    if result.refused:
        return ERROR_DESTINATION_REFUSED
    if result.http_status is None:
        return ERROR_UNREACHABLE
    return ERROR_RECEIVER_ERROR if result.retryable else ERROR_REJECTED


def _attempt_record(number: int, at: datetime, result: AttemptResult) -> Dict[str, Any]:
    return {
        "attempt": number,
        "at": at.isoformat().replace("+00:00", "Z"),
        "httpStatus": result.http_status,
        "latencyMs": result.latency_ms,
        "error": result.error,
        "responsePreview": result.response_preview,
    }


def attempt_delivery(
    database: Database,
    run: Dict[str, Any],
    *,
    client_factory: ClientFactory = build_guarded_client,
    now: Optional[Callable[[], datetime]] = None,
) -> Optional[Dict[str, Any]]:
    """Make the next attempt of a claimed run and record its outcome.

    Args:
        database: The database.
        run: The run, with ``payload`` and ``signature`` (from the insert or the sweep's claim).
        client_factory: Builds the HTTP client.
        now: The clock (tests).

    Returns:
        The updated run row.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    number = int(run.get("attempt_count") or 0) + 1
    max_attempts = int(run.get("max_attempts") or MAX_ATTEMPTS)
    at = clock()
    result = send_attempt(str(run["target_url"]), bytes(run["payload"]), str(run["signature"]),
                          delivery_id=str(run["id"]), attempt_number=number, client_factory=client_factory)
    record = _attempt_record(number, at, result)
    if result.delivered:
        return database.record_export_webhook_delivery_attempt(
            str(run["id"]), attempt=record, status=RUN_STATUS_DELIVERED, http_status=result.http_status)
    code, message = _failure_code(result), result.error or "delivery failed"
    if result.retryable and number < max_attempts:
        return database.record_export_webhook_delivery_attempt(
            str(run["id"]), attempt=record, status=RUN_STATUS_RETRYING,
            next_attempt_at=_next_attempt_at(number, result.retry_after, clock()),
            http_status=result.http_status, error_code=code, error_message=message)
    if result.retryable:
        code = ERROR_ATTEMPTS_EXHAUSTED
        message = f"No attempt succeeded after {number}; the last failed with: {message}"
    return database.record_export_webhook_delivery_attempt(
        str(run["id"]), attempt=record, status=RUN_STATUS_FAILED, http_status=result.http_status,
        error_code=code, error_message=message[:_ERROR_MESSAGE_CHARS])


def start_delivery(
    database: Database,
    *,
    client_factory: ClientFactory = build_guarded_client,
    **run_fields: Any,
) -> Optional[Dict[str, Any]]:
    """Record a new delivery and make its first attempt at once.

    Args:
        database: The database.
        client_factory: Builds the HTTP client.
        **run_fields: :meth:`app.database.Database.insert_export_webhook_delivery_run`'s arguments
            (``run_id``, ``tenant_id``, ``job_id``, ``target_url``, ``payload``, ``signature`` …).

    Returns:
        The run after its first attempt; the freshly inserted run when the attempt itself crashed
        (the sweep retries it once it is stale); ``None`` when the insert was refused.
    """
    run_fields.setdefault("max_attempts", MAX_ATTEMPTS)
    row = database.insert_export_webhook_delivery_run(status=RUN_STATUS_DELIVERING, **run_fields)
    if row is None:
        return None
    run = {**row, "payload": run_fields["payload"], "signature": run_fields["signature"]}
    try:
        return attempt_delivery(database, run, client_factory=client_factory)
    except Exception:  # noqa: BLE001 - the run stays `delivering`; the sweep picks it up when stale
        logger.exception("export webhook delivery %s: first attempt failed internally", row.get("id"))
        return row


def process_due_export_webhook_deliveries(
    database: Database,
    max_runs: int = 10,
    *,
    client_factory: ClientFactory = build_guarded_client,
) -> int:
    """Make the next attempt of up to ``max_runs`` due deliveries (the webhook delivery sweep's tick).

    Args:
        database: A database connection for this thread.
        max_runs: The most attempts this tick.
        client_factory: Builds the HTTP client.

    Returns:
        How many attempts were made.
    """
    made = 0
    for _ in range(max_runs):
        run = database.claim_next_due_export_webhook_delivery()
        if not run:
            break
        made += 1
        try:
            attempt_delivery(database, run, client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001 - record it so the run is not stuck `delivering`
            logger.exception("export webhook delivery %s: attempt failed internally", run.get("id"))
            number = int(run.get("attempt_count") or 0) + 1
            final = number >= int(run.get("max_attempts") or MAX_ATTEMPTS)
            now = datetime.now(timezone.utc)
            try:
                database.record_export_webhook_delivery_attempt(
                    str(run["id"]),
                    attempt=_attempt_record(number, now, AttemptResult(http_status=None,
                                                                         error=type(exc).__name__)),
                    status=RUN_STATUS_FAILED if final else RUN_STATUS_RETRYING,
                    next_attempt_at=None if final else _next_attempt_at(number, None, now),
                    error_code=ERROR_INTERNAL,
                    error_message=f"internal delivery error: {type(exc).__name__}"[:_ERROR_MESSAGE_CHARS],
                )
            except Exception:  # noqa: BLE001
                logger.exception("export webhook delivery %s: could not record the failure", run.get("id"))
    return made
