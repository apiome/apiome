"""Super-admin REST surface for the installation sign-up policy (SGN-1.4, #5653).

Server-scoped (NOT tenant-scoped) endpoints over ``apiome.signup_policy`` (V274) — the surface the
admin console's **Sign-up** card builds on:

* ``GET /v1/admin/signup-policy`` — the effective policy, whether it is stored or the env
  fallback, and what the env fallback would be.
* ``PUT /v1/admin/signup-policy`` — store the policy (``mode`` + ``allowed_email_domains`` +
  ``blocked_email_domains``), or clear the stored policy with ``mode: null`` so the installation
  reverts to env.
* ``GET /v1/admin/signup-policy/blocked-attempts`` — the sign-up attempts an abuse guard refused
  (SGN-1.5, #5654): rate limits, disposable email domains and failed CAPTCHAs, read from
  ``apiome.auth_events``.

Invariants:

* **Gated server-side** by :func:`app.auth_provider_config_routes.require_super_admin` — the same
  HMAC-signed super-admin session as the sign-in provider settings. No session ⇒ ``401``; an
  invalid, expired or forged one ⇒ ``403``.
* **Audited.** Every change writes an ``apiome.signup_policy_audit`` row in the same transaction
  as the change (:meth:`app.database.Database.set_signup_policy`).
* **Effective without a restart.** A successful write drops this instance's cached policy; other
  instances pick the change up within the cache lifetime
  (:func:`app.signup_policy.get_effective_signup_policy`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .auth_provider_config_routes import require_super_admin
from .database import db
from .signup_policy import (
    MAX_ALLOWED_EMAIL_DOMAINS,
    MAX_BLOCKED_EMAIL_DOMAINS,
    SIGNUP_MODES,
    SOURCE_DB,
    SOURCE_ENV,
    invalidate_signup_policy_cache,
    normalize_allowed_email_domains,
    signup_policy_from_env,
    signup_policy_from_row,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/signup-policy", tags=["admin-signup-policy"])

#: Identity recorded for changes made through the super-admin session (as for provider config).
_ACTOR = "admin"


class SignupPolicyView(BaseModel):
    """The installation sign-up policy — the shape both GET and PUT return."""

    mode: str = Field(
        ..., description="Effective mode: 'open', 'invite_only' or 'closed'."
    )
    allowed_email_domains: List[str] = Field(
        default_factory=list,
        description=(
            "Email domains allowed to sign up while the mode is 'open'. Empty means any domain."
        ),
    )
    blocked_email_domains: List[str] = Field(
        default_factory=list,
        description=(
            "Extra email domains refused for email sign-up, on top of the disposable-email list "
            "the UI bundles. Empty when none are stored. Never applied to provider sign-up."
        ),
    )
    source: str = Field(
        ...,
        description=(
            "'db' when the policy is stored in the database; 'env' when none is stored and "
            "AUTH_SIGNUP_DISABLED governs."
        ),
    )
    env_mode: str = Field(
        ...,
        description=(
            "The mode the env fallback gives ('closed' when AUTH_SIGNUP_DISABLED is true, else "
            "'open') — what applies if the stored policy is cleared."
        ),
    )
    updated_at: Optional[datetime] = Field(
        None, description="When the stored policy was last changed; null when none is stored."
    )
    updated_by: Optional[str] = Field(
        None, description="Who last changed the stored policy; null when none is stored."
    )


class SignupPolicyUpdateRequest(BaseModel):
    """Body of ``PUT /v1/admin/signup-policy``.

    The policy is replaced as a whole: send the mode and the full domain list every time.
    """

    mode: Optional[str] = Field(
        ...,
        description=(
            "'open', 'invite_only' or 'closed' to store the policy; null to clear the stored "
            "policy so the installation reverts to AUTH_SIGNUP_DISABLED."
        ),
    )
    allowed_email_domains: List[str] = Field(
        default_factory=list,
        description=(
            "Email domains allowed to sign up while the mode is 'open' (e.g. 'example.com'). "
            f"At most {MAX_ALLOWED_EMAIL_DOMAINS}; matched exactly, so list subdomains "
            "separately. Ignored when mode is null."
        ),
    )
    blocked_email_domains: List[str] = Field(
        default_factory=list,
        description=(
            "Extra email domains refused for email sign-up (e.g. 'throwaway.example'), on top of "
            f"the bundled disposable-email list. At most {MAX_BLOCKED_EMAIL_DOMAINS}; a listed "
            "domain also blocks its subdomains. Omitted ⇒ none. Ignored when mode is null."
        ),
    )


class BlockedSignupAttempt(BaseModel):
    """One sign-up attempt an abuse guard refused (SGN-1.5)."""

    id: str = Field(..., description="The auth_events row id.")
    created_at: datetime = Field(..., description="When the attempt was refused.")
    guard: str = Field(
        ..., description="Which guard refused it: 'rate_limit', 'disposable_domain' or 'captcha'."
    )
    scope: Optional[str] = Field(
        None,
        description=(
            "For rate limits: 'ip' (too many attempts from one client) or 'address' (too many "
            "emails to one address). Null for the other guards."
        ),
    )
    error_code: Optional[str] = Field(None, description="The stable code the person was shown.")
    provider: Optional[str] = Field(
        None, description="'email' for the email form, else the sign-in provider slug."
    )
    email: Optional[str] = Field(
        None, description="The address the attempt carried; null when it was refused before one was read."
    )
    client: Optional[str] = Field(
        None,
        description=(
            "The first 12 characters of the salted client-IP digest, to tell repeat clients apart. "
            "Never a raw address."
        ),
    )


class BlockedSignupAttemptList(BaseModel):
    """Payload of ``GET /v1/admin/signup-policy/blocked-attempts``."""

    attempts: List[BlockedSignupAttempt] = Field(default_factory=list)


def _policy_view(row: Optional[Mapping[str, Any]]) -> SignupPolicyView:
    """Build the response view from the stored row (or its absence).

    Args:
        row: The stored ``apiome.signup_policy`` row, or None when no policy is stored.

    Returns:
        The effective policy — the stored one, else the env fallback — with its provenance.
    """
    env_policy = signup_policy_from_env()
    stored = signup_policy_from_row(row)
    if stored is None:
        return SignupPolicyView(
            mode=env_policy.mode,
            allowed_email_domains=[],
            blocked_email_domains=[],
            source=SOURCE_ENV,
            env_mode=env_policy.mode,
        )
    return SignupPolicyView(
        mode=stored.mode,
        allowed_email_domains=list(stored.allowed_email_domains),
        blocked_email_domains=list(stored.blocked_email_domains),
        source=SOURCE_DB,
        env_mode=env_policy.mode,
        updated_at=row.get("updated_at") if row else None,
        updated_by=row.get("updated_by") if row else None,
    )


@router.get(
    "",
    response_model=SignupPolicyView,
    responses={
        401: {"description": "No super-admin session presented."},
        403: {"description": "Super-admin session invalid or expired."},
    },
)
async def get_signup_policy(_: None = Depends(require_super_admin)) -> SignupPolicyView:
    """Read the installation sign-up policy (SGN-1.4).

    Reads the stored row directly rather than the cached policy, so the admin console always shows
    what is actually stored.

    Returns:
        The effective policy, with ``source`` telling a stored policy from the env fallback.
    """
    return _policy_view(db.get_signup_policy())


@router.put(
    "",
    response_model=SignupPolicyView,
    responses={
        401: {"description": "No super-admin session presented."},
        403: {"description": "Super-admin session invalid or expired."},
        422: {"description": "Unknown mode, or an invalid or over-long email-domain list."},
    },
)
async def update_signup_policy(
    payload: SignupPolicyUpdateRequest,
    _: None = Depends(require_super_admin),
) -> SignupPolicyView:
    """Store, change or clear the installation sign-up policy (SGN-1.4).

    The change is audited and applies to the next sign-up on this instance; other instances apply
    it within the policy cache lifetime. It gates creating an account only — existing users keep
    signing in under every mode.

    Args:
        payload: The new policy, or ``mode: null`` to clear the stored one.

    Returns:
        The effective policy after the write.

    Raises:
        HTTPException: ``422`` with a structured body when the mode is not one of the three modes
            (``invalid_mode``) or a domain entry is malformed (``invalid_email_domain``).
    """
    if payload.mode is None:
        db.set_signup_policy(None, [], updated_by=_ACTOR)
        invalidate_signup_policy_cache()
        logger.info("super-admin cleared the stored sign-up policy (env governs)")
        return _policy_view(None)

    if payload.mode not in SIGNUP_MODES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_mode",
                "message": f"mode must be one of: {', '.join(SIGNUP_MODES)}.",
            },
        )
    try:
        domains = normalize_allowed_email_domains(payload.allowed_email_domains)
        blocked = normalize_allowed_email_domains(
            payload.blocked_email_domains, limit=MAX_BLOCKED_EMAIL_DOMAINS
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_email_domain", "message": str(exc)},
        ) from exc

    row = db.set_signup_policy(
        payload.mode, list(domains), updated_by=_ACTOR, blocked_email_domains=list(blocked)
    )
    invalidate_signup_policy_cache()
    logger.info(
        "super-admin set the sign-up policy: mode=%s allowed_email_domains=%d "
        "blocked_email_domains=%d",
        payload.mode,
        len(domains),
        len(blocked),
    )
    return _policy_view(row)


#: Default and maximum number of blocked attempts one read returns.
DEFAULT_BLOCKED_ATTEMPTS_LIMIT = 50
MAX_BLOCKED_ATTEMPTS_LIMIT = 200


@router.get(
    "/blocked-attempts",
    response_model=BlockedSignupAttemptList,
    responses={
        401: {"description": "No super-admin session presented."},
        403: {"description": "Super-admin session invalid or expired."},
    },
)
async def list_blocked_signup_attempts(
    limit: int = Query(
        DEFAULT_BLOCKED_ATTEMPTS_LIMIT,
        ge=1,
        le=MAX_BLOCKED_ATTEMPTS_LIMIT,
        description="How many attempts to return, newest first.",
    ),
    _: None = Depends(require_super_admin),
) -> BlockedSignupAttemptList:
    """List the sign-up attempts an abuse guard refused, newest first (SGN-1.5, #5654).

    Reads the failed ``sign_up`` rows of ``apiome.auth_events`` that carry a ``detail.guard``.
    Sign-up happens before any workspace exists, so this is an installation view for super-admins,
    not part of a workspace's access audit.

    Args:
        limit: How many attempts to return (1–200).

    Returns:
        The attempts, newest first.
    """
    rows = db.list_signup_guard_events(limit=limit)
    return BlockedSignupAttemptList(
        attempts=[
            BlockedSignupAttempt(
                id=row["id"],
                created_at=row["created_at"],
                guard=row.get("guard") or "unknown",
                scope=row.get("scope"),
                error_code=row.get("error_code"),
                provider=row.get("provider"),
                email=row.get("user_label"),
                client=(row.get("ip_hash") or "")[:12] or None,
            )
            for row in rows
        ]
    )
