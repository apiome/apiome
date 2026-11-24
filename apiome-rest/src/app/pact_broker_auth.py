"""Authentication for the Pact Broker surface — PFX-1.2 (#6915).

The rest of the API reads a workspace API key from ``X-API-Key``. Pact tooling cannot send that
header: the ``pact-broker`` CLI and the Pact libraries present their one credential as
``Authorization: Bearer <token>``. So on these routes — and only on these — a bearer token that is
not a session token is tried as a workspace API key.

Nothing else changes: the key is validated by :func:`app.auth.validate_authentication`, must belong
to the tenant in the URL, and a restricted key is still held to its scope allowlist. Basic
authentication and Pact-specific key scopes are PFX-4.2 (#6939).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, Request

from .auth import validate_authentication

__all__ = ["validate_broker_authentication"]


def _bearer_api_key(authorization: Optional[str]) -> Optional[str]:
    """Return a bearer token that can only be an API key, or ``None``.

    A session token is a JWT — three dot-separated parts — and an API key has no dot, so the two
    are told apart by shape without verifying either.

    Args:
        authorization: The ``Authorization`` header.

    Returns:
        The token when the header is ``Bearer <token>`` and the token is not JWT-shaped.
    """
    scheme, _, token = (authorization or "").strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or token.count(".") == 2:
        return None
    return token


def validate_broker_authentication(
    request: Request,
    tenant_slug: str,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Authenticate a Pact Broker request: a session, ``X-API-Key``, or an API key as bearer token.

    Args:
        request: The incoming request.
        tenant_slug: The tenant in the URL.
        authorization: The ``Authorization`` header.
        x_api_key: The ``X-API-Key`` header.

    Returns:
        The auth context of :func:`app.auth.validate_authentication`.

    Raises:
        HTTPException: 401 without a valid credential, 403 when it belongs to another tenant or a
            restricted key's scopes do not allow the request.
    """
    bearer_key = None if x_api_key else _bearer_api_key(authorization)
    if bearer_key:
        return validate_authentication(request, tenant_slug, None, bearer_key)
    return validate_authentication(request, tenant_slug, authorization, x_api_key)
