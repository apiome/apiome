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
    database_pool_max_waiting: int = Field(
        default=100,
        ge=0,
        le=100_000,
        description=(
            "Requests allowed to queue for a pooled connection before new ones fail fast (0 = unbounded) (#7207)."
        ),
    )
    database_statement_timeout_ms: int = Field(
        default=30_000,
        ge=0,
        le=600_000,
        description="Server-side statement_timeout for pooled connections in ms (0 disables) (#7207).",
    )
    database_application_name: str = Field(
        default="apiome-mock",
        min_length=1,
        max_length=63,
        description="application_name reported to PostgreSQL by pooled connections (#7207).",
    )
    access_cache_ttl_seconds: float = Field(
        default=5.0,
        ge=0,
        le=600.0,
        description=(
            "TTL for cached per-version access decisions (mock on/off, visibility, mode). A disabled "
            "mock stops being served within this window; 0 disables the cache (#7207)."
        ),
    )
    api_key_cache_ttl_seconds: float = Field(
        default=30.0,
        ge=0,
        le=3600.0,
        description=(
            "TTL for a verified API key. A revoked or expired key stops opening private mocks "
            "within this window; 0 disables the cache (#7207)."
        ),
    )
    api_key_negative_cache_ttl_seconds: float = Field(
        default=10.0,
        ge=0,
        le=3600.0,
        description="TTL for a rejected API key, so repeated bad keys skip the lookup (#7207).",
    )
    usage_flush_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=60.0,
        description=(
            "How often in-process mock usage counters are written to the database in one "
            "multi-row upsert; counters are also flushed on shutdown (#7207)."
        ),
    )
    unknown_tenant_rps: float = Field(
        default=5.0,
        gt=0,
        description=(
            "Per-client-address request rate allowed for tenant slugs that do not exist, so 404 "
            "probing is bounded (#7207)."
        ),
    )
    broker_producer_db_concurrency: int = Field(
        default=2,
        ge=1,
        le=64,
        description="Concurrent database operations the periodic Kafka producer may run (#7207).",
    )
    spec_cache_max_entries: int = Field(
        default=256,
        ge=1,
        le=10_000,
        description=(
            "Maximum compiled specs held in each in-process LRU cache (REST and canonical); was 128 before #7208."
        ),
    )
    spec_cache_ttl_seconds: float = Field(
        default=300.0,
        gt=0,
        le=86_400.0,
        description=(
            "How long a compiled spec is served before it is revalidated (seconds). At expiry one "
            "statement compares the version's updated_at and content_stamp; an unchanged spec is "
            "kept, a changed one is reloaded (#7208). NOTIFY invalidates sooner."
        ),
    )
    spec_notify_channel: str = Field(
        default="apiome_mock_spec_published",
        min_length=1,
        description="Postgres NOTIFY channel for publish-driven cache invalidation.",
    )
    internal_token: str | None = Field(
        default=None,
        description=(
            "Shared secret gating the internal dry-run preview endpoint (#5528, MSC-1.2). Must "
            "match APIOME_MOCK_INTERNAL_TOKEN on apiome-rest; unset disables the endpoint."
        ),
    )
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enforce per-tenant RPS and monthly mock quotas from license tier.",
    )
    default_mock_rps: float = Field(
        default=5.0,
        gt=0,
        description="Fallback RPS when license seats omit mock_rps.",
    )
    default_mock_requests_per_month: int = Field(
        default=10_000,
        ge=0,
        description="Fallback monthly quota when license seats omit mock_requests_per_month.",
    )
    limits_cache_ttl_seconds: float = Field(
        default=60.0,
        gt=0,
        le=3600.0,
        description="TTL for cached tenant license limits (seconds).",
    )
    monthly_usage_cache_ttl_seconds: float = Field(
        default=30.0,
        gt=0,
        le=600.0,
        description="TTL for cached monthly usage totals (seconds).",
    )
    audit_sample_rate: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Fraction of mock hits written to access_audit (0 disables).",
    )
    grpc_enabled: bool = Field(
        default=True,
        description="Start the gRPC reflection mock listener alongside the HTTP server.",
    )
    grpc_host: str = Field(default="127.0.0.1", min_length=1)
    grpc_port: int = Field(default=8776, ge=1, le=65535)
    callbacks_enabled: bool = Field(
        default=False,
        description="Deliver contract callbacks/webhooks outbound (#4746, PMR-2.3).",
    )
    callback_allow_private: bool = Field(
        default=False,
        description="Permit callback destinations on loopback/private addresses; public-only otherwise.",
    )
    callback_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=60.0,
        description="Ceiling on one callback delivery attempt (seconds).",
    )
    dev_broker_bootstrap: str | None = Field(
        default=None,
        description=(
            "The opt-in dev broker's host:port list (`docker compose --profile broker`, #5735); "
            "/health reports `broker: reachable|unreachable` while it resolves."
        ),
    )
    broker_producer_enabled: bool = Field(
        default=True,
        description=(
            "Publish example/synthesized messages to versions' bound Kafka brokers on each channel's "
            "interval (#5736, XPC-2.2). Turn off on all but one replica of a multi-replica deployment."
        ),
    )
    broker_refresh_seconds: float = Field(
        default=30.0,
        gt=0,
        le=3600.0,
        description="How often the producer re-reads which versions have a broker binding (#5736).",
    )
    capture_enabled: bool = Field(
        default=False,
        description="Permit guarded upstream proxy capture on this deployment (#4747, PMR-2.4).",
    )
    capture_allow_private_upstreams: bool = Field(
        default=False,
        description="Permit capture upstreams on loopback/private addresses; public-only otherwise.",
    )
    capture_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60.0,
        description="Ceiling on one upstream capture fetch (seconds).",
    )
    capture_max_body_bytes: int = Field(
        default=65_536,
        ge=1024,
        le=1_048_576,
        description="Largest request/response body a capture stores; larger bodies are dropped.",
    )
    capture_retention_hours: int = Field(
        default=168,
        ge=1,
        le=8760,
        description="How long a recorded exchange survives before the retention sweep removes it.",
    )
    session_store_backend: Literal["memory", "postgres"] = Field(
        default="memory",
        description="Stateful CRUD store backend (X-Mock-Session); memory for single-node, postgres for multi-replica.",
    )
    session_ttl_seconds: float = Field(
        default=3600.0,
        gt=0,
        le=86_400.0,
        description="Sliding TTL for mock session state (seconds).",
    )
    session_max_resources: int = Field(
        default=200,
        ge=1,
        le=100_000,
        description="Maximum resources stored per X-Mock-Session.",
    )
    session_max_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=100_000_000,
        description="Maximum JSON byte size stored per X-Mock-Session.",
    )
    session_max_sessions: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
        description="Maximum concurrent mock sessions (process-wide for memory; global for postgres).",
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
