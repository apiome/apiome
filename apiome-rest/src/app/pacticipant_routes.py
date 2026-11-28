"""``/v1/tenants/{tenant_slug}/pacticipants`` — the pacticipant registry, PFX-1.1 (#6914).

The applications that take part in pacts, and the versions, branches and tags Pact tooling names
them by. This is the model the rest of the Pact Broker surface (publication, verification results,
the matrix, can-i-deploy) is built on. Every route is scoped to the authenticated tenant and
guarded by the ``pacts`` resource:

* ``GET …/pacticipants``, ``GET …/pacticipants/{ref}``, ``GET …/deletion-impact`` (PFX-8.10),
  ``GET …/versions``, ``GET …/versions/{number}``, ``GET …/branches`` — ``pacts:view``;
* ``POST …/pacticipants``, ``PUT …/versions/{number}``, ``PUT …/versions/{number}/tags/{tag}`` —
  ``pacts:create``. Recording a version or a tag only ever adds; nothing stored is changed;
* ``PATCH …/pacticipants/{ref}``, ``PUT``/``DELETE …/labels/{label}`` — ``pacts:edit``;
* ``DELETE …/pacticipants/{ref}``, ``DELETE …/versions/{number}`` and their ``POST …/restore`` —
  ``pacts:delete`` (Owner and Admin), because a delete hides a whole version history.

A delete is soft (PFX-1.11, #6924): the pacticipant or version disappears from every read at once,
can be restored for ``APIOME_PACT_DELETION_GRACE_DAYS`` (default 30) days, and is then purged.
``?state=deleted`` on the two lists shows what is waiting to be purged.

``{ref}`` is the pacticipant's handle, its id, or its name — including a name it had before it was
renamed (PFX-8.10, #7307): a rename keeps the handle and the history, and old names keep resolving.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .keyset_pagination import cursor_query, limit_query
from .pact_audit import audited_write
from .pact_cleanup_store import (
    LABELS_ORDER,
    PACTICIPANT_LABELS_ORDER,
    add_label,
    delete_pacticipant,
    delete_version,
    get_label,
    list_labels,
    list_pacticipant_labels,
    remove_label,
    restore_pacticipant,
    restore_version,
    tenant_grace_days,
    with_purge_after,
)
from .pacticipant import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_LABEL_NOT_FOUND,
    CODE_NOT_DELETED,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_RESTORE_CONFLICT,
    CODE_SLUG_TAKEN,
    CODE_VERSION_IN_USE,
    CODE_VERSION_NOT_FOUND,
    PacticipantBranchRecord,
    PacticipantInput,
    PacticipantLabelRecord,
    PacticipantPatch,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionInput,
    PacticipantVersionRecord,
    RecordedPacticipantVersion,
)
from .pacticipant_deletion_impact import DeletionImpact, read_deletion_impact
from .pacticipant_store import (
    BRANCHES_ORDER,
    PACTICIPANTS_ORDER,
    VERSIONS_ORDER,
    add_tag,
    create_pacticipant,
    get_pacticipant,
    get_version,
    list_branches,
    list_pacticipants,
    list_versions,
    record_version,
    update_pacticipant,
)
from .permissions import Action, Resource, enforce_permission

__all__ = ["router", "STATUS_BY_CODE"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

#: The HTTP status of each refusal code; anything else is a 400.
STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_CONSUMER_NOT_FOUND: 404,
    CODE_LABEL_NOT_FOUND: 404,
    CODE_SLUG_TAKEN: 409,
    CODE_NOT_DELETED: 409,
    CODE_RESTORE_CONFLICT: 409,
    CODE_VERSION_IN_USE: 409,
}

_STATE_QUERY = Query(
    default="live",
    pattern="^(live|deleted)$",
    description="`live` (the default) or `deleted`: what was deleted and is waiting to be purged.",
)
_REASON_QUERY = Query(default=None, max_length=500, description="Why; stored with the delete and audited.")
_FORCE_QUERY = Query(
    default=False, description="Delete even when a version is currently deployed or released."
)

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


class PacticipantLabelListResponse(BaseModel):
    """One page of a pacticipant's labels."""

    model_config = ConfigDict(extra="forbid")

    labels: List[PacticipantLabelRecord] = Field(default_factory=list, description="By name.")
    count: int = Field(description="How many labels were returned.")
    has_more: bool = Field(default=False, description="Whether another page exists.")
    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` to read the next page; null on the last page."
    )


class LabelName(BaseModel):
    """One distinct label of the workspace."""

    model_config = ConfigDict(extra="forbid")

    name: str


class LabelNameListResponse(BaseModel):
    """One page of the workspace's distinct labels."""

    model_config = ConfigDict(extra="forbid")

    labels: List[LabelName] = Field(default_factory=list, description="By name.")
    count: int = Field(description="How many labels were returned.")
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
        status_code=STATUS_BY_CODE.get(exc.code, 400),
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
        "The applications registered as pacticipants in this workspace, ordered by handle. "
        "`label` keeps the ones carrying that label. `state=deleted` lists the deleted ones instead, "
        "each with `deleted_at` and `purge_after` (when it is removed for good unless restored).\n\n"
        f"{_PAGING_NOTE}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_tenant_pacticipants(
    tenant_slug: str,
    label: Optional[str] = Query(default=None, max_length=255, description="Only pacticipants with this label."),
    state: str = _STATE_QUERY,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantListResponse:
    """List one page of the tenant's pacticipants.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what actually scopes it).
        label: Only pacticipants carrying this label.
        state: ``live`` or ``deleted``.
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
    rows = list_pacticipants(
        db, _tenant_id(auth_data), limit=limit + 1, cursor=after, label=label, deleted=state == "deleted"
    )
    page = PACTICIPANTS_ORDER.page(rows, limit)
    window = tenant_grace_days(db.execute_query, _tenant_id(auth_data)) if state == "deleted" else None
    items = [with_purge_after(row, window) for row in page.items]
    return PacticipantListResponse(
        pacticipants=items, count=len(items), has_more=page.has_more, next_cursor=page.next_cursor
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
@audited_write("pacts.pacticipant.create", "pacticipants")
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
        "Rename it, or change the display name, repository URL, main branch or bindings. A field "
        "that is left out is not changed; `null` clears `display_name`, `repository_url` and "
        "`main_branch` and unbinds `project` and `consumer_id`.\n\n"
        "A new `name` renames the pacticipant: the handle and the whole history stay, and the old "
        "name and the new one both keep resolving to it (as `{pacticipant_ref}` and in a "
        "published pact), listed in `aliases`. `409 pacticipant-slug-taken` when another "
        "pacticipant has, or had, that name. The handle cannot be changed.\n\n"
        "Requires `pacts:edit`."
    ),
    responses={409: {"description": "`pacticipant-slug-taken`: another pacticipant answers to that name."}},
)
@audited_write("pacts.pacticipant.update", "pacticipant/{pacticipant_ref}")
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


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/deletion-impact",
    response_model=DeletionImpact,
    summary="What deleting a pacticipant takes with it",
    description=(
        "Read, before deleting, what `DELETE …/pacticipants/{ref}` would take with it: its live "
        "versions, the pacts that name it as consumer or provider and their verification results, "
        "the providers that lose it as a consumer (their can-i-deploy answers change) and the "
        "consumers that lose it as a provider (at most 20 names each, with totals), and how many "
        "days the delete can be undone. `blocked` is true while a version is deployed or released "
        "(`in_use` names them): the delete is refused until the undeployment is recorded.\n\n"
        "Requires `pacts:view`."
    ),
)
def read_pacticipant_deletion_impact(
    tenant_slug: str,
    pacticipant_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeletionImpact:
    """Read what deleting one pacticipant would take with it.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or name.
        auth_data: The authenticated principal.

    Returns:
        The counts, the partners that lose it, the versions in use, and the grace period.

    Raises:
        HTTPException: 404 for an unknown pacticipant, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return read_deletion_impact(db, pacticipant)


@router.delete(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}",
    status_code=204,
    summary="Delete a pacticipant",
    description=(
        "Delete a pacticipant **with all of its versions** — and with them its pacts, verification "
        "results, deployments, branches and tags. The delete is soft: everything disappears from "
        "every read at once, `POST …/restore` brings it back for `APIOME_PACT_DELETION_GRACE_DAYS` "
        "(default 30) days, and it is then purged for good. The handle is free again at once. The "
        "project and the consumer it was bound to are not touched.\n\n"
        "A pacticipant with a version that is currently deployed or released is refused "
        "(`409 pacticipant-version-in-use`) unless `force=true`. `reason` is stored with the delete "
        "and in the audit trail.\n\n"
        "Requires `pacts:delete` (the built-in Owner and Admin roles)."
    ),
    responses={409: {"description": "`pacticipant-version-in-use`: a version is deployed or released."}},
)
def remove_pacticipant(
    tenant_slug: str,
    pacticipant_ref: str,
    reason: Optional[str] = _REASON_QUERY,
    force: bool = _FORCE_QUERY,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Soft-delete a pacticipant and its history.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        reason: Why.
        force: Delete even when a version is deployed or released.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant, 409 when a version is in use and ``force`` is
            not set, 400 for a bad reason, 403 without ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        delete_pacticipant(
            db, tenant_id, pacticipant, actor=actor_from_auth(auth_data, user_id), reason=reason, force=force
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.post(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/restore",
    response_model=PacticipantRecord,
    summary="Restore a deleted pacticipant",
    description=(
        "Undo a pacticipant's delete before it is purged, with the versions that were deleted along "
        "with it (a version deleted on its own before stays deleted). `{pacticipant_ref}` is the "
        "deleted pacticipant's id, handle or name; with several deleted ones of the same handle the "
        "most recently deleted comes back — pass the id (from `?state=deleted`) to choose.\n\n"
        "`409 pacticipant-restore-conflict` when a live pacticipant has taken the handle since.\n\n"
        "Requires `pacts:delete`."
    ),
)
def restore_deleted_pacticipant(
    tenant_slug: str,
    pacticipant_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantRecord:
    """Restore a deleted pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: The deleted pacticipant's id, handle or name.
        auth_data: The authenticated principal.

    Returns:
        The live pacticipant.

    Raises:
        HTTPException: 404 when no deleted pacticipant matches, 409 when it is not deleted or its
            handle is taken, 403 without ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        return restore_pacticipant(
            db, _tenant_id(auth_data), pacticipant_ref, actor=actor_from_auth(auth_data, user_id)
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


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
        "the latest version tagged `prod`. `state=deleted` lists the deleted versions instead, with "
        "`delete_cause` and `purge_after`.\n\n"
        f"{_PAGING_NOTE}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_pacticipant_versions(
    tenant_slug: str,
    pacticipant_ref: str,
    branch: Optional[str] = Query(default=None, max_length=255, description="Only versions recorded on this branch."),
    tag: Optional[str] = Query(default=None, max_length=255, description="Only versions carrying this tag."),
    state: str = _STATE_QUERY,
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
        state: ``live`` or ``deleted``.
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
    rows = list_versions(
        db, pacticipant, branch=branch, tag=tag, limit=limit + 1, cursor=after, deleted=state == "deleted"
    )
    page = VERSIONS_ORDER.page(rows, limit)
    window = tenant_grace_days(db.execute_query, pacticipant.tenant_id) if state == "deleted" else None
    items = [with_purge_after(row, window) for row in page.items]
    return PacticipantVersionListResponse(
        versions=items, count=len(items), has_more=page.has_more, next_cursor=page.next_cursor
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
@audited_write("pacts.version.record", "pacticipant/{pacticipant_ref}/version/{number}")
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


@router.delete(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}",
    status_code=204,
    summary="Delete a version",
    description=(
        "Delete one version — and with it its pacts, the verification results it published, its "
        "deployments and releases, branch membership and tags. The delete is soft: the version "
        "disappears from every read (the matrix and can-i-deploy included) at once, `POST "
        "…/restore` brings it back for `APIOME_PACT_DELETION_GRACE_DAYS` (default 30) days, and it "
        "is then purged. A branch it headed falls back to its latest remaining version. The number "
        "can be recorded again at once, as a new version.\n\n"
        "A version that is currently deployed or released is refused (`409 "
        "pacticipant-version-in-use`) unless `force=true`. `reason` is stored and audited.\n\n"
        "Requires `pacts:delete`."
    ),
    responses={409: {"description": "`pacticipant-version-in-use`: the version is deployed or released."}},
)
def remove_pacticipant_version(
    tenant_slug: str,
    pacticipant_ref: str,
    number: str,
    reason: Optional[str] = _REASON_QUERY,
    force: bool = _FORCE_QUERY,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Soft-delete one version.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        number: The version number, exactly as recorded.
        reason: Why.
        force: Delete even when the version is deployed or released.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant or version, 409 when it is in use and
            ``force`` is not set, 400 for a bad reason, 403 without ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        delete_version(
            db,
            tenant_id,
            pacticipant,
            number,
            actor=actor_from_auth(auth_data, user_id),
            reason=reason,
            force=force,
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.post(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/versions/{number}/restore",
    response_model=PacticipantVersionRecord,
    summary="Restore a deleted version",
    description=(
        "Undo a version's delete (on its own or by a retention run) before it is purged: its pacts, "
        "results and deployments come back, and a branch whose head it was is headed by it again. "
        "`409 pacticipant-restore-conflict` when a live version has taken the number since.\n\n"
        "Requires `pacts:delete`."
    ),
)
def restore_deleted_version(
    tenant_slug: str,
    pacticipant_ref: str,
    number: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantVersionRecord:
    """Restore a deleted version.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name of the (live) pacticipant.
        number: The version number.
        auth_data: The authenticated principal.

    Returns:
        The live version.

    Raises:
        HTTPException: 404 when no deleted version has that number, 409 when it is not deleted or
            the number is taken, 403 without ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant_ref)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        return restore_version(db, tenant_id, pacticipant, number, actor=actor_from_auth(auth_data, user_id))
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
@audited_write("pacts.tag.add", "pacticipant/{pacticipant_ref}/version/{number}/tag/{tag}")
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


# ---------------------------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/pacticipant-labels",
    response_model=LabelNameListResponse,
    summary="List the workspace's labels",
    description=(
        "Every distinct label on the workspace's pacticipants, by name. "
        "`GET …/pacticipants?label=…` lists the pacticipants carrying one.\n\n"
        f"{_PAGING_NOTE}\n\n"
        "Requires `pacts:view`."
    ),
)
def list_workspace_labels(
    tenant_slug: str,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> LabelNameListResponse:
    """List one page of the workspace's distinct labels.

    Args:
        tenant_slug: The tenant in the URL.
        limit: Page size.
        cursor: Where the page starts.
        auth_data: The authenticated principal.

    Returns:
        The label names of the page.

    Raises:
        HTTPException: 400 for a malformed cursor, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    after = LABELS_ORDER.parse(cursor)
    _ = tenant_slug
    rows = list_labels(db, _tenant_id(auth_data), limit=limit + 1, cursor=after)
    page = LABELS_ORDER.page(rows, limit)
    labels = [LabelName(name=row["name"]) for row in page.items]
    return LabelNameListResponse(
        labels=labels, count=len(labels), has_more=page.has_more, next_cursor=page.next_cursor
    )


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/labels",
    response_model=PacticipantLabelListResponse,
    summary="List a pacticipant's labels",
    description=f"The labels on this pacticipant, by name.\n\n{_PAGING_NOTE}\n\nRequires `pacts:view`.",
)
def list_labels_of_pacticipant(
    tenant_slug: str,
    pacticipant_ref: str,
    limit: int = limit_query(),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantLabelListResponse:
    """List one page of a pacticipant's labels.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        limit: Page size.
        cursor: Where the page starts (the previous page's ``next_cursor``).
        auth_data: The authenticated principal.

    Returns:
        The labels of the page and whether another follows.

    Raises:
        HTTPException: 400 for a malformed cursor, 404 for an unknown pacticipant, 403 without
            ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    after = PACTICIPANT_LABELS_ORDER.parse(cursor)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    page = PACTICIPANT_LABELS_ORDER.page(
        list_pacticipant_labels(db, pacticipant, limit=limit + 1, cursor=after), limit
    )
    labels = list(page.items)
    return PacticipantLabelListResponse(
        labels=labels, count=len(labels), has_more=page.has_more, next_cursor=page.next_cursor
    )


@router.get(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/labels/{label:path}",
    response_model=PacticipantLabelRecord,
    summary="Read a label",
    description="One label of a pacticipant; 404 when it does not carry it.\n\nRequires `pacts:view`.",
)
def read_pacticipant_label(
    tenant_slug: str,
    pacticipant_ref: str,
    label: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantLabelRecord:
    """Read one label of a pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        label: The label.
        auth_data: The authenticated principal.

    Returns:
        The label.

    Raises:
        HTTPException: 404 for an unknown pacticipant or label, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        pacticipant = get_pacticipant(db, _tenant_id(auth_data), pacticipant_ref)
        return get_label(db, pacticipant, label)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/labels/{label:path}",
    response_model=PacticipantLabelRecord,
    summary="Label a pacticipant",
    description=(
        "Put a label on a pacticipant (`team-billing`, `tier-1`). Answers `201` when the label is "
        "new and `200` when the pacticipant already had it. A label may contain `/`.\n\n"
        "Requires `pacts:edit`."
    ),
    responses={201: {"description": "The label was added by this request.", "model": PacticipantLabelRecord}},
)
def put_pacticipant_label(
    tenant_slug: str,
    pacticipant_ref: str,
    label: str,
    response: Response,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PacticipantLabelRecord:
    """Label a pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        label: The label.
        response: The response, whose status becomes 201 when the label is new.
        auth_data: The authenticated principal.

    Returns:
        The label.

    Raises:
        HTTPException: 400 for a malformed label, 404 for an unknown pacticipant, 403 without
            ``pacts:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=pacticipant_ref)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        record, created = add_label(db, tenant_id, pacticipant, label, actor=actor_from_auth(auth_data, user_id))
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    response.status_code = 201 if created else 200
    return record


@router.delete(
    "/{tenant_slug}/pacticipants/{pacticipant_ref}/labels/{label:path}",
    status_code=204,
    summary="Remove a label",
    description="Take a label off a pacticipant; 404 when it does not carry it.\n\nRequires `pacts:edit`.",
)
def delete_pacticipant_label(
    tenant_slug: str,
    pacticipant_ref: str,
    label: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Remove a label from a pacticipant.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        label: The label.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant or label, 403 without ``pacts:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=pacticipant_ref)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        remove_label(db, tenant_id, pacticipant, label, actor=actor_from_auth(auth_data, user_id))
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)
