"""Tests for the ``apiome config`` subcommand."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from apiome_cli import config as config_module
from apiome_cli.config import (
    mask_api_key,
    read_user_config_file,
    user_config_path,
    write_user_config_file,
)
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_ENV_KEYS_TO_CLEAR = {
    "APIOME_API_KEY",
    "APIOME_BASE_URL",
    "APIOME_TENANT_ID",
}


@pytest.fixture
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Provide an isolated user config file path for config subcommand tests."""
    path = tmp_path / "apiome" / "config.toml"
    monkeypatch.setattr(config_module, "user_config_path", lambda: path)
    return path


def test_mask_api_key_hides_most_characters() -> None:
    """mask_api_key keeps only the last four characters visible."""
    assert mask_api_key("obj_super_secret_key") == "****************_key"
    assert mask_api_key("abcd") == "****"
    assert mask_api_key("ab") == "****"


def test_config_show_empty_when_file_missing(config_file: Path) -> None:
    """config show exits 0 with no output when the config file is absent."""
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout == ""


def test_config_show_masks_api_key(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config show masks api-key values read from the user config file."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        'base_url = "https://saved.example.com"\n'
        f'tenant_id = "{_TENANT_ID}"\n'
        'api_key = "obj_saved_secret"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == EXIT_SUCCESS
    assert "base-url = https://saved.example.com" in result.stdout
    assert f"tenant = {_TENANT_ID}" in result.stdout
    assert "api-key = ************cret" in result.stdout
    assert "obj_saved_secret" not in result.stdout


def test_config_set_base_url_persists_to_toml(config_file: Path) -> None:
    """config set base-url writes the normalized value to config.toml."""
    result = runner.invoke(
        app,
        ["config", "set", "base-url", "https://cli.example.com///"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert config_file.is_file()
    stored = read_user_config_file(config_file)
    assert stored["base_url"] == "https://cli.example.com"


def test_config_set_tenant_and_api_key(config_file: Path) -> None:
    """config set persists tenant and api-key alongside other keys."""
    runner.invoke(
        app,
        ["config", "set", "base-url", "https://cli.example.com"],
    )
    result = runner.invoke(
        app,
        ["config", "set", "tenant", _TENANT_ID],
    )
    assert result.exit_code == EXIT_SUCCESS
    result = runner.invoke(
        app,
        ["config", "set", "api-key", "obj_cli_key"],
    )
    assert result.exit_code == EXIT_SUCCESS

    stored = read_user_config_file(config_file)
    assert stored["base_url"] == "https://cli.example.com"
    assert stored["tenant_id"] == _TENANT_ID
    assert stored["api_key"] == "obj_cli_key"


def test_config_unset_removes_key(config_file: Path) -> None:
    """config unset removes one key and preserves the remaining values."""
    write_user_config_file(
        {
            "base_url": "https://cli.example.com",
            "tenant_id": _TENANT_ID,
            "api_key": "obj_cli_key",
        },
        path=config_file,
    )

    result = runner.invoke(app, ["config", "unset", "tenant"])
    assert result.exit_code == EXIT_SUCCESS

    stored = read_user_config_file(config_file)
    assert stored["base_url"] == "https://cli.example.com"
    assert "tenant_id" not in stored
    assert stored["api_key"] == "obj_cli_key"


def test_config_unset_last_key_deletes_file(config_file: Path) -> None:
    """Removing the final key deletes the config file."""
    write_user_config_file({"base_url": "https://cli.example.com"}, path=config_file)
    assert config_file.is_file()

    result = runner.invoke(app, ["config", "unset", "base-url"])
    assert result.exit_code == EXIT_SUCCESS
    assert not config_file.exists()


def test_config_set_invalid_base_url_exits_usage(config_file: Path) -> None:
    """Invalid base-url values exit with usage code."""
    result = runner.invoke(app, ["config", "set", "base-url", "not-a-url"])
    assert result.exit_code == EXIT_USAGE
    assert not config_file.exists()


def test_config_set_invalid_tenant_exits_usage(config_file: Path) -> None:
    """Invalid tenant slug values exit with usage code."""
    result = runner.invoke(app, ["config", "set", "tenant", " / "])
    assert result.exit_code == EXIT_USAGE


def test_config_unknown_key_exits_usage() -> None:
    """Unknown config keys exit with usage code."""
    result = runner.invoke(app, ["config", "set", "unknown-key", "value"])
    assert result.exit_code == EXIT_USAGE
    assert "Unknown config key" in result.stderr


def test_config_show_invalid_toml_exits_usage(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid TOML in the user config file surfaces as a usage error."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("base_url = [\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == EXIT_USAGE
    assert "Invalid TOML" in result.stderr


def test_config_subcommand_help_exits_zero() -> None:
    """config --help documents show, set, and unset."""
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "show" in result.stdout
    assert "set" in result.stdout
    assert "unset" in result.stdout


def test_root_help_lists_config_subcommand() -> None:
    """Root help includes the config subcommand."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "config" in result.stdout


def test_config_set_does_not_require_api_key_env(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config set works without APIOME_API_KEY in the environment."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_KEYS_TO_CLEAR
    }
    result = runner.invoke(
        app,
        ["config", "set", "base-url", "https://cli.example.com"],
        env=env,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert read_user_config_file(config_file)["base_url"] == "https://cli.example.com"


def test_user_config_path_used_by_config_set(
    real_user_config_path: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """config set writes to the resolved XDG config path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    expected = user_config_path()

    result = runner.invoke(
        app,
        ["config", "set", "base-url", "https://xdg.example.com"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert expected.is_file()
    assert read_user_config_file(expected)["base_url"] == "https://xdg.example.com"


def test_config_set_api_key_with_control_characters_produces_valid_toml(
    config_file: Path,
) -> None:
    """api-key values with embedded control characters still produce parseable TOML."""
    result = runner.invoke(
        app,
        ["config", "set", "api-key", "key\nwith\nnewlines"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert config_file.is_file()
    # The raw TOML must contain escaped newlines (not bare newlines in the value)
    raw = config_file.read_text(encoding="utf-8")
    assert "\\n" in raw
    # The round-tripped value is recoverable via read_user_config_file
    stored = read_user_config_file(config_file)
    assert stored["api_key"] == "key\nwith\nnewlines"


def test_config_set_write_failure_exits_usage(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config set exits with usage code when writing to disk fails."""
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)
    with patch(
        "apiome_cli.commands.config.write_user_config_file",
        side_effect=OSError("Permission denied"),
    ):
        result = runner.invoke(
            app,
            ["config", "set", "base-url", "https://cli.example.com"],
        )
    assert result.exit_code == EXIT_USAGE
    assert "Permission denied" in result.stderr


def test_config_unset_write_failure_exits_usage(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config unset exits with usage code when writing to disk fails."""
    write_user_config_file({"base_url": "https://cli.example.com"}, path=config_file)
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)
    with patch(
        "apiome_cli.commands.config.write_user_config_file",
        side_effect=OSError("Permission denied"),
    ):
        result = runner.invoke(app, ["config", "unset", "base-url"])
    assert result.exit_code == EXIT_USAGE
    assert "Permission denied" in result.stderr
