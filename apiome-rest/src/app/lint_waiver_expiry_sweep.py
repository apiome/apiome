"""Waiver-expiry notification sweep (CLX-4.2, #4860).

A waiver is accepted risk with a deadline (CLX-1.3): when the deadline nears, the owner must
either remediate or renew — silently reopening at read time (which the policy engine already
does) tells nobody. This sweep runs periodically on every instance and enqueues one
``lint.waiver.expiring`` webhook per granted waiver whose ``expires_at`` falls within the
configured warning window (``lint_waiver_expiry_warning_hours``, default 72h).

Exactly-once across replicas comes from the claim, not the scheduler:
:meth:`Database.claim_expiring_lint_waivers` stamps ``expiry_notified_at`` under
``FOR UPDATE SKIP LOCKED`` and returns only the rows this instance won. A waiver re-granted
with a new expiry re-arms (the decision upsert resets the marker), so renewals notify again
for their new deadline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import settings
from .database import Database
from .lint_notifications import notify_lint_waiver_expiring

logger = logging.getLogger(__name__)

__all__ = ["process_lint_waiver_expiry_sweep"]


def process_lint_waiver_expiry_sweep(
    database: Database,
    *,
    warning_hours: Optional[int] = None,
    limit: int = 50,
) -> int:
    """Claim soon-expiring waivers and notify each one (one sweep tick).

    Args:
        database: Database handle (a per-thread instance from the startup sweep).
        warning_hours: Warning window before expiry; defaults to
            ``settings.lint_waiver_expiry_warning_hours``.
        limit: Max waivers claimed per tick.

    Returns:
        The number of waivers claimed (and therefore notified at most once each).
    """
    hours = warning_hours if warning_hours is not None else int(
        settings.lint_waiver_expiry_warning_hours
    )
    cutoff = datetime.now(timezone.utc) + timedelta(hours=hours)
    try:
        claimed = database.claim_expiring_lint_waivers(cutoff=cutoff, limit=limit)
    except Exception:  # noqa: BLE001 - a failed tick retries on the next interval
        logger.warning("lint waiver expiry sweep: claim failed", exc_info=True)
        return 0
    for decision in claimed:
        notify_lint_waiver_expiring(database, decision=decision)
    if claimed:
        logger.info("lint waiver expiry sweep: notified %d waiver(s)", len(claimed))
    return len(claimed)
