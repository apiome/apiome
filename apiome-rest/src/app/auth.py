"""
Authentication module for JWT and API Key validation.

Supports both JWT tokens (from NextAuth) and API keys for authentication.
"""

import logging
import uuid
import jwt
from typing import Optional, Dict, Any
from fastapi import HTTPException, Header

from .config import settings
from .database import db

logger = logging.getLogger(__name__)

# PyJWT exposes these on the main `jwt` package; avoid `import jwt.exceptions` (fails for some
# vendor/layout installs and for the obsolete PyPI `jwt` package which is not PyJWT).
_ExpiredSignatureError = getattr(jwt, "ExpiredSignatureError", None)
_InvalidTokenError = getattr(jwt, "InvalidTokenError", None)
if _ExpiredSignatureError is None or _InvalidTokenError is None:
    raise ImportError(
        'Install PyJWT for apiome-rest (e.g. pip install "PyJWT>=2.8"). '
        "If the unrelated `jwt` package is installed, remove it: pip uninstall jwt"
    )


def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token to decode

    Returns:
        Decoded token payload if valid, None otherwise
    """
    try:
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token[7:]

        # Decode the JWT
        payload = jwt.decode(
            token,
            settings.effective_jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )

        return payload
    except _ExpiredSignatureError:
        logger.warning("decode_jwt: Token expired")
        return None
    except _InvalidTokenError as e:
        logger.warning(f"decode_jwt: Invalid token - {e}")
        return None
    except Exception as e:
        logger.error(f"decode_jwt: Exception - {e}", exc_info=True)
        return None


def normalize_user_id(value: Any) -> Optional[str]:
    """Return canonical UUID string for DB lookups, or None when invalid."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return None


def get_user_tenants(user_id: str) -> list[Dict[str, Any]]:
    """
    Get all tenants that a user belongs to (member or administrator).

    Args:
        user_id: The user's ID

    Returns:
        List of tenant dictionaries with id, slug, and name
    """
    uid = normalize_user_id(user_id)
    if not uid:
        return []
    query = """
        SELECT DISTINCT t.id, t.slug, t.name
        FROM apiome.tenants t
        INNER JOIN (
            SELECT tenant_id FROM apiome.tenant_users WHERE user_id = %s::uuid
            UNION
            SELECT tenant_id FROM apiome.tenant_administrators WHERE user_id = %s::uuid
        ) access ON access.tenant_id = t.id
        WHERE t.deleted_at IS NULL
        ORDER BY t.slug ASC
    """
    return db.execute_query(query, (uid, uid))


def validate_user_tenant_access(user_id: str, tenant_slug: str) -> Optional[Dict[str, Any]]:
    """
    Validate that a user has access to a specific tenant.

    Access is granted for ``tenant_users`` membership or ``tenant_administrators`` role.

    Args:
        user_id: The user's ID from JWT
        tenant_slug: The tenant slug from the URL

    Returns:
        Tenant information if user has access, None if tenant missing or access denied
    """
    uid = normalize_user_id(user_id)
    if not uid:
        logger.warning("validate_user_tenant_access: invalid user_id=%r", user_id)
        return None

    tenant = db.get_active_tenant_auth_row(tenant_slug)
    if not tenant:
        logger.warning("Tenant not found: %s", tenant_slug)
        return None

    tenant_id = tenant["tenant_id"]
    if not db.user_has_tenant_access(uid, tenant_id):
        logger.warning("User %s does not have access to tenant %s", uid, tenant_id)
        return None

    logger.debug(
        "validate_user_tenant_access called with user_id=%s, tenant_slug=%s - Authorized",
        uid,
        tenant_slug,
    )
    return tenant


def validate_authentication(
    tenant_slug: str,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> Dict[str, Any]:
    """
    Validate authentication using either JWT token or API key.

    Supports two authentication methods:
    1. JWT token in Authorization header (from NextAuth)
    2. API key in X-API-Key header

    Args:
        tenant_slug: The requested tenant slug
        authorization: Authorization header (Bearer token)
        x_api_key: API key header

    Returns:
        Dict with tenant information and authentication details

    Raises:
        HTTPException: If authentication fails or user doesn't have access to tenant
    """
    # Try JWT authentication first
    if authorization:
        jwt_payload = decode_jwt(authorization)

        if jwt_payload:
            # Extract user_id from JWT
            # NextAuth stores this in the 'sub' claim or 'user_id' custom claim
            user_id = jwt_payload.get('user_id') or jwt_payload.get('sub')

            if not user_id:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid JWT token: missing user identifier"
                )

            tenant_row = db.get_active_tenant_auth_row(tenant_slug)
            if not tenant_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Tenant not found: {tenant_slug}",
                )

            tenant_data = validate_user_tenant_access(user_id, tenant_slug)

            if not tenant_data:
                raise HTTPException(
                    status_code=403,
                    detail=f"User does not have access to tenant: {tenant_slug}"
                )

            # Return tenant data with user information
            return {
                **tenant_data,
                'auth_method': 'jwt',
                'user_id': user_id,
                'user_email': jwt_payload.get('email'),
                'user_name': jwt_payload.get('name')
            }

    # Try API key authentication
    if x_api_key:
        api_key_data = db.validate_api_key(x_api_key)

        if not api_key_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "API-Key"}
            )

        # Check if the API key's tenant matches the requested tenant
        if api_key_data['tenant_slug'] != tenant_slug:
            raise HTTPException(
                status_code=403,
                detail="API key does not have access to this tenant"
            )

        uid = api_key_data.get("created_by_user_id")
        return {
            **api_key_data,
            "auth_method": "api_key",
            "user_id": uid,
        }

    # No authentication provided
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide either JWT token (Authorization: Bearer <token>) or API key (X-API-Key: <key>)",
        headers={"WWW-Authenticate": "Bearer, API-Key"}
    )


