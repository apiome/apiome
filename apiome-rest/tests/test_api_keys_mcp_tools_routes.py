"""GET /api-keys/mcp-tools — MCP tool catalog (MTG-1.1, #4765)."""

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.main import app
from app.mcp_tool_registry import mcp_tool_descriptors, mcp_tool_ids

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_session_credentials] = _override_auth
    yield
    app.dependency_overrides.clear()


def test_mcp_tools_catalog_returns_every_registered_tool():
    r = client.get("/api-keys/mcp-tools")
    assert r.status_code == 200
    body = r.json()
    assert [tool["id"] for tool in body["tools"]] == mcp_tool_ids()
    assert len(body["tools"]) == len(mcp_tool_descriptors())


def test_mcp_tools_catalog_entries_are_fully_populated():
    body = client.get("/api-keys/mcp-tools").json()
    for tool, descriptor in zip(body["tools"], mcp_tool_descriptors(), strict=True):
        assert set(tool) == {"id", "description", "toolset"}
        assert tool["id"] == descriptor.id
        assert tool["description"] == descriptor.description
        assert tool["toolset"] == descriptor.toolset


def test_mcp_tools_catalog_is_deterministic():
    a = client.get("/api-keys/mcp-tools").json()
    b = client.get("/api-keys/mcp-tools").json()
    assert a == b


def test_mcp_tools_catalog_requires_auth():
    app.dependency_overrides.clear()
    r = client.get("/api-keys/mcp-tools")
    assert r.status_code == 401
