"""Admin reset of a user's two-factor (TFA-1.2, #5656).

A user who loses their authenticator *and* their backup codes cannot pass the second step, and no
amount of signing in will fix it. These two endpoints let someone with authority clear the factor
for them:

* ``POST /v1/admin/users/{user_id}/two-factor/reset`` — the installation's **super-admin**, for
  any user. Guarded by the signed super-admin session, like the rest of ``/v1/admin``.
* ``POST /v1/access/{tenant_slug}/members/{user_id}/two-factor/reset`` — a workspace **owner**,
  for a member of their workspace **who belongs to no other**. Two-factor protects the account,
  not a workspace: if the member also belongs elsewhere, removing it would weaken a sign-in that
  another workspace relies on, so that case is refused and left to the super-admin.

Both require a **reason** and a **typed confirmation** (the target's email address), and both are
checked here rather than only in the dialog that collects them — a caller that skips the dialog
still cannot reset anyone without saying why and naming who.

The reset itself is one transaction (:meth:`app.database.Database.reset_user_two_factor`): the
factor, trusted devices and sessions are removed together with the audit rows that record actor,
target and reason — an ``auth_events`` row always, and an ``access_audit`` row on the workspace's
chain when an owner did it. The response says what was cleared; telling the user by email is the
web app's job (it owns the mail sender) once this call has succeeded.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import validate_authentication
from .auth_provider_config_routes import require_super_admin
from .database import db, normalize_email
from .permissions import resolve_actor_id

logger = logging.getLogger(__name__)

__all__ = [
    "REASON_MAX_LENGTH",
    "REASON_MIN_LENGTH",
    "TwoFactorResetRequest",
    "TwoFactorResetResult",
    "admin_router",
    "member_router",
]

#: Shortest reason accepted, after trimming. Long enough that "x" or "reset" does not pass for one.
REASON_MIN_LENGTH = 10
#: Longest reason accepted, after trimming.
REASON_MAX_LENGTH = 500

#: The actor label recorded for the super-admin, who is a session, not a ``users`` row.
_SUPER_ADMIN_LABEL = "super-admin"

admin_router = APIRouter(prefix="/v1/admin/users", tags=["admin-users"])
member_router = APIRouter(prefix="/v1/access", tags=["access"])


class TwoFactorResetRequest(BaseModel):
    """Why the factor is being reset, and proof the caller means this user."""

    reason: str = Field(
        ...,
        description=(
            f"Why the two-factor is being reset ({REASON_MIN_LENGTH}–{REASON_MAX_LENGTH} "
            "characters). Stored in the audit trail."
        ),
    )
    confirm: str = Field(
        ...,
        description="The target user's email address, typed out to confirm the reset.",
    )


class TwoFactorResetResult(BaseModel):
    """What a reset cleared."""

    user_id: str = Field(..., description="The user whose two-factor was reset.")
    email: Optional[str] = Field(None, description="That user's email address.")
    name: Optional[str] = Field(None, description="That user's display name.")
    had_two_factor: bool = Field(
        ..., description="Whether the user had two-factor on before the reset."
    )
    sessions_revoked: int = Field(..., description="How many of the user's sessions were ended.")
    trusted_devices_revoked: int = Field(
        ..., description="How many trusted-device records were removed."
    )


def _refuse(status_code: int, error: str, message: str) -> HTTPException:
    """Build a refusal with a stable machine-readable ``error`` and a sentence for the reader.

    Args:
        status_code: The HTTP status.
        error: Stable code a client can branch on.
        message: What went wrong, in words.

    Returns:
        The exception to raise.
    """
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _validated_reason(payload: TwoFactorResetRequest, target: Mapping[str, Any]) -> str:
    """Check the reason and the typed confirmation, and return the trimmed reason.

    Args:
        payload: The request body.
        target: The user being reset (needs ``email``).

    Returns:
        The reason, trimmed.

    Raises:
        HTTPException: ``422`` ``invalid_reason`` when the reason is too short or too long;
            ``422`` ``confirmation_mismatch`` when ``confirm`` is not the target's email.
    """
    reason = (payload.reason or "").strip()
    if not REASON_MIN_LENGTH <= len(reason) <= REASON_MAX_LENGTH:
        raise _refuse(
            422,
            "invalid_reason",
            f"Give a reason between {REASON_MIN_LENGTH} and {REASON_MAX_LENGTH} characters.",
        )
    email = target.get("email") or ""
    typed = (payload.confirm or "").strip()
    if not email or not typed or normalize_email(typed) != normalize_email(email):
        raise _refuse(
            422,
            "confirmation_mismatch",
            "Type the user's email address exactly to confirm the reset.",
        )
    return reason


def _require_target(user_id: str) -> Dict[str, Any]:
    """Load the user to reset.

    Args:
        user_id: The path's user id.

    Returns:
        The target row from :meth:`Database.get_two_factor_reset_target`.

    Raises:
        HTTPException: ``404`` ``user_not_found`` when no live user has that id.
    """
    target = db.get_two_factor_reset_target(user_id)
    if not target:
        raise _refuse(404, "user_not_found", "No user has that id.")
    return target


def _perform(
    user_id: str, *, reason: str, actor_kind: str, **actor: Optional[str]
) -> TwoFactorResetResult:
    """Run the reset and shape its result.

    Args:
        user_id: The user to reset.
        reason: The validated reason.
        actor_kind: ``super_admin`` or ``tenant_owner``.
        **actor: ``actor_id`` / ``actor_label`` / ``tenant_id`` for the audit rows.

    Returns:
        What was cleared.

    Raises:
        HTTPException: ``404`` ``user_not_found`` when the user vanished between the checks and
            the write.
    """
    result = db.reset_user_two_factor(
        user_id=user_id, reason=reason, actor_kind=actor_kind, **actor
    )
    if not result:
        raise _refuse(404, "user_not_found", "No user has that id.")
    logger.info(
        "two-factor reset: target=%s actor_kind=%s had_two_factor=%s sessions_revoked=%s",
        user_id,
        actor_kind,
        result["had_two_factor"],
        result["sessions_revoked"],
    )
    return TwoFactorResetResult(**result)


@admin_router.post(
    "/{user_id}/two-factor/reset",
    response_model=TwoFactorResetResult,
    responses={
        401: {"description": "No super-admin session presented."},
        403: {"description": "Super-admin session invalid or expired."},
        404: {"description": "No user has that id."},
        422: {"description": "Reason missing or out of range, or the confirmation does not match."},
    },
)
async def admin_reset_two_factor(
    user_id: str,
    payload: TwoFactorResetRequest,
    _: None = Depends(require_super_admin),
) -> TwoFactorResetResult:
    """Reset any user's two-factor, as the installation's super-admin.

    Clears the user's authenticator and backup codes, forgets their trusted devices and ends
    every one of their sessions. Their next sign-in needs the first factor only. The reset is
    recorded in the authentication ledger with the reason given.

    Args:
        user_id: The user to reset.
        payload: The reason, and the user's email typed out as confirmation.

    Returns:
        What was cleared.
    """
    target = _require_target(user_id)
    reason = _validated_reason(payload, target)
    return _perform(
        user_id, reason=reason, actor_kind="super_admin", actor_label=_SUPER_ADMIN_LABEL
    )


@member_router.post(
    "/{tenant_slug}/members/{user_id}/two-factor/reset",
    response_model=TwoFactorResetResult,
    responses={
        403: {
            "description": (
                "The caller is not an owner of this workspace (owner_required), or called with "
                "an API key (session_required)."
            )
        },
        404: {"description": "The user is not an active member of this workspace."},
        409: {
            "description": (
                "The member belongs to another workspace as well (multi_tenant_member), or the "
                "caller tried to reset their own two-factor (self_reset)."
            )
        },
        422: {"description": "Reason missing or out of range, or the confirmation does not match."},
    },
)
async def member_reset_two_factor(
    tenant_slug: str,
    user_id: str,
    payload: TwoFactorResetRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TwoFactorResetResult:
    """Reset a member's two-factor, as an owner of the workspace.

    Allowed only for an **owner**, only for an **active member** of this workspace, and only when
    that member belongs to **no other workspace** — two-factor protects the whole account, so a
    member shared with another workspace is left to the installation's super-admin. An owner
    cannot reset their own two-factor here; they manage it on their Profile page.

    Recorded in the authentication ledger and in this workspace's access audit, with the reason.

    Args:
        tenant_slug: The workspace the caller is acting in.
        user_id: The member to reset.
        payload: The reason, and the member's email typed out as confirmation.

    Returns:
        What was cleared.
    """
    tenant_id = auth_data["tenant_id"]
    # A person, not a key: an API key acts as the workspace rather than as an accountable owner,
    # and this is a decision someone has to put their name and a reason to.
    if auth_data.get("auth_method") == "api_key":
        raise _refuse(
            403, "session_required", "Sign in to reset a member's two-factor; an API key cannot."
        )
    actor_id = resolve_actor_id(db, auth_data)
    if not actor_id or db.get_effective_role_slug(tenant_id, actor_id) != "owner":
        raise _refuse(
            403, "owner_required", "Only an owner of this workspace can reset a member's two-factor."
        )
    if str(actor_id) == str(user_id):
        raise _refuse(
            409, "self_reset", "Manage your own two-factor from your Profile page."
        )
    if db.get_member_status(tenant_id, user_id) != "active":
        raise _refuse(404, "member_not_found", "That user is not an active member of this workspace.")

    target = _require_target(user_id)
    if int(target.get("tenant_count") or 0) != 1:
        raise _refuse(
            409,
            "multi_tenant_member",
            "This member also belongs to another workspace, so their two-factor can only be reset "
            "by an administrator of this Apiome installation.",
        )
    reason = _validated_reason(payload, target)
    return _perform(
        user_id,
        reason=reason,
        actor_kind="tenant_owner",
        actor_id=str(actor_id),
        actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
        tenant_id=str(tenant_id),
    )
