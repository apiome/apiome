"""
Tests for Versions REST API endpoints with dual authentication (JWT and API Key)
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


def test_list_versions_requires_auth():
    """Test that listing versions requires authentication."""
    response = client.get('/v1/versions/test-tenant/some-project-id')
    assert response.status_code == 401
    assert 'Authentication required' in response.json()['detail']


def test_list_versions_invalid_jwt():
    """Test that invalid JWT token is rejected."""
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401


def test_list_versions_invalid_api_key():
    """Test that invalid API key is rejected."""
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'X-API-Key': 'invalid-key'}
    )
    assert response.status_code == 401


def test_get_version_requires_auth():
    """Test that getting a version requires authentication."""
    response = client.get('/v1/versions/test-tenant/some-project-id/some-version-id')
    assert response.status_code == 401


def test_get_version_by_version_id_requires_auth():
    """Test that getting a version by version ID requires authentication."""
    response = client.get('/v1/versions/test-tenant/some-project-id/by-version/1.0.0')
    assert response.status_code == 401


def test_create_version_requires_auth():
    """Test that creating a version requires authentication."""
    response = client.post(
        '/v1/versions/test-tenant/some-project-id',
        json={
            'version_id': '1.0.0',
            'description': 'Initial version'
        }
    )
    assert response.status_code == 401


def test_fork_version_requires_auth():
    """Test that forking a version requires authentication."""
    response = client.post(
        '/v1/versions/test-tenant/some-project-id/fork',
        json={'sourceRevisionId': '00000000-0000-0000-0000-000000000001'},
    )
    assert response.status_code == 401


def test_update_version_requires_auth():
    """Test that updating a version requires authentication."""
    response = client.put(
        '/v1/versions/test-tenant/some-project-id/some-version-id',
        json={'description': 'Updated description'}
    )
    assert response.status_code == 401


def test_delete_version_requires_auth():
    """Test that deleting a version requires authentication."""
    response = client.delete('/v1/versions/test-tenant/some-project-id/some-version-id')
    assert response.status_code == 401


def test_publish_version_requires_auth():
    """Test that publishing a version requires authentication."""
    response = client.post('/v1/versions/test-tenant/some-project-id/some-version-id/publish')
    assert response.status_code == 401


def test_unpublish_version_requires_auth():
    """Test that unpublishing a version requires authentication."""
    response = client.post('/v1/versions/test-tenant/some-project-id/some-version-id/unpublish')
    assert response.status_code == 401


def test_jwt_and_api_key_both_provided():
    """Test behavior when both JWT and API key are provided (JWT takes precedence)."""
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={
            'Authorization': 'Bearer invalid-token',
            'X-API-Key': 'also-invalid'
        }
    )
    # Should still be 401 since both are invalid
    assert response.status_code == 401


def test_create_version_empty_request():
    """Test that create version with empty request still requires auth."""
    response = client.post(
        '/v1/versions/test-tenant/some-project-id',
        json={}
    )
    assert response.status_code == 401  # Auth check happens first


def test_update_version_empty_request():
    """Test that update version with empty request still requires auth."""
    response = client.put(
        '/v1/versions/test-tenant/some-project-id/some-version-id',
        json={}
    )
    assert response.status_code == 401  # Auth check happens first


def test_version_endpoints_return_json():
    """Test that all version endpoints return JSON content type."""
    # List versions
    response = client.get('/v1/versions/test-tenant/some-project-id')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Get version
    response = client.get('/v1/versions/test-tenant/some-project-id/some-version-id')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Get version by version_id
    response = client.get('/v1/versions/test-tenant/some-project-id/by-version/1.0.0')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Create version
    response = client.post('/v1/versions/test-tenant/some-project-id', json={'version_id': '1.0.0'})
    assert response.headers.get('content-type', '').startswith('application/json')

    # Update version
    response = client.put('/v1/versions/test-tenant/some-project-id/some-version-id', json={'description': 'Test'})
    assert response.headers.get('content-type', '').startswith('application/json')

    # Delete version
    response = client.delete('/v1/versions/test-tenant/some-project-id/some-version-id')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Publish version
    response = client.post('/v1/versions/test-tenant/some-project-id/some-version-id/publish')
    assert response.headers.get('content-type', '').startswith('application/json')

    # Unpublish version
    response = client.post('/v1/versions/test-tenant/some-project-id/some-version-id/unpublish')
    assert response.headers.get('content-type', '').startswith('application/json')


def test_versions_router_is_registered():
    """Test that the versions router is properly registered."""
    # Check that the routes exist by verifying we don't get 404 Method Not Allowed
    response = client.get('/v1/versions/any-tenant/any-project')
    # 401 means the route exists but requires auth (not 404)
    assert response.status_code == 401


def test_auth_header_formats():
    """Test various authorization header formats."""
    # Without Bearer prefix
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'Authorization': 'invalid-token'}
    )
    assert response.status_code == 401

    # With Bearer prefix but invalid token
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401

    # Empty Authorization header
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'Authorization': ''}
    )
    assert response.status_code == 401


def test_api_key_header_formats():
    """Test API key header format."""
    # Empty API key
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'X-API-Key': ''}
    )
    assert response.status_code == 401

    # Invalid API key
    response = client.get(
        '/v1/versions/test-tenant/some-project-id',
        headers={'X-API-Key': 'definitely-not-valid'}
    )
    assert response.status_code == 401


def test_publish_with_visibility():
    """Test that publish with visibility parameter still requires auth."""
    response = client.post(
        '/v1/versions/test-tenant/some-project-id/some-version-id/publish',
        json={'visibility': 'public'}
    )
    assert response.status_code == 401


def test_create_version_with_source():
    """Test that create version with source_version_id still requires auth."""
    response = client.post(
        '/v1/versions/test-tenant/some-project-id',
        json={
            'version_id': '1.1.0',
            'source_version_id': 'some-source-version-id',
            'description': 'Copied from previous version'
        }
    )
    assert response.status_code == 401


def test_create_version_with_bump_strategy():
    """Test that create version with bump_strategy still requires auth."""
    response = client.post(
        '/v1/versions/test-tenant/some-project-id',
        json={
            'bump_strategy': 'minor',
            'description': 'Auto-versioned'
        }
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Fork endpoint – business logic tests (auth bypassed via dependency override)
# ---------------------------------------------------------------------------

_FAKE_PROJECT = {"id": "proj-a", "name": "Project A", "tenant_id": "test-tenant-id"}
_FAKE_VERSION = {
    "id": "ver-1",
    "project_id": "proj-a",
    "version_id": "1.0.1",
    "description": None,
    "change_log": None,
    "visibility": "private",
    "published": False,
    "published_at": None,
    "enabled": True,
    "parent_version_id": None,
    "merge_parent_version_id": None,
    "forked_from_revision_id": "src-rev-id",
    "upstream_project_id": "proj-source",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}


def test_fork_version_missing_source_revision_id():
    """POST /fork with empty sourceRevisionId returns 400 with a camelCase error message."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.versions_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = _FAKE_PROJECT
            response = client.post(
                "/v1/versions/test-tenant/proj-a/fork",
                json={"sourceRevisionId": ""},
            )
        assert response.status_code == 400
        assert "sourceRevisionId" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_fork_version_bad_semantic_version_400():
    """POST /fork with an explicit non-semver versionId returns 400."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.versions_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = _FAKE_PROJECT
            response = client.post(
                "/v1/versions/test-tenant/proj-a/fork",
                json={
                    "sourceRevisionId": "src-rev-id",
                    "versionId": "not-a-semver",
                },
            )
        assert response.status_code == 400
        assert "semantic versioning" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_fork_version_same_project_returns_400():
    """POST /fork where source and target are the same project returns 400."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.versions_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = _FAKE_PROJECT
            mock_db.get_latest_version_for_project.return_value = None
            mock_db.create_forked_version.return_value = {
                "success": False,
                "error": (
                    'Fork requires a different target project than the source. '
                    'Use \u201cBranch from here\u201d for named branches within the same project.'
                ),
            }
            response = client.post(
                "/v1/versions/test-tenant/proj-a/fork",
                json={
                    "sourceRevisionId": "src-rev-id",
                    "shortMessage": "fork test",
                },
            )
        assert response.status_code == 400
        assert "different target project" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_fork_version_bump_strategy_minor():
    """POST /fork with bumpStrategy='minor' increments the minor version component."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.versions_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = _FAKE_PROJECT
            mock_db.get_latest_version_for_project.return_value = "1.2.3"
            mock_db.create_forked_version.return_value = {
                "success": True,
                "version": _FAKE_VERSION,
                "copied_count": 0,
            }
            response = client.post(
                "/v1/versions/test-tenant/proj-a/fork",
                json={
                    "sourceRevisionId": "src-rev-id",
                    "bumpStrategy": "minor",
                    "shortMessage": "minor bump fork",
                },
            )
        # create_forked_version must have been called with the minor-bumped version "1.3.0"
        mock_db.create_forked_version.assert_called_once()
        actual_version_id = mock_db.create_forked_version.call_args.kwargs.get("version_id")
        assert actual_version_id == "1.3.0", f"Expected 1.3.0 but got {actual_version_id}"
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_sunset_timeline_requires_auth():
    """GET /v1/versions/{tenant}/sunset-timeline requires authentication."""
    response = client.get("/v1/versions/test-tenant/sunset-timeline")
    assert response.status_code == 401


def test_sunset_timeline_route_registered():
    """Sunset timeline route exists (401 without auth, not 404)."""
    response = client.get("/v1/versions/any-tenant/sunset-timeline")
    assert response.status_code == 401


def test_sunset_timeline_returns_entries():
    """GET sunset-timeline aggregates deprecation rows with #507-shaped warnings."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.versions_routes.db") as mock_db:
            mock_db.list_sunset_timeline_entries.return_value = [
                {
                    "id": "rev-uuid-1",
                    "project_id": "proj-a",
                    "version_id": "1.0.0",
                    "metadata": {
                        "deprecated": True,
                        "deprecationMessage": "Move to v2",
                        "sunsetDate": "2099-06-01",
                        "successorRevisionId": "succ-rev",
                    },
                    "published": True,
                    "project_name": "Alpha",
                    "project_slug": "alpha",
                }
            ]
            response = client.get(
                "/v1/versions/test-tenant/sunset-timeline",
                headers={"Authorization": "Bearer unused"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert len(data["entries"]) == 1
        e = data["entries"][0]
        assert e["revisionId"] == "rev-uuid-1"
        assert e["versionLine"] == "1.0.0"
        assert e["timelineStatus"] == "announced"
        assert e["lifecyclePhase"] == "deprecated"
        assert e["sunsetDate"] == "2099-06-01"
        assert len(e["deprecationWarnings"]) == 1
        assert e["deprecationWarnings"][0]["revisionId"] == "rev-uuid-1"
        mock_db.list_sunset_timeline_entries.assert_called_once_with("test-tenant-id", None)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_sunset_timeline_unknown_project_404():
    """Optional projectId filter returns 404 when project is missing."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.versions_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = None
            response = client.get(
                "/v1/versions/test-tenant/sunset-timeline?projectId=missing-proj",
                headers={"Authorization": "Bearer unused"},
            )
        assert response.status_code == 404
        mock_db.list_sunset_timeline_entries.assert_not_called()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
