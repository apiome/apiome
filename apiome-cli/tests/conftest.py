"""Shared pytest fixtures for apiome-cli."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from apiome_cli import config as config_module

_REAL_USER_CONFIG_PATH = config_module.user_config_path


@pytest.fixture(autouse=True)
def isolate_user_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent tests from reading the developer's real XDG config or package .env."""
    missing = Path("/nonexistent/apiome-cli-test-config.toml")
    monkeypatch.setattr(config_module, "user_config_path", lambda: missing)
    # Exclude the package ``.env`` (may set tenant_id) but still allow cwd ``.env``.
    monkeypatch.setattr(config_module, "CLI_ENV_FILES", (".env",))
    monkeypatch.setattr(
        config_module.CliSettings,
        "model_config",
        SettingsConfigDict(
            env_prefix="APIOME_",
            env_file=(".env",),
            extra="ignore",
        ),
    )
    isolated_cwd = tmp_path / "cwd"
    isolated_cwd.mkdir()
    monkeypatch.chdir(isolated_cwd)


@pytest.fixture
def real_user_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the real XDG config path resolver for path-resolution tests."""
    monkeypatch.setattr(config_module, "user_config_path", _REAL_USER_CONFIG_PATH)
