"""API tests for registry coverage/stats endpoint (#3454)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_ADMIN = {"tenant_id": "t1", "user_id": "admin-user", "auth_method": "jwt"}


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_ADMIN
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_registry_stats_ok():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.get_registry_coverage_stats.return_value = {
            "core_type_count": 36,
            "tenant_type_count": 12,
            "imported_count": 5,
            "properties_bound_count": 42,
            "bound_class_count": 8,
            "unresolved_ref_count": 3,
            "namespace_count": 4,
        }
        r = client.get("/v1/types/acme/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["core_type_count"] == 36
    assert data["tenant_type_count"] == 12
    assert data["imported_count"] == 5
    assert data["properties_bound_count"] == 42
    assert data["bound_class_count"] == 8
    assert data["unresolved_ref_count"] == 3
    assert data["namespace_count"] == 4
    mdb.get_registry_coverage_stats.assert_called_once_with("t1")


def test_registry_stats_requires_auth():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get("/v1/types/acme/stats")
    assert r.status_code in (401, 403)
