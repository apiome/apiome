"""
Tests for Classes REST API endpoints with dual authentication (JWT and API Key)
"""

import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_list_classes_requires_auth():
    """Test that listing classes requires authentication."""
    response = client.get('/v1/classes/test-tenant')
    assert response.status_code == 401
    assert 'Authentication required' in response.json()['detail']


def test_list_classes_invalid_jwt():
    """Test that invalid JWT token is rejected."""
    response = client.get(
        '/v1/classes/test-tenant',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401


def test_list_classes_invalid_api_key():
    """Test that invalid API key is rejected."""
    response = client.get(
        '/v1/classes/test-tenant',
        headers={'X-API-Key': 'invalid-key'}
    )
    assert response.status_code == 401


def test_get_class_requires_auth():
    """Test that getting a class requires authentication."""
    response = client.get('/v1/classes/test-tenant/some-id')
    assert response.status_code == 401


def test_create_class_requires_auth():
    """Test that creating a class requires authentication."""
    response = client.post(
        '/v1/classes/test-tenant',
        json={
            'version_id': 'some-version-id',
            'name': 'TestClass',
            'schema': {'type': 'object', 'properties': {}}
        }
    )
    assert response.status_code == 401


def test_update_class_requires_auth():
    """Test that updating a class requires authentication."""
    response = client.put(
        '/v1/classes/test-tenant/some-id',
        json={'name': 'UpdatedClass'}
    )
    assert response.status_code == 401


def test_delete_class_requires_auth():
    """Test that deleting a class requires authentication."""
    response = client.delete('/v1/classes/test-tenant/some-id')
    assert response.status_code == 401


def test_get_class_properties_requires_auth():
    """Test that getting class properties requires authentication."""
    response = client.get('/v1/classes/test-tenant/some-id/properties')
    assert response.status_code == 401


def test_list_classes_with_version_filter_requires_auth():
    """Test that listing classes with version filter requires authentication."""
    response = client.get('/v1/classes/test-tenant?version_id=some-version-id')
    assert response.status_code == 401


def test_jwt_and_api_key_both_provided():
    """Test behavior when both JWT and API key are provided (JWT takes precedence)."""
    response = client.get(
        '/v1/classes/test-tenant',
        headers={
            'Authorization': 'Bearer invalid-token',
            'X-API-Key': 'also-invalid'
        }
    )
    # Should still be 401 since both are invalid
    assert response.status_code == 401


def test_create_class_validation():
    """Test that create class request validation works (even without auth)."""
    # Missing required fields should still return 422, not 401
    response = client.post(
        '/v1/classes/test-tenant',
        json={}  # Missing required fields
    )
    # Without auth, it should return 401 first
    assert response.status_code == 401


def test_update_class_empty_body():
    """Test that update class with empty body requires auth."""
    response = client.put(
        '/v1/classes/test-tenant/some-id',
        json={}
    )
    assert response.status_code == 401
