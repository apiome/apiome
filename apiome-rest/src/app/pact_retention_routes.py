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
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
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
from .pact_retention_store import RetentionPlanChangedError, run_retention
from .pacticipant import PacticipantValidationError
from .pacticipant_routes import STATUS_BY_CODE
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

_STATUS_BY_CODE = {
    CODE_NO_SELECTOR: 422,
    CODE_PLAN_DIGEST_REQUIRED: 422,
    CODE_TOO_MANY_PACTICIPANTS: 422,
    CODE_TOO_MANY_VERSIONS: 422,
    CODE_PLAN_CHANGED: 409,
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
        return run_retention(db, _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
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
