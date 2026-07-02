from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg_pool import AsyncConnectionPool


@pytest.fixture(autouse=True)
def reset_mcp_logging_state() -> None:
    from apiome_mcp.logging_config import reset_logging_state_for_tests

    reset_logging_state_for_tests()
    yield
    reset_logging_state_for_tests()


@pytest.fixture
def mock_pool() -> MagicMock:
    """Shared mock AsyncConnectionPool for ping / lifespan tests."""
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