def get_authenticated_user_id(auth_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract user ID for attributing creates/updates (project creator_id, version creator_id, …).

    JWT: ``user_id`` from the token.
    API key: ``user_id`` from ``api_keys.created_by_user_id`` when set; otherwise the first tenant
    administrator, else the first tenant member (legacy keys without ``created_by_user_id``).
    """
    raw = auth_data.get("user_id")
    if raw is not None and str(raw).strip() != "":
        return str(raw)
    if auth_data.get("auth_method") == "api_key":
        tid = auth_data.get("tenant_id")
        if tid is not None and str(tid).strip() != "":
            return db.get_fallback_creator_user_id_for_tenant(str(tid))
    return None


def require_tenant_admin_session(
    db_handle: Any,
    auth_data: Dict[str, Any],
    *,
    detail: str = "Only tenant administrators can perform this action",
) -> str:
    """Require a signed-in tenant administrator; reject API-key auth (MTG-3.4, #4778).

    Governance mutations (MCP policy, MCP keys, style guides) are the
    buyer-admin persona's surface. An ``X-API-Key`` / publish key must not
    escalate by resolving ``created_by`` (or the tenant fallback admin) into
    ``is_user_tenant_admin``. Callers pass their module-level ``db`` so unit
    tests that patch route ``db`` exercise the same object.

    Args:
        db_handle: Database handle with ``is_user_tenant_admin``.
        auth_data: Dict from ``validate_authentication`` (tenant_id, user_id, auth_method).
        detail: 403 message when the caller is a non-admin user session.

    Returns:
        The authenticated tenant id.

    Raises:
        HTTPException: 403 when auth is an API key, no user session, or the user
            is not a tenant administrator; 500 when tenant context is missing.
    """
    if auth_data.get("auth_method") == "api_key":
        raise HTTPException(
            status_code=403,
            detail=(
                "API keys cannot mutate governance; "
                "sign in as a tenant administrator"
            ),
        )
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    tenant_id = str(tenant_id)
    user_id = get_authenticated_user_id(auth_data)
    if not user_id or not db_handle.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(status_code=403, detail=detail)
    return tenant_id


def validate_session_credentials(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """
    Validate JWT or API key without requiring a tenant path segment.

    Used by ``GET /v1/tenants/me``, ``HEAD /v1/tenants/{slug}``, and similar session-scoped endpoints.
    """
    if authorization:
        jwt_payload = decode_jwt(authorization)
        if jwt_payload:
            user_id = jwt_payload.get('user_id') or jwt_payload.get('sub')
            if not user_id:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid JWT token: missing user identifier",
                )
            return {
                'auth_method': 'jwt',
                'user_id': user_id,
                'user_email': jwt_payload.get('email'),
                'user_name': jwt_payload.get('name'),
            }

    if x_api_key:
        api_key_data = db.validate_api_key(x_api_key)
        if not api_key_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "API-Key"},
            )
        uid = api_key_data.get("created_by_user_id")
        return {**api_key_data, "auth_method": "api_key", "user_id": uid}

    raise HTTPException(
        status_code=401,
        detail=(
            "Authentication required. Provide either JWT token "
            "(Authorization: Bearer <token>) or API key (X-API-Key: <key>)"
        ),
        headers={"WWW-Authenticate": "Bearer, API-Key"},
    )


def resolve_optional_tenant_member_auth(
    tenant_slug: str,
    *,
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> bool:
    """
    Return True when JWT or API key proves membership in ``tenant_slug``.

    When no credentials are supplied, returns False so callers can serve the public directory slice.

    When credentials are supplied but invalid or not authorized for this tenant, raises
    ``HTTPException`` (401/403).
    """
    auth_header = (authorization or "").strip()
    key_header = (x_api_key or "").strip()
    if not auth_header and not key_header:
        return False

    if auth_header:
        jwt_payload = decode_jwt(auth_header)
        if not jwt_payload:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired JWT token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = jwt_payload.get("user_id") or jwt_payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid JWT token: missing user identifier",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not db.get_active_tenant_auth_row(tenant_slug):
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_slug}")
        tenant_data = validate_user_tenant_access(user_id, tenant_slug)
        if not tenant_data:
            raise HTTPException(
                status_code=403,
                detail=f"User does not have access to tenant: {tenant_slug}",
            )
        return True

    api_key_data = db.validate_api_key(key_header)
    if not api_key_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "API-Key"},
        )
    if api_key_data.get("tenant_slug") != tenant_slug:
        raise HTTPException(
            status_code=403,
            detail="API key does not have access to this tenant",
        )
    return True
