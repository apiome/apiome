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
from .database import (
    DEFAULT_FREE_MAX_AI_REQUESTS,
    DEFAULT_FREE_MAX_PROJECTS,
    DEFAULT_FREE_MAX_USERS_PER_TENANT,
    DEFAULT_FREE_MAX_VERSIONS,
    db,
)

# Stable machine-readable code for the structured 403 emitted when a tenant's
# member-seat limit is exhausted (consumed by the OLO-5.5 license panel and the
# member-invite UI).
LICENSE_SEATS_EXHAUSTED_CODE = "license-seats-exhausted"

# The plan quota keys #64 stores in ``licenses.seats``, paired with their
# Free-tier fallback. Read by ``license_quotas`` and surfaced on the license
# REST surface. A negative stored value means "unlimited" (kept as ``-1``),
# matching the apiome-ui enforcement convention
# (``entitlement-limits-from-license-seats.ts``).
_QUOTA_DEFAULTS: Dict[str, int] = {
    "max_projects": DEFAULT_FREE_MAX_PROJECTS,
    "max_versions": DEFAULT_FREE_MAX_VERSIONS,
    "max_ai_requests": DEFAULT_FREE_MAX_AI_REQUESTS,
}


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


def _quota_from_seats(seats: Dict[str, Any], key: str, default: int) -> int:
    """Resolve one quota key from a license ``seats`` dict.

    Args:
        seats: The license ``seats`` JSON (may be missing keys).
        key: The quota key to read (e.g. ``"max_projects"``).
        default: Free-tier fallback when the key is absent or non-numeric.

    Returns:
        The stored integer limit, ``-1`` when the stored value is negative
        (unlimited), or ``default`` when the key is missing or not a number.
    """
    try:
        value = int(seats.get(key))
    except (TypeError, ValueError):
        return default
    return -1 if value < 0 else value


def license_quotas(tenant_id: str) -> Dict[str, int]:
    """Resolve a tenant's stored plan quotas from its attached license (#64).

    Reads the same ``seats`` JSON the seat guard uses and projects the quota
    keys #64 stores on the license — ``max_projects``, ``max_versions`` and
    ``max_ai_requests``. A tenant with no license row (or a malformed value)
    falls back to the Free-tier defaults, mirroring ``member_seat_limit``.

    Args:
        tenant_id: Canonical UUID string of the tenant.

    Returns:
        A dict with one entry per quota key. Each value is the stored limit,
        ``-1`` for unlimited, or the Free default when unset.
    """
    seats = db.get_tenant_license_seats(tenant_id) or {}
    return {key: _quota_from_seats(seats, key, default) for key, default in _QUOTA_DEFAULTS.items()}


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
