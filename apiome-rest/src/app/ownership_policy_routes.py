"""``/v1/tenants/{tenant_slug}/ownership-policy`` and ``…/ownership-drift`` — CDG-2.5 (#5964).

* ``GET|PUT …/ownership-policy`` — the catch-all team and "require an owner to publish". Reading
  needs ``teams:view``; changing needs ``teams:edit`` (Owner and Admin by default). Audited as
  ``ownership_policy.update``.
* ``GET …/ownership-policy/publish-gate?project=`` — the owner gate's verdict for one project, which
  the publish dialog shows *before* publishing, including when the gate is off. Needs
  ``versions:view``, like the gate it previews.
* ``GET …/ownership-drift`` — entities whose owner team was deleted or is empty, and suggestions
  nobody confirmed in 30 days. Needs ``teams:view``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .ownership_policy import (
    OwnershipPolicy,
    OwnershipPolicyError,
    OwnershipPolicyInput,
    assess_owner_gate,
    ownership_drift,
    read_policy,
    update_policy,
)
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["owners"])


class OwnerGateResponse(BaseModel):
    """The owner gate's verdict for one project."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="`disabled`, `satisfied` or `blocked`.")
    message: str
    reason: Optional[str] = Field(default=None, description="`no-owner` when blocked.")
    team: Optional[Dict[str, Optional[str]]] = None


class DriftItem(BaseModel):
    """One entity whose ownership has drifted."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description="`deleted_team`, `empty_team` or `stale_suggestion`.")
    entity_kind: str
    entity_id: str
    entity_name: Optional[str] = None
    team: Dict[str, Optional[str]]
    since: Optional[str] = None


class DriftResponse(BaseModel):
    """The ownership drift report."""

    model_config = ConfigDict(extra="forbid")

    items: List[DriftItem] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict, description="Rows per reason (before the per-reason cap).")
    stale_after_days: int


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/ownership-policy",
    response_model=OwnershipPolicy,
    summary="Read the ownership policy",
    description=(
        "The catch-all team for findings on entities with no confirmed owner, and whether a project "
        "needs a confirmed owner to publish.\n\nRequires `teams:view`."
    ),
)
async def get_ownership_policy(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> OwnershipPolicy:
    """Read the policy."""
    enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW, target="ownership-policy")
    _ = tenant_slug
    return read_policy(_tenant_id(auth_data))


@router.put(
    "/{tenant_slug}/ownership-policy",
    response_model=OwnershipPolicy,
    summary="Change the ownership policy",
    description=(
        "Set `unowned_findings_team` (a team slug, or `null` for none) and/or "
        "`require_owner_to_publish`. Omitted fields are left alone.\n\n"
        "Audited as `ownership_policy.update`. Requires `teams:edit`."
    ),
)
async def put_ownership_policy(
    tenant_slug: str,
    body: OwnershipPolicyInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> OwnershipPolicy:
    """Change the policy.

    Raises:
        HTTPException: 404 when the catch-all team is unknown, 403 without ``teams:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.TEAMS, Action.EDIT, target="ownership-policy")
    _ = tenant_slug
    try:
        return update_policy(_tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
    except OwnershipPolicyError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get(
    "/{tenant_slug}/ownership-policy/publish-gate",
    response_model=OwnerGateResponse,
    summary="Preview the owner gate for a project",
    description=(
        "What the owner gate will say when a version of `project` is published: `disabled` (the "
        "gate is off), `satisfied` (the project has a confirmed owner) or `blocked` (reason "
        "`no-owner`).\n\nRequires `versions:view`."
    ),
)
async def get_owner_publish_gate(
    tenant_slug: str,
    project: str = Query(..., description="The project's id."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> OwnerGateResponse:
    """Preview the owner gate."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _ = tenant_slug
    if not is_uuid_string(project):
        raise HTTPException(status_code=400, detail={"code": "owner-gate-invalid", "message": "project must be an id"})
    return OwnerGateResponse(**assess_owner_gate(tenant_id=_tenant_id(auth_data), project_id=project).as_payload())


@router.get(
    "/{tenant_slug}/ownership-drift",
    response_model=DriftResponse,
    summary="List ownership drift",
    description=(
        "Entities whose confirmed owner team was deleted (`deleted_team`) or has no members "
        "(`empty_team`), and suggested owners nobody confirmed in 30 days (`stale_suggestion`). "
        "At most 200 rows per reason; `counts` has the totals.\n\nRequires `teams:view`."
    ),
)
async def get_ownership_drift(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> DriftResponse:
    """Read the drift report."""
    enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW, target="ownership-drift")
    _ = tenant_slug
    return DriftResponse(**ownership_drift(_tenant_id(auth_data)))
