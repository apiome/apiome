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
    total: int


@router.get(
    "/{tenant_slug}/unowned-findings",
    response_model=UnownedFindingsResponse,
    summary="List unowned findings",
    description=(
        "Findings that reached no team because their entity has no confirmed owner — never dropped, "
        "kept here, newest first. One row per entity and finding type, with `occurrences` and the "
        "latest `payload`. Assigning an owner (`PUT /v1/tenants/{tenant}/owners/{kind}/{id}`) routes "
        "the next occurrence to the team and clears the row.\n\nRequires `teams:view`."
    ),
)
async def get_unowned_findings(
    tenant_slug: str,
    finding_type: Optional[FindingType] = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UnownedFindingsResponse:
    """List the tenant's unowned findings.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes the read).
        finding_type: Only this finding type.
        limit: Page size.
        offset: Rows to skip.
        auth_data: The authenticated principal.

    Returns:
        The page and the total.

    Raises:
        HTTPException: 403 without ``teams:view`` or without a tenant.
    """
    enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW, target="unowned-findings")
    _ = tenant_slug
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    page = list_unowned_findings(
        db, str(tenant_id), finding_type=finding_type, limit=limit, offset=offset
    )
    return UnownedFindingsResponse(
        items=[UnownedFinding(**item) for item in page["items"]], total=page["total"]
    )
