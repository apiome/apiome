"""``/v1/tenants/{tenant_slug}/pacticipants`` — the pacticipant registry, PFX-1.1 (#6914).

The applications that take part in pacts, and the versions, branches and tags Pact tooling names
them by. This is the model the rest of the Pact Broker surface (publication, verification results,
the matrix, can-i-deploy) is built on. Every route is scoped to the authenticated tenant and
guarded by the ``pacts`` resource:

* ``GET …/pacticipants``, ``GET …/pacticipants/{ref}``, ``GET …/versions``,
  ``GET …/versions/{number}``, ``GET …/branches`` — ``pacts:view``;
* ``POST …/pacticipants``, ``PUT …/versions/{number}``, ``PUT …/versions/{number}/tags/{tag}`` —
  ``pacts:create``. Recording a version or a tag only ever adds; nothing stored is changed;
* ``PATCH …/pacticipants/{ref}`` — ``pacts:edit``;
* ``DELETE …/pacticipants/{ref}`` — ``pacts:delete`` (Owner and Admin), because it removes the
  pacticipant's whole version history.

``{ref}`` is the pacticipant's handle, its id, or its display name.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .keyset_pagination import cursor_query, limit_query
from .pacticipant import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_VERSION_NOT_FOUND,
    PacticipantBranchRecord,
    PacticipantInput,
    PacticipantPatch,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionInput,
    PacticipantVersionRecord,
    RecordedPacticipantVersion,
)
from .pacticipant_store import (
    BRANCHES_ORDER,
    PACTICIPANTS_ORDER,
    VERSIONS_ORDER,
    add_tag,
    create_pacticipant,
    delete_pacticipant,
    get_pacticipant,
    get_version,
    list_branches,
    list_pacticipants,
    list_versions,
    record_version,
    update_pacticipant,
)
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

#: The HTTP status of each refusal code; anything else is a 400.
_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_CONSUMER_NOT_FOUND: 404,
    CODE_SLUG_TAKEN: 409,
}

_PAGING_NOTE = (
    "Pass the previous page's `next_cursor` as `cursor` until `has_more` is false."
)


class PacticipantListResponse(BaseModel):
    """One page of the tenant's pacticipants."""

    model_config = ConfigDict(extra="forbid")

    pacticipants: List[PacticipantRecord] = Field(default_factory=list, description="By handle.")
    count: int = Field(description="How many pacticipants were returned.")
    has_more: bool = Field(default=False, description="Whether another page exists.")
    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` to read the next page; null on the last page."
    )


class PacticipantVersionListResponse(BaseModel):
    """One page of a pacticipant's versions."""

    model_config = ConfigDict(extra="forbid")

    versions: List[PacticipantVersionRecord] = Field(default_factory=list, description="Latest recorded first.")
    count: int = Field(description="How many versions were returned.")
    has_more: bool = Field(default=False, description="Whether another page exists.")
    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` to read the next page; null on the last page."
    )


class PacticipantBranchListResponse(BaseModel):
    """One page of a pacticipant's branches."""

    model_config = ConfigDict(extra="forbid")

    branches: List[PacticipantBranchRecord] = Field(default_factory=list, description="By name.")
    count: int = Field(description="How many branches were returned.")
    has_more: bool = Field(default=False, description="Whether another page exists.")
    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` to read the next page; null on the last page."
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


def _http_error(exc: PacticipantValidationError) -> HTTPException:
    """Translate a registry refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` to raise — 404 for anything unknown, 409 for a taken handle, 400 for
        every other fault — always carrying ``{"code", "message"}``.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


