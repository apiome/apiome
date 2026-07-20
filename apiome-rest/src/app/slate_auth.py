"""Tenant resolution for the Slate routers — UXE-3.1 (private-suite#2473).

``validate_authentication`` in :mod:`app.auth` declares ``tenant_slug: str`` with no default.
Every other router satisfies that by carrying ``{tenant_slug}`` in its path, so FastAPI binds
it as a path parameter. The Slate routers deliberately do not: tenancy comes from the JWT, and
the BFF proxy in both UIs says so outright — putting the slug in the URL would hand the browser
a value it has no reason to know, and would let a caller name a tenant the token was not issued
for.

FastAPI has no way to know that intent. With no path parameter of that name it binds
``tenant_slug`` as a **required query parameter**, so every ``/v1/slate/*`` call without
``?tenant_slug=`` answers 422 before any authentication logic runs. The existing route tests
never caught it because they replace the dependency wholesale
(``app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)``), which
substitutes exactly the signature that is wrong.

**This module resolves the slug; it does not re-implement authorization.** Once a slug is in
hand it delegates to the unchanged :func:`app.auth.validate_authentication`, so membership
checks, administrator fallback, API-key scope allowlisting and the 403/404 distinction all
still run in one place. A second copy of auth that drifted from the first would be worse than
the bug it replaced.

The resolved slug is only a *lookup key*. Authorization is still
``validate_user_tenant_access``, so a forged ``current_tenant_id`` buys nothing: it resolves to
a tenant the caller is then refused access to.

Scope: the Slate routers only. Changing ``validate_authentication`` itself would touch roughly
forty routers to fix two, which is a regression surface this ticket has no reason to open.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Query, Request

from .auth import decode_jwt, validate_authentication
from .database import db

__all__ = ["resolve_slate_tenant_slug", "validate_slate_authentication"]


def resolve_slate_tenant_slug(
    *,
    explicit_slug: Optional[str],
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> Optional[str]:
    """Work out which tenant a Slate request is for.

    Resolution order, each step present for a reason:

    1. An explicit ``?tenantSlug=`` when supplied. CLI and API-key callers keep a direct path,
       and the value stays the one authorization is checked against rather than a hint.
    2. The JWT's ``current_tenant_id`` claim, resolved to a slug. This is the browser path:
       the token already carries the tenant, so the URL does not have to.
    3. The API key's own tenant. A key belongs to exactly one tenant, so there is nothing to
       choose.

    Args:
        explicit_slug: Value of the ``tenantSlug`` query parameter, if any.
        authorization: ``Authorization`` header, if any.
        x_api_key: ``X-API-Key`` header, if any.

    Returns:
        The tenant slug, or ``None`` when no credential identifies one. Callers turn ``None``
        into 401 rather than guessing a default tenant.
    """
    if explicit_slug:
        return explicit_slug

    if authorization:
        payload = decode_jwt(authorization)
        if payload:
            tenant_id = payload.get("current_tenant_id")
            if tenant_id:
                row = db.get_active_tenant_auth_row_by_id(str(tenant_id))
                if row:
                    return row["tenant_slug"]

    if x_api_key:
        key_row = db.validate_api_key(x_api_key)
        if key_row and key_row.get("tenant_slug"):
            return key_row["tenant_slug"]

    return None


def validate_slate_authentication(
    request: Request,
    tenant_slug: Optional[str] = Query(
        None,
        alias="tenantSlug",
        description=(
            "Tenant slug. Optional: the Slate routes read tenancy from the credential, so a "
            "browser call carrying a session JWT does not need to name a tenant in the URL."
        ),
    ),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Authenticate a ``/v1/slate/*`` request without requiring a slug in the URL.

    Args:
        request: Incoming request, forwarded to the shared validator for API-key scope
            allowlisting.
        tenant_slug: Optional explicit ``tenantSlug`` query parameter.
        authorization: ``Authorization`` header (Bearer token).
        x_api_key: ``X-API-Key`` header.

    Returns:
        The same auth dict :func:`app.auth.validate_authentication` returns, so downstream
        ``auth_data["tenant_id"]`` reads and ``enforce_permission`` calls are unchanged.

    Raises:
        HTTPException: 401 when no credential identifies a tenant, and whatever the shared
            validator raises otherwise — 403 for a tenant the caller cannot reach, 404 for one
            that does not exist.
    """
    resolved = resolve_slate_tenant_slug(
        explicit_slug=tenant_slug,
        authorization=authorization,
        x_api_key=x_api_key,
    )
    if not resolved:
        raise HTTPException(
            status_code=401,
            detail=(
                "Authentication required. Provide a session token whose tenant claim names a "
                "tenant, an API key, or an explicit tenantSlug."
            ),
        )

    return validate_authentication(
        request=request,
        tenant_slug=resolved,
        authorization=authorization,
        x_api_key=x_api_key,
    )


#: Dependency alias, so routers read as ``Depends(slate_auth_dependency)`` at the call site.
slate_auth_dependency = Depends(validate_slate_authentication)
