"""Tenant license REST surface (OLO-5.4, #4214).

``GET /v1/tenants/{tenant_slug}/license`` lets the UI (OLO-5.5 license panel) and
the CLI read a tenant's plan, seat usage, and effective feature entitlements in
one call:

* **Plan** — name and billing type from the V182 ``tenant_licenses`` attachment
  joined to the V097 catalog. A tenant predating the V183 backfill has no
  attachment; the plan is then reported as ``null`` while seat limits still fall
  back to the Free default, mirroring the OLO-5.3 enforcement path.
* **Seats** — member seats used vs. the license maximum. Both numbers come from
  the same helpers the enforcement guard uses (``license_capacity.member_seat_limit``
  and ``Database.count_member_seats_in_use``), so the surface always reports
  exactly what enforcement enforces.
* **Quotas** — the plan's stored project / published-version / AI-request limits
  (#64), read from the license ``seats`` JSON via ``license_capacity.license_quotas``
  (Free defaults when unlicensed; ``-1`` = unlimited). Project and version quotas
  are enforced by apiome-ui on the write paths; the AI cap is stored/reported only.
* **Features** — the V097 composition: the license's bundled flags
  (``license_feature_flags``) unioned with per-tenant overrides
  (``tenant_feature_flags``). An override beats the license default; a flag whose
  global master switch is off is never effective. Per-user overrides are
  deliberately excluded — this is the tenant's surface, not one member's view.

Authorization: ``validate_authentication`` resolves the path slug and rejects
non-members (404 unknown tenant, 403 non-member), then the central RBAC guard
requires ``billing:view`` — held by every built-in role (Owner, Admin, Editor,
Viewer), so ordinary members can read, while a custom role stripped of
``billing:view`` is denied per the grid. Billing *administration* stays
Owner-only via the ``billing`` edit/create/delete cells (future OLO tickets).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .auth import validate_authentication
from .database import db
from .license_capacity import license_quotas, member_seat_limit
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/tenants", tags=["license"])

# ``source`` values on LicenseFeatureSchema: where the effective state came from.
FEATURE_SOURCE_LICENSE = "license"
FEATURE_SOURCE_TENANT_OVERRIDE = "tenant-override"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LicensePlanSchema(BaseModel):
    """The tenant's attached license plan (V097 catalog via V182 attachment)."""

    name: str = Field(..., description="Plan display name, e.g. 'Free'.")
    type: str = Field(..., description="Billing classification: free, paid, or sponsor.")


class LicenseSeatsSchema(BaseModel):
    """Member-seat usage against the license limit."""

    used: int = Field(..., description="Seats occupied (active + pending members).")
    max: int = Field(..., description="Seat limit from the license (Free default when unlicensed).")


class LicenseQuotasSchema(BaseModel):
    """The plan quota limits stored on the license (#64).

    Values are the tenant's effective limits from its license ``seats`` JSON,
    falling back to the Free-tier defaults when unlicensed. ``-1`` means
    unlimited (Sponsor tier). Storage/reporting only — project and version
    quotas are enforced by apiome-ui on the write paths; the AI cap has no
    usage meter yet.
    """

    max_projects: int = Field(
        ..., description="Projects the plan allows (-1 = unlimited, Free default 1)."
    )
    max_versions: int = Field(
        ..., description="Published versions per project the plan allows (-1 = unlimited, Free default 3)."
    )
    max_ai_requests: int = Field(
        ..., description="AI-assistant requests the plan allows (-1 = unlimited, 0 = none, Free default 0)."
    )


class LicenseFeatureSchema(BaseModel):
    """One feature flag in the tenant's effective composition."""

    name: str = Field(..., description="Machine slug, e.g. 'designer'.")
    label: str = Field(..., description="Human-readable label.")
    description: Optional[str] = Field(None, description="What the feature does.")
    is_preview: bool = Field(False, description="Show a 'Preview' badge when true.")
    enabled: bool = Field(..., description="Effective state after composition.")
    source: str = Field(
        ...,
        description=(
            "Where the effective state came from: 'license' (bundled in the plan) "
            "or 'tenant-override' (explicit per-tenant grant/revoke)."
        ),
    )


class TenantLicenseResponse(BaseModel):
    """Payload of ``GET /v1/tenants/{tenant_slug}/license``."""

    plan: Optional[LicensePlanSchema] = Field(
        None,
        description="Attached plan; null when the tenant has no license row (pre-V183 tenant).",
    )
    seats: LicenseSeatsSchema
    quotas: LicenseQuotasSchema
    features: List[LicenseFeatureSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Composition helper
# ---------------------------------------------------------------------------


def compose_effective_features(rows: List[Dict[str, Any]]) -> List[LicenseFeatureSchema]:
    """Fold raw composition rows into effective feature states.

    Args:
        rows: Rows from ``Database.list_tenant_effective_features`` — one per flag
            in the license-bundle ∪ tenant-override union, each carrying
            ``flag_enabled`` (global master switch), ``license_grant``, and
            ``tenant_override`` (tri-state: True/False/None).

    Returns:
        One ``LicenseFeatureSchema`` per row, in input order. ``enabled`` is the
        tenant override when one exists, else the license grant — and always
        False when the flag's global master switch is off. ``source`` reports
        which layer decided (``tenant-override`` wins over ``license``).
    """
    features: List[LicenseFeatureSchema] = []
    for row in rows:
        override = row.get("tenant_override")
        if override is not None:
            effective = bool(override)
            source = FEATURE_SOURCE_TENANT_OVERRIDE
        else:
            effective = bool(row.get("license_grant"))
            source = FEATURE_SOURCE_LICENSE
        if not row.get("flag_enabled"):
            # Globally disabled master switch — off for everyone, whatever the layers say.
            effective = False
        features.append(
            LicenseFeatureSchema(
                name=str(row.get("name") or ""),
                label=str(row.get("label") or ""),
                description=row.get("description"),
                is_preview=bool(row.get("is_preview")),
                enabled=effective,
                source=source,
            )
        )
    return features


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/license",
    response_model=TenantLicenseResponse,
    responses={
        401: {"description": "Missing or invalid credentials."},
        403: {"description": "Caller is not a member, or lacks billing:view."},
        404: {"description": "Tenant not found."},
    },
)
async def get_tenant_license(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantLicenseResponse:
    """Read the tenant's plan, seat usage, and effective features (OLO-5.4).

    Args:
        tenant_slug: Tenant slug from the path; membership is validated by
            ``validate_authentication``.
        auth_data: The authenticated principal (tenant_id resolved from the slug).

    Returns:
        The tenant's license summary. ``plan`` is null for a tenant with no
        license row; ``seats.max`` then falls back to the Free default so the
        numbers always match what the OLO-5.3 guard enforces.
    """
    enforce_permission(db, auth_data, Resource.BILLING, Action.VIEW)
    tenant_id = str(auth_data["tenant_id"])

    info = db.get_tenant_license_info(tenant_id)
    plan: Optional[LicensePlanSchema] = None
    if info is not None:
        plan = LicensePlanSchema(
            name=str(info.get("name") or ""),
            type=str(info.get("license_type") or ""),
        )

    seats = LicenseSeatsSchema(
        used=db.count_member_seats_in_use(tenant_id),
        max=member_seat_limit(tenant_id),
    )

    quotas = LicenseQuotasSchema(**license_quotas(tenant_id))

    features = compose_effective_features(db.list_tenant_effective_features(tenant_id))
    return TenantLicenseResponse(plan=plan, seats=seats, quotas=quotas, features=features)
