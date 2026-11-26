"""Authentication for the Pact Broker surface — PFX-1.2 (#6915), PFX-4.2 (#6939).

The rest of the API reads a workspace API key from ``X-API-Key``. Pact tooling cannot send that
header: the ``pact-broker`` CLI and the Pact libraries present their one credential either as
``Authorization: Bearer <token>`` (``--broker-token``, ``PACT_BROKER_TOKEN``) or as HTTP basic auth
(``--broker-username`` / ``--broker-password``, ``PACT_BROKER_USERNAME`` / ``PACT_BROKER_PASSWORD``).
So on these routes — and only on these — both are mapped onto a workspace API key:

* **Bearer** — a token that is not session-shaped (a JWT has three dot-separated parts, an API key
  none) is the API key.
* **Basic** — the **password** is the API key; the username is ignored, as the schema registry
  does (CDG-4.3). Basic auth without a password, or not well-formed, is refused with the reason.
* Any other ``Authorization`` scheme is refused with the reason instead of being ignored.

Nothing else changes: the key is validated by :func:`app.auth.validate_authentication`, must belong
to the tenant in the URL, and a restricted key is held to its scope allowlist — the Pact scopes
``pact:read`` / ``pact:publish`` / ``pact:verify`` (:mod:`app.auth`). The route's RBAC check on the
``pacts`` resource applies to the key's user on top of that.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

from .auth import api_key_from_basic, validate_authentication

__all__ = ["validate_broker_authentication"]

#: The challenge a Pact Broker 401 carries: either credential form works.
BROKER_CHALLENGE = 'Bearer, Basic realm="apiome-pact-broker"'

#: ``Authorization`` schemes this surface reads. ``Reader`` (Browse sessions) is deliberately absent.
_SUPPORTED_SCHEMES = ("bearer", "basic")


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


def _refuse(detail: str) -> HTTPException:
    """A 401 with the broker challenge.

    Args:
        detail: Why the credential was refused — never the credential itself.

    Returns:
        The exception to raise.
    """
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": BROKER_CHALLENGE})


def _basic_api_key(authorization: str) -> str:
    """Return the API key carried by a basic ``Authorization`` value.

    Args:
        authorization: A header whose scheme is ``Basic``.

    Returns:
        The password, which is the API key.

    Raises:
        HTTPException: 401 when the value is not base64 ``<name>:<password>`` or the password is
            empty — the message says where the key goes.
    """
    key = api_key_from_basic(authorization)
    if key is None:
        raise _refuse(
            "Malformed basic auth credentials: send the workspace API key as the password "
            "(<any-name>:<api-key>, e.g. --broker-username apiome --broker-password <api-key>); "
            "the username is ignored"
        )
    return key


def validate_broker_authentication(
    request: Request,
    tenant_slug: str,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Authenticate a Pact Broker request: a session, ``X-API-Key``, or an API key as bearer / basic.

    ``X-API-Key`` wins when it is sent; otherwise the ``Authorization`` header is read as described
    in the module docstring.

    Args:
        request: The incoming request.
        tenant_slug: The tenant in the URL.
        authorization: The ``Authorization`` header.
        x_api_key: The ``X-API-Key`` header.

    Returns:
        The auth context of :func:`app.auth.validate_authentication`.

    Raises:
        HTTPException: 401 without a valid credential, for malformed basic auth or an unsupported
            scheme; 403 when the key belongs to another tenant or its scopes do not allow the request.
    """
    if x_api_key:
        return validate_authentication(request, tenant_slug, authorization, x_api_key)
    header = (authorization or "").strip()
    if not header:
        return validate_authentication(request, tenant_slug, None, None)
    scheme, space, _ = header.partition(" ")
    if not space:
        # Never echo the value: a bare header is most likely the key itself.
        raise _refuse(
            "The Authorization header has no scheme: send 'Bearer <api-key>', basic auth with the "
            "key as the password, or X-API-Key"
        )
    if scheme.lower() not in _SUPPORTED_SCHEMES:
        raise _refuse(
            f"Unsupported Authorization scheme {scheme!r}: send the workspace API key as "
            "'Bearer <api-key>', as basic auth with the key as the password, or as X-API-Key"
        )
    if scheme.lower() == "basic":
        return validate_authentication(request, tenant_slug, None, _basic_api_key(header))
    bearer_key = _bearer_api_key(header)
    if bearer_key:
        return validate_authentication(request, tenant_slug, None, bearer_key)
    return validate_authentication(request, tenant_slug, header, None)
