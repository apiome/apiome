"""Contract health rollup and verification analytics — PFX-6.3 (#6955): the HTTP face of :mod:`app.pact_health`.

Outside ``…/pact-broker``, because no Pact Broker or PactFlow client knows them (the broker surface stays
the catalogued, compatible one, :mod:`app.pact_broker_compat`):

* ``GET /v1/tenants/{tenant}/pact-health`` (``window``, ``provider``, ``consumer``, ``state``) — every
  consumer ↔ provider pair's health state, its fused signals and its window's analytics, worst first.
* ``GET /v1/tenants/{tenant}/pact-health/providers/{provider}/consumers/{consumer}`` (``window``) — one
  pair's health with its pass-rate, flakiness and duration trend, one bucket per day (per week for
  ``90d``).

**Permissions.** Both read and need ``pacts:view``. Every lookup is scoped to the authenticated tenant:
another workspace's pacticipant is a ``404``. Nothing is stored: health is computed on every read.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_health import (
    CODE_PAIR_NOT_FOUND,
    CODE_STATE_INVALID,
    CODE_WINDOW_INVALID,
    DEFAULT_WINDOW,
    MAX_HEALTH_PAIRS,
    HealthError,
    PactHealthOverview,
    PactPairHealthDetail,
)
from .pact_health_store import pair_health, workspace_health
from .pacticipant import PacticipantValidationError
from .pacticipant_routes import STATUS_BY_CODE
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_HEALTH = "/{tenant_slug}/pact-health"

_STATUS = {
    CODE_WINDOW_INVALID: 400,
    CODE_STATE_INVALID: 400,
    CODE_PAIR_NOT_FOUND: 404,
}

_WINDOW_DESCRIPTION = f"`7d`, `30d` or `90d` (default `{DEFAULT_WINDOW}`)."


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _error(exc: Exception) -> HTTPException:
    """The HTTP error for a refusal, carrying ``{"code", "message"}``.

    Args:
        exc: A :class:`HealthError` or :class:`PacticipantValidationError`.

    Returns:
        The exception to raise.
    """
    code = getattr(exc, "code", "")
    if isinstance(exc, HealthError):
        status = _STATUS.get(code, 400)
    else:
        status = STATUS_BY_CODE.get(code, 400)
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


@router.get(
    _HEALTH,
    response_model=PactHealthOverview,
    summary="Read the workspace's contract health",
    description=(
        "Every consumer ↔ provider pair with a pact (PFX-6.3), rolled up into one state — `healthy`, "
        "`degraded`, `failing` or `unknown` — fused from its signals: the newest pact's latest verdict, the "
        "window's pass rate and flakiness (how often the verdict flips between consecutive results), whether "
        "the stale-pact sweep found it overdue, an open re-publish request, and failed contract-webhook "
        "deliveries. Each signal says `ok`, `warn`, `fail` or `unknown` with a reason code. Pairs are listed "
        f"worst first, at most {MAX_HEALTH_PAIRS} (`truncated`, `omitted_pairs`). Narrow by `provider`, "
        "`consumer` and `state`; the `counts` cover every pair the provider/consumer filter matches. "
        "Computed on every read. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-health-window-invalid` or `pact-health-state-invalid`."},
        404: {"description": "`pacticipant-not-found` for the `provider` or `consumer` filter."},
    },
)
def read_health(
    tenant_slug: str,
    window: Optional[str] = Query(None, max_length=8, description=_WINDOW_DESCRIPTION),
    provider: Optional[str] = Query(None, min_length=1, max_length=255, description="Only this provider's pairs."),
    consumer: Optional[str] = Query(None, min_length=1, max_length=255, description="Only this consumer's pairs."),
    state: Optional[str] = Query(
        None, max_length=16, description="Only pairs in this state: `healthy`, `degraded`, `failing` or `unknown`."
    ),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactHealthOverview:
    """Read the workspace's contract health.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        window: The window.
        provider: Only this provider's pairs.
        consumer: Only this consumer's pairs.
        state: Only pairs in this state.
        auth_data: The authenticated principal.

    Returns:
        The overview.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 / 404 as documented.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-health")
    _ = tenant_slug
    try:
        return workspace_health(
            db,
            _tenant_id(auth_data),
            window=window,
            provider_ref=provider,
            consumer_ref=consumer,
            state=state,
        )
    except (HealthError, PacticipantValidationError) as exc:
        raise _error(exc) from exc


@router.get(
    _HEALTH + "/providers/{provider}/consumers/{consumer}",
    response_model=PactPairHealthDetail,
    summary="Read one pair's contract health and trends",
    description=(
        "One consumer ↔ provider pair's health (PFX-6.3) — its state, every fused signal and the window's "
        "analytics — and its **trend**: one bucket per day for `7d` and `30d`, per week for `90d`, oldest "
        "first and empty ones included, each with runs, pass rate, verdict flips, flakiness and mean "
        "duration. `{provider}` and `{consumer}` are handles, ids or names. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-health-window-invalid`."},
        404: {
            "description": (
                "`pacticipant-not-found`, or `pact-health-pair-not-found` when the consumer has published no "
                "pact for the provider."
            )
        },
    },
)
def read_pair_health(
    tenant_slug: str,
    provider: str,
    consumer: str,
    window: Optional[str] = Query(None, max_length=8, description=_WINDOW_DESCRIPTION),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactPairHealthDetail:
    """Read one pair's health and trend.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider (handle, id or name).
        consumer: The consumer.
        window: The window.
        auth_data: The authenticated principal.

    Returns:
        The pair's health and trend.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 / 404 as documented.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-health")
    _ = tenant_slug
    try:
        return pair_health(db, _tenant_id(auth_data), provider, consumer, window=window)
    except (HealthError, PacticipantValidationError) as exc:
        raise _error(exc) from exc
