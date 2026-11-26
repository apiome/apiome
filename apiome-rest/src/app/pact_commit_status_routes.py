"""``/v1/tenants/{tenant_slug}/pact-commit-statuses`` — pact verdicts on commits, PFX-4.4 (#6941).

Apiome posts the verdict of every consumer ↔ provider pair back to GitHub (commit status) and
GitLab (commit status) when a pact is published or verified (:mod:`app.pact_commit_status`
explains when and where). These two endpoints show what was posted, and send again what was not:

* ``GET …/pact-commit-statuses`` — the recorded statuses, newest first, each with its outcome and,
  when it was not sent, the reason (``pacts:view``);
* ``POST …/pact-commit-statuses/{status_id}/retry`` — send a ``suppressed`` or ``failed`` status
  again, deciding afresh where it can go (``pacts:edit``).

The tenant is the caller's; a status of another tenant reads as not found.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .auth import validate_authentication
from .database import db
from .keyset_pagination import cursor_query, limit_query, parse_time_id_cursor
from .pact_audit import audited_write
from .pact_commit_status import (
    CODE_STATUS_NOT_FOUND,
    CODE_STATUS_NOT_RETRYABLE,
    OUTCOMES,
    CommitStatusList,
    CommitStatusRecord,
    PactCommitStatusError,
)
from .pact_commit_status_store import list_commit_statuses, retry_commit_status
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

_STATUS_BY_CODE = {CODE_STATUS_NOT_FOUND: 404, CODE_STATUS_NOT_RETRYABLE: 409}

#: Most statuses one page returns.
MAX_PAGE = 200


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse with 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/pact-commit-statuses",
    response_model=CommitStatusList,
    summary="List pact commit statuses",
    description=(
        "The pact verdicts Apiome posted (or could not post) to GitHub and GitLab commits, most "
        "recently updated first. One status per pacticipant version and context "
        "(`apiome-pact/<consumer>/<provider>`): `pending` while a published pact awaits the "
        "provider's verification, then `pass` or `fail` on both the consumer's and the provider's "
        "commit.\n\n"
        "`outcome` says what happened to the send: `dispatched` (the provider accepted it), "
        "`suppressed` (not attempted — `reason_code` says why: no repository URL, version not a "
        "commit SHA, repository not registered, unsupported provider, no stored credential, "
        "publishing switched off), `failed` (the provider refused or could not be reached) or "
        "`queued`.\n\n"
        "Requires `pacts:view`."
    ),
)
def get_pact_commit_statuses(
    tenant_slug: str,
    response: Response,
    pacticipant: Optional[str] = Query(
        default=None, max_length=255, description="Only this pacticipant's commits (handle)."
    ),
    version: Optional[str] = Query(default=None, max_length=255, description="Only this version number."),
    outcome: Optional[str] = Query(default=None, description="Only this outcome: " + ", ".join(OUTCOMES) + "."),
    limit: int = limit_query(50, maximum=MAX_PAGE),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommitStatusList:
    """List the tenant's commit statuses.

    Args:
        tenant_slug: The tenant in the URL (the caller's tenant is used).
        response: Carries ``X-Next-Cursor`` when a further page exists.
        pacticipant: Narrow to one pacticipant's commits.
        version: Narrow to one version number.
        outcome: Narrow to one outcome.
        limit: Page size.
        cursor: The previous page's ``next_cursor``.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 400 for an unknown outcome or a bad cursor; 403 without ``pacts:view``.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    if outcome is not None and outcome not in OUTCOMES:
        raise HTTPException(
            status_code=400,
            detail={"code": "pact-status-invalid-outcome", "message": f"outcome must be one of {', '.join(OUTCOMES)}."},
        )
    items, next_cursor = list_commit_statuses(
        db,
        _tenant_id(auth_data),
        pacticipant=pacticipant,
        version=version,
        outcome=outcome,
        limit=limit,
        after=parse_time_id_cursor(cursor),
    )
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return CommitStatusList(items=items, next_cursor=next_cursor)


@router.post(
    "/{tenant_slug}/pact-commit-statuses/{status_id}/retry",
    response_model=CommitStatusRecord,
    summary="Send a pact commit status again",
    description=(
        "Send a `suppressed` or `failed` commit status again. Where it can go is decided afresh, so "
        "a retry after registering the repository, linking the account or fixing the pacticipant's "
        "repository URL sends it; one whose cause remains comes back with the same `reason_code`.\n\n"
        "Requires `pacts:edit`."
    ),
    responses={
        404: {"description": "`pact-status-not-found`: no such status in this workspace."},
        409: {"description": "`pact-status-not-retryable`: the status was accepted or is being sent."},
    },
)
@audited_write("pacts.commit_status.retry", "pact-commit-status/{status_id}")
def retry_pact_commit_status(
    tenant_slug: str,
    status_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommitStatusRecord:
    """Retry one status.

    Args:
        tenant_slug: The tenant in the URL (the caller's tenant is used).
        status_id: The status.
        auth_data: The authenticated principal.

    Returns:
        The status after the retry.

    Raises:
        HTTPException: 404 for an unknown status; 409 for one that cannot be retried; 403 without
            ``pacts:edit``.
    """
    _ = tenant_slug
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=status_id)
    try:
        return retry_commit_status(db, _tenant_id(auth_data), status_id, actor_id=user_id)
    except PactCommitStatusError as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CODE.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)}
        ) from exc
