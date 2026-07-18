"""License seat-capacity enforcement for tenant membership (OLO-5.3, #4213).

The V097 license catalog carries per-license seat shapes
(``seats.max_users_per_tenant``) and V182/V183 attach a license to every tenant —
this module makes those limits real. It mirrors ``feature_gating.py``: a factory
builds a FastAPI dependency that wraps ``validate_authentication`` and returns the
same ``auth_data`` dict, so gated routes swap the dependency without any other
handler changes (and tests overriding ``validate_authentication`` keep working).

Seat accounting rules (see ``Database.count_member_seats_in_use``):

* ``active`` and ``pending`` memberships occupy a seat (an outstanding invite
  reserves its seat).
* ``suspended`` members (V121) do **not** occupy a seat — suspending frees one,
  reinstating consumes one again (the reinstate path re-checks capacity via
  ``assert_member_seat_available``).
* Soft-deleted user accounts (``users.deleted_at``) never occupy a seat.

When a tenant has no license row, or its ``seats`` JSON is missing or malformed,
the Free-tier default (``DEFAULT_FREE_MAX_USERS_PER_TENANT``) applies, so
enforcement can never strand a tenant that predates the V183 backfill.

Blocked callers receive a structured 403 payload
``{"code": "license-seats-exhausted", "message": ...}`` so the UI (OLO-5.5) and
the onboarding wizard can render upgrade guidance from the stable code. The
sibling tenant-cap guard (code ``tenant-cap-reached``) lives in the
first-tenant provisioning path (``Database.provision_first_tenant`` +
``onboarding_routes``), which enforces ``user_entitlements.max_tenants``.

The whole guard honours the operator kill switch
``settings.license_enforcement_enabled`` (default ``True``); switching it off
restores pre-5.3 behavior without redeploying.
"""

from typing import Any, Callable, Dict, Optional

from fastapi import Depends, HTTPException

from .auth import validate_authentication
from .config import settings
from .database import DEFAULT_FREE_MAX_USERS_PER_TENANT, db

# Stable machine-readable code for the structured 403 emitted when a tenant's
# member-seat limit is exhausted (consumed by the OLO-5.5 license panel and the
# member-invite UI).
LICENSE_SEATS_EXHAUSTED_CODE = "license-seats-exhausted"


def member_seat_limit(tenant_id: str) -> int:
    """Resolve the tenant's member-seat limit from its attached license.

    Args:
        tenant_id: Canonical UUID string of the tenant.

    Returns:
        ``seats.max_users_per_tenant`` from the tenant's license, or
        ``DEFAULT_FREE_MAX_USERS_PER_TENANT`` when the tenant has no license row
        or the value is missing, non-numeric, or negative.
    """
    seats = db.get_tenant_license_seats(tenant_id) or {}
    try:
        limit = int(seats.get("max_users_per_tenant"))
    except (TypeError, ValueError):
        return DEFAULT_FREE_MAX_USERS_PER_TENANT
    return limit if limit >= 0 else DEFAULT_FREE_MAX_USERS_PER_TENANT


def assert_member_seat_available(tenant_id: str) -> None:
    """Raise a structured 403 unless the tenant has a free member seat.

    Compares the current seat count (non-suspended, non-deleted members) against
    the license limit. Call this before any seat-consuming write: adding or
    inviting a member, or reinstating a suspended one.

    Args:
        tenant_id: Canonical UUID string of the tenant.

    Raises:
        HTTPException: 403 with ``detail={"code": "license-seats-exhausted",
            "message": ...}`` when every seat is already occupied.
    """
    limit = member_seat_limit(tenant_id)
    used = db.count_member_seats_in_use(tenant_id)
    if used >= limit:
        raise HTTPException(
            status_code=403,
            detail={
                "code": LICENSE_SEATS_EXHAUSTED_CODE,
                "message": (
                    f"This tenant's license allows {limit} member seat(s) and all "
                    f"{used} are in use. Suspend or offboard a member, or upgrade "
                    "the tenant's license, to add more members."
                ),
            },
        )


def require_license_capacity(
    *,
    enforcement_enabled: Callable[[], bool],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Build a FastAPI dependency that blocks seat-consuming routes at capacity.

    Args:
        enforcement_enabled: Zero-arg predicate read at request time deciding
            whether enforcement is active. Read lazily (not captured as a bool)
            so the operator switch can be toggled — and patched in tests —
            without rebuilding the dependency.

    Returns:
        A dependency callable that returns the authenticated ``auth_data`` when
        a seat is available (or enforcement is off), or raises
        ``HTTPException(403)`` with the ``license-seats-exhausted`` code when the
        tenant's seats are exhausted.
    """

    def _dependency(
        auth_data: Dict[str, Any] = Depends(validate_authentication),
    ) -> Dict[str, Any]:
        if not enforcement_enabled():
            return auth_data

        tenant_id: Optional[str] = auth_data.get("tenant_id")
        if tenant_id:
            assert_member_seat_available(tenant_id)
        return auth_data

    return _dependency


# Gate for seat-consuming membership routes (member invite). Enforced unless the
# ``license_enforcement_enabled`` kill switch is turned off.
require_member_seat = require_license_capacity(
    enforcement_enabled=lambda: settings.license_enforcement_enabled,
)
