"""
Session-scoped tenant discovery for the CLI (#3198).

``GET /v1/tenants/me`` lists tenants for the authenticated principal.
``HEAD /v1/tenants/{slug}`` verifies access without a response body (#3199).
``GET /v1/tenants/{slug}`` returns aggregate tenant details when the caller has access.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .auth import normalize_user_id, validate_session_credentials
from .database import db
from .models import TenantInfoResponse, TenantMembershipSchema, TenantsMeResponse

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])

_MAX_PAGE = 100
_DEFAULT_LIMIT = 50


def _authorize_tenant_access_row(tenant_slug: str, session: Dict[str, Any]) -> Dict[str, Any]:
    """Return tenant row when ``tenant_slug`` exists and ``session`` may access it."""
    if tenant_slug == "me":
        raise HTTPException(status_code=404, detail="Not found")

    row = db.get_tenant_row_by_slug(tenant_slug)
    if not row:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_slug}")

    tenant_id = str(row["id"])

    if session.get("auth_method") == "api_key":
        key_tid = session.get("tenant_id")
        if key_tid is None or str(key_tid) != tenant_id:
            raise HTTPException(
                status_code=403,
                detail=f"No access to tenant: {tenant_slug}",
            )
    else:
        user_id = session.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Missing user identifier")
        uid = normalize_user_id(user_id)
        if not uid:
            raise HTTPException(status_code=401, detail="Missing user identifier")
        if not db.user_has_tenant_access(uid, tenant_id):
            raise HTTPException(
                status_code=403,
                detail=f"No access to tenant: {tenant_slug}",
            )

    return row


def _format_created(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:10]
    return None


@router.get("/me", response_model=TenantsMeResponse)
async def list_my_tenants(
    session: Dict[str, Any] = Depends(validate_session_credentials),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_PAGE),
    offset: int = Query(0, ge=0),
) -> TenantsMeResponse:
    """
    Tenants accessible to the caller.

    - JWT: all ``tenant_users`` memberships for the user, with admin vs member role.
    - API key: the key's tenant only (single-item list).
    """
    if session.get("auth_method") == "api_key":
        slug = session.get("tenant_slug")
        name = session.get("tenant_name") or ""
        if not isinstance(slug, str) or slug.strip() == "":
            raise HTTPException(status_code=500, detail="API key session missing tenant slug")
        all_items = [TenantMembershipSchema(slug=slug, name=str(name), role="member")]
        items = all_items[offset : offset + limit]
        return TenantsMeResponse(items=items, total=len(all_items), limit=limit, offset=offset)

    user_id = session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user identifier")

    total = db.count_tenants_for_user(str(user_id))
    rows = db.list_tenants_for_user_page(str(user_id), limit, offset)
    items = [
        TenantMembershipSchema(
            slug=str(r["slug"]),
            name=str(r["name"] or ""),
            role=str(r.get("role") or "member"),
        )
        for r in rows
    ]
    return TenantsMeResponse(items=items, total=total, limit=limit, offset=offset)

@router.head(
    "/{tenant_slug}",
    response_class=Response,
    responses={
        200: {"description": "Caller has access to the tenant."},
        401: {"description": "Missing or invalid session credentials."},
        403: {"description": "Credentials valid but caller has no access to this tenant."},
        404: {"description": "Tenant not found."},
    },
)
async def verify_tenant_access(
    tenant_slug: str,
    session: Dict[str, Any] = Depends(validate_session_credentials),
) -> Response:
    """Lightweight access check for CLI default-tenant selection (#3199)."""
    _authorize_tenant_access_row(tenant_slug, session)
    return Response(status_code=200)


@router.get("/{tenant_slug}", response_model=TenantInfoResponse)
async def get_tenant_info(
    tenant_slug: str,
    session: Dict[str, Any] = Depends(validate_session_credentials),
) -> TenantInfoResponse:
    """Tenant summary including usage counts; 403 when the caller cannot access the tenant."""
    row = _authorize_tenant_access_row(tenant_slug, session)
    tenant_id = str(row["id"])

    stats = db.get_tenant_usage_stats(tenant_id)
    return TenantInfoResponse(
        slug=str(row["slug"]),
        name=str(row["name"] or ""),
        plan=None,
        created_at=_format_created(row.get("created_at")),
        members_count=int(stats.get("members_count") or 0),
        projects_count=int(stats.get("projects_count") or 0),
        versions_count=int(stats.get("versions_count") or 0),
        published_versions_count=int(stats.get("published_versions_count") or 0),
        storage_used_bytes=None,
        storage_quota_bytes=None,
    )
