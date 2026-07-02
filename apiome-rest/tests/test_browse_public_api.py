"""Tests for unauthenticated GET /v1/browse/tenants."""

from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_browse_tenants_ok_no_auth():
    stats = {"tenant_count": 2, "project_count": 5, "version_count": 12}
    rows = [
        {
            "slug": "acme-corp",
            "name": "Acme Corporation",
            "project_count": 7,
            "published_versions": 18,
            "latest_version": "2.1.0",
            "latest_activity_at": datetime(2026, 5, 6, 12, 0, 0),
        },
        {
            "slug": "demo",
            "name": "Apiome Demo",
            "project_count": 12,
            "published_versions": 45,
            "latest_version": "0.9.7",
            "latest_activity_at": None,
        },
    ]
    with patch("app.browse_public_routes.db") as m:
        m.get_public_browse_directory_stats.return_value = stats
        m.list_public_browse_tenants.return_value = rows
        r = client.get("/v1/browse/tenants")
    assert r.status_code == 200
    body = r.json()
    assert body["directory_stats"]["tenant_count"] == 2
    assert body["filtered_count"] == 2
    assert len(body["tenants"]) == 2
    assert body["tenants"][0]["slug"] == "acme-corp"
    assert body["tenants"][0]["published_versions"] == 18
    assert body["tenants"][0]["latest_version"] == "2.1.0"


def test_browse_tenants_passes_search_and_sort():
    with patch("app.browse_public_routes.db") as m:
        m.get_public_browse_directory_stats.return_value = {
            "tenant_count": 0,
            "project_count": 0,
            "version_count": 0,
        }
        m.list_public_browse_tenants.return_value = []
        r = client.get("/v1/browse/tenants?search=acme&sort=latest")
    assert r.status_code == 200
    m.list_public_browse_tenants.assert_called_once()
    ca = m.list_public_browse_tenants.call_args
    assert ca.kwargs["search"] == "acme"
    assert ca.kwargs["sort"] == "latest"


def test_browse_projects_tenant_missing_is_404():
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = None
        r = client.get("/v1/browse/tenants/nope/projects")
    assert r.status_code == 404


def test_browse_projects_anonymous_ok_and_passes_query_params():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    rows = [
        {
            "slug": "payments-api",
            "name": "Payments API",
            "metadata": {"domain": "finance"},
            "published_versions": 3,
            "latest_version": "2.1.0",
            "latest_published_at": datetime(2026, 5, 6, 12, 0, 0),
        },
    ]
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant
        m.list_public_browse_projects_for_tenant.return_value = rows
        r = client.get(
            "/v1/browse/tenants/acme-corp/projects"
            "?search=pay&domain=finance&has_published=true",
        )
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_slug"] == "acme-corp"
    assert body["tenant_name"] == "Acme Corp"
    assert body["filtered_count"] == 1
    assert len(body["projects"]) == 1
    assert body["projects"][0]["slug"] == "payments-api"
    assert body["projects"][0]["domain"] == "finance"
    assert body["projects"][0]["published_versions"] == 3
    assert body["projects"][0]["latest_version"] == "2.1.0"
    m.list_public_browse_projects_for_tenant.assert_called_once()
    ca = m.list_public_browse_projects_for_tenant.call_args
    assert ca.kwargs["search"] == "pay"
    assert ca.kwargs["domain"] == "finance"
    assert ca.kwargs["require_published"] is True


def test_browse_projects_x_api_key_member_invokes_member_list():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    with patch("app.browse_public_routes.db") as m, patch(
        "app.auth.db.validate_api_key",
        return_value={"tenant_slug": "acme-corp"},
    ):
        m.get_tenant_row_by_slug.return_value = tenant
        m.list_member_browse_projects_for_tenant.return_value = []
        r = client.get(
            "/v1/browse/tenants/acme-corp/projects",
            headers={"X-API-Key": "member-key"},
        )
    assert r.status_code == 200
    m.list_member_browse_projects_for_tenant.assert_called_once()
    m.list_public_browse_projects_for_tenant.assert_not_called()


def test_browse_projects_invalid_jwt_when_header_present():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    with patch("app.browse_public_routes.db") as m, patch("app.auth.decode_jwt", return_value=None):
        m.get_tenant_row_by_slug.return_value = tenant
        r = client.get(
            "/v1/browse/tenants/acme-corp/projects",
            headers={"Authorization": "Bearer invalid"},
        )
    assert r.status_code == 401


