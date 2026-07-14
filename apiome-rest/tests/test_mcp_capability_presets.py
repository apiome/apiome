"""MCP capability presets — matrix helpers and GET catalog (MTG-5.1, #4785)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.main import app
from app.mcp_capability_presets import (
    CUSTOM_PRESET_ID,
    enabled_toolsets_for,
    list_presets,
    preset_by_id,
)

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_session_credentials] = _override_auth
    yield
    app.dependency_overrides.clear()


def test_named_presets_match_documented_matrix():
    presets = {p.id: p for p in list_presets()}
    assert set(presets) == {"catalog_only", "search_catalog", "full_read"}
    assert presets["catalog_only"].toolsets == ("health", "catalog")
    assert presets["search_catalog"].toolsets == ("health", "catalog", "search")
    assert presets["full_read"].toolsets == (
        "health",
        "catalog",
        "search",
        "document",
        "structure",
    )
    assert presets["catalog_only"].label == "Catalog only"
    assert presets["search_catalog"].label == "Search + catalog"
    assert presets["full_read"].label == "Full read"


def test_custom_is_not_a_named_preset():
    assert preset_by_id(CUSTOM_PRESET_ID) is None
    assert enabled_toolsets_for(CUSTOM_PRESET_ID) is None
    assert enabled_toolsets_for("nope") is None
    assert enabled_toolsets_for("catalog_only") == ("health", "catalog")


def test_mcp_capability_presets_catalog_returns_matrix():
    r = client.get("/api-keys/mcp-capability-presets")
    assert r.status_code == 200
    body = r.json()
    assert [p["id"] for p in body["presets"]] == [p.id for p in list_presets()]
    for item, preset in zip(body["presets"], list_presets(), strict=True):
        assert set(item) == {"id", "label", "toolsets"}
        assert item["id"] == preset.id
        assert item["label"] == preset.label
        assert item["toolsets"] == list(preset.toolsets)
    assert CUSTOM_PRESET_ID not in {p["id"] for p in body["presets"]}


def test_mcp_capability_presets_requires_auth():
    app.dependency_overrides.clear()
    r = client.get("/api-keys/mcp-capability-presets")
    assert r.status_code == 401
