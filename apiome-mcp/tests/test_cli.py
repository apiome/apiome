from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_MIN_ENV = {
    "APIOME_MCP_DATABASE_URL": "postgresql://localhost/db",
    "APIOME_MCP_INTERNAL_SECRET": "x" * 16,
}


def test_module_help_prints_usage() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "apiome_mcp", "--help"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
    )
    assert "apiome-mcp" in result.stdout
    assert result.stderr == ""


def test_keys_revoke_invokes_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.cli import main
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    for key, value in _MIN_ENV.items():
        monkeypatch.setenv(key, value)

    recorded: list[str] = []

    async def stub_revoke(prefix: str) -> int:
        recorded.append(prefix)
        return 0

    monkeypatch.setattr("apiome_mcp.cli._run_keys_revoke", stub_revoke)
    monkeypatch.setattr(sys, "argv", ["apiome-mcp", "keys", "revoke", "abcdefghijkl"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert recorded == ["abcdefghijkl"]
    get_settings.cache_clear()


def test_keys_revoke_rejects_invalid_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.cli import main
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    for key, value in _MIN_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["apiome-mcp", "keys", "revoke", "..."])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    get_settings.cache_clear()


def test_console_script_entrypoint_prints_usage() -> None:
    """Validates the [project.scripts] entrypoint (cli.main) directly."""
    result = subprocess.run(
        [sys.executable, "-c", "from apiome_mcp.cli import main; main()"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
    )
    assert "apiome-mcp" in result.stdout
    assert result.returncode == 0


def test_package_version_matches_pyproject() -> None:
    import tomllib
    from pathlib import Path

    from apiome_mcp import __version__

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == data["project"]["version"]


def test_serve_validate_only_exits_without_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.cli import main
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    for key, value in _MIN_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["apiome-mcp", "serve"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    get_settings.cache_clear()


def test_serve_http_runs_catalog_and_agent_streamable_http(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.cli import main
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    for key, value in _MIN_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APIOME_MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("APIOME_MCP_HTTP_PORT", "9876")
    monkeypatch.setattr(
        sys,
        "argv",
        ["apiome-mcp", "serve", "--transport", "http", "--host", "127.0.0.1", "--port", "9999"],
    )
    import uvicorn
    from starlette.routing import Mount

    served: list[uvicorn.Server] = []

    async def fake_serve(self: uvicorn.Server, sockets: object = None) -> None:
        served.append(self)

    with patch.object(uvicorn.Server, "serve", fake_serve):
        main()
    assert len(served) == 1
    config = served[0].config
    assert (config.host, config.port, config.log_level, config.lifespan) == ("127.0.0.1", 9999, "info", "on")
    # AGX-2.1 (#4533): the catalog MCP at /mcp and the agent runtime at /agent/mcp, one port.
    mounts = {route.path: route for route in config.app.routes if isinstance(route, Mount)}
    assert set(mounts) == {"/agent", ""}
    catalog_paths = {getattr(route, "path", None) for route in mounts[""].app.routes}
    agent_paths = {getattr(route, "path", None) for route in mounts["/agent"].app.routes}
    assert {"/mcp", "/health"} <= catalog_paths
    assert "/mcp" in agent_paths
    for mounted in mounts.values():
        assert any(mw.cls.__name__ == "HttpCredentialExtractionMiddleware" for mw in mounted.app.user_middleware)
    get_settings.cache_clear()


def test_serve_http_rejects_bad_port(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.cli import main
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    for key, value in _MIN_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["apiome-mcp", "serve", "--transport", "http", "--port", "0"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    get_settings.cache_clear()


def test_serve_stdio_runs_fastmcp_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.cli import main
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    for key, value in _MIN_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["apiome-mcp", "serve", "--transport", "stdio"])
    mock_stdio = AsyncMock(return_value=None)
    with patch("apiome_mcp.server.mcp.run_stdio_async", mock_stdio):
        main()
    mock_stdio.assert_awaited_once()
    get_settings.cache_clear()


def test_server_module_exposes_mcp() -> None:
    from apiome_mcp.server import database_lifespan, mcp

    assert mcp.name == "Apiome"
    assert database_lifespan is not None
