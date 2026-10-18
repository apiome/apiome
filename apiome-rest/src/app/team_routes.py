"""``/v1/tenants/{tenant_slug}/teams`` — CDG-2.1 (#5960).

The HTTP surface of teams: list and create a tenant's teams, read, update and delete one, and
replace its membership. A team is the durable "who" that CDG-2.2 assigns entities to and CDG-2.3
routes findings to; this ticket adds the group itself.

**Authorization** uses the ``teams`` RBAC resource added by apiome-db V284. Owner and Admin hold
``view|create|edit|delete``; Editor and Viewer hold ``view`` only, because membership decides who
is notified about — and paged for — an entity's findings. Replacing the membership is ``edit``.

**A refusal carries a stable code.** Every error detail is ``{"code", "message"}``; a delete
refused because the team still owns entities is a 409 that also carries ``owned_count``, so a
client can say how many entities need a new owner before offering ``?reassign_to=``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .permissions import Action, Resource, enforce_permission
from .team_store import (
    create_team,
    delete_team,
    get_team,
    list_teams,
    replace_team_members,
    team_activity,
    update_team,
)
from .teams import (
    CODE_MEMBER_NOT_IN_TENANT,
    CODE_NOT_FOUND,
    CODE_OWNS_ENTITIES,
    CODE_SLUG_TAKEN,
    TeamInput,
    TeamMembersInput,
    TeamPatch,
    TeamRecord,
    TeamValidationError,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["teams"])

#: A refusal maps onto the status that matches what kind of refusal it is; anything else is 400.
_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_SLUG_TAKEN: 409,
    CODE_OWNS_ENTITIES: 409,
    CODE_MEMBER_NOT_IN_TENANT: 422,
}


class TeamListResponse(BaseModel):
    """Every live team of the tenant."""

    model_config = ConfigDict(extra="forbid")

    teams: List[TeamRecord] = Field(default_factory=list, description="The teams, by name.")
    count: int = Field(description="How many teams were returned.")


class OwnedEntity(BaseModel):
    """An entity the team is the confirmed owner of."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="`project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`.")
    id: str
    name: str
    source: str = Field(description="How the ownership was set: `manual`, `gateway_tag`, …")


class RoutedEvent(BaseModel):
    """One finding routed to the team (one event, however many members it reached)."""

    model_config = ConfigDict(extra="forbid")

    type: str
    entity_kind: Optional[str] = None
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    summary: Optional[str] = None
    link: Optional[str] = None
    created_at: Optional[str] = None
    recipients: int = Field(description="How many members it reached.")


class TeamActivityResponse(BaseModel):
    """A team page's ownership and routing picture (CDG-2.4)."""

    model_config = ConfigDict(extra="forbid")

    team_id: str
    owned: List[OwnedEntity] = Field(default_factory=list, description="Confirmed ownership, by kind then name.")
    owned_counts: Dict[str, int] = Field(default_factory=dict, description="Owned entities per kind.")
    suggested_count: int = Field(description="Entities that suggest this team as owner.")
    open_findings: int = Field(
        description="The caller's unread owner-finding notifications routed to this team."
    )
    events: List[RoutedEvent] = Field(
        default_factory=list, description="Findings routed to the team in the last 30 days, newest first."
    )


