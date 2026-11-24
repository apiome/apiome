"""Shared pytest fixtures for apiome-mock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg_pool import AsyncConnectionPool


@pytest.fixture(autouse=True)
def disable_grpc_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MOCK_GRPC_ENABLED", "false")
    from apiome_mock.settings import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_mock_logging_state() -> None:
    from apiome_mock.logging_config import reset_logging_state_for_tests

    reset_logging_state_for_tests()
    yield
    reset_logging_state_for_tests()


@pytest.fixture
def mock_pool() -> MagicMock:
    exec_mock = AsyncMock()
    conn = MagicMock()
    conn.execute = exec_mock
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = None
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm)
    pool.open = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def reset_request_path_caches() -> None:
    """Empty the process-wide request-path caches and usage/audit writers (#7207, DBP-1.24)."""
    from apiome_mock import audit
    from apiome_mock.api_key import clear_api_key_cache
    from apiome_mock.spec_loader import clear_access_cache
    from apiome_mock.tenant_limits import clear_limits_caches_for_tests
    from apiome_mock.usage import reset_usage_recorders_for_tests

    def _reset() -> None:
        clear_access_cache()
        clear_api_key_cache()
        clear_limits_caches_for_tests()
        reset_usage_recorders_for_tests()
        audit._WRITERS.clear()

    _reset()
    yield
    _reset()
