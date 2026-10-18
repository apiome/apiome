"""``/v1/tenants/{tenant_slug}/owners`` — CDG-2.2 (#5961).

Read and change who owns a catalog entity: a project, catalog item, MCP endpoint, consumer or
connector. An entity has at most one **confirmed** owner team — the one findings are routed to
(CDG-2.3) — and any number of **suggested** owners that importers found (gateway tags, CODEOWNERS,
``x-apiome-owner``, ``info.contact``), each with its source. Suggestions never receive anything
until someone confirms one.

**Authorization** is the permission that already guards editing the entity (see
:data:`app.entity_owners.KINDS`): reads need its ``view``, changes its ``edit``. A bulk assignment
checks ``edit`` for every kind it touches.

Every change is audited (``owner.assign``, ``owner.remove``, ``owner.confirm``, ``owner.bulk_assign``).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .entity_owner_store import (
    assign_owner,
    bulk_assign_owner,
    confirm_owner,
    read_owners,
    remove_owner,
)
from .entity_owners import (
    CODE_ENTITY_NOT_FOUND,
    CODE_NO_SUGGESTION,
    CODE_TEAM_NOT_FOUND,
    BulkAssignInput,
    OwnerAssignInput,
    OwnerConfirmInput,
    OwnersResponse,
    OwnerValidationError,
    kind_spec,
)
from .ownership_policy import owner_facts
from .permissions import Action, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["owners"])

_STATUS_BY_CODE = {
    CODE_ENTITY_NOT_FOUND: 404,
    CODE_TEAM_NOT_FOUND: 404,
    CODE_NO_SUGGESTION: 404,
}


class BulkAssignResponse(BaseModel):
    """The owners of every entity a bulk assignment touched."""

    model_config = ConfigDict(extra="forbid")

    results: List[OwnersResponse] = Field(default_factory=list)
    count: int


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or 403 when the credential carries none."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(exc: OwnerValidationError) -> HTTPException:
    """404 for an unknown entity/team/suggestion, 400 otherwise, always ``{"code", "message"}``."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


def _guard(auth_data: Dict[str, Any], kind: str, action: str, entity_id: str) -> str:
    """Enforce the kind's own permission for ``action``; an unknown kind is a 400.

    Returns:
        The acting user id.
    """
    try:
        spec = kind_spec(kind)
    except OwnerValidationError as exc:
        raise _http_error(exc) from exc
    return enforce_permission(db, auth_data, spec.resource, action, target=f"{kind}:{entity_id}")


_KIND_HELP = (
    "`kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; reading needs "
    "the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP "
    "endpoints, `consumer_contracts` for consumers, `imports` for connectors)."
)


