"""``…/versions/{version_ref}/binding/sync`` and ``…/sync-plans/{plan_id}`` — GNC-2.3 (#4739).

The HTTP surface of three-way spec synchronization: compute the merge of a bound draft against the
commit its branch moved to, read what the last merge found, and settle the conflicts it could not
decide. The rules are :mod:`app.spec_sync_store`; the vocabulary and the merge itself are
:mod:`app.spec_sync`.

**Nothing here changes a draft.** Computing a merge reads three documents and writes one row;
settling a conflict records which side a person chose. Neither touches the canonical model, the
version, or any review — which is why a merge is safe to compute for a commit a webhook reported,
and why a reviewer's decision can never be invalidated by something a provider did.

**Authorization.** There is no synchronization RBAC resource, and the same two checks the binding
surface applies apply here:

* Reading a merge result requires ``projects:view``.
* Computing a merge and settling a conflict change a version's workflow, so both require
  ``versions:edit``. Computing additionally **proves repository access**: it resolves a stored
  credential and reads both commits through the provider, exactly as binding does, so a repository
  the tenant cannot reach is answered ``403 binding-repository-forbidden`` rather than merged from
  a guess. A credential is never accepted in a request body.

**Audit.** Every merge and every settlement is written to ``workflow_audit`` as a ``sync.*`` action
in the same transaction as the change, and is readable through
``GET /v1/tenants/{tenant_slug}/workflow-audit?version_id=…``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import spec_sync_store
from .auth import validate_authentication
from .database import db
from .draft_binding_routes import STATUS_BY_CODE as BINDING_STATUS_BY_CODE
from .draft_bindings import DraftBindingValidationError
from .permissions import Action, Resource, enforce_permission
from .spec_sync import (
    CODE_BASE_DRIFTED,
    CODE_CONFLICT,
    CODE_CONFLICT_NOT_FOUND,
    CODE_CONFLICT_RESOLVED,
    CODE_INVALID_DOCUMENT,
    CODE_NOT_BOUND,
    CODE_NOTHING_TO_MERGE,
    CODE_PLAN_NOT_FOUND,
    SpecSyncValidationError,
    SyncConflictResolve,
    SyncPlanCompute,
    SyncPlanDetail,
    VersionSyncStatus,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["spec-sync"])

#: A synchronization refusal maps onto the HTTP status of its kind; anything else is a 400. The
#: repository refusals keep the statuses the binding surface already gives them.
_STATUS_BY_CODE: Dict[str, int] = {
    **BINDING_STATUS_BY_CODE,
    CODE_NOT_BOUND: 404,
    CODE_PLAN_NOT_FOUND: 404,
    CODE_CONFLICT_NOT_FOUND: 404,
    CODE_BASE_DRIFTED: 409,
    CODE_NOTHING_TO_MERGE: 409,
    CODE_CONFLICT_RESOLVED: 409,
    CODE_CONFLICT: 409,
    CODE_INVALID_DOCUMENT: 422,
}

_PROJECT_BASE = "/{tenant_slug}/projects/{project_ref}"
_VERSION_BASE = f"{_PROJECT_BASE}/versions/{{version_ref}}/binding/sync"
_PLAN_BASE = f"{_PROJECT_BASE}/sync-plans/{{plan_id}}"


class SyncErrorDetail(BaseModel):
    """The body of every refusal from this surface."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="The stable refusal code a client branches on.")
    message: str = Field(description="A human-readable explanation.")


def _caller(auth_data: Dict[str, Any], resource: str, action: str) -> Tuple[str, str]:
    """Require a permission and return ``(tenant_id, user_id)``.

    Args:
        auth_data: The authenticated principal.
        resource: The RBAC resource.
        action: The RBAC action.

    Returns:
        The tenant and the acting user.

    Raises:
        HTTPException: 403 without the permission, without an attributable user, or without a
            tenant.
    """
    user_id = enforce_permission(db, auth_data, resource, action)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="An authenticated user id is required to synchronize a draft.",
        )
    return str(tenant_id), str(user_id)


def _http_error(exc: Exception) -> HTTPException:
    """Translate a store refusal into the HTTP error a client sees.

    Both refusal vocabularies reach this surface: this module's ``sync-*`` codes and the binding
    module's ``binding-*`` codes, which a repository read still raises. Neither is re-coded, so a
    client that already understands one understands it here too.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` to raise, always carrying ``{"code", "message"}``.
    """
    code = str(getattr(exc, "code", "")) or "sync-failed"
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(code, 400),
        detail={"code": code, "message": str(exc)},
    )


async def _off_loop(work: Any, *args: Any) -> Any:
    """Run a store call that may reach a provider on a worker thread.

    Computing a merge issues two blocking reads to the provider and rebuilds a document out of the
    database; keeping it off the event loop is what stops one slow repository from stalling every
    other request.

    Args:
        work: The store function.
        *args: Its positional arguments.

    Returns:
        Whatever the store returned.

    Raises:
        HTTPException: The translation of any store refusal.
    """
    try:
        return await asyncio.to_thread(work, *args)
    except (SpecSyncValidationError, DraftBindingValidationError) as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


