"""HTTP ``/health`` route tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apiome_mock.spec_cache import SpecCache


def test_health_returns_200_json(monkeypatch: pytest.MonkeyPatch, mock_pool: object) -> None:
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    from apiome_mock.settings import get_settings

    get_settings.cache_clear()
    try:
        from apiome_mock.server import create_app

        with patch("apiome_mock.server.create_async_pool", return_value=mock_pool):
            app = create_app()
            app.state.db_pool = mock_pool
            app.state.spec_cache = SpecCache(max_entries=8, ttl_seconds=60.0)
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        get_settings.cache_clear()
