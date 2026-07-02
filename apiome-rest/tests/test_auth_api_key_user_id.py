"""creator_id resolution for API key authentication (#3329)."""

from unittest.mock import patch

from app.auth import get_authenticated_user_id


def test_jwt_returns_user_id():
    assert get_authenticated_user_id({"auth_method": "jwt", "user_id": "user-a"}) == "user-a"


def test_api_key_uses_created_by_user_id():
    assert (
        get_authenticated_user_id(
            {
                "auth_method": "api_key",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "user_id": "00000000-0000-0000-0000-0000000000aa",
            }
        )
        == "00000000-0000-0000-0000-0000000000aa"
    )


def test_api_key_fallback_when_no_user_id_on_key():
    with patch("app.auth.db") as mock_db:
        mock_db.get_fallback_creator_user_id_for_tenant.return_value = "fallback-user"
        uid = get_authenticated_user_id(
            {
                "auth_method": "api_key",
                "tenant_id": "00000000-0000-0000-0000-000000000002",
            }
        )
        assert uid == "fallback-user"
        mock_db.get_fallback_creator_user_id_for_tenant.assert_called_once_with(
            "00000000-0000-0000-0000-000000000002"
        )


def test_unknown_auth_returns_none():
    assert get_authenticated_user_id({"auth_method": "other"}) is None