@router.get(
    _VERSION_BASE,
    response_model=VersionSyncStatus,
    responses={404: {"model": SyncErrorDetail}},
    summary="Read a version's synchronization state",
    description=(
        "The most recent three-way merge of this draft against its repository ref, with its "
        "conflicts, plus the merges before it.\n\n"
        "No provider is contacted: this is what is already known. A result whose `stale` flag is "
        "set was computed against a draft that has since been edited.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_version_sync(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionSyncStatus:
    """Read a version's synchronization state.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        auth_data: The authenticated principal.

    Returns:
        The status.

    Raises:
        HTTPException: 404 for an unknown project or version, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return spec_sync_store.version_sync_status(tenant_id, project_ref, version_ref)
    except (SpecSyncValidationError, DraftBindingValidationError) as exc:
        raise _http_error(exc) from exc


@router.get(
    _PLAN_BASE,
    response_model=SyncPlanDetail,
    responses={404: {"model": SyncErrorDetail}},
    summary="Read one merge result",
    description=(
        "One three-way merge with every conflict it found — outstanding ones first — each "
        "carrying the base, incoming and current values and the repository file and line it "
        "lives at.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_plan(
    tenant_slug: str,
    project_ref: str,
    plan_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SyncPlanDetail:
    """Read one merge result.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        plan_id: The merge result.
        auth_data: The authenticated principal.

    Returns:
        The detail.

    Raises:
        HTTPException: 404 for an unknown project or plan, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return spec_sync_store.get_plan(tenant_id, project_ref, plan_id)
    except (SpecSyncValidationError, DraftBindingValidationError) as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


@router.post(
    _VERSION_BASE,
    response_model=SyncPlanDetail,
    status_code=200,
    responses={
        403: {"model": SyncErrorDetail},
        404: {"model": SyncErrorDetail},
        409: {"model": SyncErrorDetail},
        422: {"model": SyncErrorDetail},
        502: {"model": SyncErrorDetail},
    },
    summary="Merge a bound draft against its repository ref",
    description=(
        "Reads the bound selection at the commit this draft is synchronized with (the base) and "
        "at the commit its branch moved to, rebuilds the draft's own document, and merges the "
        "three.\n\n"
        "Incoming changes that touch nothing the draft touched are recorded as applied; every "
        "overlap becomes a conflict naming its JSON Pointer, its repository file and line, and "
        "the base, incoming and current values side by side.\n\n"
        "**The draft is never modified.** A merge result is a reading of three documents; what to "
        "do about it is a separate decision.\n\n"
        "Re-running a merge of the same three documents returns the result already stored rather "
        "than computing a second answer to the same question, so a redelivered webhook or a "
        "double-click costs nothing.\n\n"
        "Requires `versions:edit`, and proves the tenant's stored credential can read the "
        "repository."
    ),
)
async def compute_plan(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    body: SyncPlanCompute = SyncPlanCompute(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SyncPlanDetail:
    """Compute a three-way merge for a bound draft.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        body: Which candidate to merge, and whether to re-read.
        auth_data: The authenticated principal.

    Returns:
        The merge result with its conflicts.

    Raises:
        HTTPException: 404 when the version is not bound, 409 when there is nothing to merge or
            the merge base has been rewritten, 422 when a side is not a readable spec document,
            403/502 when the repository cannot be read, 403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    return await _off_loop(
        spec_sync_store.compute_plan, tenant_id, project_ref, version_ref, user_id, body
    )


@router.post(
    f"{_PLAN_BASE}/conflicts/{{conflict_id}}",
    response_model=SyncPlanDetail,
    status_code=200,
    responses={
        404: {"model": SyncErrorDetail},
        409: {"model": SyncErrorDetail},
    },
    summary="Settle one conflict of a merge result",
    description=(
        "Records which side wins at one pointer: `git` takes the repository's value, `draft` "
        "keeps the version's.\n\n"
        "Settling **records a decision and nothing else** — it does not edit the draft, take "
        "anything from the repository, or move the binding. A settlement is final; the merge "
        "moves to `resolved` once none are outstanding.\n\n"
        "Requires `versions:edit`."
    ),
)
async def resolve_conflict(
    tenant_slug: str,
    project_ref: str,
    plan_id: str,
    conflict_id: str,
    body: SyncConflictResolve,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SyncPlanDetail:
    """Settle one conflict.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        plan_id: The merge result.
        conflict_id: The conflict.
        body: ``git`` or ``draft``, with an optional note.
        auth_data: The authenticated principal.

    Returns:
        The plan, with the conflict now settled.

    Raises:
        HTTPException: 404 for an unknown project, plan or conflict, 409 when it already settled,
            403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    try:
        return spec_sync_store.resolve_conflict(
            tenant_id, project_ref, plan_id, conflict_id, user_id, body
        )
    except (SpecSyncValidationError, DraftBindingValidationError) as exc:
        raise _http_error(exc) from exc
