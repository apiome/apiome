"""Paths canvas persistence API (#2642)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_get_canvas_ok_defaults():
    with patch("app.paths_routes.db") as mdb:
        mdb.get_version_for_tenant.return_value = {"id": "ver-1"}
        mdb.get_path_canvas.return_value = {
            "nodes": [],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "updated_at": None,
        }
        r = client.get("/v1/paths/acme/ver-1/path-a/canvas")
        assert r.status_code == 200
        d = r.json()
        assert d["nodes"] == []
        assert d["edges"] == []
        assert d["viewport"]["zoom"] == 1
        mdb.get_path_canvas.assert_called_once_with("ver-1", "path-a", "t1")


def test_get_canvas_version_404():
    with patch("app.paths_routes.db") as mdb:
        mdb.get_version_for_tenant.return_value = None
        r = client.get("/v1/paths/acme/ver-1/path-a/canvas")
        assert r.status_code == 404


def test_put_canvas_ok():
    with patch("app.paths_routes.db") as mdb:
        mdb.get_version_for_tenant.return_value = {"id": "ver-1"}
        mdb.upsert_path_canvas.return_value = {
            "nodes": [{"id": "n1"}],
            "edges": [],
            "viewport": {"x": 1, "y": 2, "zoom": 0.5},
            "updated_at": "2026-04-13T12:00:00Z",
        }
        r = client.put(
            "/v1/paths/acme/ver-1/path-a/canvas",
            json={
                "nodes": [{"id": "n1"}],
                "edges": [],
                "viewport": {"x": 1, "y": 2, "zoom": 0.5},
            },
        )
        assert r.status_code == 200
        d = r.json()
        assert d["nodes"][0]["id"] == "n1"
        mdb.upsert_path_canvas.assert_called_once()


def test_put_canvas_path_mismatch_404():
    with patch("app.paths_routes.db") as mdb:
        mdb.get_version_for_tenant.return_value = {"id": "ver-1"}
        mdb.upsert_path_canvas.return_value = None
        r = client.put(
            "/v1/paths/acme/ver-1/path-a/canvas",
            json={"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}},
        )
        assert r.status_code == 404
