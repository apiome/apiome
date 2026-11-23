"""Tests for GET /v1/tenants/me, HEAD /v1/tenants/{slug}, and GET /v1/tenants/{slug}."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.main import app

client = TestClient(app)

_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _session_jwt():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "auth_method": "jwt",
        "user_id": _USER_ID,
    }
    yield
    app.dependency_overrides.pop(validate_session_credentials, None)


def test_list_my_tenants_jwt():
    rows = [
        {
            "id": _TENANT_ID,
            "slug": "acme",
            "name": "Acme",
            "role": "owner",
            "status": "active",
            "license_name": "Free",
            "license_type": "free",
        },
        {
            "id": "550e8400-e29b-41d4-a716-446655440099",
            "slug": "beta",
            "name": "Beta",
            "role": "editor",
            "status": "active",
            "license_name": "Paid",
            "license_type": "paid",
        },
    ]
    with patch("app.tenants_session_routes.db") as m:
        m.count_tenants_for_user.return_value = 2
        m.list_tenants_for_user_page.return_value = rows
        r = client.get("/v1/tenants/me")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["slug"] == "acme"
    assert body["items"][0]["id"] == _TENANT_ID
    assert body["items"][0]["role"] == "owner"
    assert body["items"][0]["status"] == "active"
    assert body["items"][0]["license_name"] == "Free"
    assert body["items"][0]["license_type"] == "free"
    assert body["items"][1]["role"] == "editor"
    assert body["items"][1]["license_type"] == "paid"


def test_list_my_tenants_jwt_membership_enrichment_defaults():
    """Rows missing enrichment fields fall back to editor/active with null license (OLO-6.2)."""
    rows = [
        {"id": _TENANT_ID, "slug": "acme", "name": "Acme", "role": None, "status": None},
    ]
    with patch("app.tenants_session_routes.db") as m:
        m.count_tenants_for_user.return_value = 1
        m.list_tenants_for_user_page.return_value = rows
        r = client.get("/v1/tenants/me")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["role"] == "editor"
    assert item["status"] == "active"
    assert item["license_name"] is None
    assert item["license_type"] is None


def test_list_my_tenants_jwt_status_and_custom_role_passthrough():
    """Suspended members stay listed with their status; custom role slugs pass through (OLO-6.2)."""
    rows = [
        {
            "id": _TENANT_ID,
            "slug": "acme",
            "name": "Acme",
            "role": "release-manager",
            "status": "suspended",
            "license_name": "Sponsor",
            "license_type": "sponsor",
        },
    ]
    with patch("app.tenants_session_routes.db") as m:
        m.count_tenants_for_user.return_value = 1
        m.list_tenants_for_user_page.return_value = rows
        r = client.get("/v1/tenants/me")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["role"] == "release-manager"
    assert item["status"] == "suspended"
    assert item["license_type"] == "sponsor"


def test_list_my_tenants_pagination_query():
    with patch("app.tenants_session_routes.db") as m:
        m.count_tenants_for_user.return_value = 120
        m.list_tenants_for_user_page.return_value = []
        r = client.get("/v1/tenants/me?limit=50&offset=50")
    assert r.status_code == 200
    m.list_tenants_for_user_page.assert_called_once()
    args = m.list_tenants_for_user_page.call_args[0]
    assert args[0] == _USER_ID
    # One row past the page: `has_more` without relying on the total (#7196).
    assert args[1] == 51
    assert args[2] == 50
    assert m.list_tenants_for_user_page.call_args.kwargs == {"cursor": None}


def _memberships(count):
    return [
        {
            "id": f"990e8400-e29b-41d4-a716-{index:012d}",
            "slug": f"tenant-{index:02d}",
            "name": f"Tenant {index}",
            "role": "editor",
            "status": "active",
            "license_name": None,
            "license_type": None,
        }
        for index in range(count)
    ]


def _paged(rows):
    """A ``list_tenants_for_user_page`` stand-in honouring ``limit`` and the ``[slug, id]`` cursor."""

    def page(_user_id, limit, offset, cursor=None):
        matching = [r for r in rows if cursor is None or [r["slug"], r["id"]] > list(cursor)]
        offset = 0 if cursor is not None else offset
        return matching[offset : offset + limit]

    return page


def test_list_my_tenants_pages_by_cursor_to_the_end():
    from tests.keyset_paging_fakes import walk

    rows = _memberships(5)
    with patch("app.tenants_session_routes.db") as m:
        m.count_tenants_for_user.return_value = 5
        m.list_tenants_for_user_page.side_effect = _paged(rows)
        seen = walk(lambda params: client.get("/v1/tenants/me", params=params), "items")
        first = client.get("/v1/tenants/me", params={"limit": 2}).json()
    assert [item["slug"] for item in seen] == [row["slug"] for row in rows]
    # The membership count stays on every page: the switcher sizes itself from it.
    assert first["total"] == 5 and first["has_more"] is True and first["next_cursor"]


def test_list_my_tenants_refuses_a_malformed_cursor_and_oversized_pages():
    from app.keyset_pagination import encode_key_cursor

    with patch("app.tenants_session_routes.db") as m:
        assert client.get("/v1/tenants/me", params={"cursor": "not-a-cursor"}).status_code == 400
        forged = encode_key_cursor(["acme", "not-a-uuid"])
        assert client.get("/v1/tenants/me", params={"cursor": forged}).status_code == 400
        assert client.get("/v1/tenants/me", params={"limit": 101}).status_code == 422
        assert client.get("/v1/tenants/me", params={"offset": 10_001}).status_code == 422
    m.list_tenants_for_user_page.assert_not_called()


def test_the_membership_query_is_a_total_order_and_a_cursor_drops_the_offset():
    from unittest.mock import MagicMock

    from app.database import Database

    database = Database.__new__(Database)
    database.execute_query = MagicMock(return_value=[])
    tenant = "990e8400-e29b-41d4-a716-000000000001"
    database.list_tenants_for_user_page(_USER_ID, 11, 40, cursor=["acme", tenant])
    sql, params = database.execute_query.call_args[0]
    assert "AND (t.slug, t.id) > (%s, %s::uuid)" in sql
    assert "ORDER BY t.slug ASC, t.id ASC" in sql
    assert params == (_USER_ID, _USER_ID, _USER_ID, "acme", tenant, 11, 0)


def test_head_tenant_access_ok():
    tenant_row = {
        "id": _TENANT_ID,
        "slug": "acme",
        "name": "Acme Co",
        "created_at": "2024-08-12T00:00:00+00:00",
    }
    with patch("app.tenants_session_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant_row
        m.user_has_tenant_access.return_value = True
        r = client.head("/v1/tenants/acme")
    assert r.status_code == 200
    assert (r.text or "") == ""


def test_head_tenant_access_not_found():
    with patch("app.tenants_session_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = None
        r = client.head("/v1/tenants/missing")
    assert r.status_code == 404


def test_head_tenant_access_forbidden():
    tenant_row = {"id": _TENANT_ID, "slug": "other", "name": "Other", "created_at": None}
    with patch("app.tenants_session_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant_row
        m.user_has_tenant_access.return_value = False
        r = client.head("/v1/tenants/other")
    assert r.status_code == 403


def test_get_tenant_info_ok():
    tenant_row = {
        "id": _TENANT_ID,
        "slug": "acme",
        "name": "Acme Co",
        "created_at": "2024-08-12T00:00:00+00:00",
    }
    stats = {
        "members_count": 3,
        "projects_count": 2,
        "versions_count": 10,
        "published_versions_count": 4,
    }
    with patch("app.tenants_session_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant_row
        m.user_has_tenant_access.return_value = True
        m.get_tenant_usage_stats.return_value = stats
        r = client.get("/v1/tenants/acme")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "acme"
    assert body["members_count"] == 3
    assert body["versions_count"] == 10


def test_get_tenant_info_forbidden():
    tenant_row = {"id": _TENANT_ID, "slug": "other", "name": "Other", "created_at": None}
    with patch("app.tenants_session_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant_row
        m.user_has_tenant_access.return_value = False
        r = client.get("/v1/tenants/other")
    assert r.status_code == 403


def test_list_my_tenants_api_key_single_tenant():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "auth_method": "api_key",
        "tenant_id": _TENANT_ID,
        "tenant_slug": "acme",
        "tenant_name": "Acme",
    }
    try:
        with patch("app.tenants_session_routes.db") as m:
            m.get_tenant_license_info.return_value = {
                "name": "Free",
                "license_type": "free",
            }
            r = client.get("/v1/tenants/me")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["slug"] == "acme"
        assert body["items"][0]["role"] == "member"
        assert body["items"][0]["status"] == "active"
        assert body["items"][0]["license_name"] == "Free"
        assert body["items"][0]["license_type"] == "free"
    finally:
        app.dependency_overrides[validate_session_credentials] = lambda: {
            "auth_method": "jwt",
            "user_id": _USER_ID,
        }


def test_list_my_tenants_api_key_unlicensed_tenant():
    """An API-key tenant with no license row reports null license fields (OLO-6.2)."""
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "auth_method": "api_key",
        "tenant_id": _TENANT_ID,
        "tenant_slug": "acme",
        "tenant_name": "Acme",
    }
    try:
        with patch("app.tenants_session_routes.db") as m:
            m.get_tenant_license_info.return_value = None
            r = client.get("/v1/tenants/me")
        assert r.status_code == 200
        item = r.json()["items"][0]
        assert item["license_name"] is None
        assert item["license_type"] is None
    finally:
        app.dependency_overrides[validate_session_credentials] = lambda: {
            "auth_method": "jwt",
            "user_id": _USER_ID,
        }


def test_list_my_tenants_api_key_offset_past_end():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "auth_method": "api_key",
        "tenant_id": _TENANT_ID,
        "tenant_slug": "acme",
        "tenant_name": "Acme",
    }
    try:
        with patch("app.tenants_session_routes.db") as m:
            m.get_tenant_license_info.return_value = None
            r = client.get("/v1/tenants/me?limit=50&offset=50")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["offset"] == 50
        assert body["limit"] == 50
        assert body["items"] == []
    finally:
        app.dependency_overrides[validate_session_credentials] = lambda: {
            "auth_method": "jwt",
            "user_id": _USER_ID,
        }
