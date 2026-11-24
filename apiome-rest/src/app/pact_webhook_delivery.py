"""Sending a contract webhook — PFX-1.9 (#6922).

A firing of a contract webhook is a row of the push-webhook delivery queue
(:mod:`app.push_webhook_delivery`) that names a ``pact_webhook_id``. The queue's worker hands such
a row to :func:`deliver_pact_webhook_event`, which sends the webhook's *own* request instead of
the subscription envelope and records the attempt in the same tables — so the retry schedule, the
``Retry-After`` handling and the dead-letter state are exactly the ones every other outbound
webhook has.

What is specific here:

* **The request is rendered when it is sent**, from the webhook as it is now and the template
  parameters stored with the firing (:func:`app.pact_webhook.render_request`).
* **It goes through the SSRF guard** (:func:`app.ssrf_guard.build_guarded_client`), which checks
  the address on every send. Redirects are not followed, so credentials never travel to a host the
  webhook did not name.
* **It is signed** when the webhook has a signing secret: ``X-Apiome-Signature: sha256=<hex>`` is
  the HMAC-SHA256 of the body, as on push-webhook subscriptions.
* **Every attempt leaves an execution log** — the request and the response as text — in
  ``push_webhook_delivery_attempts.execution_log``. Secret header values are replaced by
  ``**********`` and every secret value is scrubbed from the whole text, the response included, so
  a receiver that echoes a token back does not get it stored.

:func:`execute_webhook` is the same send without the queue, for ``POST …/webhooks/{uuid}/execute``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .pact_webhook import (
    REDACTED,
    SIGNATURE_HEADER,
    RenderedRequest,
    WebhookRecord,
    is_secret_header,
    render_request,
    scrub,
)
from .pact_webhook_secrets import KEYS_SETTING
from .pact_webhook_store import load_for_delivery
from .push_webhook_delivery import (
    MAX_DELIVERY_ATTEMPTS,
    _next_retry_utc,
    _sign_payload,
    _truncate,
    retry_after_seconds,
)
from .ssrf_guard import build_guarded_client

logger = logging.getLogger(__name__)

__all__ = ["ExecutionResult", "deliver_pact_webhook_event", "execute_webhook", "send_request"]

USER_AGENT = "Apiome-Webhooks/1.0"
#: Seconds one request may take.
REQUEST_TIMEOUT_SEC = 30.0
#: How much of a response body an execution log and a test run keep.
_RESPONSE_BODY_LIMIT = 4096
_LAST_ERROR_LIMIT = 2000
#: The longest secret a webhook can hold (:mod:`app.pact_webhook`), plus the scheme word before it.
_SECRET_MARGIN = 4200
_RATE_LIMIT_STATUSES = (429, 503)


class ExecutionResult(BaseModel):
    """What one send did.

    Attributes:
        success: Whether the receiver answered 2xx.
        status: The response status, or ``None`` when no response arrived.
        error: Why no response arrived (connection refused, SSRF refusal, timeout), scrubbed.
        latency_ms: How long the request took.
        retry_after: Seconds the receiver asked to wait (``Retry-After`` on 429/503).
        request_headers: The headers sent, secret values redacted.
        request_body: The body sent, scrubbed.
        response_headers: The response headers, secret values redacted.
        response_body: The start of the response body, scrubbed.
        url: The URL the request went to.
        method: The request method.
        logs: The execution log.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    status: Optional[int] = None
    error: Optional[str] = None
    latency_ms: int = 0
    retry_after: Optional[int] = None
    request_headers: Dict[str, str] = Field(default_factory=dict)
    request_body: Optional[str] = None
    response_headers: Dict[str, str] = Field(default_factory=dict)
    response_body: Optional[str] = None
    url: str = ""
    method: str = "POST"
    logs: str = ""


def _redacted_headers(headers: Mapping[str, str], secret_names: List[str]) -> Dict[str, str]:
    """Headers as a log shows them: a secret header's value is ``**********``."""
    hidden = {name.lower() for name in secret_names}
    return {
        name: REDACTED if name.lower() in hidden or is_secret_header(name) else value
        for name, value in headers.items()
    }


