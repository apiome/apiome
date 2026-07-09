"""Settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apiome_mock.settings import Settings, get_settings


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APIOME_MOCK_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings()
    get_settings.cache_clear()


def test_settings_pool_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MOCK_DATABASE_POOL_MIN_SIZE", "5")
    monkeypatch.setenv("APIOME_MOCK_DATABASE_POOL_MAX_SIZE", "2")
    with pytest.raises(ValidationError):
        Settings()
