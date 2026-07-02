"""Tests for CLI settings loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from apiome_cli import config as config_module
from apiome_cli.config import (
    API_KEY_ENV_VAR,
    CLI_ENV_FILES,
    CliSettings,
    ConfigFileError,
    EnvFileNotFoundError,
    _toml_string,
    load_settings,
    mask_api_key,
    read_user_config_file,
    require_api_key,
    require_session_token,
    resolve_config_cli_key,
    resolve_env_file_path,
    user_config_path,
    validate_config_set,
    write_user_config_file,
)
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_ENV_KEYS_TO_CLEAR = {
    API_KEY_ENV_VAR,
    "APIOME_BASE_URL",
    "APIOME_TENANT_ID",
}


def test_cli_settings_default_base_url() -> None:
    """Default base URL is localhost without a trailing slash."""
    settings = CliSettings(_env_file=None)
    assert settings.base_url_str == "http://localhost:8000"
    assert settings.tenant_id is None
    assert settings.api_key is None


def test_cli_env_files_include_package_dotenv() -> None:
    """Package .env is loaded when the cwd has no local .env file."""
    assert CLI_ENV_FILES == (str(config_module._PACKAGE_ROOT / ".env"), ".env")
    assert Path(CLI_ENV_FILES[0]).parent.name == "apiome-cli"


def test_base_url_strips_trailing_slash_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """APIOME_BASE_URL trailing slashes are removed."""
    monkeypatch.setenv("APIOME_BASE_URL", "https://api.example.com/")
    settings = CliSettings(_env_file=None)
    assert settings.base_url_str == "https://api.example.com"


def test_base_url_override_strips_trailing_slash() -> None:
    """load_settings base_url override normalizes slashes."""
    settings = load_settings(base_url="http://rest.local:9000///")
    assert settings.base_url_str == "http://rest.local:9000"


def test_invalid_base_url_override_rejected() -> None:
    """Invalid base_url override fails validation."""
    with pytest.raises(ValidationError):
        load_settings(base_url="not-a-url")


def test_tenant_id_parsed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """APIOME_TENANT_ID accepts a tenant UUID string."""
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_ID)
    settings = CliSettings(_env_file=None)
    assert settings.tenant_id == _TENANT_ID


def test_tenant_slug_parsed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """APIOME_TENANT_ID accepts a tenant slug."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    settings = CliSettings(_env_file=None)
    assert settings.tenant_id == "acme-corp"


def test_invalid_tenant_id_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenant values that cannot form a slug fail validation."""
    monkeypatch.setenv("APIOME_TENANT_ID", " / ")
    with pytest.raises(ValidationError):
        CliSettings(_env_file=None)


def test_invalid_tenant_id_override_rejected() -> None:
    """Invalid tenant_id override fails validation."""
    with pytest.raises(ValidationError):
        load_settings(tenant_id=" / ")


def test_api_key_loaded_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """APIOME_API_KEY is stored as a secret."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_secret")
    settings = CliSettings(_env_file=None)
    assert settings.api_key_value() == "obj_secret"


def test_load_settings_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI overrides win over environment variables."""
    monkeypatch.setenv("APIOME_BASE_URL", "http://from-env:8000")
    monkeypatch.setenv("APIOME_API_KEY", "env_key")
    settings = load_settings(
        base_url="http://from-cli:9000",
        api_key="cli_key",
    )
    assert settings.base_url_str == "http://from-cli:9000"
    assert settings.api_key_value() == "cli_key"


def test_require_api_key_exits_when_missing() -> None:
    """require_api_key raises typer.Exit when no key is configured."""
    settings = CliSettings(_env_file=None)
    with pytest.raises(typer.Exit) as exc_info:
        require_api_key(settings)
    assert exc_info.value.exit_code == EXIT_USAGE


def test_projects_list_missing_api_key_is_actionable() -> None:
    """Protected commands fail before HTTP when API key is absent."""
    env = {key: value for key, value in os.environ.items() if key not in _ENV_KEYS_TO_CLEAR}
    result = runner.invoke(app, ["projects", "list"], env=env)
    assert result.exit_code == EXIT_USAGE
    assert API_KEY_ENV_VAR in result.stderr
    assert "API key required" in result.stderr


def test_health_does_not_require_api_key(httpx_mock: object) -> None:
    """GET /health remains usable without credentials."""
    httpx_mock.add_response(url="http://localhost:8000/health", json={"status": "ok"})
    env = {key: value for key, value in os.environ.items() if key not in _ENV_KEYS_TO_CLEAR}
    env["APIOME_BASE_URL"] = "http://localhost:8000"
    result = runner.invoke(app, ["health"], env=env)
    assert result.exit_code == EXIT_SUCCESS


def test_user_config_path_default_under_home_config(
    real_user_config_path: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default config path is ~/.config/apiome/config.toml."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    expected = Path.home() / ".config" / "apiome" / "config.toml"
    assert user_config_path() == expected


def test_user_config_path_honors_xdg_config_home(
    real_user_config_path: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """XDG_CONFIG_HOME relocates the config file directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    expected = tmp_path / "xdg" / "apiome" / "config.toml"
    assert user_config_path() == expected


