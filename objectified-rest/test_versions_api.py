"""
Tests for Versions REST API endpoints with dual authentication (JWT and API Key)
"""

import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


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
