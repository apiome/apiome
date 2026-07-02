"""CLI configuration model and resolution (file, env, flags)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any
import typer
from uuid import UUID

from apiome_cli.extract.slug import slugify_project_name
from pydantic import HttpUrl, SecretStr, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from apiome_cli.exit_codes import EXIT_USAGE

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CLI_ENV_FILES = (str(_PACKAGE_ROOT / ".env"), ".env")

API_KEY_ENV_VAR = "APIOME_API_KEY"
API_KEY_HEADER = "X-API-Key"
SESSION_TOKEN_ENV_VAR = "APIOME_SESSION_TOKEN"
SESSION_AUTH_HEADER = "Authorization"

_MISSING_SESSION_TOKEN_MESSAGE = (
    "Session token required for this command. "
    f"Set {SESSION_TOKEN_ENV_VAR} or run `apiome config set session-token` "
    "after `POST /auth/login`."
)

APP_CONFIG_DIR_NAME = "apiome"
USER_CONFIG_FILE_NAME = "config.toml"

_MISSING_API_KEY_MESSAGE = (
    "API key required for this command. "
    f"Set {API_KEY_ENV_VAR}."
)

_CONFIG_FIELD_NAMES = frozenset({"base_url", "tenant_id", "api_key", "session_token"})
_CONFIG_FIELD_ORDER = ("base_url", "tenant_id", "api_key", "session_token")

CONFIG_CLI_KEYS = frozenset({"base-url", "tenant", "api-key", "session-token"})
CLI_KEY_TO_FIELD = {
    "base-url": "base_url",
    "tenant": "tenant_id",
    "api-key": "api_key",
    "session-token": "session_token",
}
FIELD_TO_CLI_KEY = {field: cli_key for cli_key, field in CLI_KEY_TO_FIELD.items()}


class ConfigFileError(ValueError):
    """Raised when the user config file exists but cannot be parsed."""


class EnvFileNotFoundError(FileNotFoundError):
    """Raised when ``--env-file`` points at a path that is not a regular file."""


def resolve_env_file_path(path: str) -> Path:
    """Resolve and validate an explicit ``--env-file`` path."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise EnvFileNotFoundError(resolved)
    return resolved


