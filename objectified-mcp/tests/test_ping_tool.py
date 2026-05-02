from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

from objectified_mcp import __version__
from objectified_mcp.ping_tool import build_ping_response


def test_build_ping_response_ok(mock_pool: MagicMock) -> None:
    async def run() -> dict[str, object]:
        return await build_ping_response(mock_pool)

    result = asyncio.run(run())
    assert result["service"] == "objectified-mcp"
    assert result["version"] == __version__
    assert result["db_ok"] is True
    assert "db_error" not in result
    parsed = datetime.fromisoformat(str(result["ts"]).replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_build_ping_response_db_failure_includes_error_string(mock_pool: MagicMock) -> None:
    mock_pool.connection.side_effect = OSError("connection refused")

    async def run() -> dict[str, object]:
        return await build_ping_response(mock_pool)

    result = asyncio.run(run())

    assert result["service"] == "objectified-mcp"
    assert result["version"] == __version__
    assert result["db_ok"] is False
    assert result["db_error"] == "connection refused"
    assert result["ts"]


def test_build_ping_response_db_error_redacts_dsn(mock_pool: MagicMock) -> None:
    """DSN fragments (credentials/hostnames) must be stripped from the returned error."""
    mock_pool.connection.side_effect = OSError(
        "could not connect: postgresql://admin:s3cr3t@db.internal:5432/app"
    )

    async def run() -> dict[str, object]:
        return await build_ping_response(mock_pool)

    result = asyncio.run(run())

    assert result["db_ok"] is False
    error = result["db_error"]
    assert "s3cr3t" not in error
    assert "admin" not in error
    assert "[redacted]" in error


def test_build_ping_response_db_error_is_capped(mock_pool: MagicMock) -> None:
    """Very long error messages must be truncated so payloads stay bounded."""
    from objectified_mcp.ping_tool import _MAX_DB_ERROR_LEN

    mock_pool.connection.side_effect = OSError("x" * 500)

    async def run() -> dict[str, object]:
        return await build_ping_response(mock_pool)

    result = asyncio.run(run())

    assert result["db_ok"] is False
    assert len(result["db_error"]) <= _MAX_DB_ERROR_LEN + len("...")


def test_ping_tool_registered_on_mcp() -> None:
    from objectified_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("ping")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "ping"
