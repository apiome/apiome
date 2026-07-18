"""
Atomic first-tenant provisioning (OLO-4.3, #4207).

``POST /v1/onboarding/first-tenant`` creates the authenticated user's tenant in
one transaction: tenant row, active ``tenant_users`` membership, built-in
**Owner** role assignment (V118 seed), legacy ``tenant_administrators`` entry,
and free-tier ``user_entitlements`` — then best-effort seeds the curated sample
project. The caller's ``user_entitlements.max_tenants`` cap is enforced inside
the same transaction (409 ``tenant-cap-reached`` when exceeded).

This endpoint is the single provisioning path: the onboarding wizard and the
OAuth-signup server action (``apiome-ui/lib/auth/oauth-signup-actions.ts``)
both call it instead of issuing their own DB writes.
"""

from __future__ import annotations

import logging
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
        403: {"description": "API-key sessions cannot provision tenants."},
        409: {
            "description": (
                "Structured conflict: ``tenant-cap-reached`` when the caller is at "
                "their max-tenants entitlement, ``tenant-slug-taken`` when the slug "
                "is already in use."
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
    user already at their ``max_tenants`` cap returns 409 ``tenant-cap-reached``.
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
    except (TenantCapReachedError, TenantSlugConflictError) as e:
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
