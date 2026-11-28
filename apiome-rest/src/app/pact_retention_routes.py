"""``POST /v1/tenants/{tenant_slug}/pact-retention`` — selector-based version cleanup, PFX-1.11 (#6924).

One endpoint, dry-run first (:mod:`app.pact_retention` explains the selectors and the rules):

1. send the keep selectors (``dry_run`` defaults to ``true``) — the answer is the plan: per
   pacticipant, how many versions are kept and why, and which would be deleted — plus its
   ``plan_digest``;
2. send the same request with ``"dry_run": false`` and that ``plan_digest`` — the deletions are made
   (soft: restorable until the purge), or the run is refused with ``409
   pact-retention-plan-changed`` and the fresh plan when something moved in between.

A dry run needs ``pacts:view``; applying needs ``pacts:delete`` (Owner and Admin). A CI or cron job
runs the two calls in sequence.

**Stored rules (PFX-8.14, #7311).** The Contracts *Settings → Clean-up* tab and
``apiome pact retention show|set|preview`` use four more routes (:mod:`app.pact_retention_policy`):

* ``GET …/pact-retention/policy`` — the rules, the nightly switch, the restore window, the last and
  next nightly run, and whether the caller may change them (``pacts:view``);
* ``PUT …/pact-retention/policy`` — replace them (``pacts:delete``); a rule set that would remove a
  deployed or released version is refused;
* ``POST …/pact-retention/policy/preview`` — what the saved rules, or a draft, would remove if the
  clean-up ran now: the same plan the nightly run applies (``pacts:view``, changes nothing);
* ``GET …/pact-retention/deleted`` — Recently deleted, newest first, each with when it is purged
  (``pacts:view``); restoring uses the pacticipant and version ``…/restore`` routes.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_cleanup_store import tenant_grace_days
from .pact_retention import (
    CODE_NO_SELECTOR,
    CODE_PLAN_CHANGED,
    CODE_PLAN_DIGEST_REQUIRED,
    CODE_TOO_MANY_PACTICIPANTS,
    CODE_TOO_MANY_VERSIONS,
    RetentionError,
    RetentionPlan,
    RetentionRequest,
)
from .pact_retention_policy import (
    CODE_KEEPS_IN_USE,
    DeletedPage,
    RetentionPolicy,
    RetentionPreview,
    RetentionPreviewRequest,
    RetentionRules,
)
from .pact_retention_policy_store import (
    CODE_BAD_CURSOR,
    get_policy,
    list_recently_deleted,
    preview_policy,
    save_policy,
)
from .pact_retention_store import RetentionPlanChangedError, run_retention
from .pacticipant import PacticipantValidationError
from .pacticipant_routes import STATUS_BY_CODE
from .permissions import Action, Resource, enforce_permission, has_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

_STATUS_BY_CODE = {
    CODE_NO_SELECTOR: 422,
    CODE_PLAN_DIGEST_REQUIRED: 422,
    CODE_TOO_MANY_PACTICIPANTS: 422,
    CODE_TOO_MANY_VERSIONS: 422,
    CODE_PLAN_CHANGED: 409,
    CODE_KEEPS_IN_USE: 422,
    CODE_BAD_CURSOR: 422,
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse with 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.post(
    "/{tenant_slug}/pact-retention",
    response_model=RetentionPlan,
    summary="Clean up pacticipant versions (dry run first)",
    description=(
        "Delete the versions no keep selector needs. A version is **kept** when any of these holds:\n\n"
        "- it is its pacticipant's latest version (always);\n"
        "- `keep.latest_per_branch`: it is one of the newest N versions of a branch;\n"
        "- `keep.deployed_or_released` (default `true`): it is currently deployed or released;\n"
        "- `keep.created_within_days`: it was recorded in the last D days.\n\n"
        "Every other live version of the pacticipants named in `pacticipants` (all of them when "
        "omitted) is deleted — softly, with its pacts, results and deployments, restorable until "
        "it is purged (`grace_days`).\n\n"
        "**Dry run first.** `dry_run` defaults to `true`: the answer is the plan and its "
        "`plan_digest`, and nothing changes. To apply, send the same request with `dry_run: false` "
        "and that `plan_digest`. If the plan changed in between, the answer is `409 "
        "pact-retention-plan-changed` with the fresh plan under `detail.plan`.\n\n"
        "A run deletes at most `max_deletions` versions, oldest first; `remaining` counts the rest "
        "for the next run.\n\n"
        "A dry run requires `pacts:view`; applying requires `pacts:delete`."
    ),
    responses={
        409: {"description": "`pact-retention-plan-changed`: review `detail.plan` and apply its digest."},
        422: {"description": "No keep selector, no `plan_digest` when applying, or a run too large."},
    },
)
def run_pact_retention(
    tenant_slug: str,
    body: RetentionRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RetentionPlan:
    """Plan, or apply, a retention run.

    Args:
        tenant_slug: The tenant in the URL.
        body: The run.
        auth_data: The authenticated principal.

    Returns:
        The plan; ``applied`` true when the deletions were made.

    Raises:
        HTTPException: 422 for a run with no selector, no digest when applying, or too large;
            404 for an unknown pacticipant; 409 when the plan changed; 403 without ``pacts:view``
            (dry run) or ``pacts:delete`` (apply).
    """
    action = Action.VIEW if body.dry_run else Action.DELETE
    user_id = enforce_permission(db, auth_data, Resource.PACTS, action, target="pact-retention")
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        return run_retention(
            db,
            tenant_id,
            body,
            actor=actor_from_auth(auth_data, user_id),
            grace=tenant_grace_days(db.execute_query, tenant_id),
        )
    except RetentionPlanChangedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc), "plan": exc.plan.model_dump(mode="json")},
        ) from exc
    except RetentionError as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CODE.get(exc.code, 422), detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except PacticipantValidationError as exc:
        raise HTTPException(
            status_code=STATUS_BY_CODE.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)}
        ) from exc


def _refusal(exc: RetentionError) -> HTTPException:
    """The HTTP answer for a retention refusal: its status, code and message."""
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 422), detail={"code": exc.code, "message": str(exc)})


def _may_change(auth_data: Dict[str, Any]) -> bool:
    """Whether the caller may save the rules and restore (``pacts:delete``: Owner and Admin)."""
    return bool(has_permission(db, auth_data, Resource.PACTS, Action.DELETE))


@router.get(
    "/{tenant_slug}/pact-retention/policy",
    response_model=RetentionPolicy,
    summary="Read the workspace's clean-up rules",
    description=(
        "The Contracts clean-up rules: what is kept (every deployed or released version, always; the "
        "latest N of each main branch; the latest N of every other branch, optionally for D days; "
        "versions with a listed tag), whether the clean-up runs nightly (after 02:00 UTC), and how "
        "many days a deleted item stays restorable. `configured: false` shows the defaults (clean-up "
        "off). `last_run` / `next_run_at` say what the nightly run did and when it runs next; "
        "`can_edit` whether the caller may change the rules.\n\nRequires `pacts:view`."
    ),
)
def read_pact_retention_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RetentionPolicy:
    """Read the clean-up rules.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        The rules, the last and next nightly run, and ``can_edit``.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    return get_policy(db, _tenant_id(auth_data), can_edit=_may_change(auth_data))


