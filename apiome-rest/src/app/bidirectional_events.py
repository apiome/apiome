"""Bi-directional verdicts set commit statuses and fire webhooks — PFX-8.15 (#7312).

Until PFX-8.15 a bi-directional comparison (:mod:`app.bidirectional_store`) stored its
``verification_result`` row and nothing else: no ``provider_verification_*`` webhook fired and no
commit status was written (#6941 deferred it). The workspace's **For bi-directional verdicts too**
switch (``pact_contract_settings.status_bidirectional``, Contracts → Settings → CI and commit
statuses) now decides:

* **On** — each stored verdict runs the same two hooks a published verification runs:
  :func:`app.pact_webhook_events.fire_verification_events` and
  :func:`app.pact_commit_status_store.post_verification_statuses` (which still applies the consumer /
  provider commit switches);
* **Off** (the default) — nothing fires and nothing is written, as before. The verdict is in the
  matrix and the verification history either way.

It never fails the publish that caused the comparison: everything is caught and logged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .pact_commit_status_store import post_verification_statuses
from .pact_contract_settings import read_settings
from .pact_remediation_sweep import broker_base_for
from .pact_webhook_events import fire_verification_events
from .verification_result_store import get_verification_result

__all__ = ["publish_bidirectional_verdict"]

logger = logging.getLogger(__name__)


def _tenant_slug(db: Any, tenant_id: str) -> str:
    """The workspace handle the broker links are built under."""
    rows = db.execute_query("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (tenant_id,)) or []
    return str(rows[0]["slug"]) if rows else str(tenant_id)


def publish_bidirectional_verdict(
    db: Any,
    tenant_id: str,
    *,
    provider_ref: str,
    consumer_ref: str,
    sha: str,
    number: int,
    base: Optional[str] = None,
) -> bool:
    """Fire the webhooks and post the commit statuses of one stored bi-directional verdict.

    Args:
        db: The database.
        tenant_id: The tenant of the comparison.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        sha: The compared pact version.
        number: The stored result's number within that pact version.
        base: The broker base URL links start with; built from ``APIOME_API_PUBLIC_URL`` when ``None``.

    Returns:
        ``True`` when the switch is on and the hooks ran; ``False`` when it is off or anything failed
        (logged).
    """
    try:
        if not read_settings(db.execute_query, tenant_id).commit_statuses.bidirectional:
            return False
        record = get_verification_result(db, tenant_id, provider_ref, consumer_ref, sha, number)
        link_base = base or broker_base_for(_tenant_slug(db, tenant_id))
        fire_verification_events(db, tenant_id, link_base, record)
        post_verification_statuses(db, tenant_id, link_base, record)
        return True
    except Exception:  # noqa: BLE001 - a hook never fails the publish that caused the comparison
        logger.exception("bi-directional verdict %s/%s #%s: webhooks and statuses not sent", provider_ref, sha, number)
        return False
