"""Tenant access checks: members, administrators, and JWT validation."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.authz_cache import AuthorizationContext
from app.auth import normalize_user_id, validate_user_tenant_access, validate_authentication

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_TENANT_ROW = {
    "tenant_id": _TENANT_ID,
    "tenant_slug": "apis-guru",
    "tenant_name": "APIs Guru",
}


def test_normalize_user_id_accepts_uuid_string():
    assert normalize_user_id(_USER_ID) == _USER_ID


def test_normalize_user_id_rejects_garbage():
    assert normalize_user_id("not-a-uuid") is None


def _context(*, is_admin: bool = False, is_active_member: bool = False) -> AuthorizationContext:
    return AuthorizationContext(
        tenant_id=_TENANT_ID,
        tenant_slug="apis-guru",
        tenant_name="APIs Guru",
        tenant_active=True,
        user_id=_USER_ID,
        is_admin=is_admin,
        is_active_member=is_active_member,
    )


def test_validate_user_tenant_access_allows_admin_without_member_row():
    with patch("app.auth.db") as mdb:
        mdb.get_authorization_context.return_value = _context(is_admin=True)
        out = validate_user_tenant_access(_USER_ID, "apis-guru")
    assert out == _TENANT_ROW
    mdb.get_authorization_context.assert_called_once_with(_USER_ID, tenant_slug="apis-guru")


def test_validate_user_tenant_access_denies_when_no_membership():
    with patch("app.auth.db") as mdb:
        mdb.get_authorization_context.return_value = _context()
        assert validate_user_tenant_access(_USER_ID, "apis-guru") is None


def test_validate_authentication_returns_404_for_missing_tenant():
    from unittest.mock import MagicMock

    req = MagicMock()
    req.method = "GET"
    req.url.path = "/v1/projects/missing-tenant"
    with patch("app.auth.decode_jwt") as mjwt, patch("app.auth.db") as mdb:
        mjwt.return_value = {"user_id": _USER_ID, "sub": _USER_ID}
        mdb.get_authorization_context.return_value = None
        with pytest.raises(HTTPException) as exc:
            validate_authentication(
                req, "missing-tenant", authorization="Bearer token"
            )
    assert exc.value.status_code == 404


def test_validate_authentication_returns_403_when_not_member_or_admin():
    from unittest.mock import MagicMock

    req = MagicMock()
    req.method = "GET"
    req.url.path = "/v1/projects/apis-guru"
    with patch("app.auth.decode_jwt") as mjwt, patch("app.auth.db") as mdb:
        mjwt.return_value = {"user_id": _USER_ID, "sub": _USER_ID}
        mdb.get_authorization_context.return_value = _context()
        with pytest.raises(HTTPException) as exc:
            validate_authentication(
                req, "apis-guru", authorization="Bearer token"
            )
    assert exc.value.status_code == 403
    assert "apis-guru" in str(exc.value.detail)


def test_user_has_tenant_access_checks_admin_table():
    from app.database import db

    with patch.object(db, "execute_query", side_effect=[[], [{"?column?": 1}]]):
        assert db.user_has_tenant_access(_USER_ID, _TENANT_ID) is True
