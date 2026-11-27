"""The Contracts landing's integrations list — PFX-8.1 (#7298): the HTTP face of :mod:`app.pact_integrations`.

``GET /v1/tenants/{tenant}/pact-integrations`` (``q``, ``filter``, ``limit``, ``offset``) — every
consumer ↔ provider pair with a pact, worst verdict first, with its kind (Pact or bi-directional),
verdict, pending flag, the environments both sides are deployed in and when it was last verified;
the counts and named pairs the landing's status strip and facts line show; and the workspace's
pacticipant and environment counts.

Outside ``…/pact-broker``: no Pact Broker client knows it (the broker surface stays the catalogued,
compatible one, :mod:`app.pact_broker_compat`).

**Permissions.** Needs ``pacts:view``. Scoped to the authenticated tenant; the URL's slug never
widens it. Nothing is stored.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_integrations import (
    CODE_MINE_NEEDS_USER,
    DEFAULT_LIMIT,
    FILTERS,
    MAX_INTEGRATIONS,
    MAX_LIMIT,
    MAX_SEARCH_LENGTH,
    IntegrationsError,
    PactIntegrationsPage,
    parse_query,
)
from .pact_integrations_store import list_integrations
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/pact-integrations",
    response_model=PactIntegrationsPage,
    summary="List the workspace's contract integrations",
    description=(
        "Every consumer ↔ provider pair with a pact (PFX-8.1), for the Contracts landing: its kind (`pact`, or "
        "`bidirectional` when a provider contract is compared), its verdict — `failing`, `stale`, "
        "`no-provider-contract`, `unverified` or `verified` — whether it is pending (a Pact-kind pact the provider "
        "has never passed), the environments both sides are deployed in now, and when it was last verified. "
        "Worst verdict first, then by consumer and provider name. `q` matches handles and names; `filter` is "
        f"one of {', '.join(f'`{name}`' for name in FILTERS)} (`mine`: a team you are on owns either side). "
        "`counts` and `attention` (up to three pairs per status-strip category) cover every pair, whatever the "
        f"search and filter. At most {MAX_INTEGRATIONS} pairs are classified (`truncated`, "
        "`omitted_integrations`). Requires `pacts:view`."
    ),
    responses={
        400: {
            "description": (
                "`pact-integrations-filter-invalid`, `pact-integrations-search-invalid`, "
                "`pact-integrations-page-invalid`, or `pact-integrations-mine-needs-user` for `filter=mine` "
                "with a credential that is not a user."
            )
        },
    },
)
def read_integrations(
    tenant_slug: str,
    q: Optional[str] = Query(None, max_length=MAX_SEARCH_LENGTH, description="Text a handle or name contains."),
    filter: Optional[str] = Query(None, max_length=16, description="`all` (default), `failing`, `stale`, …"),
    limit: Optional[int] = Query(
        None, ge=1, le=MAX_LIMIT, description=f"Page size, 1 … {MAX_LIMIT} (default {DEFAULT_LIMIT})."
    ),
    offset: Optional[int] = Query(
        None, ge=0, le=MAX_INTEGRATIONS, description=f"Rows to skip, 0 … {MAX_INTEGRATIONS}."
    ),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactIntegrationsPage:
    """List the workspace's integrations.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        q: The search text.
        filter: The filter chip.
        limit: The page size.
        offset: Rows to skip.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 for a refused query, carrying ``{"code", "message"}``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-integrations")
    _ = tenant_slug
    try:
        query = parse_query(search=q, filter=filter, limit=limit, offset=offset)
    except IntegrationsError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    user_id = auth_data.get("user_id")
    if query.filter == "mine" and not user_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": CODE_MINE_NEEDS_USER,
                "message": "The 'mine' filter needs a signed-in user; this credential has none.",
            },
        )
    return list_integrations(db, _tenant_id(auth_data), query, user_id=str(user_id) if user_id else None)
