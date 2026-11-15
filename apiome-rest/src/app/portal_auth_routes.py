"""``/v1/portal/{tenant_slug}/auth`` — reader sign-in for Browse, PCX-1.1 (#5889).

Four routes, tag ``portal-auth``:

* ``POST …/magic-link`` — mail a one-time sign-in link. **Always ``202``** for a well-formed request,
  whether or not a link was sent, so the route cannot be used to learn who has an account. Budgeted
  per address and per client address (``429 portal-rate-limited`` with ``Retry-After``). Browse calls
  it **from the reader's browser**, so the per-address budget sees the reader's own address rather
  than the Browse server's.
* ``POST …/exchange`` — trade the link's token for a reader session (the token is burned). Browse's
  server calls it, sets the ``HttpOnly`` cookie, and forwards the reader's ``User-Agent`` so the
  session records the browser family.
* ``POST …/sign-out`` — revoke the session in ``Authorization: Reader <token>``. Idempotent.
* ``GET …/me`` — the signed-in reader, or ``401 portal-session-invalid``.

The two that hash or mail are plain ``def`` routes, so FastAPI runs them in its thread pool and a
slow bcrypt or SendGrid call never blocks the event loop.

None of them accept a JWT or an API key, and a reader session is accepted nowhere outside these
routes and the ``browse`` tag (see :mod:`app.portal_auth`).
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response

from . import portal_auth_store
from .config import settings
from .portal_auth import (
    CODE_INVALID_EMAIL,
    CODE_INVALID_RETURN_TO,
    CODE_RATE_LIMITED,
    CODE_SESSION_INVALID,
    CODE_TOKEN_EXPIRED,
    CODE_TOKEN_INVALID,
    CODE_TOKEN_USED,
    READER_SCHEME,
    MagicLinkAccepted,
    MagicLinkRequest,
    PortalAuthError,
    ReaderProfile,
    ReaderSessionGrant,
    TokenExchange,
    normalize_email,
    reader_token_from_header,
)
from .portal_mail import default_reader_mailer
from .rate_limit import FixedWindowRateLimiter, _client_ip
from .signup_policy import get_effective_signup_policy, signup_rejection_code

__all__ = ["router"]

router = APIRouter(prefix="/v1/portal", tags=["portal-auth"])

_BASE = "/{tenant_slug}/auth"

#: A refusal maps onto the HTTP status of its kind.
_STATUS_BY_CODE = {
    CODE_INVALID_EMAIL: 422,
    CODE_INVALID_RETURN_TO: 422,
    CODE_TOKEN_INVALID: 400,
    CODE_TOKEN_EXPIRED: 410,
    CODE_TOKEN_USED: 410,
    CODE_SESSION_INVALID: 401,
}

_magic_link_limiter = FixedWindowRateLimiter()


def _http_error(exc: PortalAuthError) -> HTTPException:
    """Translate a store refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` to raise, always carrying ``{"code", "message"}``.
    """
    headers = (
        {"WWW-Authenticate": READER_SCHEME} if exc.code == CODE_SESSION_INVALID else None
    )
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
        headers=headers,
    )


def _enforce_budget(bucket_key: str, limit: int) -> None:
    """Record one magic-link request against a budget, refusing when it is spent.

    Args:
        bucket_key: The namespaced limiter key.
        limit: Requests allowed per window (clamped to at least 1).

    Raises:
        HTTPException: ``429 portal-rate-limited`` with ``Retry-After`` and ``X-RateLimit-*``.
    """
    effective = max(1, limit)
    window_seconds = max(1, settings.rate_limit_window_seconds)
    allowed, remaining, reset_after, retry_after = _magic_link_limiter.check(
        bucket_key, effective, window_seconds, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": CODE_RATE_LIMITED,
                "message": "Too many sign-in requests. Wait a moment and try again.",
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(effective),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_after),
            },
        )


def enforce_magic_link_rate_limit(request: Request, tenant_slug: str, email: str) -> None:
    """Apply the per-client-address and per-email magic-link budgets (SGN-1.5 pattern).

    The email budget is keyed per tenant, so one portal's traffic cannot exhaust another's. Does
    nothing while the global ``rate_limit_enabled`` kill switch is off.

    Args:
        request: The inbound request (its direct peer address is the IP key).
        tenant_slug: The portal.
        email: The normalized address.

    Raises:
        HTTPException: ``429 portal-rate-limited``.
    """
    if not settings.rate_limit_enabled:
        return
    _enforce_budget(f"portalip:{_client_ip(request)}", settings.portal_magic_link_rate_limit_ip_per_minute)
    _enforce_budget(
        f"portalmail:{tenant_slug}:{email}", settings.portal_magic_link_rate_limit_email_per_minute
    )


def _signup_rejection(email: str) -> Optional[str]:
    """The installation sign-up policy's refusal for creating an account at ``email``."""
    return signup_rejection_code(get_effective_signup_policy(), email)


@router.post(
    f"{_BASE}/magic-link",
    response_model=MagicLinkAccepted,
    status_code=202,
    summary="Send a reader sign-in link",
    description=(
        "Mail a one-time sign-in link for the tenant's Browse portal. The link expires in 15 "
        "minutes and works once.\n\n"
        "An address with no account gets one (a password-less user) and an `invited` reader "
        "membership, when the installation sign-up policy allows new accounts; a second request "
        "for the same address reuses both.\n\n"
        "**Always `202`** for a well-formed request: the response never says whether a link was "
        "sent, so it cannot be used to discover accounts. `422` for a malformed address or a "
        "`return_to` that is not a path inside Browse. Budgeted per client address and per email "
        "address (`429 portal-rate-limited` with `Retry-After`).\n\n"
        "No authentication."
    ),
)
def request_magic_link(
    tenant_slug: str, body: MagicLinkRequest, request: Request
) -> MagicLinkAccepted:
    """Mail a sign-in link.

    Args:
        tenant_slug: The portal.
        body: The address and optional ``return_to``.
        request: The inbound request (rate-limit key).

    Returns:
        ``{"accepted": true}`` — always, for well-formed input.

    Raises:
        HTTPException: 422 for malformed input, 429 over a budget.
    """
    try:
        email = normalize_email(body.email)
        enforce_magic_link_rate_limit(request, tenant_slug, email)
        portal_auth_store.request_magic_link(
            portal_auth_store.default_repository(),
            default_reader_mailer(),
            tenant_slug=tenant_slug,
            email=email,
            return_to=body.return_to,
            browse_url=settings.public_browse_url,
            signup_rejection=_signup_rejection,
        )
    except PortalAuthError as exc:
        raise _http_error(exc) from exc
    return MagicLinkAccepted()


@router.post(
    f"{_BASE}/exchange",
    response_model=ReaderSessionGrant,
    summary="Exchange a sign-in link for a reader session",
    description=(
        "Trade a magic-link token for a reader session. The token is burned: a second exchange is "
        "`410 portal-token-used`, an exchange after 15 minutes `410 portal-token-expired`, and an "
        "unknown or malformed token `400 portal-token-invalid`.\n\n"
        "The session token is returned **once**. It is bound to this tenant and is sent back as "
        "`Authorization: Reader <token>`; it is accepted only by the `portal-auth` and `browse` "
        "routes. The request's `User-Agent` is reduced to a browser family before it is stored.\n\n"
        "No authentication — the token is the credential."
    ),
)
def exchange_magic_link(
    tenant_slug: str,
    body: TokenExchange,
    user_agent: Optional[str] = Header(default=None),
) -> ReaderSessionGrant:
    """Exchange a token for a session.

    Args:
        tenant_slug: The portal named in the link.
        body: The token.
        user_agent: The reader's ``User-Agent``.

    Returns:
        The session grant.

    Raises:
        HTTPException: 400 / 410 with the refusal code.
    """
    try:
        return portal_auth_store.exchange_token(
            portal_auth_store.default_repository(),
            tenant_slug=tenant_slug,
            token=body.token,
            user_agent=user_agent,
            session_ttl=timedelta(hours=settings.portal_reader_session_ttl_hours),
        )
    except PortalAuthError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/sign-out",
    status_code=204,
    summary="Sign a reader out",
    description=(
        "Revoke the reader session in `Authorization: Reader <token>`. The session is refused from "
        "the next request on. Idempotent: an unknown or already revoked session is also `204`."
    ),
)
async def sign_out(tenant_slug: str, authorization: Optional[str] = Header(default=None)) -> Response:
    """Revoke the caller's session.

    Args:
        tenant_slug: The portal (the session's own tenant is what is revoked).
        authorization: ``Reader <token>``.

    Returns:
        An empty 204.
    """
    _ = tenant_slug
    portal_auth_store.revoke_session(
        portal_auth_store.default_repository(), reader_token_from_header(authorization)
    )
    return Response(status_code=204)


@router.get(
    f"{_BASE}/me",
    response_model=ReaderProfile,
    summary="The signed-in reader",
    description=(
        "The reader behind `Authorization: Reader <token>`: their address, the tenant the session "
        "is bound to, and when the session ends.\n\n"
        "`401 portal-session-invalid` for a missing, expired or revoked session, a session for "
        "another tenant, or a reader whose membership was revoked."
    ),
)
async def read_me(tenant_slug: str, authorization: Optional[str] = Header(default=None)) -> ReaderProfile:
    """Return the signed-in reader.

    Args:
        tenant_slug: The portal; must be the session's tenant.
        authorization: ``Reader <token>``.

    Returns:
        The reader profile.

    Raises:
        HTTPException: 401 ``portal-session-invalid``.
    """
    try:
        session = portal_auth_store.resolve_session(
            portal_auth_store.default_repository(), reader_token_from_header(authorization)
        )
    except PortalAuthError as exc:
        raise _http_error(exc) from exc
    if session.tenant_slug != tenant_slug:
        raise _http_error(PortalAuthError(CODE_SESSION_INVALID, "Sign in again to continue."))
    return session.profile