def _log_lines(lines: List[str]) -> str:
    """Stamp log lines the way the Pact Broker's execution log does."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "\n".join(f"[{stamp}] {line}" for line in lines) + "\n"


def send_request(
    rendered: RenderedRequest,
    *,
    event_type: str,
    delivery_id: Optional[str] = None,
    signing_secret: Optional[str] = None,
    completion: Optional[str] = None,
) -> ExecutionResult:
    """Send one rendered request through the SSRF guard and describe what happened.

    Args:
        rendered: The request, from :func:`app.pact_webhook.render_request`.
        event_type: Sent as ``X-Apiome-Event``.
        delivery_id: Sent as ``X-Apiome-Delivery`` — the same for every retry of one firing, so a
            receiver can ignore a repeat.
        signing_secret: When set, the body's HMAC-SHA256 is sent as ``X-Apiome-Signature``.
        completion: A last log line (the caller knows whether a failure will be retried).

    Returns:
        The outcome, with nothing secret in it.
    """
    headers = dict(rendered.headers)
    if not any(name.lower() == "user-agent" for name in headers):
        headers["User-Agent"] = USER_AGENT
    headers["X-Apiome-Event"] = event_type
    if delivery_id:
        headers["X-Apiome-Delivery"] = delivery_id
    body = rendered.body or b""
    secrets = list(rendered.secrets)
    if signing_secret:
        headers[SIGNATURE_HEADER] = _sign_payload(signing_secret, body)
        secrets.append(signing_secret)
    secret_names = [name for name, value in rendered.headers.items() if value in rendered.secrets]

    shown_headers = _redacted_headers(headers, secret_names)
    shown_url = scrub(rendered.url, secrets) or ""
    shown_body = scrub(body.decode("utf-8", "replace"), secrets) if rendered.body is not None else None
    lines = [f"INFO: HTTP/1.1 {rendered.method} {shown_url}"]
    lines += [f"INFO: {name}: {value}" for name, value in shown_headers.items()]
    if shown_body:
        lines.append(f"INFO: {shown_body}")

    result = ExecutionResult(
        success=False, request_headers=shown_headers, request_body=shown_body, url=shown_url, method=rendered.method
    )
    try:
        with build_guarded_client(timeout=REQUEST_TIMEOUT_SEC, follow_redirects=False) as client:
            started = time.perf_counter()
            response = client.request(rendered.method, rendered.url, content=body, headers=headers)
            result.latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001 - whatever went wrong is a failed attempt, scrubbed
        # Among them: a connection error, a timeout, the SSRF guard refusing the destination
        # (ValueError), and a header value the HTTP library will not send.
        # Scrub before cutting, so the cut can not leave the start of a secret behind.
        result.error = _truncate(scrub(f"{type(exc).__name__}: {exc}", secrets), _LAST_ERROR_LIMIT)
        lines.append(f"ERROR: {result.error}")
    else:
        result.status = response.status_code
        result.success = 200 <= response.status_code < 300
        response_headers = {name: scrub(value, secrets) or "" for name, value in response.headers.items()}
        result.response_headers = _redacted_headers(response_headers, [])
        # Scrub a little past the limit before cutting, so the cut can not leave part of a secret.
        scrubbed = scrub(response.text[: _RESPONSE_BODY_LIMIT + _SECRET_MARGIN], secrets)
        result.response_body = _truncate(scrubbed, _RESPONSE_BODY_LIMIT)
        if response.status_code in _RATE_LIMIT_STATUSES:
            result.retry_after = retry_after_seconds(response.headers.get("Retry-After"))
        if not result.success:
            result.error = f"HTTP {response.status_code}"
        lines.append(f"INFO: HTTP/1.1 {response.status_code} {response.reason_phrase}")
        lines += [f"INFO: {name}: {value}" for name, value in result.response_headers.items()]
        if result.response_body:
            lines.append(f"INFO: {result.response_body}")
    if completion:
        lines.append(f"INFO: {completion}")
    result.logs = _log_lines(lines)
    return result


def _render(record: WebhookRecord, secrets: Mapping[str, Any], parameters: Mapping[str, str]) -> RenderedRequest:
    """Render a stored webhook's request with its opened secrets."""
    return render_request(
        method=record.method,
        url=record.url,
        headers=record.headers,
        body=record.body,
        parameters=parameters,
        username=record.username,
        password=secrets.get("password"),
        secret_headers=secrets.get("headers") or {},
    )


