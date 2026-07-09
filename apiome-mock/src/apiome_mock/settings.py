"""Environment-backed settings for the mock server process."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Configuration loaded when ``apiome-mock serve`` starts (fail-fast validation)."""

    model_config = SettingsConfigDict(
        env_prefix="APIOME_MOCK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: PostgresDsn = Field(
        ...,
        description="PostgreSQL connection URI for the Apiome database.",
    )
    log_level: LogLevel = Field(default="INFO")
    http_host: str = Field(default="127.0.0.1", min_length=1)
    http_port: int = Field(default=8775, ge=1, le=65535)
    database_pool_min_size: int = Field(default=1, ge=1, le=256)
    database_pool_max_size: int = Field(default=10, ge=1, le=256)
    database_pool_timeout: float = Field(default=30.0, gt=0, le=600.0)
    spec_cache_max_entries: int = Field(
        default=128,
        ge=1,
        le=10_000,
        description="Maximum compiled specs held in the in-process LRU cache.",
    )
    spec_cache_ttl_seconds: float = Field(
        default=300.0,
        gt=0,
        le=86_400.0,
        description="TTL fallback for compiled spec cache entries (seconds).",
    )
    spec_notify_channel: str = Field(
        default="apiome_mock_spec_published",
        min_length=1,
        description="Postgres NOTIFY channel for publish-driven cache invalidation.",
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
    return Settings()  # type: ignore[call-arg]