# ---------------------------------------------------------------------------------------------
# Pacticipants
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/pacticipants",
    response_model=PacticipantListResponse,
    summary="List pacticipants",
    description=(
        "The applications registered as pacticipants in this workspace, ordered by handle.\n\n"
        f"{_PAGING_NOTE}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_tenant_pacticipants(
    tenant_slug: str,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantListResponse:
    """List one page of the tenant's pacticipants.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what actually scopes it).
        limit: Page size.
        cursor: Where the page starts (the previous page's ``next_cursor``).
        auth_data: The authenticated principal.

    Returns:
        The pacticipants of the page and whether another follows.

    Raises:
        HTTPException: 400 for a malformed cursor, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    after = PACTICIPANTS_ORDER.parse(cursor)
    _ = tenant_slug
    rows = list_pacticipants(db, _tenant_id(auth_data), limit=limit + 1, cursor=after)
    page = PACTICIPANTS_ORDER.page(rows, limit)
    return PacticipantListResponse(
        pacticipants=page.items, count=len(page.items), has_more=page.has_more, next_cursor=page.next_cursor
    )


@router.post(
    "/{tenant_slug}/pacticipants",
    response_model=PacticipantRecord,
    status_code=201,
    summary="Register a pacticipant",
    description=(
        "Register an application that takes part in pacts. The handle (`slug`) is what URLs and CI "
        "name; it is derived from `name` when omitted (`Billing Service` becomes "
        "`billing-service`), is unique in the workspace, and is **not** editable afterwards.\n\n"
        "`project` binds a provider to the project that describes it; `consumer_id` binds a "
        "consumer to its row in the consumer registry. Both are optional and must belong to this "
        "workspace. Deleting the project or the consumer clears the binding and keeps the "
        "pacticipant.\n\n"
        "Requires `pacts:create`."
    ),
    responses={409: {"description": "`pacticipant-slug-taken`: the workspace already has that handle."}},
)
def register_pacticipant(
    tenant_slug: str,
    body: PacticipantInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantRecord:
    """Register a new pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        body: The pacticipant's identity and optional bindings.
        auth_data: The authenticated principal.

    Returns:
        The stored pacticipant.

    Raises:
        HTTPException: 400 for a malformed field, 404 for an unknown project or consumer, 409 when
            the handle is taken, 403 without ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=body.slug or body.name)
    _ = tenant_slug
    try:
        return create_pacticipant(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}",
    response_model=PacticipantRecord,
    summary="Read one pacticipant",
    description=(
        "Read a pacticipant by its handle, its id, or its display name (`Billing Service` finds "
        "`billing-service`).\n\n"
        "Requires `pacts:view`."
    ),
)
def read_pacticipant(
    tenant_slug: str,
    pacticipant_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantRecord:
    """Read one pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        auth_data: The authenticated principal.

    Returns:
        The pacticipant.

    Raises:
        HTTPException: 404 when nothing matches in this tenant, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}",
    response_model=PacticipantRecord,
    summary="Update a pacticipant",
    description=(
        "Change the display name, repository URL, main branch or bindings. A field that is left "
        "out is not changed; `null` clears `repository_url` and `main_branch` and unbinds "
        "`project` and `consumer_id`. The handle cannot be changed.\n\n"
        "Requires `pacts:edit`."
    ),
)
def patch_pacticipant(
    tenant_slug: str,
    pacticipant_ref: str,
    body: PacticipantPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantRecord:
    """Update a pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        body: The fields to change.
        auth_data: The authenticated principal.

    Returns:
        The updated pacticipant.

    Raises:
        HTTPException: 400 for a malformed field, 404 for an unknown pacticipant, project or
            consumer, 403 without ``pacts:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=pacticipant_ref)
    _ = tenant_slug
    try:
        return update_pacticipant(
            db, _tenant_id(auth_data), pacticipant_ref, body, actor=actor_from_auth(auth_data, user_id)
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}",
    status_code=204,
    summary="Delete a pacticipant",
    description=(
        "Delete a pacticipant **with all of its versions, branches and tags**. This cannot be "
        "undone. The project and the consumer it was bound to are not touched.\n\n"
        "Requires `pacts:delete` (the built-in Owner and Admin roles)."
    ),
)
def remove_pacticipant(
    tenant_slug: str,
    pacticipant_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a pacticipant and its history.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant, 403 without ``pacts:delete``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        delete_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------
# Versions, branches and tags
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/versions",
    response_model=PacticipantVersionListResponse,
    summary="List a pacticipant's versions",
    description=(
        "The versions recorded for this pacticipant, latest recorded first, each with the "
        "branches it was recorded on and its tags. `branch` and `tag` narrow the list, so the "
        "first row of `?branch=main` is the head of `main` and the first row of `?tag=prod` is "
        "the latest version tagged `prod`.\n\n"
        f"{_PAGING_NOTE}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_pacticipant_versions(
    tenant_slug: str,
    pacticipant_ref: str,
    branch: Optional[str] = Query(default=None, max_length=255, description="Only versions recorded on this branch."),
    tag: Optional[str] = Query(default=None, max_length=255, description="Only versions carrying this tag."),
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantVersionListResponse:
    """List one page of a pacticipant's versions.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        branch: Only versions recorded on this branch.
        tag: Only versions carrying this tag.
        limit: Page size.
        cursor: Where the page starts (the previous page's ``next_cursor``).
        auth_data: The authenticated principal.

    Returns:
        The versions of the page and whether another follows.

    Raises:
        HTTPException: 400 for a malformed cursor, 404 for an unknown pacticipant, 403 without
            ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    after = VERSIONS_ORDER.parse(cursor)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    rows = list_versions(db, pacticipant, branch=branch, tag=tag, limit=limit + 1, cursor=after)
    page = VERSIONS_ORDER.page(rows, limit)
    return PacticipantVersionListResponse(
        versions=page.items, count=len(page.items), has_more=page.has_more, next_cursor=page.next_cursor
    )


@router.put(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}",
    response_model=RecordedPacticipantVersion,
    summary="Record a version",
    description=(
        "Record that a build produced version `number` of this pacticipant, optionally with the "
        "branch it was built from and tags. Safe to repeat:\n\n"
        "- **A version is created once and never changes.** The first request answers `201` and "
        "stores `build_url`. A later request for the same number answers `200` with the stored "
        "version; its `build_url` is not replaced.\n"
        "- **A branch head only moves forward.** The version is added to `branch`, and becomes "
        "its head only when it was recorded later than the current head (`head_moved`). Recording "
        "an older version on a branch does not move the head back.\n"
        "- **Tags are added once.** Sending a tag the version already has changes nothing.\n\n"
        "The version number is stored exactly as sent. It cannot contain a `/` here, because it is "
        "a path segment.\n\n"
        "Requires `pacts:create`."
    ),
    responses={201: {"description": "The version was created by this request.", "model": RecordedPacticipantVersion}},
)
def put_pacticipant_version(
    tenant_slug: str,
    pacticipant_ref: str,
    number: str,
    response: Response,
    body: Optional[PacticipantVersionInput] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RecordedPacticipantVersion:
    """Record a version, its branch and its tags.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        number: The version number, as the build reported it.
        response: The response, whose status becomes 201 when the version is new.
        body: Build URL, branch and tags; may be omitted.
        auth_data: The authenticated principal.

    Returns:
        The stored version, whether it was created, and whether the branch head moved.

    Raises:
        HTTPException: 400 for a malformed number, URL, branch or tag, 404 for an unknown
            pacticipant, 403 without ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
        recorded = record_version(
            db, pacticipant, number, body or PacticipantVersionInput(), actor=actor_from_auth(auth_data, user_id)
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    response.status_code = 201 if recorded.created else 200
    return recorded


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}",
    response_model=PacticipantVersionRecord,
    summary="Read one version",
    description=(
        "Read a version by its number, with the branches it was recorded on and its tags.\n\n"
        "Requires `pacts:view`."
    ),
)
def read_pacticipant_version(
    tenant_slug: str,
    pacticipant_ref: str,
    number: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantVersionRecord:
    """Read one version.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        number: The version number, exactly as recorded.
        auth_data: The authenticated principal.

    Returns:
        The version.

    Raises:
        HTTPException: 404 for an unknown pacticipant or version, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
        return get_version(db, pacticipant, number)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}/tags/{tag:path}",
    response_model=PacticipantVersionRecord,
    summary="Tag a version",
    description=(
        "Put a tag on a recorded version. Tagging a version that already has the tag changes "
        "nothing and answers the same way. A tag may contain `/` (`feat/new-invoice`).\n\n"
        "Requires `pacts:create`."
    ),
)
def put_pacticipant_version_tag(
    tenant_slug: str,
    pacticipant_ref: str,
    number: str,
    tag: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantVersionRecord:
    """Tag a version.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        number: The version number.
        tag: The tag.
        auth_data: The authenticated principal.

    Returns:
        The version with its tags.

    Raises:
        HTTPException: 400 for a malformed tag, 404 for an unknown pacticipant or version, 403
            without ``pacts:create``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
        return add_tag(db, pacticipant, number, tag)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/branches",
    response_model=PacticipantBranchListResponse,
    summary="List a pacticipant's branches",
    description=(
        "The branches versions were recorded on, by name, each with its head: the latest version "
        "recorded on it. `is_main` marks the pacticipant's main branch.\n\n"
        f"{_PAGING_NOTE}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_pacticipant_branches(
    tenant_slug: str,
    pacticipant_ref: str,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantBranchListResponse:
    """List one page of a pacticipant's branches.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        limit: Page size.
        cursor: Where the page starts (the previous page's ``next_cursor``).
        auth_data: The authenticated principal.

    Returns:
        The branches of the page and whether another follows.

    Raises:
        HTTPException: 400 for a malformed cursor, 404 for an unknown pacticipant, 403 without
            ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    after = BRANCHES_ORDER.parse(cursor)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    rows = list_branches(db, pacticipant, limit=limit + 1, cursor=after)
    page = BRANCHES_ORDER.page(rows, limit)
    return PacticipantBranchListResponse(
        branches=page.items, count=len(page.items), has_more=page.has_more, next_cursor=page.next_cursor
    )
