"""API key scope allowlisting (CTG-2.3 / #4473)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.auth import (
    API_KEY_SCOPE_DIFF_READ,
    API_KEY_SCOPE_FULL,
    API_KEY_SCOPE_LINT_READ,
    enforce_api_key_scopes,
    is_full_access_key,
    normalize_api_key_scopes,
    required_scope_for_request,
    validate_authentication,
)

_TENANT = "acme"
_KEY_FULL = {
    "id": "key-1",
    "tenant_id": "tenant-1",
    "tenant_slug": _TENANT,
    "tenant_name": "Acme",
    "created_by_user_id": "user-1",
    "scopes": ["*"],
}
_KEY_DIFF = {**_KEY_FULL, "id": "key-diff", "scopes": ["diff:read"]}
_KEY_LINT = {**_KEY_FULL, "id": "key-lint", "scopes": ["lint:read"]}
_KEY_BOTH = {**_KEY_FULL, "id": "key-both", "scopes": ["diff:read", "lint:read"]}


def test_normalize_api_key_scopes_defaults_to_full():
    assert normalize_api_key_scopes(None) == [API_KEY_SCOPE_FULL]
    assert normalize_api_key_scopes([]) == [API_KEY_SCOPE_FULL]
    assert normalize_api_key_scopes(["diff:read"]) == ["diff:read"]


def test_is_full_access_key():
    assert is_full_access_key(["*"]) is True
    assert is_full_access_key(["diff:read"]) is False
    assert is_full_access_key([]) is True


def test_required_scope_for_request_allowlist():
    assert (
        required_scope_for_request("POST", f"/v1/diff/{_TENANT}/classified")
        == API_KEY_SCOPE_DIFF_READ
    )
    assert (
        required_scope_for_request(
            "GET", "/v1/versions/acme/proj/ver/lint"
        )
        == API_KEY_SCOPE_LINT_READ
    )
    assert (
        required_scope_for_request(
            "GET", "/v1/versions/acme/proj/ver/lint/gate"
        )
        == API_KEY_SCOPE_LINT_READ
    )
    assert (
        required_scope_for_request(
            "GET",
            "/v1/mcp/acme/endpoints/ep/versions/ver/lint",
        )
        == API_KEY_SCOPE_LINT_READ
    )
    assert (
        required_scope_for_request(
            "GET",
            "/v1/mcp/acme/endpoints/ep/versions/ver/lint/gate",
        )
        == API_KEY_SCOPE_LINT_READ
    )
    # Writes / other routes are not allowlisted
    assert required_scope_for_request("POST", "/v1/projects/acme") is None
    assert required_scope_for_request("GET", "/v1/versions/acme/proj/ver/lint/axes") is None
    assert required_scope_for_request(
        "POST", "/v1/mcp/acme/endpoints/ep/versions/ver/lint"
    ) is None


def test_enforce_api_key_scopes_jwt_passthrough():
    req = MagicMock()
    req.method = "POST"
    req.url.path = "/v1/projects/acme"
    enforce_api_key_scopes({"auth_method": "jwt"}, req)


def test_enforce_api_key_scopes_full_access_passthrough():
    req = MagicMock()
    req.method = "POST"
    req.url.path = "/v1/projects/acme"
    enforce_api_key_scopes(
        {"auth_method": "api_key", "scopes": [API_KEY_SCOPE_FULL]}, req
    )


def test_enforce_api_key_scopes_diff_allows_classified():
    req = MagicMock()
    req.method = "POST"
    req.url.path = f"/v1/diff/{_TENANT}/classified"
    enforce_api_key_scopes(
        {"auth_method": "api_key", "scopes": [API_KEY_SCOPE_DIFF_READ]}, req
    )


def test_enforce_api_key_scopes_diff_denies_write():
    req = MagicMock()
    req.method = "POST"
    req.url.path = "/v1/projects/acme"
    with pytest.raises(HTTPException) as exc:
        enforce_api_key_scopes(
            {"auth_method": "api_key", "scopes": [API_KEY_SCOPE_DIFF_READ]}, req
        )
    assert exc.value.status_code == 403


def test_enforce_api_key_scopes_lint_denies_classified():
    req = MagicMock()
    req.method = "POST"
    req.url.path = f"/v1/diff/{_TENANT}/classified"
    with pytest.raises(HTTPException) as exc:
        enforce_api_key_scopes(
            {"auth_method": "api_key", "scopes": [API_KEY_SCOPE_LINT_READ]}, req
        )
    assert exc.value.status_code == 403


def _auth_via_key(key_row: dict):
    """Exercise real validate_authentication with a mocked DB key lookup."""

    def _run(method: str, path: str):
        req = MagicMock()
        req.method = method
        req.url.path = path
        with patch("app.auth.db") as mock_db:
            mock_db.validate_api_key.return_value = dict(key_row)
            return validate_authentication(
                request=req,
                tenant_slug=_TENANT,
                authorization=None,
                x_api_key="sk_test_key_value",
            )

    return _run


def test_validate_authentication_diff_key_allows_classified():
    auth = _auth_via_key(_KEY_DIFF)("POST", f"/v1/diff/{_TENANT}/classified")
    assert auth["auth_method"] == "api_key"
    assert auth["scopes"] == ["diff:read"]


def test_validate_authentication_diff_key_rejects_write():
    with pytest.raises(HTTPException) as exc:
        _auth_via_key(_KEY_DIFF)("POST", f"/v1/projects/{_TENANT}")
    assert exc.value.status_code == 403


def test_validate_authentication_lint_key_allows_gate():
    auth = _auth_via_key(_KEY_LINT)(
        "GET", "/v1/versions/acme/proj-1/ver-1/lint/gate"
    )
    assert auth["scopes"] == ["lint:read"]


def test_validate_authentication_lint_key_rejects_classified():
    with pytest.raises(HTTPException) as exc:
        _auth_via_key(_KEY_LINT)("POST", f"/v1/diff/{_TENANT}/classified")
    assert exc.value.status_code == 403


def test_validate_authentication_both_scopes_allow_diff_and_lint():
    run = _auth_via_key(_KEY_BOTH)
    assert run("POST", f"/v1/diff/{_TENANT}/classified")["scopes"] == [
        "diff:read",
        "lint:read",
    ]
    assert run("GET", "/v1/versions/acme/p/v/lint")["scopes"] == [
        "diff:read",
        "lint:read",
    ]


def test_validate_authentication_full_key_allows_write_path():
    auth = _auth_via_key(_KEY_FULL)("POST", f"/v1/projects/{_TENANT}")
    assert auth["scopes"] == ["*"]