@router.put(
    "/{tenant_slug}/pact-retention/policy",
    response_model=RetentionPolicy,
    summary="Save the workspace's clean-up rules",
    description=(
        "Replace the clean-up rules; a field left out takes its default. Every version deployed or "
        "released anywhere is always kept: `keep_deployed_or_released: false` is refused with "
        "`422 pact-retention-keeps-in-use` (*Deployed and released versions are always kept.*). "
        "An unknown field, a repeated tag or `keep_other_branch_days` without "
        "`keep_other_branch_latest` is refused with the reason — nothing is dropped silently.\n\n"
        "Run `POST …/pact-retention/policy/preview` first to see what the rules remove. "
        "Requires `pacts:delete` (Owner and Admin)."
    ),
    responses={422: {"description": "`pact-retention-keeps-in-use`, or an invalid rule."}},
)
def save_pact_retention_policy(
    tenant_slug: str,
    body: RetentionRules,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RetentionPolicy:
    """Save the clean-up rules.

    Args:
        tenant_slug: The tenant in the URL.
        body: The rules.
        auth_data: The authenticated principal.

    Returns:
        The saved policy.

    Raises:
        HTTPException: 422 for a rule set that would remove a deployed or released version; 403
            without ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-retention/policy")
    _ = tenant_slug
    try:
        return save_policy(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
    except RetentionError as exc:
        raise _refusal(exc) from exc


@router.post(
    "/{tenant_slug}/pact-retention/policy/preview",
    response_model=RetentionPreview,
    summary="Preview what the clean-up rules remove",
    description=(
        "What the saved rules — or the draft in `rules` — would remove if the clean-up ran now: the "
        "versions, with the pacts and verification results that go with them, listed per "
        "pacticipant. It is planned exactly as the nightly run plans, so it is what the next run "
        "removes unless something is published, deployed or deleted in between. Nothing changes.\n\n"
        "`nightly_enabled: false` means nothing is removed while clean-up is off.\n\nRequires `pacts:view`."
    ),
    responses={
        422: {"description": "`pact-retention-keeps-in-use`, `pact-retention-too-many-versions`, or an invalid rule."}
    },
)
def preview_pact_retention_policy(
    tenant_slug: str,
    body: RetentionPreviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RetentionPreview:
    """Preview the clean-up rules.

    Args:
        tenant_slug: The tenant in the URL.
        body: Optional draft rules.
        auth_data: The authenticated principal.

    Returns:
        The preview.

    Raises:
        HTTPException: 422 for refused rules or a registry too large to plan; 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        return preview_policy(db, _tenant_id(auth_data), body.rules)
    except RetentionError as exc:
        raise _refusal(exc) from exc


@router.get(
    "/{tenant_slug}/pact-retention/deleted",
    response_model=DeletedPage,
    summary="List recently deleted pacticipants and versions",
    description=(
        "Deleted pacticipants, and versions deleted on their own (by hand or by the clean-up), newest "
        "first, each with who deleted it, what comes back with a restore and `purge_after` — when it "
        "is removed for good under the workspace's restore window. Restore one with "
        "`POST …/pacticipants/{pacticipant}/restore` or `POST …/pacticipants/{pacticipant}/versions/{number}/restore`."
        "\n\nRequires `pacts:view`; `can_restore` says whether the caller may restore (`pacts:delete`)."
    ),
    responses={422: {"description": "`pact-retention-bad-cursor`."}},
)
def list_pact_retention_deleted(
    tenant_slug: str,
    limit: int = Query(default=25, ge=1, le=100, description="Rows per page."),
    cursor: str = Query(default="", max_length=512, description="`next_cursor` of the previous page."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeletedPage:
    """List Recently deleted.

    Args:
        tenant_slug: The tenant in the URL.
        limit: Rows per page.
        cursor: The previous page's ``next_cursor``.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 422 for a cursor this list did not return; 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        return list_recently_deleted(
            db, _tenant_id(auth_data), limit=limit, after=cursor or None, can_restore=_may_change(auth_data)
        )
    except RetentionError as exc:
        raise _refusal(exc) from exc
