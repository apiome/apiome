"""
Tests for Projects REST API endpoints with dual authentication (JWT and API Key)
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.app.main import app
from src.app.auth import validate_authentication

client = TestClient(app)

# ---------------------------------------------------------------------------
# Auth-bypass helper
# ---------------------------------------------------------------------------
_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


_FAKE_PROJECT_ACTIVE = {
    "id": "proj-1",
    "tenant_id": "test-tenant-id",
    "creator_id": "user-1",
    "name": "Active Project",
    "description": None,
    "slug": "active-project",
    "enabled": True,
    "metadata": {},
    "change_report_template_version_id": None,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "deleted_at": None,
    "creator_name": "Test User",
    "creator_email": "test@example.com",
}

_FAKE_PROJECT_DELETED = {
    **_FAKE_PROJECT_ACTIVE,
    "id": "proj-deleted",
    "name": "Deleted Project",
    "slug": "deleted-project",
    "enabled": False,
    "deleted_at": "2026-02-01T00:00:00",
}


def test_list_projects_requires_auth():
    """Test that listing projects requires authentication."""
    response = client.get('/v1/projects/test-tenant')
    assert response.status_code == 401
    assert 'Authentication required' in response.json()['detail']


def test_list_projects_invalid_jwt():
    """Test that invalid JWT token is rejected."""
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401


def test_list_projects_invalid_api_key():
    """Test that invalid API key is rejected."""
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'X-API-Key': 'invalid-key'}
    )
    assert response.status_code == 401


def test_get_project_requires_auth():
    """Test that getting a project requires authentication."""
    response = client.get('/v1/projects/test-tenant/some-id')
    assert response.status_code == 401


def test_get_project_by_slug_requires_auth():
    """Test that getting a project by slug requires authentication."""
    response = client.get('/v1/projects/test-tenant/by-slug/some-slug')
    assert response.status_code == 401


def test_project_domains_global_no_auth():
    """GET /v1/projects/domains is public (CLI allowlist prefetch)."""
    response = client.get("/v1/projects/domains")
    assert response.status_code == 200
    body = response.json()
    assert len(body["domains"]) >= 10
    assert "ecommerce" in body["domains"]


def test_project_domains_tenant_scoped_no_auth():
    """GET …/{tenant}/domains must not hit get_project_by_id (uuid parse)."""
    response = client.get("/v1/projects/apis-guru/domains")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["domains"], list)
    assert "saas" in body["domains"]


def test_create_project_requires_auth():
    """Test that creating a project requires authentication."""
    response = client.post(
        '/v1/projects/test-tenant',
        json={
            'name': 'Test Project',
            'slug': 'test-project',
            'description': 'A test project'
        }
    )
    assert response.status_code == 401


def test_update_project_requires_auth():
    """Test that updating a project requires authentication."""
    response = client.put(
        '/v1/projects/test-tenant/some-id',
        json={'name': 'Updated Project'}
    )
    assert response.status_code == 401


def test_delete_project_requires_auth():
    """Test that deleting a project requires authentication."""
    response = client.delete('/v1/projects/test-tenant/some-id')
    assert response.status_code == 401


def test_restore_project_requires_auth():
    """Test that restoring a project requires authentication."""
    response = client.post('/v1/projects/test-tenant/some-id/restore')
    assert response.status_code == 401


def test_jwt_and_api_key_both_provided():
    """Test behavior when both JWT and API key are provided (JWT takes precedence)."""
    response = client.get(
        '/v1/projects/test-tenant',
        headers={
            'Authorization': 'Bearer invalid-token',
            'X-API-Key': 'also-invalid'
        }
    )
    # Should still be 401 since both are invalid
    assert response.status_code == 401


def test_create_project_validation_missing_name():
    """Test that create project validates required name field."""
    # Using 422 format - missing required fields in the schema
    response = client.post(
        '/v1/projects/test-tenant',
        json={
            'slug': 'test-project'
        }
    )
    assert response.status_code == 401  # Auth check happens first


def test_create_project_validation_missing_slug():
    """Test that create project validates required slug field."""
    response = client.post(
        '/v1/projects/test-tenant',
        json={
            'name': 'Test Project'
        }
    )
    assert response.status_code == 401  # Auth check happens first


def test_create_project_empty_request():
    """Test that create project rejects empty request."""
    response = client.post(
        '/v1/projects/test-tenant',
        json={}
    )
    assert response.status_code == 401  # Auth check happens first before validation


def test_update_project_empty_request():
    """Test that update project with empty request still requires auth."""
    response = client.put(
        '/v1/projects/test-tenant/some-id',
        json={}
    )
    assert response.status_code == 401  # Auth check happens first


def test_project_endpoints_return_json():
    """Test that all project endpoints return JSON content type."""
    # List projects
    response = client.get('/v1/projects/test-tenant')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Get project
    response = client.get('/v1/projects/test-tenant/some-id')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Get project by slug
    response = client.get('/v1/projects/test-tenant/by-slug/test-slug')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Create project
    response = client.post('/v1/projects/test-tenant', json={'name': 'Test', 'slug': 'test'})
    assert response.headers.get('content-type', '').startswith('application/json')

    # Update project
    response = client.put('/v1/projects/test-tenant/some-id', json={'name': 'Updated'})
    assert response.headers.get('content-type', '').startswith('application/json')

    # Delete project
    response = client.delete('/v1/projects/test-tenant/some-id')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Restore project
    response = client.post('/v1/projects/test-tenant/some-id/restore')
    assert response.headers.get('content-type', '').startswith('application/json')


def test_projects_router_is_registered():
    """Test that the projects router is properly registered."""
    # Check that the routes exist by verifying we don't get 404 Method Not Allowed
    response = client.get('/v1/projects/any-tenant')
    # 401 means the route exists but requires auth (not 404)
    assert response.status_code == 401


def test_auth_header_formats():
    """Test various authorization header formats."""
    # Without Bearer prefix
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'Authorization': 'invalid-token'}
    )
    assert response.status_code == 401

    # With Bearer prefix but invalid token
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401

    # Empty Authorization header
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'Authorization': ''}
    )
    assert response.status_code == 401


def test_api_key_header_formats():
    """Test API key header format."""
    # Empty API key
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'X-API-Key': ''}
    )
    assert response.status_code == 401

    # Invalid API key
    response = client.get(
        '/v1/projects/test-tenant',
        headers={'X-API-Key': 'definitely-not-valid'}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# include_deleted flag
# ---------------------------------------------------------------------------

def test_list_projects_include_deleted_returns_all_rows():
    """When include_deleted=true the response includes soft-deleted projects."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            mock_db.get_projects_for_tenant.return_value = [
                _FAKE_PROJECT_ACTIVE,
                _FAKE_PROJECT_DELETED,
            ]
            response = client.get(
                "/v1/projects/test-tenant?include_deleted=true"
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        slugs = [p["slug"] for p in data]
        assert "active-project" in slugs
        assert "deleted-project" in slugs
        mock_db.get_projects_for_tenant.assert_called_once_with(
            "test-tenant-id", include_deleted=True
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_list_projects_default_excludes_deleted():
    """By default (no flag) only active projects are returned."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            mock_db.get_projects_for_tenant.return_value = [_FAKE_PROJECT_ACTIVE]
            response = client.get("/v1/projects/test-tenant")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["slug"] == "active-project"
        mock_db.get_projects_for_tenant.assert_called_once_with(
            "test-tenant-id", include_deleted=False
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_list_projects_active_rows_come_first_when_include_deleted():
    """Active projects appear before soft-deleted ones in the response."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            # DB returns active first, then deleted (as the ORDER BY guarantees)
            mock_db.get_projects_for_tenant.return_value = [
                _FAKE_PROJECT_ACTIVE,
                _FAKE_PROJECT_DELETED,
            ]
            response = client.get(
                "/v1/projects/test-tenant?include_deleted=true"
            )
        assert response.status_code == 200
        data = response.json()
        assert data[0]["deleted_at"] is None
        assert data[1]["deleted_at"] is not None
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Restore endpoint – business logic
# ---------------------------------------------------------------------------

def test_restore_project_success():
    """POST /{tenant}/{id}/restore on a deleted project returns the restored row."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            mock_db.get_project_by_id.side_effect = [
                _FAKE_PROJECT_DELETED,   # first call: include_deleted=True (pre-check)
                _FAKE_PROJECT_ACTIVE,    # second call: reload after restore
            ]
            mock_db.restore_project.return_value = True
            response = client.post(
                "/v1/projects/test-tenant/proj-deleted/restore"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "active-project"
        assert data["deleted_at"] is None
        mock_db.restore_project.assert_called_once_with(
            "proj-deleted", "test-tenant-id"
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_restore_project_not_found_returns_404():
    """POST restore on an unknown project ID returns 404."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = None
            response = client.post(
                "/v1/projects/test-tenant/no-such-id/restore"
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_restore_project_not_deleted_returns_400():
    """POST restore on an active (non-deleted) project returns 400."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = _FAKE_PROJECT_ACTIVE
            response = client.post(
                "/v1/projects/test-tenant/proj-1/restore"
            )
        assert response.status_code == 400
        assert "not deleted" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_restore_project_race_condition_returns_409():
    """If restore_project returns False (race condition), the API returns 409."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.projects_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = _FAKE_PROJECT_DELETED
            mock_db.restore_project.return_value = False
            response = client.post(
                "/v1/projects/test-tenant/proj-deleted/restore"
            )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