class TeamDeleteResponse(BaseModel):
    """What a delete did."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="The deleted team's slug (now free for reuse).")
    owned_count: int = Field(description="How many entities the team owned when it was deleted.")
    reassigned_to: Optional[str] = Field(
        default=None, description="The team that took over those entities, when any moved."
    )


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(exc: TeamValidationError) -> HTTPException:
    """Translate a team refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException``: 404 unknown team, 409 slug taken or team owns entities, 422 member
        not in tenant, 400 otherwise — always ``{"code", "message"}``, plus ``owned_count`` for
        ``team-owns-entities``.
    """
    detail: Dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.owned_count is not None:
        detail["owned_count"] = exc.owned_count
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=detail)


@router.get(
    "/{tenant_slug}/teams",
    response_model=TeamListResponse,
    summary="List teams",
    description=(
        "Every live team of the tenant, by name, with its owner links and member count. "
        "Deleted teams are not listed.\n\nRequires `teams:view`."
    ),
)
async def list_tenant_teams(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> TeamListResponse:
    """List the tenant's teams.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        auth_data: The authenticated principal.

    Returns:
        The teams.

    Raises:
        HTTPException: 403 without ``teams:view``.
    """
    enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW)
    _ = tenant_slug
    teams = list_teams(_tenant_id(auth_data))
    return TeamListResponse(teams=teams, count=len(teams))


@router.post(
    "/{tenant_slug}/teams",
    response_model=TeamRecord,
    status_code=201,
    summary="Create a team",
    description=(
        "Create a team. The `slug` is derived from `name` when omitted and cannot be changed "
        "afterwards — gateway tags (`owner:<slug>`) and the `x-apiome-owner` extension name "
        "teams by it. `chat_url`, `oncall_url` and `docs_url` must be absolute http(s) URLs.\n\n"
        "Audited as `team.create`. Requires `teams:create`."
    ),
)
async def create_tenant_team(
    tenant_slug: str,
    body: TeamInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TeamRecord:
    """Create a team.

    Args:
        tenant_slug: The tenant in the URL.
        body: The team.
        auth_data: The authenticated principal.

    Returns:
        The stored team.

    Raises:
        HTTPException: 400 for a malformed field, 409 when the slug is taken, 403 without
            ``teams:create``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.TEAMS, Action.CREATE, target=body.slug or body.name
    )
    _ = tenant_slug
    try:
        return create_team(
            _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id)
        )
    except TeamValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/teams/{team_slug}",
    response_model=TeamRecord,
    summary="Read a team",
    description="One live team with its members, leads first.\n\nRequires `teams:view`.",
)
async def read_tenant_team(
    tenant_slug: str,
    team_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TeamRecord:
    """Read one team with its members.

    Args:
        tenant_slug: The tenant in the URL.
        team_slug: The team's slug.
        auth_data: The authenticated principal.

    Returns:
        The team.

    Raises:
        HTTPException: 404 for an unknown team, 403 without ``teams:view``.
    """
    enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_team(_tenant_id(auth_data), team_slug)
    except TeamValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/teams/{team_slug}/activity",
    response_model=TeamActivityResponse,
    summary="Read a team's ownership and routed findings",
    description=(
        "What the team owns (confirmed owners only, by kind), how many entities suggest it, how "
        "many owner-finding notifications routed to it the caller has not read, and the findings "
        "routed to it in the last 30 days — one row per event, however many members it reached."
        "\n\nRequires `teams:view`."
    ),
)
async def read_tenant_team_activity(
    tenant_slug: str,
    team_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TeamActivityResponse:
    """Read a team's ownership and routing picture.

    Args:
        tenant_slug: The tenant in the URL.
        team_slug: The team's slug.
        auth_data: The authenticated principal.

    Returns:
        The activity.

    Raises:
        HTTPException: 404 for an unknown team, 403 without ``teams:view``.
    """
    user_id = enforce_permission(db, auth_data, Resource.TEAMS, Action.VIEW)
    _ = tenant_slug
    try:
        return TeamActivityResponse(**team_activity(_tenant_id(auth_data), team_slug, user_id))
    except TeamValidationError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{tenant_slug}/teams/{team_slug}",
    response_model=TeamRecord,
    summary="Update a team",
    description=(
        "Change a team's name, description or owner links. Omitted fields are left alone; "
        "`null` clears an optional field. The slug is not updatable.\n\n"
        "Audited as `team.update` with each changed field's old and new value. "
        "Requires `teams:edit`."
    ),
)
async def patch_tenant_team(
    tenant_slug: str,
    team_slug: str,
    body: TeamPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TeamRecord:
    """Update a team.

    Args:
        tenant_slug: The tenant in the URL.
        team_slug: The team's slug.
        body: The fields to change.
        auth_data: The authenticated principal.

    Returns:
        The updated team with its members.

    Raises:
        HTTPException: 400 for a malformed field, 404 for an unknown team, 403 without
            ``teams:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.TEAMS, Action.EDIT, target=team_slug)
    _ = tenant_slug
    try:
        return update_team(
            _tenant_id(auth_data), team_slug, body, actor=actor_from_auth(auth_data, user_id)
        )
    except TeamValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/teams/{team_slug}",
    response_model=TeamDeleteResponse,
    summary="Delete a team",
    description=(
        "Soft-delete a team: it disappears from reads and its slug becomes free. A team that "
        "still owns entities is refused with **409** `team-owns-entities` and the "
        "`owned_count`, unless `reassign_to` names another live team to take them over.\n\n"
        "Audited as `team.delete`. Requires `teams:delete`."
    ),
)
async def delete_tenant_team(
    tenant_slug: str,
    team_slug: str,
    reassign_to: Optional[str] = Query(
        default=None,
        max_length=128,
        description="Slug of the live team that takes over the deleted team's entities.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TeamDeleteResponse:
    """Delete a team.

    Args:
        tenant_slug: The tenant in the URL.
        team_slug: The team's slug.
        reassign_to: The team that takes over the deleted team's entities.
        auth_data: The authenticated principal.

    Returns:
        What the delete did.

    Raises:
        HTTPException: 404 for an unknown team, 409 when it owns entities and ``reassign_to`` is
            absent, 400 when ``reassign_to`` is this team or unknown, 403 without
            ``teams:delete``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.TEAMS, Action.DELETE, target=team_slug
    )
    _ = tenant_slug
    try:
        result = delete_team(
            _tenant_id(auth_data),
            team_slug,
            actor=actor_from_auth(auth_data, user_id),
            reassign_to=reassign_to,
        )
    except TeamValidationError as exc:
        raise _http_error(exc) from exc
    return TeamDeleteResponse(**result)


@router.put(
    "/{tenant_slug}/teams/{team_slug}/members",
    response_model=TeamRecord,
    summary="Replace a team's members",
    description=(
        "Set the team's complete membership; anyone not listed is removed, and an empty list "
        "empties the team. Each member is a `user_id` with a `role` of `lead` or `member`. "
        "Every user must be a member of the tenant — otherwise **422** "
        "`team-member-not-in-tenant` names them and nothing changes. A user who later leaves "
        "the tenant leaves every team automatically.\n\n"
        "Audited as `team.members.replace` with who was added, removed or changed role. "
        "Requires `teams:edit`."
    ),
)
async def put_tenant_team_members(
    tenant_slug: str,
    team_slug: str,
    body: TeamMembersInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TeamRecord:
    """Replace a team's membership.

    Args:
        tenant_slug: The tenant in the URL.
        team_slug: The team's slug.
        body: The complete new membership.
        auth_data: The authenticated principal.

    Returns:
        The team with its new members.

    Raises:
        HTTPException: 400 for a duplicate or malformed user id, 404 for an unknown team, 422
            when a user is not a tenant member, 403 without ``teams:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.TEAMS, Action.EDIT, target=team_slug)
    _ = tenant_slug
    try:
        return replace_team_members(
            _tenant_id(auth_data),
            team_slug,
            body.members,
            actor=actor_from_auth(auth_data, user_id),
        )
    except TeamValidationError as exc:
        raise _http_error(exc) from exc
