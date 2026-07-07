"""Scheduled catalog digest sweep — cadence-driven per-tenant digest delivery (V2-MCP-33.5 / MCAT-19.5, #4654).

Operators want a recurring "here's your catalog this week" without opening the app. This module is
the periodic worker (wired in :mod:`app.main`, mirroring :mod:`app.repository_refresh_sweep`) that,
on each tick, selects the tenants whose digest cadence has elapsed, compiles a digest over the window
since each tenant's last digest, and delivers it over that tenant's existing push-webhook
subscriptions — the same channel the RAR-5.4 refresh notifications use.

Due-selection (:meth:`Database.list_due_mcp_catalog_digests`) does the policy work: it returns only
opted-in tenants whose effective cadence has elapsed, each with a database-computed window
(``window_start`` .. ``window_end``) so the window is free of application clock skew. For each due
tenant the sweep:

1. takes a per-tenant advisory lock so two workers / overlapping ticks never double-send
   (:meth:`Database.try_acquire_mcp_catalog_digest_lock`);
2. reads the window's real catalog activity — new endpoints, grade movements, breaking changes and
   discovery-health problems — each scoped to the tenant;
3. folds it into a :class:`app.mcp_catalog_digest.CatalogDigest` via the pure compiler;
4. honours the **empty-window policy**: a tenant with ``send_empty = False`` whose window has nothing
   to report sends nothing (an acceptance criterion); ``send_empty = True`` sends an explicit "no
   changes" digest; and
5. advances ``last_digest_at`` to the window end each tick — success, empty-skip, or failure — so
   successive windows abut and a tenant whose compilation errors cannot stay perpetually due and
   hammer the sweep every tick.

The global ``APIOME_MCP_DIGEST_ENABLED`` kill switch short-circuits the whole tick (like the
discovery/refresh sweeps' kill switches), so operators can halt all digest delivery for incident
response without touching per-tenant opt-in state. Delivery is best-effort: a per-subscription
enqueue failure is logged and skipped, and one tenant's failure never aborts the rest of the tick.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping

from .mcp_catalog_digest import (
    EVENT_TYPE_DIGEST,
    CatalogDigest,
    build_digest_payload,
    compile_digest,
    digest_is_empty,
)

_logger = logging.getLogger(__name__)


def compile_tenant_digest(db: Any, due_row: Mapping[str, Any]) -> CatalogDigest:
    """Read the window's catalog activity for one due tenant and compile its digest (MCAT-19.5).

    Runs the four tenant-scoped window reads (new endpoints, all changes, grade movements,
    discovery-health problems) over ``(window_start, window_end]`` and folds them with the pure
    :func:`app.mcp_catalog_digest.compile_digest`. The breaking-change section is derived by the
    compiler from the full change set, so severity is classified once, consistently.

    Args:
        db: Database handle exposing the ``list_mcp_*_in_window`` reads.
        due_row: A row from :meth:`Database.list_due_mcp_catalog_digests` (``tenant_id`` /
            ``tenant_slug`` / ``window_start`` / ``window_end`` / ``send_empty``).

    Returns:
        The compiled :class:`CatalogDigest`.
    """
    tenant_id = str(due_row["tenant_id"])
    tenant_slug = str(due_row["tenant_slug"])
    window_start = due_row["window_start"]
    window_end = due_row["window_end"]

    return compile_digest(
        tenant_slug=tenant_slug,
        window_start=window_start,
        window_end=window_end,
        new_endpoint_rows=db.list_mcp_new_endpoints_in_window(
            tenant_id, window_start, window_end
        ),
        change_rows=db.list_mcp_catalog_changes_in_window(
            tenant_id, window_start, window_end
        ),
        grade_movement_rows=db.list_mcp_grade_movements_in_window(
            tenant_id, window_start, window_end
        ),
        health_rows=db.list_mcp_health_problems_in_window(
            tenant_id, window_start, window_end
        ),
    )


def deliver_digest(db: Any, tenant_id: str, payload: Dict[str, Any]) -> List[str]:
    """Fan the digest payload out to a tenant's active push-webhook subscriptions (MCAT-19.5).

    Mirrors :func:`app.repository_refresh_notifications.notify_refresh_outcome`: one delivery is
    enqueued per active subscription, each tagged :data:`app.mcp_catalog_digest.EVENT_TYPE_DIGEST`.
    Best-effort — a per-subscription enqueue failure (e.g. a subscription deactivated between the
    listing and the enqueue) is logged and skipped, and the function never raises, so a delivery
    problem can never fail the sweep. A tenant with no active subscription simply gets an empty list.

    Args:
        db: Database handle exposing ``list_active_push_webhook_subscription_ids`` and
            ``enqueue_push_webhook_delivery``.
        tenant_id: The owning tenant id (subscription + delivery scope).
        payload: The JSON-serializable digest payload.

    Returns:
        The list of enqueued delivery-event ids (empty when no active subscription exists).
    """
    try:
        subscription_ids = db.list_active_push_webhook_subscription_ids(tenant_id)
    except Exception:
        _logger.exception(
            "catalog-digest fan-out: failed to list subscriptions for tenant %s", tenant_id
        )
        return []

    enqueued: List[str] = []
    for subscription_id in subscription_ids:
        try:
            row = db.enqueue_push_webhook_delivery(
                tenant_id, subscription_id, EVENT_TYPE_DIGEST, payload
            )
            event_id = str(row["id"]) if isinstance(row, Mapping) and row.get("id") else None
            if event_id is not None:
                enqueued.append(event_id)
        except Exception:
            _logger.exception(
                "catalog-digest fan-out: failed to enqueue %s for subscription %s",
                EVENT_TYPE_DIGEST,
                subscription_id,
            )
    return enqueued


def process_mcp_catalog_digest_sweep(db: Any) -> int:
    """Run one scheduled catalog digest sweep tick over all due tenants (MCAT-19.5).

    Iterates the tenants due for a digest (cadence elapsed; opt-out excluded), serializing each
    behind a per-tenant advisory lock, compiling the window's digest and delivering it over the
    tenant's push-webhook subscriptions. An empty window is silent unless the tenant opted into
    "no changes" digests. ``last_digest_at`` is advanced to the window end for every processed tenant
    — even when compilation fails or the window was empty — so the cadence keeps moving and a broken
    tenant cannot monopolize the sweep.

    The global ``APIOME_MCP_DIGEST_ENABLED`` kill switch short-circuits the whole tick.

    Args:
        db: Database handle for this tick (one connection holds the advisory locks; the caller uses a
            dedicated ``Database`` per tick).

    Returns:
        The number of tenants for which a digest was compiled and delivered this tick (an empty
        window that was skipped, and a tenant whose kill switch is off, are not counted).
    """
    from .config import settings

    if not settings.mcp_digest_enabled:
        # Global kill switch: halt all digest delivery for this tick.
        _logger.info(
            "mcp catalog digest sweep halted: APIOME_MCP_DIGEST_ENABLED is disabled"
        )
        return 0

    default_cadence = int(settings.mcp_digest_default_cadence_seconds)
    delivered_total = 0
    for due_row in db.list_due_mcp_catalog_digests(default_cadence_seconds=default_cadence):
        tenant_id = str(due_row["tenant_id"])

        if not db.try_acquire_mcp_catalog_digest_lock(tenant_id):
            # Another worker / overlapping tick owns this tenant right now.
            _logger.debug(
                "mcp catalog digest skipped (lock held) tenant_id=%s", tenant_id
            )
            continue

        try:
            digest = compile_tenant_digest(db, due_row)
            if digest_is_empty(digest) and not bool(due_row.get("send_empty")):
                # Empty window and the tenant did not opt into "no changes" digests: stay silent.
                # The anchor still advances (finally) so the next window starts fresh.
                _logger.debug(
                    "mcp catalog digest empty window (silent) tenant_id=%s", tenant_id
                )
                continue
            payload = build_digest_payload(digest)
            deliver_digest(db, tenant_id, payload)
            delivered_total += 1
        except Exception:
            _logger.exception(
                "mcp catalog digest sweep failed tenant_id=%s", tenant_id
            )
        finally:
            # Advance the window/cadence anchor each tick (success, empty-skip, or failure) so the
            # tenant is not immediately due again, then release the lock.
            try:
                db.mark_mcp_catalog_digest_sent(tenant_id, due_row["window_end"])
            except Exception:
                _logger.exception(
                    "mcp catalog digest anchor advance failed tenant_id=%s", tenant_id
                )
            db.release_mcp_catalog_digest_lock(tenant_id)

    return delivered_total
