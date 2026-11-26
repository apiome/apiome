"""Verification results and operations — PFX-5.5 (#6949): the HTTP face of :mod:`app.pact_verification_ops`.

Five routes under ``/v1/tenants/{tenant}/pact-verifier/pacts/provider/{provider}``, beside the hosted
verifier (PFX-3.2) and outside ``…/pact-broker``, because no Pact Broker or PactFlow client knows
them (the broker surface stays the catalogued, compatible one, :mod:`app.pact_broker_compat`):

* ``GET …/verification-status`` — each consumer's newest pact, its newest result, stale or not.
* ``GET …/results`` — the provider's verification history, newest first (``consumer``, ``cursor``).
* ``GET …/results/{result_id}`` — one result with its test results and evidence run (its log).
* ``POST …/consumer/{consumer}/pact-version/{sha}/reverify`` — run one pact again.
* ``POST …/verify-stale`` — verify every stale pact.

**Permissions.** The reads need ``pacts:view``; the evidence run of a result is included only for a
caller who also holds ``verification_evidence:view`` (otherwise ``evidence_status: forbidden``).
The runs publish results and write evidence, so they need ``pacts:create`` on the provider and
``verification_evidence:create``, as the hosted verifier does. Every lookup is scoped to the
authenticated tenant: another workspace's provider or result is a ``404``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import _base_url, _http_error
from .pact_publication import PactPublicationError
from .pact_verification_ops import (
    CODE_IN_PROGRESS,
    CODE_NO_PROVIDER_VERSION,
    ConsoleRunRequest,
    ConsoleRunResponse,
    ResultDetail,
    ResultHistoryPage,
    VerificationStatus,
    list_results,
    read_result,
    reverify_pact,
    verification_status,
    verify_stale_pacts,
)
from .pact_verifier_service import CODE_TARGET_AUTH_UNAVAILABLE, CODE_TOO_MANY_PACTS, PactVerifierError
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission, has_permission
from .verification_result_store import MAX_HISTORY_PAGE
from .verification_target import CODE_NOT_FOUND as CODE_TARGET_NOT_FOUND
from .verification_target import TargetValidationError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-verifier/pacts/provider/{provider}"

_RUN_STATUS = {
    CODE_IN_PROGRESS: 409,
    CODE_NO_PROVIDER_VERSION: 422,
    CODE_TOO_MANY_PACTS: 422,
    CODE_TARGET_AUTH_UNAVAILABLE: 422,
}

_READ_ERRORS: Dict[int | str, Dict[str, Any]] = {
    404: {"description": "`pacticipant-not-found` or `pact-verification-not-found` in this workspace."},
}

_RUN_ERRORS: Dict[int | str, Dict[str, Any]] = {
    400: {"description": "A malformed provider version, branch or build URL."},
    404: {"description": "`pacticipant-not-found`, `pact-not-found` or `target-not-found` in this workspace."},
    409: {"description": "`pact-verify-in-progress`: a console run of this pair is already running."},
    422: {
        "description": (
            "`pact-verify-provider-version-required`, `pact-verify-target-auth-unavailable`, or a target "
            "that cannot be used (`target-disabled`, `target-protocol-mismatch`, a URL refusal)."
        )
    },
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _run_error(exc: Exception) -> HTTPException:
    """The HTTP error for a run that could not start (or a pair already running).

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` carrying ``{"code", "message"}``.
    """
    if isinstance(exc, (PactPublicationError, PacticipantValidationError)):
        return _http_error(exc)
    if isinstance(exc, TargetValidationError):
        status = 404 if exc.code == CODE_TARGET_NOT_FOUND else 422
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    code = getattr(exc, "code", "")
    return HTTPException(status_code=_RUN_STATUS.get(code, 422), detail={"code": code, "message": str(exc)})


@router.get(
    _PREFIX + "/verification-status",
    response_model=VerificationStatus,
    summary="Where a provider's verification stands",
    description=(
        "Each consumer's newest pact for the provider (PFX-5.5), with the newest verification result "
        "of that pact version and whether it is **stale**: a pact version with no result at all — it "
        "changed since the provider last verified, or was never verified. `counts` is the KPI strip "
        "(pacts, verified, failing, stale, interactions, passing interactions, last verified). At most "
        "500 consumers (`truncated`). Requires `pacts:view`."
    ),
    responses=_READ_ERRORS,
)
def read_verification_status(
    tenant_slug: str,
    provider: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> VerificationStatus:
    """Read where the provider's verification stands.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        provider: The provider's handle, id or name.
        auth_data: The authenticated principal.

    Returns:
        The status.

    Raises:
        HTTPException: 403 without ``pacts:view``; 404 for an unknown provider.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target=provider)
    try:
        return verification_status(db, _tenant_id(auth_data), provider)
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc


@router.get(
    _PREFIX + "/results",
    response_model=ResultHistoryPage,
    summary="List a provider's verification results",
    description=(
        "Every verification result of the provider, newest first (PFX-5.5): native results a Pact "
        "verifier published, the hosted verifier's, console re-runs and bi-directional comparisons. "
        "Each has its provider version and branch, build URL, verifier, trigger (`published`, "
        "`hosted`, `manual`, `stale-recheck`, `bidirectional`, or null before triggers were recorded), "
        "run duration and interaction counts. `consumer` narrows to one consumer; pass `next_cursor` "
        "as `cursor` for the next page. Requires `pacts:view`."
    ),
    responses={**_READ_ERRORS, 400: {"description": "`pact-history-cursor-invalid`."}},
)
def read_results(
    tenant_slug: str,
    provider: str,
    consumer: Optional[str] = Query(None, min_length=1, max_length=255, description="Only this consumer's results."),
    cursor: Optional[str] = Query(None, max_length=32, description="The `next_cursor` of the previous page."),
    limit: int = Query(MAX_HISTORY_PAGE, ge=1, le=MAX_HISTORY_PAGE, description="Page size."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ResultHistoryPage:
    """Read one page of the provider's verification history.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: Only this consumer's results.
        cursor: The previous page's ``next_cursor``.
        limit: Page size.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 for a bad cursor; 404 for an unknown pacticipant.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target=provider)
    try:
        return list_results(db, _tenant_id(auth_data), provider, consumer_ref=consumer, cursor=cursor, limit=limit)
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc


@router.get(
    _PREFIX + "/results/{result_id}",
    response_model=ResultDetail,
    summary="Read one verification result with its log",
    description=(
        "One verification result of the provider (PFX-5.5): its summary, its `test_results` as "
        "stored (each failed interaction's mismatches with `expected` and `actual` where the verifier "
        "sent them), a bi-directional result's `comparison`, and — when Apiome ran it — its evidence "
        "run, every request with its assertions. `evidence_status` says why the run is absent: "
        "`not-recorded` (a Pact verifier published the result), `not-found` (pruned) or `forbidden` "
        "(the caller lacks `verification_evidence:view`). Requires `pacts:view`."
    ),
    responses=_READ_ERRORS,
)
def read_one_result(
    tenant_slug: str,
    provider: str,
    result_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ResultDetail:
    """Read one result in full.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        result_id: The result's id.
        auth_data: The authenticated principal.

    Returns:
        The result.

    Raises:
        HTTPException: 403 without ``pacts:view``; 404 for an unknown provider or result.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target=provider)
    include_evidence = has_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    try:
        return read_result(db, _tenant_id(auth_data), provider, result_id, include_evidence=include_evidence)
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc


def _enforce_run(auth_data: Dict[str, Any], provider: str) -> Optional[str]:
    """Require what a console run needs: ``pacts:create`` and ``verification_evidence:create``."""
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=provider)
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.CREATE)
    return user_id


@router.post(
    _PREFIX + "/consumer/{consumer}/pact-version/{sha}/reverify",
    response_model=ConsoleRunResponse,
    summary="Re-run the verification of one pact",
    description=(
        "Verify one pact version again on a registered verification target (PFX-5.5), with the "
        "hosted verifier (PFX-3.2): the same replay, matching, evidence and publishing. Without "
        "`provider_version` the run verifies as the provider version and branch of the pact "
        "version's newest result. The published result records `trigger: manual`.\n\n"
        "A console run of the same consumer ↔ provider pair that is still running makes this a "
        "`409` (`pact-verify-in-progress`). Like the hosted verifier, a run that happened is `200` "
        "whatever it found: read `success` and `outcome`. Requires `pacts:create` and "
        "`verification_evidence:create`."
    ),
    responses=_RUN_ERRORS,
)
@audited_write("pacts.verification.run", "pact/provider/{provider}/consumer/{consumer}/pact-version/{sha}")
def reverify(
    request: Request,
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    body: ConsoleRunRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ConsoleRunResponse:
    """Re-run one pact's verification.

    Args:
        request: The request (its origin shapes the published result's links).
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version.
        body: The target and, optionally, the provider version, branch and build.
        auth_data: The authenticated principal.

    Returns:
        The run.

    Raises:
        HTTPException: As the route documents.
    """
    user_id = _enforce_run(auth_data, provider)
    try:
        return reverify_pact(
            db,
            _tenant_id(auth_data),
            provider,
            consumer,
            sha,
            body,
            actor=actor_from_auth(auth_data, user_id),
            broker_base=_base_url(request, tenant_slug),
        )
    except (PactPublicationError, PacticipantValidationError, TargetValidationError, PactVerifierError) as exc:
        raise _run_error(exc) from exc


@router.post(
    _PREFIX + "/verify-stale",
    response_model=ConsoleRunResponse,
    summary="Verify every stale pact of a provider",
    description=(
        "Verify each consumer's newest pact that has no verification result yet (PFX-5.5) in one run "
        "of the hosted verifier, as `provider_version` (required) on a registered verification "
        "target. The published results record `trigger: stale-recheck`. At most 25 pacts are "
        "verified; the rest are listed in `skipped` with `pact-verify-over-limit`, and a pair whose "
        "console run is still running with `pact-verify-in-progress` — none is dropped. No stale pact "
        "is `outcome: no-pacts`. Requires `pacts:create` and `verification_evidence:create`."
    ),
    responses=_RUN_ERRORS,
)
@audited_write("pacts.verification.run", "pacticipant/{provider}/stale")
def verify_stale(
    request: Request,
    tenant_slug: str,
    provider: str,
    body: ConsoleRunRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> ConsoleRunResponse:
    """Verify every stale pact of the provider.

    Args:
        request: The request (its origin shapes the published results' links).
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        body: The target and the provider version.
        auth_data: The authenticated principal.

    Returns:
        The run.

    Raises:
        HTTPException: As the route documents.
    """
    user_id = _enforce_run(auth_data, provider)
    try:
        return verify_stale_pacts(
            db,
            _tenant_id(auth_data),
            provider,
            body,
            actor=actor_from_auth(auth_data, user_id),
            broker_base=_base_url(request, tenant_slug),
        )
    except (PactPublicationError, PacticipantValidationError, TargetValidationError, PactVerifierError) as exc:
        raise _run_error(exc) from exc
