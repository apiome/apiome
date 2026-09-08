"""Drift alerts over the existing push-webhook channel — CTG-4.4 (#4501).

Two events, both fired by the scheduled-verification sweep and by nothing else::

    verification.drift.detected  — a scheduled run found the deployment disagreeing with its
                                   contract, or could not get an answer at all
    verification.drift.resolved  — a schedule that was alerting verified clean again

Delivery is the **existing** push-webhook pipeline (``apiome.push_webhook_subscriptions`` /
``push_webhook_delivery_events``, #2587/#2588): the same HMAC-signed ``X-Apiome-Signature``, the
same four attempts with backoff, the same dead-letter behaviour the repository-refresh, lint, and
catalog-digest notifications use. Nothing about retry or dead-lettering is special-cased here —
this module only decides *what* is enqueued, never *how* it is delivered.

Noise is controlled upstream, in :func:`app.verification_schedule.decide_alert`: a pass→fail
transition notifies once, a repeat of the same failure is silent, and a failure whose violation set
changed notifies again. By the time a function here is called, the decision to speak has been made.

Payloads carry ids, the conformance summary, and located violations only — never a request header,
a credential, or a response body. The fan-out loop itself is
:func:`app.push_webhook_fanout.enqueue_event` — extracted here rather than copied a fifth time —
and is **best-effort**: per-subscription failures are logged and skipped and no function here ever
raises, so a notification problem can never fail the sweep it describes.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .push_webhook_fanout import enqueue_event

#: Names this family in the shared fan-out's log lines.
_LOG_LABEL = "verification-alert"

__all__ = [
    "EVENT_VERIFICATION_DRIFT_DETECTED",
    "EVENT_VERIFICATION_DRIFT_RESOLVED",
    "notify_verification_drift",
    "notify_verification_recovered",
]

#: A scheduled run found drift (or could not reach a verdict).
EVENT_VERIFICATION_DRIFT_DETECTED = "verification.drift.detected"
#: A drifting deployment verified clean again.
EVENT_VERIFICATION_DRIFT_RESOLVED = "verification.drift.resolved"


def notify_verification_drift(
    db: Any, *, tenant_id: str, payload: Dict[str, Any]
) -> List[str]:
    """Announce that a scheduled verification found drift.

    Args:
        db: Database handle for the fan-out.
        tenant_id: The schedule's owning tenant.
        payload: The body built by :func:`app.verification_schedule.build_alert_payload`.

    Returns:
        Enqueued delivery-event ids.
    """
    return enqueue_event(
        db,
        tenant_id=tenant_id,
        event_type=EVENT_VERIFICATION_DRIFT_DETECTED,
        payload=payload,
        log_label=_LOG_LABEL,
    )


def notify_verification_recovered(
    db: Any, *, tenant_id: str, payload: Dict[str, Any]
) -> List[str]:
    """Announce that a drifting deployment verified clean again.

    Args:
        db: Database handle for the fan-out.
        tenant_id: The schedule's owning tenant.
        payload: The body built by :func:`app.verification_schedule.build_alert_payload`.

    Returns:
        Enqueued delivery-event ids.
    """
    return enqueue_event(
        db,
        tenant_id=tenant_id,
        event_type=EVENT_VERIFICATION_DRIFT_RESOLVED,
        payload=payload,
        log_label=_LOG_LABEL,
    )