def execute_webhook(
    record: WebhookRecord,
    secrets: Mapping[str, Any],
    parameters: Mapping[str, str],
    *,
    event_type: str = "pact.test",
) -> ExecutionResult:
    """Send a webhook's request once, now, outside the queue (a test run).

    Args:
        record: The webhook.
        secrets: Its opened secrets (``{}`` when it has none).
        parameters: The template parameters to render it with.
        event_type: Sent as ``X-Apiome-Event``.

    Returns:
        The outcome.
    """
    return send_request(
        _render(record, secrets, parameters),
        event_type=event_type,
        signing_secret=secrets.get("signingSecret"),
        completion=None,
    )


def _finalize(
    database: Any,
    row: Mapping[str, Any],
    attempt_number: int,
    *,
    delivered: bool,
    http_status: Optional[int] = None,
    preview: Optional[str] = None,
    error: Optional[str] = None,
    latency_ms: int = 0,
    retry_after: Optional[int] = None,
    execution_log: Optional[str] = None,
    retryable: bool = True,
) -> None:
    """Record one attempt and move the delivery to ``delivered``, ``retrying`` or ``dead_letter``.

    Args:
        database: The delivery's database handle.
        row: The claimed event.
        attempt_number: This attempt, from 1.
        delivered: Whether the receiver answered 2xx.
        http_status: The response status.
        preview: The start of the response body.
        error: Why it failed.
        latency_ms: How long the request took.
        retry_after: Seconds the receiver asked to wait.
        execution_log: The attempt's log.
        retryable: False dead-letters at once (the webhook is gone or disabled).
    """
    if delivered:
        status, next_at, last_error = "delivered", None, None
    elif not retryable or attempt_number >= MAX_DELIVERY_ATTEMPTS:
        status, next_at, last_error = "dead_letter", None, error
    else:
        status, next_at, last_error = "retrying", _next_retry_utc(attempt_number, retry_after=retry_after), error
    database.finalize_push_webhook_delivery_attempt(
        str(row["event_id"]),
        attempt_number=attempt_number,
        http_status=http_status,
        response_body_preview=_truncate(preview, 1024),
        error_message=None if delivered else error,
        latency_ms=latency_ms,
        new_status=status,
        new_attempt_count=attempt_number,
        next_retry_at=next_at,
        last_error=_truncate(last_error, _LAST_ERROR_LIMIT),
        execution_log=execution_log,
    )


def deliver_pact_webhook_event(database: Any, row: Mapping[str, Any]) -> None:
    """Make one attempt at a queued contract-webhook firing and persist the outcome.

    Called by :func:`app.push_webhook_delivery.deliver_one_due_event` for a claimed event that
    names a ``pact_webhook_id``.

    Args:
        database: The delivery's database handle.
        row: The claimed event: ``event_id``, ``tenant_id``, ``pact_webhook_id``, ``event_type``,
            ``payload`` (``{"eventName", "parameters"}``) and ``attempt_count``.
    """
    attempt_number = int(row["attempt_count"]) + 1
    hook = load_for_delivery(database, str(row["pact_webhook_id"]), str(row["tenant_id"]))
    if hook is None or not hook.record.enabled:
        reason = "the webhook was deleted" if hook is None else "the webhook is disabled"
        _finalize(
            database, row, attempt_number, delivered=False, error=reason, retryable=False,
            execution_log=_log_lines([f"ERROR: not sent: {reason}"]),
        )
        return
    if hook.secrets is None:
        reason = f"the webhook's secrets cannot be opened (check {KEYS_SETTING})"
        _finalize(
            database, row, attempt_number, delivered=False, error=reason,
            execution_log=_log_lines([f"ERROR: not sent: {reason}"]),
        )
        return

    payload = row.get("payload") or {}
    parameters = payload.get("parameters") if isinstance(payload, Mapping) else None
    rendered = _render(hook.record, hook.secrets, parameters or {})
    last = attempt_number >= MAX_DELIVERY_ATTEMPTS
    result = send_request(
        rendered,
        event_type=str(row.get("event_type") or ""),
        delivery_id=str(row["event_id"]),
        signing_secret=hook.secrets.get("signingSecret"),
    )
    if result.success:
        closing = "Webhook delivered"
    elif last:
        closing = f"Webhook failed after {MAX_DELIVERY_ATTEMPTS} attempts; moved to the dead-letter list"
    else:
        closing = "Webhook failed; it will be retried"
    _finalize(
        database,
        row,
        attempt_number,
        delivered=result.success,
        http_status=result.status,
        preview=result.response_body,
        error=result.error or "delivery failed",
        latency_ms=result.latency_ms,
        retry_after=result.retry_after,
        execution_log=result.logs + _log_lines([f"INFO: {closing}"]),
    )
