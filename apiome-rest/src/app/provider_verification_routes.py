"""Provider verification endpoints — CTG-4.3 (#4489).

Three routes, one question each:

* ``POST /v1/tenants/{tenant}/contracts/{version_ref}/verify-provider`` — *does the deployment
  still match this contract?* Runs the version's compiled suite against a registered target and
  returns a conformance report.
* ``GET /v1/tenants/{tenant}/provider-verifications`` — *what has drifted, and when was this
  version last checked?* The list read CTG-4.4 (scheduling) and CTG-4.5 (deploy gating) consume.
* ``GET /v1/tenants/{tenant}/provider-verifications/{report_id}`` — the full report, with every
  drift located by its JSON Pointer.

Authorization mirrors the ECA-2.1 runner: running requires ``versions:view`` (to compile the
suite) **and** ``verification_evidence:create`` (because a run always writes evidence); reading
requires ``verification_evidence:view``. A conformance report is verification evidence, so it is
governed by that resource rather than one of its own.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .provider_verification_service import (
    ProviderVerificationRequest,
    ProviderVerificationResponse,
    SchemaReferenceError,
    verify_version_against_target,
)
from .provider_verification_store import (
    CODE_REPORT_NOT_FOUND,
    CODE_REPORT_UNREADABLE,
    ConformanceReportRecord,
    ConformanceReportSummary,
    ProviderVerificationStoreError,
    get_report,
    list_reports,
)
from .verification_evidence import EvidenceValidationError
from .verification_evidence_store import actor_from_auth
from .verification_target import CODE_NOT_FOUND, TargetValidationError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["contract-assurance"])

_TARGET_STATUS_BY_CODE = {CODE_NOT_FOUND: 404}
#: A missing report is the caller's mistake; a report this build cannot parse is ours, so it must
#: not be dressed up as a 404 that sends somebody looking for a deletion that never happened.
_STORE_STATUS_BY_CODE = {CODE_REPORT_NOT_FOUND: 404, CODE_REPORT_UNREADABLE: 500}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The authenticated principal.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant context.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.post(
    "/{tenant_slug}/contracts/{version_ref:path}/verify-provider",
    response_model=ProviderVerificationResponse,
    summary="Verify a live deployment against a published contract",
    description=(
        "Compile the version's deterministic contract suite (ECA-1.1), resolve the named "
        "verification target (ECA-1.2), execute the cases this run is allowed to send, validate "
        "every response against the contract's own schema, and return a **conformance report**: "
        "per-operation verdicts, each schema violation located by its JSON Pointer into the "
        "response body, and coverage measured against every operation in the specification.\n\n"
        "**Safe by default.** Only `GET`/`HEAD`/`OPTIONS` are executed unless the request both "
        "sets `verification.allow_mutating` **and** supplies a fixture naming the operation — "
        "opting in is a permission, not a payload. Neither can widen the verification target's "
        "own `allow_mutating_methods` policy, and a fixture may not carry credentials.\n\n"
        "**Coverage is honest.** The denominator is every operation the specification declares, "
        "including those the suite compiler could not compile; what was not exercised is named "
        "with its reason rather than left out.\n\n"
        "The run is always recorded as immutable ECA-1.3 evidence and the report is persisted "
        "beside it. A version that cannot yield executable cases answers **200** with "
        "`ok: false` and a stable taxonomy `error`. Addressing faults are HTTP errors "
        "(400/404/422); target resolution faults are 400/404; evidence faults are 400."
    ),
)
async def verify_provider_for_version(
    tenant_slug: str,
    version_ref: str,
    body: ProviderVerificationRequest,
    response: Response,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProviderVerificationResponse:
    """Run provider verification for ``version_ref`` against ``body.target_ref``.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes the work).
        version_ref: Path-shaped version reference.
        body: Target, compiler options, mutation opt-in and fixtures, CI context.
        response: FastAPI response — 201 for new evidence, 200 for an idempotent replay.
        auth_data: Authenticated principal.

    Returns:
        The verification response, carrying the conformance report when ``ok`` is true.

    Raises:
        HTTPException: Permission denials, addressing faults, target faults, evidence faults.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    _ = tenant_slug

    actor = actor_from_auth(auth_data)
    try:
        result = verify_version_against_target(
            version_ref, body, tenant_id=tenant_id, actor=actor
        )
    except SchemaReferenceError as exc:
        detail: Dict[str, Any] = {"message": str(exc)}
        if exc.candidates:
            detail["candidates"] = exc.candidates
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except TargetValidationError as exc:
        raise HTTPException(
            status_code=_TARGET_STATUS_BY_CODE.get(exc.code, 400),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except EvidenceValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc

    if result.ok and result.created is True:
        response.status_code = 201
    return result


@router.get(
    "/{tenant_slug}/provider-verifications",
    response_model=List[ConformanceReportSummary],
    summary="List provider verification reports",
    description=(
        "A tenant's conformance reports, newest first, without their per-operation detail. "
        "Every field is a stored column, so a deploy gate can ask *did the newest report for "
        "this version pass, and how much did it cover?* without opening a report body.\n\n"
        "Filter by `version_ref` for one version's history, `target_id` for one deployment, or "
        "`outcome` for what is currently drifting."
    ),
)
async def list_provider_verifications(
    tenant_slug: str,
    version_ref: Optional[str] = Query(
        default=None, description="Restrict to one version reference."
    ),
    target_id: Optional[str] = Query(
        default=None, description="Restrict to one verification target."
    ),
    outcome: Optional[str] = Query(
        default=None, description="Restrict to one verdict: `passed`, `failed`, or `errored`."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum reports to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[ConformanceReportSummary]:
    """List the tenant's conformance reports.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes the read).
        version_ref: Optional version filter.
        target_id: Optional target filter.
        outcome: Optional verdict filter.
        limit: Maximum reports.
        auth_data: Authenticated principal.

    Returns:
        The summaries, newest first.

    Raises:
        HTTPException: 403 when the caller may not read verification evidence.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    _ = tenant_slug
    return list_reports(
        tenant_id,
        version_ref=version_ref,
        target_id=target_id,
        outcome=outcome,
        limit=limit,
    )


@router.get(
    "/{tenant_slug}/provider-verifications/{report_id}",
    response_model=ConformanceReportRecord,
    summary="Read one provider verification report",
    description=(
        "The full conformance report: per-operation verdicts, every drift located by its JSON "
        "Pointer into the response body, the operations the run does not vouch for and why, and "
        "the id of the immutable evidence run the report was read from."
    ),
)
async def read_provider_verification(
    tenant_slug: str,
    report_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConformanceReportRecord:
    """Read one conformance report in full.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes the read).
        report_id: The report id.
        auth_data: Authenticated principal.

    Returns:
        The stored report.

    Raises:
        HTTPException: 403 when the caller may not read evidence, 404 when no such report exists
            in this tenant, 500 when the stored report cannot be read by this build.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    _ = tenant_slug
    try:
        return get_report(tenant_id, report_id)
    except ProviderVerificationStoreError as exc:
        raise HTTPException(
            status_code=_STORE_STATUS_BY_CODE.get(exc.code, 400),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
