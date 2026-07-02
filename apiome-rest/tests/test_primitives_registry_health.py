"""Primitives type-registry skeleton: health/ping + auth scoping (#3450).

Covers the registry-layer health endpoint (anonymous, reports the
``apiome-db`` connection status backing ``apiome.primitives``) and confirms
the existing primitive data endpoints remain authenticated and tenant-scoped.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_registry_health_healthy():
    """A live apiome-db connection yields a healthy registry report."""
    with patch("app.primitives_routes.db") as mdb:
        mdb.registry_ping.return_value = {
            "connection": "connected",
            "storage_present": True,
        }
        r = client.get("/v1/primitives/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["service"] == "primitives-registry"
    assert body["database"] == "apiome-db"
    assert body["connection"] == "connected"
    assert body["storage_present"] is True
    assert body["error"] is None


def test_registry_health_reports_missing_storage_table():
    """A live connection but absent apiome.primitives is still healthy/connected."""
    with patch("app.primitives_routes.db") as mdb:
        mdb.registry_ping.return_value = {
            "connection": "connected",
            "storage_present": False,
        }
        r = client.get("/v1/primitives/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["connection"] == "connected"
    assert body["storage_present"] is False


def test_registry_health_unhealthy_on_connection_failure():
    """When the apiome-db probe raises, the registry reports unhealthy."""
    with patch("app.primitives_routes.db") as mdb:
        mdb.registry_ping.side_effect = RuntimeError("could not connect to server")
        r = client.get("/v1/primitives/health")

    assert r.status_code == 200  # probe must always be reachable (mirrors /health)
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["connection"] == "disconnected"
    assert body["storage_present"] is False
    assert "could not connect to server" in body["error"]


def test_registry_health_is_anonymous():
    """The health route requires no credentials and is not shadowed by the
    tenant-slug list route (``health`` must not be read as a tenant slug)."""
    with patch("app.primitives_routes.db") as mdb:
        mdb.registry_ping.return_value = {
            "connection": "connected",
            "storage_present": True,
        }
        r = client.get("/v1/primitives/health")  # no Authorization / X-API-Key

    assert r.status_code == 200
    # Proves we hit the health handler, not list_primitives(tenant_slug="health").
    assert r.json()["service"] == "primitives-registry"
    mdb.get_primitives_for_tenant.assert_not_called()


def test_primitive_list_requires_authentication():
    """Existing tenant-scoped data access stays authenticated (unaffected)."""
    r = client.get("/v1/primitives/acme")  # no credentials supplied
    assert r.status_code == 401