def test_toml_config_applies_when_env_omits_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Config file values apply when environment variables are unset."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'base_url = "https://from-toml.example.com"\n'
        f'tenant_id = "{_TENANT_ID}"\n'
        'api_key = "toml_key"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)

    settings = CliSettings(_env_file=None)
    assert settings.base_url_str == "https://from-toml.example.com"
    assert settings.tenant_id == _TENANT_ID
    assert settings.api_key_value() == "toml_key"


def test_env_overrides_toml_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Environment variables win over the user config file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'base_url = "https://from-toml.example.com"\n'
        'api_key = "toml_key"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)
    monkeypatch.setenv("APIOME_BASE_URL", "https://from-env.example.com")
    monkeypatch.setenv("APIOME_API_KEY", "env_key")

    settings = CliSettings(_env_file=None)
    assert settings.base_url_str == "https://from-env.example.com"
    assert settings.api_key_value() == "env_key"


def test_load_settings_reads_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """load_settings includes values from .env when present."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "APIOME_BASE_URL=https://from-dotenv.example.com\n"
        "APIOME_API_KEY=dotenv_key\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("APIOME_BASE_URL", raising=False)
    monkeypatch.delenv("APIOME_API_KEY", raising=False)

    settings = load_settings()
    assert settings.base_url_str == "https://from-dotenv.example.com"
    assert settings.api_key_value() == "dotenv_key"


def test_load_settings_cli_overrides_toml_and_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI overrides win over config file and environment."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'base_url = "https://from-toml.example.com"\n'
        'api_key = "toml_key"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)
    monkeypatch.setenv("APIOME_BASE_URL", "https://from-env.example.com")
    monkeypatch.setenv("APIOME_API_KEY", "env_key")

    settings = load_settings(
        base_url="https://from-cli.example.com",
        api_key="cli_key",
    )
    assert settings.base_url_str == "https://from-cli.example.com"
    assert settings.api_key_value() == "cli_key"


def test_global_flags_override_toml_and_env_via_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    httpx_mock: object,
) -> None:
    """Root flags override config file and environment for all subcommands."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'base_url = "https://from-toml.example.com"\n'
        f'tenant_id = "{_TENANT_ID}"\n'
        'api_key = "toml_key"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_KEYS_TO_CLEAR
    }
    env["APIOME_BASE_URL"] = "https://from-env.example.com"
    env["APIOME_API_KEY"] = "env_key"
    httpx_mock.add_response(
        url="https://from-cli.example.com/health",
        json={"status": "ok"},
    )
    result = runner.invoke(
        app,
        [
            "--base-url",
            "https://from-cli.example.com",
            "--api-key",
            "cli_key",
            "health",
        ],
        env=env,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert httpx_mock.get_requests()[0].url == "https://from-cli.example.com/health"


def test_apiome_section_in_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The [apiome] table is supported alongside top-level keys."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[apiome]\n"
        'base_url = "https://section.example.com"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)

    settings = CliSettings(_env_file=None)
    assert settings.base_url_str == "https://section.example.com"


def test_invalid_toml_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Invalid TOML in the user config file raises ConfigFileError."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("base_url = [\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "user_config_path", lambda: config_file)

    with pytest.raises(ConfigFileError, match=r"Invalid TOML in .+config\.toml"):
        CliSettings(_env_file=None)


def test_toml_string_escapes_backslash_and_quote() -> None:
    """_toml_string escapes backslashes and double quotes."""
    assert _toml_string('say "hello"') == r'"say \"hello\""'
    assert _toml_string("path\\to\\file") == r'"path\\to\\file"'


def test_toml_string_escapes_control_characters() -> None:
    """_toml_string escapes newlines, carriage returns, tabs, and other controls."""
    assert _toml_string("line1\nline2") == r'"line1\nline2"'
    assert _toml_string("col1\tcol2") == r'"col1\tcol2"'
    assert _toml_string("cr\rend") == r'"cr\rend"'
    # Backspace and form feed
    assert _toml_string("\b") == r'"\b"'
    assert _toml_string("\f") == r'"\f"'
    # Arbitrary control character (e.g. U+0001) uses \uXXXX notation
    assert _toml_string("\x01") == '"\\u0001"'
    assert _toml_string("\x7f") == '"\\u007F"'


def test_toml_string_control_chars_round_trip(tmp_path: Path) -> None:
    """Values with control characters produce parseable TOML that round-trips."""
    import tomllib

    raw = _toml_string("key\nwith\nnewlines\tand\ttabs")
    toml_text = f"api_key = {raw}\n"
    parsed = tomllib.loads(toml_text)
    assert parsed["api_key"] == "key\nwith\nnewlines\tand\ttabs"


def test_validate_config_set_normalizes_base_url() -> None:
    """validate_config_set strips trailing slashes from base_url."""
    assert (
        validate_config_set("base_url", "https://api.example.com///")
        == "https://api.example.com"
    )


def test_validate_config_set_accepts_tenant_uuid() -> None:
    """validate_config_set returns a canonical tenant UUID string."""
    assert validate_config_set("tenant_id", _TENANT_ID) == _TENANT_ID


def test_validate_config_set_rejects_invalid_tenant() -> None:
    """validate_config_set rejects tenant values that cannot form a slug."""
    with pytest.raises(ValidationError):
        validate_config_set("tenant_id", " / ")


def test_validate_config_set_strips_api_key() -> None:
    """validate_config_set trims whitespace from api_key values."""
    assert validate_config_set("api_key", "  obj_key  ") == "obj_key"


def test_validate_config_set_rejects_empty_api_key() -> None:
    """validate_config_set rejects blank api-key values."""
    with pytest.raises(ValueError, match="api-key cannot be empty"):
        validate_config_set("api_key", "   ")


def test_validate_config_set_unknown_field_raises_key_error() -> None:
    """validate_config_set only accepts supported field names."""
    with pytest.raises(KeyError):
        validate_config_set("unknown", "value")


def test_session_token_loaded_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """APIOME_SESSION_TOKEN is stored as a secret."""
    monkeypatch.setenv("APIOME_SESSION_TOKEN", "obj_sess_secret")
    settings = CliSettings(_env_file=None)
    assert settings.session_token_value() == "obj_sess_secret"


def test_require_session_token_exits_when_missing() -> None:
    """require_session_token exits with usage when no token is configured."""
    with pytest.raises(typer.Exit) as exc:
        require_session_token(CliSettings(_env_file=None))
    assert exc.value.exit_code == EXIT_USAGE


def test_validate_config_set_strips_session_token() -> None:
    """validate_config_set trims whitespace from session_token values."""
    assert validate_config_set("session_token", "  obj_sess_x  ") == "obj_sess_x"


def test_resolve_config_cli_key_maps_known_keys() -> None:
    """resolve_config_cli_key maps kebab-case CLI keys to field names."""
    assert resolve_config_cli_key("base-url") == "base_url"
    assert resolve_config_cli_key("tenant") == "tenant_id"
    assert resolve_config_cli_key("api-key") == "api_key"
    assert resolve_config_cli_key("session-token") == "session_token"


def test_resolve_config_cli_key_unknown_raises() -> None:
    """resolve_config_cli_key lists allowed keys for unknown input."""
    with pytest.raises(ValueError, match="Unknown config key"):
        resolve_config_cli_key("not-a-key")


def test_read_user_config_file_missing_returns_empty(tmp_path: Path) -> None:
    """read_user_config_file returns {} when the path does not exist."""
    missing = tmp_path / "missing.toml"
    assert read_user_config_file(missing) == {}


def test_read_user_config_file_ignores_nested_table_values(tmp_path: Path) -> None:
    """Top-level table values for config keys are ignored."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('base_url = { nested = "bad" }\n', encoding="utf-8")
    assert read_user_config_file(config_file) == {}


def test_read_user_config_file_invalid_utf8_raises(tmp_path: Path) -> None:
    """Non-UTF-8 config files raise ConfigFileError."""
    config_file = tmp_path / "config.toml"
    config_file.write_bytes(b"base_url = \xff\xfe\n")
    with pytest.raises(ConfigFileError, match="must be UTF-8"):
        read_user_config_file(config_file)


def test_write_user_config_file_skips_blank_values(tmp_path: Path) -> None:
    """write_user_config_file omits empty or whitespace-only values."""
    config_file = tmp_path / "config.toml"
    write_user_config_file(
        {
            "base_url": "https://cli.example.com",
            "tenant_id": "   ",
            "api_key": "",
        },
        path=config_file,
    )
    text = config_file.read_text(encoding="utf-8")
    assert 'base_url = "https://cli.example.com"' in text
    assert "tenant_id" not in text
    assert "api_key" not in text


def test_mask_api_key_empty_string() -> None:
    """mask_api_key returns an empty string for blank input."""
    assert mask_api_key("") == ""
    assert mask_api_key("   ") == ""


def test_load_settings_tenant_id_override_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """load_settings can override tenant_id without touching other fields."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".env").exists()
    monkeypatch.delenv("APIOME_BASE_URL", raising=False)
    monkeypatch.delenv("APIOME_TENANT_ID", raising=False)
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    settings = load_settings(tenant_id=_TENANT_ID)
    assert settings.tenant_id == _TENANT_ID
    assert settings.base_url_str == "http://localhost:8000"


def test_load_settings_reads_alternate_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """--env-file replaces the default dotenv chain."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "APIOME_BASE_URL=https://from-default-dotenv.example.com\n",
        encoding="utf-8",
    )
    alt_env = tmp_path / "staging.env"
    alt_env.write_text(
        "APIOME_BASE_URL=https://from-alt-env.example.com\n"
        "APIOME_API_KEY=alt_env_key\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("APIOME_BASE_URL", raising=False)
    monkeypatch.delenv("APIOME_API_KEY", raising=False)

    settings = load_settings(env_file=str(alt_env))
    assert settings.base_url_str == "https://from-alt-env.example.com"
    assert settings.api_key_value() == "alt_env_key"


def test_resolve_env_file_path_rejects_missing_file(tmp_path: Path) -> None:
    """resolve_env_file_path fails when the path does not exist."""
    missing = tmp_path / "missing.env"
    with pytest.raises(EnvFileNotFoundError):
        resolve_env_file_path(str(missing))


def test_global_env_file_flag_overrides_default_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    httpx_mock: object,
) -> None:
    """Root --env-file wins over the cwd .env for subcommands."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "APIOME_BASE_URL=https://from-default-dotenv.example.com\n",
        encoding="utf-8",
    )
    alt_env = tmp_path / "custom.env"
    alt_env.write_text(
        "APIOME_BASE_URL=https://from-alt-env.example.com\n",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_KEYS_TO_CLEAR
    }
    httpx_mock.add_response(
        url="https://from-alt-env.example.com/health",
        json={"status": "ok"},
    )
    result = runner.invoke(
        app,
        ["--env-file", str(alt_env), "health"],
        env=env,
    )
    assert result.exit_code == EXIT_SUCCESS


def test_global_env_file_missing_exits_usage(tmp_path: Path) -> None:
    """Root --env-file exits with usage when the file is missing."""
    missing = tmp_path / "missing.env"
    result = runner.invoke(app, ["--env-file", str(missing), "health"])
    assert result.exit_code == EXIT_USAGE
    assert "Env file not found" in result.stderr
