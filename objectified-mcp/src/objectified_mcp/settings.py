"""Environment-backed settings for the MCP server process."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Transport = Literal["stdio", "http"]


class Settings(BaseSettings):
    """Configuration loaded when ``objectified-mcp serve`` starts (fail-fast validation)."""

    model_config = SettingsConfigDict(
        env_prefix="OBJECTIFIED_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: PostgresDsn = Field(
        ...,
        description="PostgreSQL connection URI for the Objectified database.",
    )
    internal_secret: SecretStr = Field(
        ...,
        min_length=16,
        description="Secret material for internal signing (e.g. HMAC, session derivation).",
    )
    log_level: LogLevel = Field(default="INFO")
    transport: Transport = Field(default="stdio")
    http_host: str = Field(default="127.0.0.1", min_length=1)
    http_port: int = Field(default=8765, ge=1, le=65535)
    database_pool_min_size: int = Field(default=1, ge=1, le=256)
    database_pool_max_size: int = Field(default=10, ge=1, le=256)
    database_pool_timeout: float = Field(default=30.0, gt=0, le=600.0)
    openapi_max_json_bytes: int = Field(
        default=2_097_152,
        ge=1024,
        le=100_000_000,
        description=(
            "Max UTF-8 size of exported OpenAPI from spec.get_openapi (compact JSON) and "
            "spec.export_yaml (YAML text); 413-style limit."
        ),
    )

    @model_validator(mode="after")
    def pool_size_bounds(self) -> Self:
        if self.database_pool_max_size < self.database_pool_min_size:
            raise ValueError(
                "database_pool_max_size must be greater than or equal to database_pool_min_size",
            )
        return self

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> str:
        if isinstance(value, str):
            return value.upper()
        return str(value).upper()


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings (parsed once per interpreter)."""
    # Required fields are populated from the environment by pydantic-settings.
    return Settings()  # type: ignore[call-arg]