def test_browse_projects_x_api_key_for_other_tenant_is_403():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    with patch("app.browse_public_routes.db") as m, patch(
        "app.auth.db.validate_api_key",
        return_value={"tenant_slug": "other-tenant"},
    ):
        m.get_tenant_row_by_slug.return_value = tenant
        r = client.get(
            "/v1/browse/tenants/acme-corp/projects",
            headers={"X-API-Key": "other-tenant-key"},
        )
    assert r.status_code == 403
    m.list_member_browse_projects_for_tenant.assert_not_called()
    m.list_public_browse_projects_for_tenant.assert_not_called()


def test_browse_versions_anonymous_ok_semver_order_and_since():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    project = {"id": "pid-1", "slug": "payments-api", "name": "Payments API"}
    rows = [
        {
            "id": "v2",
            "version_id": "2.0.0",
            "published_at": datetime(2026, 2, 18, 12, 0, 0),
            "description": None,
            "change_log": None,
            "change_model_json": None,
            "tags": [],
        },
        {
            "id": "v3",
            "version_id": "2.1.0",
            "published_at": datetime(2026, 5, 4, 12, 0, 0),
            "description": None,
            "change_log": None,
            "change_model_json": None,
            "tags": ["latest", "stable"],
        },
    ]
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant
        m.get_project_by_slug.return_value = project
        m.project_has_public_published_version.return_value = True
        m.list_public_browse_versions_for_project.return_value = rows
        r = client.get(
            "/v1/browse/tenants/acme-corp/projects/payments-api/versions"
            "?since=2026-02-01T00:00:00Z",
        )
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_slug"] == "acme-corp"
    assert body["project_slug"] == "payments-api"
    assert [v["version_id"] for v in body["versions"]] == ["2.1.0", "2.0.0"]
    m.list_public_browse_versions_for_project.assert_called_once()
    ca = m.list_public_browse_versions_for_project.call_args
    assert ca.kwargs.get("since") is not None


def test_browse_versions_member_lists_all_visibilities():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    project = {"id": "pid-1", "slug": "payments-api", "name": "Payments API"}
    with patch("app.browse_public_routes.db") as m, patch(
        "app.auth.db.validate_api_key",
        return_value={"tenant_slug": "acme-corp"},
    ):
        m.get_tenant_row_by_slug.return_value = tenant
        m.get_project_by_slug.return_value = project
        m.list_member_browse_versions_for_project.return_value = []
        r = client.get(
            "/v1/browse/tenants/acme-corp/projects/payments-api/versions",
            headers={"X-API-Key": "member-key"},
        )
    assert r.status_code == 200
    m.list_member_browse_versions_for_project.assert_called_once()
    m.list_public_browse_versions_for_project.assert_not_called()


def test_browse_versions_semver_prerelease_ordering():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    project = {"id": "pid-1", "slug": "payments-api", "name": "Payments API"}
    rows = [
        {
            "id": "v1",
            "version_id": "2.0.0-rc.2",
            "published_at": datetime(2026, 5, 1, 12, 0, 0),
            "description": None,
            "change_log": None,
            "change_model_json": None,
            "tags": [],
        },
        {
            "id": "v2",
            "version_id": "2.0.0",
            "published_at": datetime(2026, 5, 2, 12, 0, 0),
            "description": None,
            "change_log": None,
            "change_model_json": None,
            "tags": [],
        },
        {
            "id": "v3",
            "version_id": "2.0.0-rc.10",
            "published_at": datetime(2026, 5, 3, 12, 0, 0),
            "description": None,
            "change_log": None,
            "change_model_json": None,
            "tags": [],
        },
        {
            "id": "v4",
            "version_id": "2.0.0-alpha",
            "published_at": datetime(2026, 5, 4, 12, 0, 0),
            "description": None,
            "change_log": None,
            "change_model_json": None,
            "tags": [],
        },
    ]
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant
        m.get_project_by_slug.return_value = project
        m.project_has_public_published_version.return_value = True
        m.list_public_browse_versions_for_project.return_value = rows
        r = client.get("/v1/browse/tenants/acme-corp/projects/payments-api/versions")
    assert r.status_code == 200
    body = r.json()
    assert [v["version_id"] for v in body["versions"]] == [
        "2.0.0",
        "2.0.0-rc.10",
        "2.0.0-rc.2",
        "2.0.0-alpha",
    ]


def test_browse_versions_unknown_project_is_404():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant
        m.get_project_by_slug.return_value = None
        r = client.get("/v1/browse/tenants/acme-corp/projects/nope/versions")
    assert r.status_code == 404


def test_browse_versions_public_masked_when_no_public_publish():
    tenant = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
    project = {"id": "pid-1", "slug": "private-only", "name": "Private Only"}
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = tenant
        m.get_project_by_slug.return_value = project
        m.project_has_public_published_version.return_value = False
        r = client.get("/v1/browse/tenants/acme-corp/projects/private-only/versions")
    assert r.status_code == 404
    m.list_public_browse_versions_for_project.assert_not_called()
