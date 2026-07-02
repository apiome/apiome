"""HTTP ``/health`` custom route (Docker / load-balancer liveness)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.testclient import TestClient

from apiome_mcp.http_credential_middleware import HttpCredentialExtractionMiddleware


def test_health_returns_200_json(monkeypatch: pytest.MonkeyPatch, mock_pool: object) -> None:
    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 16)

    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()

    try:
        from apiome_mcp.server import mcp

        with patch("apiome_mcp.server.create_async_pool", return_value=mock_pool):
            app = mcp.http_app(
                path="/mcp",
                middleware=[StarletteMiddleware(HttpCredentialExtractionMiddleware)],
            )
            with TestClient(app) as client:
                response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        get_settings.cache_clear()
