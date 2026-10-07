"""Environment-backed settings for the MCP server process."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apiome_mcp.mock_target import normalize_base_url

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Transport = Literal["stdio", "http"]


class Settings(BaseSettings):
    """Configuration loaded when ``apiome-mcp serve`` starts (fail-fast validation)."""

    model_config = SettingsConfigDict(
        env_prefix="APIOME_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: PostgresDsn = Field(
        ...,
        description="PostgreSQL connection URI for the Apiome database.",
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
    openai_api_key: SecretStr | None = Field(
        default=None,
        description="Bearer token for OpenAI-compatible /v1/embeddings (spec.search_semantic query vectors).",
    )
    openai_embedding_url: str = Field(
        default="https://api.openai.com/v1/embeddings",
        min_length=8,
        description="HTTP endpoint for embedding requests.",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        min_length=1,
        description="Embedding model name passed to the embeddings API.",
    )
    openai_embedding_dimensions: int = Field(
        default=1536,
        ge=8,
        le=3072,
        description="Vector width; must match apiome.versions.mcp_public_embedding and the model output.",
    )
    openai_embedding_timeout_s: float = Field(
        default=60.0,
        gt=0,
        le=600.0,
        description="HTTP timeout for embedding requests.",
    )
    mock_public_base_url: str = Field(
        default="http://localhost:8775",
        min_length=1,
        description=(
            "Public root of the hosted SIM mock runtime (no trailing slash). AGX-2.4 toolsets "
            "with target='mock' route tools/call to {root}/{tenant}/{project}/{version}. Mirrors "
            "apiome-rest's APIOME_MOCK_PUBLIC_BASE_URL so agents and the Control Panel agree."
        ),
    )
    anonymous_policy_tenant_id: UUID | None = Field(
        default=None,
        description=(
            "Host tenant whose MCP policy governs anonymous tools/call (MTG-2.3). "
            "When unset, anonymous callers are not gated (legacy passthrough)."
        ),
    )

    agent_usage_sweep_interval_seconds: int = Field(
        default=3600,
        ge=0,
        le=86_400,
        description=(
            "AGX-3.3: seconds between agent usage sweeps (daily rollups + per-tier retention) run by "
            "the server. 0 disables the in-process sweep (run `apiome-mcp agent-usage sweep` from cron)."
        ),
    )
    agent_usage_sweep_batch_size: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
        description="AGX-3.3: most rows each retention purge deletes per sweep tick.",
    )
    agent_usage_finalize_grace_hours: int = Field(
        default=6,
        ge=1,
        le=72,
        description=(
            "AGX-3.3: hours after a UTC day ends before its rollup is final and its raw rows may be "
            "pruned. Must exceed the longest agent call."
        ),
    )
    agent_upstream_use_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        description="AGX-2.2 upstream credential-use ledger retention, applied by the AGX-3.3 sweep.",
    )
    agent_quota_limits_cache_seconds: float = Field(
        default=60.0,
        ge=0,
        le=3600,
        description=(
            "AGX-3.2: seconds a tenant's agent key caps (license tier) are cached; a tier change "
            "applies within this time."
        ),
    )
    agent_quota_usage_cache_seconds: float = Field(
        default=5.0,
        ge=0,
        le=300,
        description=(
            "AGX-3.2: seconds between re-reads of an agent key's daily call count from "
            "agent_invocations. Longer is cheaper; across instances a key can overshoot its daily "
            "cap by about (instances - 1) x rps x this."
        ),
    )

    mock_invocation_base_url: str | None = Field(
        default=None,
        description=(
            "AGX-2.1: root of the SIM mock as this process reaches it, when that differs from "
            "mock_public_base_url (e.g. http://mock:8775 inside docker compose). Unset = the public root."
        ),
    )
    agent_upstream_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        description="AGX-2.1: most seconds one upstream attempt of an agent tools/call may take.",
    )
    agent_upstream_connect_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=60,
        description="AGX-2.1: most seconds opening the upstream connection may take.",
    )
    agent_upstream_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "AGX-2.1: retries after the first upstream attempt. Idempotent methods retry on timeouts, dropped "
            "connections and 502/503/504; other methods only when the connection could not be opened."
        ),
    )
    agent_upstream_budget_seconds: float = Field(
        default=45.0,
        gt=0,
        le=600,
        description="AGX-2.1: most seconds all upstream attempts and back-off pauses of one call may take together.",
    )
    agent_upstream_backoff_seconds: float = Field(
        default=0.2,
        ge=0,
        le=30,
        description="AGX-2.1: pause before the first upstream retry; doubles each retry.",
    )
    agent_response_max_bytes: int = Field(
        default=65_536,
        ge=1024,
        le=10_000_000,
        description=(
            "AGX-2.1: most upstream response-body bytes returned to the agent; longer bodies are cut and "
            "marked truncated."
        ),
    )
    agent_toolset_cache_size: int = Field(
        default=256,
        ge=1,
        le=100_000,
        description="AGX-2.1: compiled agent toolsets kept in memory per process.",
    )

    @model_validator(mode="after")
    def pool_size_bounds(self) -> Self:
        if self.database_pool_max_size < self.database_pool_min_size:
            raise ValueError(
                "database_pool_max_size must be greater than or equal to database_pool_min_size",
            )
        return self

    @field_validator("mock_public_base_url")
    @classmethod
    def validate_mock_public_base_url(cls, value: str) -> str:
        """Fail fast on a mock root that is not an absolute http(s) URL; strip trailing slashes."""
        return normalize_base_url("mock_public_base_url", value)

    @field_validator("mock_invocation_base_url")
    @classmethod
    def validate_mock_invocation_base_url(cls, value: str | None) -> str | None:
        """Same rule as the public root; blank means unset."""
        if value is None or not value.strip():
            return None
        return normalize_base_url("mock_invocation_base_url", value)

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