def user_config_path() -> Path:
    """Return the XDG user config file path for apiome-cli."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        base = Path(config_home)
    else:
        base = Path.home() / ".config"
    return base / APP_CONFIG_DIR_NAME / USER_CONFIG_FILE_NAME


def read_user_config_file(path: Path | None = None) -> dict[str, Any]:
    """Return settings stored in the user config file (empty dict if missing)."""
    config_path = path if path is not None else user_config_path()
    return _load_toml_config(config_path)


def mask_api_key(value: str) -> str:
    """Return a masked representation of an API key for display."""
    stripped = value.strip()
    if not stripped:
        return ""
    if len(stripped) <= 4:
        return "****"
    return f"{'*' * (len(stripped) - 4)}{stripped[-4:]}"


_TOML_ESCAPE_MAP: dict[str, str] = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_string(value: str) -> str:
    """Format a string as a TOML double-quoted literal.

    Escapes backslashes, double quotes, and all ASCII control characters
    so the resulting TOML file is always parseable regardless of the input.
    """
    parts: list[str] = []
    for ch in value:
        if ch in _TOML_ESCAPE_MAP:
            parts.append(_TOML_ESCAPE_MAP[ch])
        else:
            code = ord(ch)
            if code < 0x20 or code == 0x7F:
                parts.append(f"\\u{code:04X}")
            else:
                parts.append(ch)
    return '"' + "".join(parts) + '"'


def write_user_config_file(
    values: dict[str, Any],
    *,
    path: Path | None = None,
) -> None:
    """Persist supported settings keys to the user config TOML file."""
    config_path = path if path is not None else user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for field_name in _CONFIG_FIELD_ORDER:
        if field_name not in values:
            continue
        value = values[field_name]
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        lines.append(f"{field_name} = {_toml_string(text)}")

    if lines:
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif config_path.is_file():
        config_path.unlink()


def validate_config_set(field_name: str, value: str) -> str:
    """Validate and normalize a config file value for the given field name."""
    if field_name not in _CONFIG_FIELD_NAMES:
        raise KeyError(field_name)

    if field_name == "base_url":
        settings = CliSettings.model_validate({"base_url": value})
        return settings.base_url_str

    if field_name == "tenant_id":
        settings = CliSettings.model_validate({"tenant_id": value})
        tenant_id = settings.tenant_id
        if tenant_id is None:
            raise ValueError("tenant cannot be empty")
        return tenant_id

    secret = value.strip()
    if not secret:
        raise ValueError(f"{FIELD_TO_CLI_KEY[field_name]} cannot be empty")
    return secret


def resolve_config_cli_key(cli_key: str) -> str:
    """Map a CLI config key (kebab-case) to the internal field name."""
    field_name = CLI_KEY_TO_FIELD.get(cli_key)
    if field_name is None:
        allowed = ", ".join(sorted(CONFIG_CLI_KEYS))
        raise ValueError(f"Unknown config key {cli_key!r}. Expected one of: {allowed}.")
    return field_name


def _load_toml_config(path: Path) -> dict[str, Any]:
    """Load supported settings keys from a TOML config file."""
    if not path.is_file():
        return {}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigFileError(
            f"Cannot read config file {path}: {exc}",
        ) from exc
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigFileError(
            f"Invalid TOML in {path}: {exc}",
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigFileError(
            f"Config file {path} must be UTF-8: {exc}",
        ) from exc

    values: dict[str, Any] = {}
    for key, value in document.items():
        if key in _CONFIG_FIELD_NAMES and not isinstance(value, dict):
            values[key] = value

    section = document.get("apiome")
    if isinstance(section, dict):
        for key, value in section.items():
            if key in _CONFIG_FIELD_NAMES:
                values[key] = value

    return values


class TomlConfigSettingsSource(PydanticBaseSettingsSource):
    """Load defaults from the XDG user config TOML file."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        *,
        config_path: Path | None = None,
    ) -> None:
        super().__init__(settings_cls)
        path = config_path if config_path is not None else user_config_path()
        self._values = _load_toml_config(path)

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        return self._values.get(field_name), field_name, False

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        return value

    def __call__(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = self.get_field_value(
                field,
                field_name,
            )
            field_value = self.prepare_field_value(
                field_name,
                field,
                field_value,
                value_is_complex,
            )
            if field_value is not None:
                data[field_key] = field_value
        return data


class CliSettings(BaseSettings):
    """Runtime settings for the apiome CLI."""

    model_config = SettingsConfigDict(
        env_prefix="APIOME_",
        env_file=CLI_ENV_FILES,
        extra="ignore",
    )

    base_url: HttpUrl = HttpUrl("http://localhost:8000")
    tenant_id: str | None = None
    api_key: SecretStr | None = None
    session_token: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Apply clig.dev precedence: flags > env > dotenv > config file > defaults."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("tenant_id", mode="before")
    @classmethod
    def normalize_tenant_id(cls, value: Any) -> Any:
        """Accept a tenant UUID or URL slug in configuration."""
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return str(UUID(text))
        except ValueError:
            return slugify_project_name(text)

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: Any) -> Any:
        """Strip trailing slashes before URL validation."""
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            return value
        return text.rstrip("/")

    @property
    def base_url_str(self) -> str:
        """Normalized base URL string without a trailing slash."""
        return str(self.base_url).rstrip("/")

    def api_key_value(self) -> str | None:
        """Return the API key plaintext when configured."""
        if self.api_key is None:
            return None
        secret = self.api_key.get_secret_value().strip()
        return secret or None

    def session_token_value(self) -> str | None:
        """Return the UI session bearer token plaintext when configured."""
        if self.session_token is None:
            return None
        secret = self.session_token.get_secret_value().strip()
        return secret or None


def _cli_settings_from_sources(*, env_file: str | None = None) -> CliSettings:
    """Load settings from dotenv, env, TOML, and defaults."""
    if env_file is None:
        return CliSettings()
    return CliSettings(_env_file=(env_file,))


def load_settings(
    *,
    base_url: str | None = None,
    tenant_id: str | None = None,
    api_key: str | None = None,
    session_token: str | None = None,
    env_file: str | None = None,
) -> CliSettings:
    """Load settings from file/env, applying non-None CLI overrides (highest precedence)."""
    settings = _cli_settings_from_sources(env_file=env_file)

    updates: dict[str, Any] = {}
    if base_url is not None:
        updates["base_url"] = base_url
    if tenant_id is not None:
        updates["tenant_id"] = tenant_id
    if api_key is not None:
        updates["api_key"] = SecretStr(api_key)
    if session_token is not None:
        updates["session_token"] = SecretStr(session_token)
    if not updates:
        return settings
    merged = {
        "base_url": settings.base_url_str,
        "tenant_id": settings.tenant_id,
        "api_key": settings.api_key,
        "session_token": settings.session_token,
    }
    merged.update(updates)
    return CliSettings.model_validate(merged)


def require_api_key(settings: CliSettings) -> None:
    """Exit with usage code when a Tier 2 command has no API key configured."""
    if settings.api_key_value() is not None:
        return
    typer.echo(_MISSING_API_KEY_MESSAGE, err=True)
    raise typer.Exit(EXIT_USAGE)


def require_session_token(settings: CliSettings) -> None:
    """Exit with usage code when an auth command has no session token configured."""
    if settings.session_token_value() is not None:
        return
    typer.echo(_MISSING_SESSION_TOKEN_MESSAGE, err=True)
    raise typer.Exit(EXIT_USAGE)
