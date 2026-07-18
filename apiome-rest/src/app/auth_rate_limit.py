"""Dedicated rate limiting for the authentication surface (OLO-7.1, #4223).

The onboarding endpoints (``/v1/onboarding/*``) complete signup (first-tenant
provisioning) and invited-member activation, which makes them abuse targets
beyond generic API traffic. On top of the global :mod:`app.rate_limit`
middleware they carry two tighter budgets:

* **Per-IP** — ``auth_rate_limit_ip_per_minute``, enforced as a router
  dependency *before* session validation, so an unauthenticated flood is cut
  off without touching the session/DB layer.
* **Per-account** — ``auth_rate_limit_account_per_minute``, enforced once the
  caller's user id is known, so a single account cannot spray provisioning
  calls from many addresses.

Both budgets reuse the global fixed window (``rate_limit_window_seconds``) and
the global ``rate_limit_enabled`` kill switch — which also keeps the existing
test-suite neutralization pattern working (``tests/conftest.py`` flips that one
flag off for route tests).

Over-limit requests get a structured ``429`` (stable code
:data:`AUTH_RATE_LIMITED_CODE`) with ``Retry-After`` and ``X-RateLimit-*``
headers, matching the public-export guard (:mod:`app.public_export_guards`).
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request

from .config import settings
from .rate_limit import FixedWindowRateLimiter, _client_ip

# Stable error code carried in the structured 429 detail so clients (and the
# auth error contract, OLO-1.5) can key their handling off it.
AUTH_RATE_LIMITED_CODE = "auth-rate-limited"

_auth_limiter = FixedWindowRateLimiter()


def _enforce_budget(bucket_key: str, limit: int) -> None:
    """Record a hit on ``bucket_key`` and raise a structured 429 when over ``limit``.

    Args:
        bucket_key: Namespaced limiter key (``authip:...`` / ``authacct:...``).
        limit: Max requests allowed per window (clamped to at least 1).

    Raises:
        HTTPException: ``429`` with the stable ``auth-rate-limited`` code plus
            ``Retry-After`` / ``X-RateLimit-*`` headers when the budget is spent.
    """
    effective_limit = max(1, limit)
    window_seconds = max(1, settings.rate_limit_window_seconds)
    allowed, remaining, reset_after, retry_after = _auth_limiter.check(
        bucket_key, effective_limit, window_seconds, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": AUTH_RATE_LIMITED_CODE,
                "message": "Too many authentication requests. Slow down and retry later.",
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(effective_limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_after),
            },
        )


def enforce_auth_ip_rate_limit(request: Request) -> None:
    """FastAPI dependency: per-IP budget for the auth surface.

    Runs before session validation (router-level dependency), so brute-force
    floods are refused without a DB hit.

    Args:
        request: The inbound HTTP request; its direct peer address is the key.

    Raises:
        HTTPException: ``429`` when this client IP exhausted its window.
    """
    if not settings.rate_limit_enabled:
        return
    _enforce_budget(
        f"authip:{_client_ip(request)}", settings.auth_rate_limit_ip_per_minute
    )


def enforce_auth_account_rate_limit(user_id: str) -> None:
    """Per-account budget for the auth surface; call once the user id is known.

    Args:
        user_id: The authenticated caller's user id (bucket key). A falsy id is
            a no-op — the endpoint's own 401 handling covers that case.

    Raises:
        HTTPException: ``429`` when this account exhausted its window.
    """
    if not settings.rate_limit_enabled or not user_id:
        return
    _enforce_budget(
        f"authacct:{user_id}", settings.auth_rate_limit_account_per_minute
    )
