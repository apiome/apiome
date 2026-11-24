"""Environment-backed settings for the MCP server process."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

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
    agent_database_pool_min_size: int = Field(
        default=1,
        ge=1,
        le=256,
        description=(
            "DBP-1.21: fewest connections the agent runtime's (/agent/mcp) pool keeps open. The catalog "
            "(/mcp) pool uses database_pool_min_size; a process serving both holds the two pools."
        ),
    )
    agent_database_pool_max_size: int = Field(
        default=10,
        ge=1,
        le=256,
        description=(
            "DBP-1.21: most connections the agent runtime's pool opens. One HTTP process can hold "
            "database_pool_max_size + agent_database_pool_max_size connections."
        ),
    )
    database_statement_timeout_ms: int = Field(
        default=30_000,
        ge=0,
        le=86_400_000,
        description=(
            "DBP-1.21: statement_timeout set on every pooled connection, in milliseconds (0 = none). "
            "The usage sweep lifts it for its own transactions."
        ),
    )
    database_idle_in_transaction_timeout_ms: int = Field(
        default=60_000,
        ge=0,
        le=86_400_000,
        description=(
            "DBP-1.21: idle_in_transaction_session_timeout on every pooled connection, in milliseconds "
            "(0 = none). Ends a session that left a transaction open."
        ),
    )
    key_cache_seconds: float = Field(
        default=60.0,
        ge=0,
        le=3600,
        description=(
            "DBP-1.21: seconds a verified MCP or agent key skips bcrypt (cached by SHA-256 of the "
            "secret). Each call still re-reads the key row, so revocation and expiry apply on the next "
            "call. 0 turns the cache off."
        ),
    )
    key_cache_max_entries: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
        description="DBP-1.21: most verified keys kept per process (oldest dropped first).",
    )
    agent_toolset_manifest_cache_seconds: float = Field(
        default=5.0,
        ge=0,
        le=300,
        description=(
            "DBP-1.21: seconds an agent toolset's manifest (enabled tools, descriptions, target) and its "
            "upstream credential rows are reused. An edit to the toolset row applies on the next call; "
            "a tool switch, accepted description or credential change within this time. 0 = read every call."
        ),
    )
    audit_flush_interval_ms: int = Field(
        default=250,
        ge=10,
        le=60_000,
        description=(
            "DBP-1.21: milliseconds between flushes of the batched audit writer (agent invocations, "
            "credential uses, private-access audit, capability denials)."
        ),
    )
    audit_queue_max_rows: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
        description=(
            "DBP-1.21: most audit rows waiting to be written per pool. A row submitted to a full queue is "
            "dropped, counted and logged (audit_rows_dropped)."
        ),
    )
    audit_batch_max_rows: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="DBP-1.21: most rows one multi-row INSERT of the audit writer carries.",
    )
    openapi_document_cache_bytes: int = Field(
        default=67_108_864,
        ge=0,
        le=17_179_869_184,
        description=(
            "DBP-1.22: budget of the spec tools' built-document cache, counted as the compact-JSON "
            "size of the cached OpenAPI documents (memory use is several times that). A revision's "
            "document is rebuilt only when the revision changes. 0 turns the cache off."
        ),
    )
    spec_tag_histogram_cache_seconds: float = Field(
        default=45.0,
        ge=0,
        le=3600,
        description=(
            "DBP-1.22: seconds spec.list_tags serves its tag counts from memory before recounting "
            "(a new or removed tag shows within this time). 0 recounts on every call."
        ),
    )
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
    api_key: SecretStr | None = Field(
        default=None,
        description=(
            "MCP API key for stdio hosts (Claude Desktop, Cursor), which cannot send a key per "
            "request. Read on stdio only — over HTTP every caller presents its own key."
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
        description=(
            "AGX-3.3: most rows one retention purge batch deletes. DBP-1.23: each purge repeats, one "
            "committed batch at a time, until a batch comes back short or the time budget runs out."
        ),
    )
    agent_usage_sweep_time_budget_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
        description=(
            "DBP-1.23: seconds one sweep tick may keep purging. Every purge still runs at least one "
            "batch; whatever is left goes on the next tick."
        ),
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
    access_audit_retention_days: int = Field(
        default=365,
        ge=1,
        le=3650,
        description=(
            "DBP-1.23: days rows of mcp_access_audit (private-revision reads) are kept; the usage sweep "
            "deletes older ones."
        ),
    )
    capability_denial_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        description=(
            "DBP-1.23: days rows of mcp_capability_denials (refused tools/call) are kept; the usage "
            "sweep deletes older ones."
        ),
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

    rest_internal_url: str | None = Field(
        default=None,
        description=(
            "MFX-40.1: root of apiome-rest as this process reaches it (e.g. http://rest:8000 inside docker "
            "compose). The export.targets / version.export tools call its /v1/internal/mcp/export routes. "
            "Unset = the export tools answer that export is not configured."
        ),
    )
    rest_internal_service_token: SecretStr | None = Field(
        default=None,
        description=(
            "MFX-40.1: apiome-rest's INTERNAL_SERVICE_TOKEN, sent as X-Internal-Service-Token to its internal "
            "export routes. Must match the rest service's value byte for byte."
        ),
    )
    export_wait_seconds: int = Field(
        default=60,
        ge=0,
        le=300,
        description="MFX-40.1: how long version.export waits for an export job before answering `running`.",
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
    agent_request_max_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=100_000_000,
        description=(
            "AGX-2.3: most request-body bytes one agent tools/call may send upstream; a larger body is refused "
            "with request_too_large before anything is sent."
        ),
    )
    agent_upstream_allow_private: bool = Field(
        default=False,
        description=(
            "AGX-2.3: turn off the SSRF address rule for prod upstreams (local development against a private "
            "API only). The configured mock root is always exempt."
        ),
    )
    agent_toolset_cache_size: int = Field(
        default=256,
        ge=1,
        le=100_000,
        description="AGX-2.1: compiled agent toolsets kept in memory per process.",
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        description=(
            "ATQ-4.4: OTLP/HTTP collector root (e.g. http://otel-collector:4318). Unset (the default) "
            "exports nothing. Spans go to {root}/v1/traces, metrics to {root}/v1/metrics."
        ),
    )
    otel_exporter_otlp_headers: SecretStr | None = Field(
        default=None,
        description=(
            "ATQ-4.4: headers sent with every OTLP export, as comma-separated key=value pairs "
            "(e.g. a vendor API key). Never logged."
        ),
    )
    otel_service_name: str = Field(
        default="apiome-mcp",
        min_length=1,
        max_length=128,
        description="ATQ-4.4: the OTel service.name resource attribute.",
    )
    otel_traces_sampler_ratio: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "ATQ-4.4: share of new traces sampled (0..1; default 0.25 keeps the CPU cost under 2%). "
            "Metrics count every call whatever the ratio. A call whose caller sent a traceparent "
            "follows the caller's sampling decision."
        ),
    )
    otel_metric_export_interval_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=3600.0,
        description="ATQ-4.4: seconds between metric exports.",
    )
    otel_export_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60.0,
        description="ATQ-4.4: most seconds one OTLP export may take. Exports run in the background.",
    )

    @field_validator("otel_exporter_otlp_endpoint")
    @classmethod
    def validate_otel_endpoint(cls, value: str | None) -> str | None:
        """An empty value means "off"; otherwise an http(s) URL without a trailing slash."""
        if value is None or not value.strip():
            return None
        text = value.strip().rstrip("/")
        if not text.startswith(("http://", "https://")):
            raise ValueError("otel_exporter_otlp_endpoint must be an http:// or https:// URL")
        return text

    @model_validator(mode="after")
    def pool_size_bounds(self) -> Self:
        if self.database_pool_max_size < self.database_pool_min_size:
            raise ValueError(
                "database_pool_max_size must be greater than or equal to database_pool_min_size",
            )
        if self.agent_database_pool_max_size < self.agent_database_pool_min_size:
            raise ValueError(
                "agent_database_pool_max_size must be greater than or equal to agent_database_pool_min_size",
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


def setting_or_default(name: str, default: float) -> float:
    """Return a numeric setting, or ``default`` when settings cannot be loaded (tests, tooling).

    Process-wide caches read their lifetimes through this, so importing a module never needs a
    configured environment.

    Args:
        name: The :class:`Settings` field name.
        default: The value used when the environment is not configured.

    Returns:
        The configured value, else ``default``.
    """
    try:
        return float(getattr(get_settings(), name))
    except Exception:
        return default