@router.get(
    "/{tenant_slug}/owners/{kind}/{entity_id}",
    response_model=OwnersResponse,
    summary="Read an entity's owner",
    description=(
        "The confirmed owner team, if any, and every suggested owner with its `source` "
        "(`gateway_tag`, `codeowners`, `spec_extension`, …) and `source_ref`.\n\n" + _KIND_HELP
    ),
)
async def get_entity_owner(
    tenant_slug: str,
    kind: str,
    entity_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> OwnersResponse:
    """Read an entity's owners.

    Raises:
        HTTPException: 400 unknown kind, 404 unknown entity, 403 without the kind's ``view``.
    """
    _guard(auth_data, kind, Action.VIEW, entity_id)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        response = read_owners(tenant_id, kind, entity_id)
    except OwnerValidationError as exc:
        raise _http_error(exc) from exc
    # CDG-2.5: the owner.* facts GVM-1.x ladders read, from one shared function.
    return response.model_copy(update={"facts": owner_facts(tenant_id, kind, entity_id)})


@router.put(
    "/{tenant_slug}/owners/{kind}/{entity_id}",
    response_model=OwnersResponse,
    summary="Assign an entity's owner",
    description=(
        "Make `team` (a team slug) the confirmed owner, replacing any previous one. A previous "
        "owner that came from a suggestion goes back to being a suggestion.\n\n"
        "Audited as `owner.assign`. " + _KIND_HELP
    ),
)
async def put_entity_owner(
    tenant_slug: str,
    kind: str,
    entity_id: str,
    body: OwnerAssignInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> OwnersResponse:
    """Assign an entity's owner.

    Raises:
        HTTPException: 400 unknown kind, 404 unknown entity or team, 403 without the kind's ``edit``.
    """
    user_id = _guard(auth_data, kind, Action.EDIT, entity_id)
    _ = tenant_slug
    try:
        return assign_owner(
            _tenant_id(auth_data), kind, entity_id, body.team,
            actor=actor_from_auth(auth_data, user_id),
        )
    except OwnerValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/owners/{kind}/{entity_id}",
    response_model=OwnersResponse,
    summary="Remove an entity's owner",
    description=(
        "Remove the confirmed owner. Suggestions are kept; an owner that came from a suggestion "
        "becomes a suggestion again.\n\nAudited as `owner.remove`. " + _KIND_HELP
    ),
)
async def delete_entity_owner(
    tenant_slug: str,
    kind: str,
    entity_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> OwnersResponse:
    """Remove an entity's confirmed owner.

    Raises:
        HTTPException: 400 unknown kind, 404 unknown entity, 403 without the kind's ``edit``.
    """
    user_id = _guard(auth_data, kind, Action.EDIT, entity_id)
    _ = tenant_slug
    try:
        return remove_owner(
            _tenant_id(auth_data), kind, entity_id, actor=actor_from_auth(auth_data, user_id)
        )
    except OwnerValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{tenant_slug}/owners/{kind}/{entity_id}/confirm",
    response_model=OwnersResponse,
    summary="Confirm a suggested owner",
    description=(
        "Make a suggested owner the confirmed owner. Name it with `team`; it may be omitted when "
        "only one team is suggested. The owner keeps its `source` and records who confirmed it "
        "(`confirmed_by`, `confirmed_at`).\n\nAudited as `owner.confirm`. " + _KIND_HELP
    ),
)
async def confirm_entity_owner(
    tenant_slug: str,
    kind: str,
    entity_id: str,
    body: OwnerConfirmInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> OwnersResponse:
    """Confirm a suggestion.

    Raises:
        HTTPException: 404 when there is no such suggestion, 400 when several teams are suggested
            and none is named, 403 without the kind's ``edit``.
    """
    user_id = _guard(auth_data, kind, Action.EDIT, entity_id)
    _ = tenant_slug
    try:
        return confirm_owner(
            _tenant_id(auth_data), kind, entity_id, body.team,
            actor=actor_from_auth(auth_data, user_id),
        )
    except OwnerValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{tenant_slug}/owners:assign",
    response_model=BulkAssignResponse,
    summary="Assign one owner to many entities",
    description=(
        "Make `team` the confirmed owner of every entity in `entities` (`[{kind, id}]`, up to "
        "200), all or nothing: an entity that does not exist fails the whole request with 404.\n\n"
        "Needs `edit` on every kind in the list. Audited as one `owner.bulk_assign`."
    ),
)
async def bulk_assign_entity_owner(
    tenant_slug: str,
    body: BulkAssignInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BulkAssignResponse:
    """Assign one owner to many entities.

    Raises:
        HTTPException: 404 unknown team or entity, 403 without ``edit`` on any kind listed.
    """
    user_id = ""
    for kind in sorted({ref.kind for ref in body.entities}):
        user_id = _guard(auth_data, kind, Action.EDIT, "bulk")
    _ = tenant_slug
    try:
        results = bulk_assign_owner(
            _tenant_id(auth_data), body.team, body.entities,
            actor=actor_from_auth(auth_data, user_id),
        )
    except OwnerValidationError as exc:
        raise _http_error(exc) from exc
    return BulkAssignResponse(results=results, count=len(results))
