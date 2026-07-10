"""Version mock chaos knob REST route tests (#4455, SIM-4.3)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

TENANT = "acme-corp"
PROJECT_ID = "proj-1"
VERSION_ID = "ver-1"
USER_ID = "user-1"
_AUTH = {"tenant_id": "t1", "user_id": USER_ID, "auth_method": "api_key"}

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"type": "array", "items": {"type": "object"}},
                            }
                        },
                    },
                }
            }
        }
    },
}

CHAOS_PAYLOAD = {
    "scenarios": {},
    "chaos": {
        "default": {"delayMs": 800, "jitterMs": 200, "errorRate": 10},
        "operations": {"get /pets": {"errorRate": 50}},
    },
}

STORED_SETTINGS = {
    "mode": "private",
    "chaos": {
        "default": {"delayMs": 800, "jitterMs": 200, "errorRate": 10.0},
        "operations": {"GET /pets": {"errorRate": 50.0}},
    },
}


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield TestClient(app)
    app.dependency_overrides.clear()


def _version_row(*, mock_settings: dict | None = None) -> dict:
    return {
        "id": VERSION_ID,
        "project_id": PROJECT_ID,
        "creator_id": USER_ID,
        "version_id": "1.0.0",
        "published": True,
        "mock_enabled": True,
        "mock_settings": mock_settings if mock_settings is not None else {},
        "project_slug": "petstore",
        "metadata": None,
    }


def test_get_returns_stored_chaos(client: TestClient) -> None:
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(mock_settings=STORED_SETTINGS),
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.get(f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios")
    assert resp.status_code == 200, resp.text
    chaos = resp.json()["chaos"]
    assert chaos["default"] == {"delayMs": 800, "jitterMs": 200, "errorRate": 10.0}
    assert chaos["operations"]["GET /pets"] == {"delayMs": None, "jitterMs": None, "errorRate": 50.0}


def test_get_without_chaos_returns_null(client: TestClient) -> None:
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(),
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.get(f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios")
    assert resp.status_code == 200
    assert resp.json()["chaos"] is None


def test_get_skips_malformed_chaos(client: TestClient) -> None:
    settings = {"chaos": {"default": {"delayMs": 90_000}}}
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(mock_settings=settings),
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.get(f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios")
    assert resp.status_code == 200
    assert resp.json()["chaos"] is None


def test_put_persists_canonical_chaos(client: TestClient) -> None:
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(),
    ), patch(
        "app.versions_routes._generated_spec_for_version",
        return_value=SPEC,
    ), patch(
        "app.versions_routes.db.set_version_mock_scenarios",
        return_value=_version_row(mock_settings=STORED_SETTINGS),
    ) as set_mock, patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios",
            json=CHAOS_PAYLOAD,
        )
    assert resp.status_code == 200, resp.text
    set_mock.assert_called_once()
    stored = set_mock.call_args.kwargs["chaos"]
    assert stored == {
        "default": {"delayMs": 800, "jitterMs": 200, "errorRate": 10.0},
        "operations": {"GET /pets": {"errorRate": 50.0}},
    }
    assert resp.json()["chaos"]["default"]["delayMs"] == 800


def test_put_without_chaos_clears_stored_block(client: TestClient) -> None:
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(mock_settings=STORED_SETTINGS),
    ), patch(
        "app.versions_routes._generated_spec_for_version",
        return_value=SPEC,
    ), patch(
        "app.versions_routes.db.set_version_mock_scenarios",
        return_value=_version_row(mock_settings={"mode": "private"}),
    ) as set_mock, patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios",
            json={"scenarios": {}},
        )
    assert resp.status_code == 200
    assert set_mock.call_args.kwargs["chaos"] is None
    assert resp.json()["chaos"] is None


def test_put_unknown_chaos_operation_returns_422(client: TestClient) -> None:
    payload = {"scenarios": {}, "chaos": {"operations": {"DELETE /pets": {"delayMs": 5}}}}
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(),
    ), patch(
        "app.versions_routes._generated_spec_for_version",
        return_value=SPEC,
    ), patch(
        "app.versions_routes.db.set_version_mock_scenarios",
    ) as set_mock, patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios",
            json=payload,
        )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert any("DELETE /pets" in error for error in detail["errors"])
    set_mock.assert_not_called()


def test_put_out_of_range_knob_rejected_by_model(client: TestClient) -> None:
    payload = {"scenarios": {}, "chaos": {"default": {"delayMs": 30_001}}}
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(),
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios",
            json=payload,
        )
    assert resp.status_code == 422


def test_put_scenario_scoped_chaos_round_trips(client: TestClient) -> None:
    payload = {
        "scenarios": {
            "degraded": {"operations": {}, "chaos": {"default": {"errorRate": 100}}}
        }
    }
    stored_settings = {
        "scenarios": {"degraded": {"operations": {}, "chaos": {"default": {"errorRate": 100.0}}}}
    }
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(),
    ), patch(
        "app.versions_routes._generated_spec_for_version",
        return_value=SPEC,
    ), patch(
        "app.versions_routes.db.set_version_mock_scenarios",
        return_value=_version_row(mock_settings=stored_settings),
    ) as set_mock, patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios",
            json=payload,
        )
    assert resp.status_code == 200, resp.text
    stored = set_mock.call_args.kwargs["scenarios"]
    assert stored["degraded"]["chaos"] == {"default": {"errorRate": 100.0}}
    assert resp.json()["scenarios"]["degraded"]["chaos"]["default"]["errorRate"] == 100.0
