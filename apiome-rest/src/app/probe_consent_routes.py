"""Probe consent and security probe report routes — ASP-4.1 (#5939).

* ``POST | GET | DELETE /v1/tenants/{tenant}/verification-targets/{ref}/probe-consent`` — grant,
  read and revoke the consent a security probe needs before it may fire at a target other than the
  Apiome-hosted mock.
* ``GET /v1/tenants/{tenant}/security-probe-reports[/{id}]`` — the write-once reports probe runs
  leave behind.

**Authorization** reuses the ``verification_evidence`` RBAC resource (V212): granting or revoking
consent needs ``verification_evidence:create`` — the same permission a probe run needs, so nobody can
authorize traffic they could not send — and reading needs ``verification_evidence:view``. A
``production`` target's consent additionally needs a signed-in tenant administrator; an API key can
never grant it.

The run itself (``POST …/contracts/{ref}/probe``) arrives with ASP-4.4; this ticket ships the gate it
passes through (:func:`app.probe_consent_store.authorize_probe_run`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_tenant_admin_session, validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .probe_consent import ENVIRONMENT_PRODUCTION
from .probe_consent_store import (
    CODE_CONSENT_NOT_FOUND,
    CODE_REPORT_NOT_FOUND,
    MAX_LIST_LIMIT,
    ProbeConsentGrant,
    ProbeConsentRecord,
    ProbeConsentStoreError,
    SecurityProbeReportRecord,
    SecurityProbeReportSummary,
    actor_from_auth,
    get_live_consent,
    get_report,
    grant_consent,
    list_reports,
    revoke_consent,
)
from .verification_target import CODE_NOT_FOUND, TargetValidationError, VerificationTargetRecord
from .verification_target_store import get_target

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["contract-assurance"])

_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_CONSENT_NOT_FOUND: 404,
    CODE_REPORT_NOT_FOUND: 404,
}


class SecurityProbeReportListResponse(BaseModel):
    """A tenant's security probe reports."""

    model_config = ConfigDict(extra="forbid")

    reports: List[SecurityProbeReportSummary] = Field(
        default_factory=list, description="Reports, newest first."
    )
    count: int = Field(description="How many reports were returned.")


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse with 403.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The tenant id.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(code: str, message: str) -> HTTPException:
    """Map a stable code onto its HTTP status, carrying ``{"code", "message"}``.

    Args:
        code: The stable code.
        message: Human-readable explanation.

    Returns:
        404 for a missing target, consent or report; 400 otherwise.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(code, 400), detail={"code": code, "message": message}
    )


def _load_target(tenant_id: str, target_ref: str) -> VerificationTargetRecord:
    """Resolve a live target by slug or id inside the tenant, or raise the mapped HTTP error.

    Args:
        tenant_id: The caller's tenant.
        target_ref: Slug or id.

    Returns:
        The target.
    """
    try:
        return get_target(tenant_id, target_ref)
    except TargetValidationError as exc:
        raise _http_error(exc.code, str(exc)) from exc


@router.post(
    "/{tenant_slug}/verification-targets/{target_ref}/probe-consent",
    response_model=ProbeConsentRecord,
    status_code=201,
    summary="Grant security probe consent for a target",
    description=(
        "Authorize security probes against this verification target until `expires_at`, for the "
        "listed `profiles_allowed` (`passive`, `safe-active`, `payload`).\n\n"
        "You must declare `ownership_declared: true` — that you own the target or are authorized "
        "to test it. Test identities are credential **references** (an environment-variable name "
        "or a credential-vault id), never a credential; a pasted token is rejected.\n\n"
        "A target has one live consent: granting replaces (revokes) the previous one. A target "
        "whose environment is `mock` and whose base URL is the Apiome-hosted mock needs no "
        "consent.\n\n"
        "Requires `verification_evidence:create`; a `production` target also needs a signed-in "
        "tenant administrator. Every grant is written to the access audit."
    ),
)
async def grant_probe_consent(
    tenant_slug: str,
    target_ref: str,
    body: ProbeConsentGrant,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProbeConsentRecord:
    """Grant consent for a target.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes it).
        target_ref: The target's slug or id.
        body: The grant.
        auth_data: The authenticated principal.

    Returns:
        The stored consent.

    Raises:
        HTTPException: 404 unknown target, 400 invalid grant, 403 without permission.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.CREATE, target=target_ref
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    target = _load_target(tenant_id, target_ref)
    if target.environment == ENVIRONMENT_PRODUCTION:
        require_tenant_admin_session(
            db,
            auth_data,
            detail="Only a tenant administrator can grant probe consent for a production target",
        )
    try:
        return grant_consent(tenant_id, target, body, actor=actor_from_auth(auth_data, user_id))
    except ProbeConsentStoreError as exc:
        raise _http_error(exc.code, str(exc)) from exc


