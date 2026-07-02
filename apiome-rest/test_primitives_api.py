"""
Tests for Primitives REST API endpoints with dual authentication (JWT and API Key)
"""

import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_list_primitives_requires_auth():
    """Test that listing primitives requires authentication."""
    response = client.get('/v1/primitives/test-tenant')
    assert response.status_code == 401
    assert 'Authentication required' in response.json()['detail']


def test_list_primitives_invalid_jwt():
    """Test that invalid JWT token is rejected."""
    response = client.get(
        '/v1/primitives/test-tenant',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401


def test_list_primitives_invalid_api_key():
    """Test that invalid API key is rejected."""
    response = client.get(
        '/v1/primitives/test-tenant',
        headers={'X-API-Key': 'invalid-key'}
    )
    assert response.status_code == 401


def test_get_primitive_requires_auth():
    """Test that getting a primitive requires authentication."""
    response = client.get('/v1/primitives/test-tenant/some-id')
    assert response.status_code == 401


def test_create_primitive_requires_auth():
    """Test that creating a primitive requires authentication."""
    response = client.post(
        '/v1/primitives/test-tenant',
        json={'name': 'Test', 'category': 'string', 'schema': {'type': 'string'}}
    )
    assert response.status_code == 401


def test_update_primitive_requires_auth():
    """Test that updating a primitive requires authentication."""
    response = client.put(
        '/v1/primitives/test-tenant/some-id',
        json={'name': 'Updated'}
    )
    assert response.status_code == 401


def test_delete_primitive_requires_auth():
    """Test that deleting a primitive requires authentication."""
    response = client.delete('/v1/primitives/test-tenant/some-id')
    assert response.status_code == 401


def test_import_primitives_requires_auth():
    """Test that importing primitives requires authentication."""
    response = client.post(
        '/v1/primitives/test-tenant/import',
        json={'schema': {'$defs': {}}, 'import_all': True}
    )
    assert response.status_code == 401


def test_jwt_and_api_key_both_provided():
    """Test behavior when both JWT and API key are provided (JWT takes precedence)."""
    response = client.get(
        '/v1/primitives/test-tenant',
        headers={
            'Authorization': 'Bearer invalid-jwt',
            'X-API-Key': 'valid-key'
        }
    )
    # Should still fail because JWT is checked first and is invalid
    assert response.status_code in [401, 403]


