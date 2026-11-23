"""``/v1/tenants/{tenant_slug}/unowned-findings`` — CDG-2.3 (#5962).

The **Unowned findings** report: findings owner routing could not deliver because the entity has no
confirmed owner team. One row per entity and finding type, with how many times it happened and the
latest occurrence's summary and link. Routing removes a row once the entity has an owner and the same
kind of finding reaches it; CDG-2.5 adds the catch-all team that receives these instead.

Reading it needs ``teams:view``: it is a report about ownership.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .database import db
from .keyset_pagination import (
    cursor_query,
    include_total_query,
    limit_query,
    offset_query,
    parse_time_id_cursor,
)
from .owner_routing import list_unowned_findings
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["owners"])

FindingType = Literal[
    "owner_finding", "owner_breaking_change", "owner_verification_drift", "owner_gate_blocked",
    "owner_trust_drift", "owner_shadow_api", "owner_sync_failed",
]


class UnownedFinding(BaseModel):
    """One entity and finding type that reached no owner."""

    model_config = ConfigDict(extra="ignore")

    id: str
    entity_kind: str = Field(description="`project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`.")
    entity_id: str
    finding_type: str
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="The latest occurrence: `summary`, `link`, `finding_id`, `entity_name` and details.",
    )
    occurrences: int = Field(description="How many times this finding has happened on the entity.")
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None


class UnownedFindingsResponse(BaseModel):
    """A page of the report."""

    model_config = ConfigDict(extra="forbid")

    items: List[UnownedFinding] = Field(default_factory=list)
    total: Optional[int] = Field(
        default=None,
        description=(
            "How many findings match, counted up to 10,000. Present only when the request set "
            "`include_total`."
        ),
    )
    has_more: bool = Field(default=False, description="Whether another page exists.")
    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` to read the next page; null on the last page."
    )


@router.get(
    "/{tenant_slug}/unowned-findings",
    response_model=UnownedFindingsResponse,
    summary="List unowned findings",
    description=(
        "Findings that reached no team because their entity has no confirmed owner — never dropped, "
        "kept here, newest first. One row per entity and finding type, with `occurrences` and the "
        "latest `payload`. Assigning an owner (`PUT /v1/tenants/{tenant}/owners/{kind}/{id}`) routes "
        "the next occurrence to the team and clears the row.\n\n"
        "Pages by `cursor`: pass the previous page's `next_cursor` until `has_more` is false. "
        "The `total` is counted only when `include_total` is set.\n\nRequires `teams:view`."
    ),
)
def get_unowned_findings(
    tenant_slug: str,
    finding_type: Optional[FindingType] = Query(default=None, alias="type"),
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    include_total: bool = include_total_query(),
    offset: int = offset_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UnownedFindingsResponse:
    """List the tenant's unowned findings.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes the read).
        finding_type: Only this finding type.
        limit: Page size.
        cursor: Where the page starts (``next_cursor`` of the previous page).
        include_total: Also count the matches.
        offset: Rows to skip (deprecated).
        auth_data: The authenticated principal.

    Returns:
        The page, whether another follows, and the total when asked for.

    Raises:
        HTTPException: 400 for a malformed cursor; 403 without ``teams:view`` or without a
            tenant.
    """
    enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW, target="unowned-findings")
    _ = tenant_slug
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    page = list_unowned_findings(
        db,
        str(tenant_id),
        finding_type=finding_type,
        limit=limit,
        offset=offset,
        cursor=parse_time_id_cursor(cursor),
        include_total=include_total,
    )
    return UnownedFindingsResponse(
        items=[UnownedFinding(**item) for item in page["items"]],
        total=page.get("total"),
        has_more=bool(page.get("has_more")),
        next_cursor=page.get("next_cursor"),
    )
