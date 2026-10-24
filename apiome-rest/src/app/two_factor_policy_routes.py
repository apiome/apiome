"""``/v1/tenants/{tenant_slug}/two-factor-policy`` — TFA-1.3 (#5657).

* ``GET`` — whether the tenant requires two-factor, the grace period, when it was turned on and how
  many active members have two-factor, are in their grace period, or are overdue. Needs
  ``members:view``.
* ``PUT`` — turn the requirement on or off and/or change the grace period (0–90 days). Needs
  ``members:edit`` (Owner and Admin by default). Audited as ``two_factor_policy.update``.

Each member's own state is on ``GET /v1/access/{tenant_slug}/members`` as ``two_factor_status`` and
``two_factor_due_at``.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .permissions import Action, Resource, enforce_permission
from .two_factor_policy import TwoFactorPolicy, TwoFactorPolicyInput, read_policy, update_policy

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["access"])


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/two-factor-policy",
    response_model=TwoFactorPolicy,
    summary="Read the two-factor policy",
    description=(
        "Whether every member must turn on two-factor authentication, the grace period in days, "
        "when the requirement was turned on, and how many active members have two-factor "
        "(`enabled`), are still inside their grace period (`grace`) or are past it (`overdue`).\n\n"
        "A member's deadline is the later of the requirement being turned on and the member "
        "joining, plus the grace period.\n\nRequires `members:view`."
    ),
)
async def get_two_factor_policy(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> TwoFactorPolicy:
    """Read the policy."""
    enforce_permission(db, auth_data, Resource.MEMBERS, Action.VIEW, target="two-factor-policy")
    _ = tenant_slug
    return read_policy(_tenant_id(auth_data))


@router.put(
    "/{tenant_slug}/two-factor-policy",
    response_model=TwoFactorPolicy,
    summary="Change the two-factor policy",
    description=(
        "Set `require_two_factor` and/or `grace_days` (0–90). Omitted fields are left alone. "
        "Turning the requirement on starts every member's grace period; turning it off and on "
        "again restarts them. Members past their deadline are asked to set up two-factor before "
        "they can use the app; API keys are unaffected.\n\n"
        "Audited as `two_factor_policy.update`. Requires `members:edit`."
    ),
)
async def put_two_factor_policy(
    tenant_slug: str,
    body: TwoFactorPolicyInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TwoFactorPolicy:
    """Change the policy."""
    user_id = enforce_permission(db, auth_data, Resource.MEMBERS, Action.EDIT, target="two-factor-policy")
    _ = tenant_slug
    return update_policy(_tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
