"""
Onboarding endpoints: first-tenant provisioning and invited-member arrival.

``POST /v1/onboarding/first-tenant`` (OLO-4.3, #4207) creates the
authenticated user's tenant in one transaction: tenant row, active
``tenant_users`` membership, built-in **Owner** role assignment (V118 seed),
legacy ``tenant_administrators`` entry, and free-tier ``user_entitlements`` —
then best-effort seeds the curated sample project. The caller's
``user_entitlements.max_tenants`` cap is enforced inside the same transaction
(409 ``tenant-cap-reached`` when exceeded).

``POST /v1/onboarding/membership-activation`` (OLO-4.4, #4208) covers the
invited-user path: a user invited to an existing tenant arrives with a
``pending`` membership (V121) and must not create a tenant — on first arrival
the UI calls this endpoint to transition that pending membership to
``active``. Only the caller's own membership can be activated, and a
``suspended`` membership is never reactivated by logging in.

These endpoints are the single provisioning path: the onboarding wizard, the
OAuth-signup server action (``apiome-ui/lib/auth/oauth-signup-actions.ts``),
and the sign-in arrival hook all call them instead of issuing their own DB
writes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import normalize_user_id, validate_session_credentials
from .database import (
    TenantCapReachedError,
    TenantProvisioningError,
    TenantSlugConflictError,
    db,
)
from .models import (
    FirstTenantProvisionRequest,
    FirstTenantProvisionResponse,
    MembershipActivationRequest,
    MembershipActivationResponse,
    TenantProvisionedSchema,
)
from .tenant_slug import generate_tenant_slug, validate_tenant_slug

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])


def _format_created(value: Any) -> Optional[str]:
    """Render a created_at column value as an ISO date string, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:10]
    return None


@router.post(
    "/first-tenant",
    response_model=FirstTenantProvisionResponse,
    status_code=201,
    responses={
        400: {"description": "Invalid organization name or slug."},
        401: {"description": "Missing or invalid session credentials."},
        403: {
            "description": (
                "API-key sessions cannot provision tenants, or (structured, "
                "OLO-5.3) ``tenant-cap-reached`` when the caller is at their "
                "max-tenants entitlement."
            )
        },
        409: {
            "description": (
                "Structured conflict: ``tenant-slug-taken`` when the slug is "
                "already in use."
            )
        },
    },
)
async def provision_first_tenant(
    payload: FirstTenantProvisionRequest,
    session: Dict[str, Any] = Depends(validate_session_credentials),
) -> FirstTenantProvisionResponse:
    """
    Atomically provision the caller's first tenant (or next, when their
    entitlement allows more than one).

    All-or-nothing: any failure rolls back every write. A second call for a
    user already at their ``max_tenants`` cap returns 403 ``tenant-cap-reached``
    (the license enforcement guard, OLO-5.3 #4213).
    """
    if session.get("auth_method") != "jwt":
        # API keys are tenant-scoped credentials; only a user session may
        # bootstrap new tenants.
        raise HTTPException(
            status_code=403,
            detail="Tenant provisioning requires a user session, not an API key",
        )

    user_id = normalize_user_id(session.get("user_id"))
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user identifier")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Organization name is required")

    raw_slug = (payload.slug or "").strip().lower()
    slug = raw_slug if raw_slug else generate_tenant_slug(name)
    slug_error = validate_tenant_slug(slug)
    if slug_error:
        raise HTTPException(status_code=400, detail=slug_error)

    try:
        tenant = db.provision_first_tenant(user_id, name, slug)
    except TenantCapReachedError as e:
        # License enforcement guard (OLO-5.3, #4213): the caller's tenant count is
        # at ``user_entitlements.max_tenants`` (Free default when no row) — a 403
        # with the stable ``tenant-cap-reached`` code, not a 409, so the wizard and
        # UI can render upgrade guidance alongside the seat-exhausted guard.
        raise HTTPException(status_code=403, detail={"code": e.code, "message": e.message})
    except TenantSlugConflictError as e:
        raise HTTPException(status_code=409, detail={"code": e.code, "message": e.message})
    except TenantProvisioningError as e:
        logger.error("first-tenant provisioning failed for user %s: %s", user_id, e.message)
        raise HTTPException(status_code=500, detail={"code": e.code, "message": e.message})

    sample_project_id: Optional[str] = None
    if payload.provision_sample_project:
        # Best-effort: a fresh tenant may simply start empty; never fail the
        # committed provisioning over the sample seed.
        try:
            sample_project_id = db.provision_sample_project(tenant["id"], user_id)
        except Exception as e:
            logger.warning(
                "sample-project seed failed for tenant %s: %s", tenant["id"], e
            )

    return FirstTenantProvisionResponse(
        tenant=TenantProvisionedSchema(
            id=str(tenant["id"]),
            name=str(tenant["name"]),
            slug=str(tenant["slug"]),
            created_at=_format_created(tenant.get("created_at")),
        ),
        sample_project_id=sample_project_id,
    )


def _normalize_tenant_id(value: Any) -> Optional[str]:
    """Return the canonical UUID string for a tenant id, or None when invalid.

    Guarding here keeps malformed ids out of the ``::uuid`` casts in the
    database layer (which would raise on a non-UUID string).
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return None


@router.post(
    "/membership-activation",
    response_model=MembershipActivationResponse,
    responses={
        400: {"description": "``tenant_id`` is missing or not a UUID."},
        401: {"description": "Missing or invalid session credentials."},
        403: {
            "description": (
                "API-key sessions cannot activate memberships, or the "
                "membership is ``suspended`` (structured code "
                "``membership-suspended``) — logging in never unsuspends."
            )
        },
        404: {
            "description": (
                "The caller has no membership in this tenant (structured "
                "code ``membership-not-found``)."
            )
        },
    },
)
async def activate_membership(
    payload: MembershipActivationRequest,
    session: Dict[str, Any] = Depends(validate_session_credentials),
) -> MembershipActivationResponse:
    """
    Activate the caller's *pending* membership in a tenant (invited-user
    first arrival, OLO-4.4).

    Idempotent: an already-active membership returns 200
    ``already-active``. Only ``pending`` rows are touched — a ``suspended``
    membership returns 403 ``membership-suspended`` and stays suspended.
    """
    if session.get("auth_method") != "jwt":
        # API keys are tenant-scoped credentials; membership lifecycle belongs
        # to the user's own session.
        raise HTTPException(
            status_code=403,
            detail="Membership activation requires a user session, not an API key",
        )

    user_id = normalize_user_id(session.get("user_id"))
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user identifier")

    tenant_id = _normalize_tenant_id(payload.tenant_id)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id must be a UUID")

    try:
        outcome = db.activate_pending_membership(tenant_id, user_id)
    except Exception as e:
        logger.error(
            "membership activation failed for user %s in tenant %s: %s",
            user_id,
            tenant_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "membership-activation-failed",
                "message": "Could not activate the membership",
            },
        )

    if outcome == "none":
        raise HTTPException(
            status_code=404,
            detail={
                "code": "membership-not-found",
                "message": "You are not a member of this tenant",
            },
        )
    if outcome not in ("activated", "already-active"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "membership-suspended",
                "message": "This membership is suspended and cannot be activated by signing in",
            },
        )

    if outcome == "activated":
        logger.info(
            "activated pending membership for user %s in tenant %s", user_id, tenant_id
        )
    return MembershipActivationResponse(status=outcome, tenant_id=tenant_id)
