"""Endpoint tests for the Mock Server management + data planes (#3615, RC1-2.2)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.auth import validate_authentication
from src.app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

TENANT = "acme"
MOCK_ID = "00000000-0000-0000-0000-0000000000aa"

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Pet"},
                                    "minItems": 1,
                                }
                            }
                        },
                    }
                },
            }
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        },
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            }
        }
    },
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _instance_row(**overrides):
    """A representative odb.mock_instances row as returned by RealDictCursor."""
    row = {
        "id": MOCK_ID,
        "tenant_id": "t1",
        "version_id": "v1",
        "tenant_slug": TENANT,
        "project_slug": "petstore",
        "version_slug": "1.0.0",
        "name": "petstore mock",
        "spec": SPEC,
        "config": {"scenarios": [], "active_scenario": "happy-path", "seed": 0},
        "rate_limit_per_minute": 60,
        "status": "active",
        "created_by": "u1",
        "request_count": 0,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
        "last_activity_at": None,
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- #
# Management plane
# --------------------------------------------------------------------------- #


def test_provision_returns_base_url_and_metadata():
    version = {
        "id": "v1",
        "version_id": "1.0.0",
        "published": True,
        "project_description": "pets",
        "metadata": None,
        "project_metadata": None,
    }
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return _instance_row(
            spec=kwargs["spec"],
            config=kwargs["config"],
            rate_limit_per_minute=kwargs["rate_limit_per_minute"],
            expires_at=kwargs["expires_at"],
        )

    with patch("src.app.mock_routes.db.get_version_by_slugs", return_value=version), patch(
        "src.app.mock_routes._build_spec_for_version", return_value=SPEC
    ), patch("src.app.mock_routes.db.create_mock_instance", side_effect=_create):
        r = client.post(
            f"/v1/mocks/{TENANT}",
            json={"projectSlug": "petstore", "versionSlug": "1.0.0", "ttlHours": 12},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["baseUrl"].endswith(f"/v1/mock/{MOCK_ID}")
    assert body["operationCount"] == 2
    assert body["activeScenario"] == "happy-path"
    assert "server-error" in body["scenarios"]
    # TTL was honoured and frozen spec was passed through.
    assert captured["spec"] == SPEC


def test_provision_rejects_unpublished_version():
    version = {"id": "v1", "version_id": "1.0.0", "published": False}
    with patch("src.app.mock_routes.db.get_version_by_slugs", return_value=version):
        r = client.post(
            f"/v1/mocks/{TENANT}",
            json={"projectSlug": "petstore", "versionSlug": "1.0.0"},
        )
    assert r.status_code == 400


def test_provision_404_for_missing_version():
    with patch("src.app.mock_routes.db.get_version_by_slugs", return_value=None):
        r = client.post(
            f"/v1/mocks/{TENANT}",
            json={"projectSlug": "nope", "versionSlug": "9.9.9"},
        )
    assert r.status_code == 404


def test_provision_rejects_unknown_active_scenario():
    version = {"id": "v1", "version_id": "1.0.0", "published": True}
    with patch("src.app.mock_routes.db.get_version_by_slugs", return_value=version), patch(
        "src.app.mock_routes._build_spec_for_version", return_value=SPEC
    ):
        r = client.post(
            f"/v1/mocks/{TENANT}",
            json={
                "projectSlug": "petstore",
                "versionSlug": "1.0.0",
                "activeScenario": "ghost",
            },
        )
    assert r.status_code == 400


def test_list_mocks():
    with patch("src.app.mock_routes.db.list_mock_instances", return_value=[_instance_row()]):
        r = client.get(f"/v1/mocks/{TENANT}")
    assert r.status_code == 200
    assert r.json()[0]["id"] == MOCK_ID


def test_get_mock_detail_and_404():
    with patch("src.app.mock_routes.db.get_mock_instance_for_tenant", return_value=_instance_row()):
        r = client.get(f"/v1/mocks/{TENANT}/{MOCK_ID}")
    assert r.status_code == 200
    with patch("src.app.mock_routes.db.get_mock_instance_for_tenant", return_value=None):
        r = client.get(f"/v1/mocks/{TENANT}/{MOCK_ID}")
    assert r.status_code == 404


def test_switch_active_scenario():
    updated = _instance_row(
        config={"scenarios": [], "active_scenario": "server-error", "seed": 0}
    )
    with patch(
        "src.app.mock_routes.db.get_mock_instance_for_tenant", return_value=_instance_row()
    ), patch("src.app.mock_routes.db.update_mock_instance_config", return_value=updated):
        r = client.put(
            f"/v1/mocks/{TENANT}/{MOCK_ID}/active-scenario",
            json={"activeScenario": "server-error"},
        )
    assert r.status_code == 200
    assert r.json()["activeScenario"] == "server-error"


def test_switch_unknown_scenario_rejected():
    with patch(
        "src.app.mock_routes.db.get_mock_instance_for_tenant", return_value=_instance_row()
    ):
        r = client.put(
            f"/v1/mocks/{TENANT}/{MOCK_ID}/active-scenario",
            json={"activeScenario": "ghost"},
        )
    assert r.status_code == 400


def test_destroy_mock():
    with patch("src.app.mock_routes.db.delete_mock_instance", return_value=True):
        r = client.delete(f"/v1/mocks/{TENANT}/{MOCK_ID}")
    assert r.status_code == 204
    with patch("src.app.mock_routes.db.delete_mock_instance", return_value=False):
        r = client.delete(f"/v1/mocks/{TENANT}/{MOCK_ID}")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Data plane
# --------------------------------------------------------------------------- #


def test_data_plane_serves_schema_valid_response():
    mid = "00000000-0000-0000-0000-0000000000b1"
    with patch(
        "src.app.mock_routes.db.get_mock_instance", return_value=_instance_row(id=mid)
    ), patch("src.app.mock_routes.db.touch_mock_instance"):
        r = client.get(f"/v1/mock/{mid}/pets/7")
    assert r.status_code == 200
    body = r.json()
    assert set(["id", "name"]).issubset(body.keys())
    assert r.headers["X-Mock-Schema-Valid"] == "true"
    assert r.headers["X-Mock-Operation"] == "GET /pets/{petId}"


def test_data_plane_list_endpoint():
    mid = "00000000-0000-0000-0000-0000000000b2"
    with patch(
        "src.app.mock_routes.db.get_mock_instance", return_value=_instance_row(id=mid)
    ), patch("src.app.mock_routes.db.touch_mock_instance"):
        r = client.get(f"/v1/mock/{mid}/pets")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_data_plane_unknown_path_404():
    mid = "00000000-0000-0000-0000-0000000000b3"
    with patch(
        "src.app.mock_routes.db.get_mock_instance", return_value=_instance_row(id=mid)
    ), patch("src.app.mock_routes.db.touch_mock_instance"):
        r = client.get(f"/v1/mock/{mid}/widgets")
    assert r.status_code == 404
    assert r.headers["X-Mock-Matched"] == "false"


def test_data_plane_missing_instance_404():
    with patch("src.app.mock_routes.db.get_mock_instance", return_value=None):
        r = client.get("/v1/mock/00000000-0000-0000-0000-0000000000b4/pets")
    assert r.status_code == 404


def test_data_plane_expired_returns_410():
    mid = "00000000-0000-0000-0000-0000000000b5"
    expired = _instance_row(
        id=mid, expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    with patch("src.app.mock_routes.db.get_mock_instance", return_value=expired):
        r = client.get(f"/v1/mock/{mid}/pets")
    assert r.status_code == 410


def test_data_plane_scenario_header_overrides():
    mid = "00000000-0000-0000-0000-0000000000b6"
    with patch(
        "src.app.mock_routes.db.get_mock_instance", return_value=_instance_row(id=mid)
    ), patch("src.app.mock_routes.db.touch_mock_instance"):
        r = client.get(
            f"/v1/mock/{mid}/pets/1", headers={"X-Mock-Scenario": "server-error"}
        )
    assert r.status_code == 500
    assert r.headers["X-Mock-Scenario"] == "server-error"


def test_data_plane_per_instance_rate_limit():
    mid = "00000000-0000-0000-0000-0000000000b7"
    row = _instance_row(id=mid, rate_limit_per_minute=2)
    with patch("src.app.mock_routes.db.get_mock_instance", return_value=row), patch(
        "src.app.mock_routes.db.touch_mock_instance"
    ):
        statuses = [client.get(f"/v1/mock/{mid}/pets").status_code for _ in range(3)]
    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429


def test_data_plane_respects_feature_flag(monkeypatch):
    monkeypatch.setattr("src.app.mock_routes.settings.mock_server_enabled", False)
    r = client.get("/v1/mock/00000000-0000-0000-0000-0000000000b8/pets")
    assert r.status_code == 404