@router.get(
    "/{tenant_slug}/verification-targets/{target_ref}/probe-consent",
    response_model=ProbeConsentRecord,
    summary="Read a target's security probe consent",
    description=(
        "The target's live (unrevoked) consent, with `status` `active` or `expired` at read "
        "time. 404 when the target has none.\n\nRequires `verification_evidence:view`."
    ),
)
async def get_probe_consent(
    tenant_slug: str,
    target_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProbeConsentRecord:
    """Read a target's live consent.

    Args:
        tenant_slug: The tenant in the URL.
        target_ref: The target's slug or id.
        auth_data: The authenticated principal.

    Returns:
        The consent.

    Raises:
        HTTPException: 404 when the target or its consent does not exist.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    target = _load_target(tenant_id, target_ref)
    record = get_live_consent(tenant_id, target.id)
    if record is None:
        raise _http_error(
            CODE_CONSENT_NOT_FOUND, f"target '{target.slug}' has no live probe consent"
        )
    return record


@router.delete(
    "/{tenant_slug}/verification-targets/{target_ref}/probe-consent",
    response_model=ProbeConsentRecord,
    summary="Revoke a target's security probe consent",
    description=(
        "Revoke the target's live consent. Probe runs against the target are refused from then "
        "on. The row is kept, revoked, for the audit trail.\n\n"
        "Requires `verification_evidence:create`. Every revocation is written to the access audit."
    ),
)
async def revoke_probe_consent(
    tenant_slug: str,
    target_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProbeConsentRecord:
    """Revoke a target's live consent.

    Args:
        tenant_slug: The tenant in the URL.
        target_ref: The target's slug or id.
        auth_data: The authenticated principal.

    Returns:
        The revoked consent.

    Raises:
        HTTPException: 404 when there is nothing to revoke.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.CREATE, target=target_ref
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    target = _load_target(tenant_id, target_ref)
    try:
        return revoke_consent(tenant_id, target, actor=actor_from_auth(auth_data, user_id))
    except ProbeConsentStoreError as exc:
        raise _http_error(exc.code, str(exc)) from exc


@router.get(
    "/{tenant_slug}/security-probe-reports",
    response_model=SecurityProbeReportListResponse,
    summary="List security probe reports",
    description=(
        "The tenant's write-once security probe reports, newest first: target snapshot, profile, "
        "consent, limits, proof ceiling and counts by tier.\n\n"
        "Requires `verification_evidence:view`."
    ),
)
async def list_security_probe_reports(
    tenant_slug: str,
    target_id: Optional[str] = Query(default=None, description="Restrict to one target id."),
    limit: int = Query(default=50, ge=1, le=MAX_LIST_LIMIT, description="Maximum reports."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SecurityProbeReportListResponse:
    """List reports.

    Args:
        tenant_slug: The tenant in the URL.
        target_id: Optional target filter.
        limit: Maximum rows.
        auth_data: The authenticated principal.

    Returns:
        The reports.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    _ = tenant_slug
    reports = list_reports(_tenant_id(auth_data), target_id=target_id, limit=limit)
    return SecurityProbeReportListResponse(reports=reports, count=len(reports))


@router.get(
    "/{tenant_slug}/security-probe-reports/{report_id}",
    response_model=SecurityProbeReportRecord,
    summary="Read one security probe report",
    description="One report with its body.\n\nRequires `verification_evidence:view`.",
)
async def get_security_probe_report(
    tenant_slug: str,
    report_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SecurityProbeReportRecord:
    """Read one report.

    Args:
        tenant_slug: The tenant in the URL.
        report_id: The report id.
        auth_data: The authenticated principal.

    Returns:
        The report.

    Raises:
        HTTPException: 404 when nothing matches in the tenant.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    _ = tenant_slug
    try:
        return get_report(_tenant_id(auth_data), report_id)
    except ProbeConsentStoreError as exc:
        raise _http_error(exc.code, str(exc)) from exc
