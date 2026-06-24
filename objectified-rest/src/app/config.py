import logging
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Insecure development-only JWT secret. Used (with a warning) when no secret is configured
# outside production; production fails closed instead — see Settings.effective_jwt_secret.
INSECURE_JWT_SECRET_FALLBACK = "your-secret-key-here"

# Default CORS allow-list applied when OBJECTIFIED_CORS_ALLOWED_ORIGINS is unset.
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",  # Next.js default port
    "http://localhost:3001",  # Next.js when 3000 is taken
]

# Default CORS origin regex applied when OBJECTIFIED_CORS_ALLOWED_ORIGIN_REGEX is unset.
DEFAULT_CORS_ORIGIN_REGEX = r"https://.*\.objectified\.dev"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database settings - can use DATABASE_URL directly or build from components
    database_url: Optional[str] = None
    postgres_user: str = "postgres"
    postgres_password: str = "password"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "objectified"

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True

    # Deployment environment. "production"/"prod" enables fail-closed checks (e.g. the JWT
    # secret must be configured — no insecure built-in fallback). Defaults to development.
    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices(
            "OBJECTIFIED_ENV",
            "APP_ENV",
            "ENVIRONMENT",
            "app_env",
        ),
    )

    # JWT settings (should match NextAuth secret)
    # Can be set via JWT_SECRET or NEXTAUTH_SECRET env var
    jwt_secret: Optional[str] = None
    nextauth_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"

    # CORS allow-list. Comma-separated exact origins via OBJECTIFIED_CORS_ALLOWED_ORIGINS
    # (defaults to the local Next.js dev ports). A regex for trusted subdomains is supplied
    # via OBJECTIFIED_CORS_ALLOWED_ORIGIN_REGEX (defaults to *.objectified.dev); set it to an
    # empty string to disable subdomain matching entirely.
    cors_allowed_origins: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "OBJECTIFIED_CORS_ALLOWED_ORIGINS",
            "cors_allowed_origins",
        ),
    )
    cors_allowed_origin_regex: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "OBJECTIFIED_CORS_ALLOWED_ORIGIN_REGEX",
            "cors_allowed_origin_regex",
        ),
    )

    # Embedding (Ollama) for data_snapshot vectorization
    ollama_base_url: str = "http://localhost:11434"

    # Pre-commit policy default when project metadata omits maxCommitPayloadBytes (#2565)
    commit_policy_max_payload_bytes_default: int = 5_242_880

    # Fernet key (url-safe base64) from `Fernet.generate_key()` — encrypts webhook signing secrets at rest (#2588)
    webhook_signing_secret_encryption_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "OBJECTIFIED_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY",
            "webhook_signing_secret_encryption_key",
        ),
    )

    # Repository auto-refresh cadence (RAR-3.1, #3522). Per-repo cadence is stored
    # in odb.tenant_repositories.refresh_interval_seconds; these set the default
    # applied when a repo has no explicit value and the global minimum floor that
    # clamps sub-floor per-repo values at read time.
    refresh_default_interval_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices(
            "OBJECTIFIED_REFRESH_DEFAULT_INTERVAL",
            "refresh_default_interval_seconds",
        ),
    )
    refresh_min_interval_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "OBJECTIFIED_REFRESH_MIN_INTERVAL",
            "refresh_min_interval_seconds",
        ),
    )

    # Primitives type-registry entitlement gating (#3478). When False (default), the
    # advanced Type Registry surface (resolver, namespaces, settings, stats, import) is
    # open to every authenticated tenant — current behavior, unchanged. When True, those
    # routes require the calling tenant/user to hold the ``primitives-registry`` feature
    # flag (per-user override > per-tenant override > license default); non-entitled
    # callers get 403. Baseline primitives CRUD and /health are never gated.
    primitives_registry_gating_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "OBJECTIFIED_PRIMITIVES_REGISTRY_GATING",
            "primitives_registry_gating_enabled",
        ),
    )

    # SSRF guard (#3612). When False (default), user-supplied URLs fetched by the
    # import-from-URL and public repository-registration paths are resolved and
    # rejected if they point at non-public addresses (loopback, RFC1918,
    # link-local incl. the 169.254.169.254 metadata IP, etc.). Set to True only
    # for local development where importing from localhost is intentional; the
    # http/https-only and no-credentials-in-URL checks always apply.
    ssrf_allow_private: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "OBJECTIFIED_SSRF_ALLOW_PRIVATE",
            "ssrf_allow_private",
        ),
    )

    # Per-tenant rate limiting (#3612). The limiter buckets requests per API key
    # / tenant slug / client IP and enforces a fixed window. Authenticated
    # traffic (API key or Authorization header) uses the higher limit; public
    # traffic uses the lower one. Set ``OBJECTIFIED_RATE_LIMIT_ENABLED=false`` to
    # disable entirely. Limits are per replica (in-process counter).
    rate_limit_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "OBJECTIFIED_RATE_LIMIT_ENABLED",
            "rate_limit_enabled",
        ),
    )
    rate_limit_authenticated_per_minute: int = Field(
        default=600,
        validation_alias=AliasChoices(
            "OBJECTIFIED_RATE_LIMIT_AUTHENTICATED_PER_MINUTE",
            "rate_limit_authenticated_per_minute",
        ),
    )
    rate_limit_public_per_minute: int = Field(
        default=120,
        validation_alias=AliasChoices(
            "OBJECTIFIED_RATE_LIMIT_PUBLIC_PER_MINUTE",
            "rate_limit_public_per_minute",
        ),
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "OBJECTIFIED_RATE_LIMIT_WINDOW_SECONDS",
            "rate_limit_window_seconds",
        ),
    )

    # Mock Server (#3615, RC1-2.2). Free-tier mocks auto-expire after a default TTL (capped at a
    # maximum) and are rate limited per instance on the data plane. Set
    # OBJECTIFIED_MOCK_SERVER_ENABLED=false to disable provisioning + serving entirely.
    mock_server_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "OBJECTIFIED_MOCK_SERVER_ENABLED",
            "mock_server_enabled",
        ),
    )
    mock_default_ttl_hours: int = Field(
        default=24,
        validation_alias=AliasChoices(
            "OBJECTIFIED_MOCK_DEFAULT_TTL_HOURS",
            "mock_default_ttl_hours",
        ),
    )
    mock_max_ttl_hours: int = Field(
        default=168,  # 7 days
        validation_alias=AliasChoices(
            "OBJECTIFIED_MOCK_MAX_TTL_HOURS",
            "mock_max_ttl_hours",
        ),
    )
    mock_rate_limit_per_minute: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "OBJECTIFIED_MOCK_RATE_LIMIT_PER_MINUTE",
            "mock_rate_limit_per_minute",
        ),
    )

    # Global auto-refresh kill switch (RAR-3.3, #3524). When False, the refresh
    # sweep halts entirely (no repository is auto-refreshed) regardless of per-repo
    # auto_refresh_enabled. Intended for incident response. Manual "Refresh Now"
    # (RAR-5.2) is unaffected. Per-repo opt-out is the auto_refresh_enabled column.
    refresh_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "OBJECTIFIED_REFRESH_ENABLED",
            "refresh_enabled",
        ),
    )

    @property
    def effective_database_url(self) -> str:
        """Get the database URL, preferring DATABASE_URL over building from components."""
        if self.database_url:
            return self.database_url
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def is_production(self) -> bool:
        """True when running in a production-like environment (fail-closed checks on)."""
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def effective_jwt_secret(self) -> str:
        """
        Get the JWT secret, preferring NEXTAUTH_SECRET over JWT_SECRET.

        Fail-closed in production: if neither secret is configured we refuse to fall back
        to the insecure built-in default (which would let anyone forge JWTs). In
        development the well-known default is returned with a warning so local setups
        keep working.

        Raises:
            RuntimeError: in production when no JWT secret is configured.
        """
        secret = self.nextauth_secret or self.jwt_secret
        if secret:
            return secret
        if self.is_production:
            raise RuntimeError(
                "JWT secret is not configured. Set NEXTAUTH_SECRET (or JWT_SECRET) before "
                "starting objectified-rest in production; refusing to use the insecure default."
            )
        logger.warning(
            "Using the insecure built-in JWT secret. Set NEXTAUTH_SECRET (or JWT_SECRET) "
            "for any non-local deployment."
        )
        return INSECURE_JWT_SECRET_FALLBACK

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """Exact CORS origins: configured comma-separated list, or the local dev defaults."""
        if self.cors_allowed_origins:
            return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]
        return list(DEFAULT_CORS_ORIGINS)

    @property
    def effective_cors_origin_regex(self) -> Optional[str]:
        """
        CORS origin regex: the configured value, or the *.objectified.dev default.

        An explicitly-empty string disables subdomain matching (returns None so the regex
        is not applied at all).
        """
        if self.cors_allowed_origin_regex is None:
            return DEFAULT_CORS_ORIGIN_REGEX
        stripped = self.cors_allowed_origin_regex.strip()
        return stripped or None

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()

# Maximum number of HTTP delivery attempts before an event is moved to dead-letter.
# Shared by the delivery worker (push_webhook_delivery.py) and the DB query in database.py
# to ensure the retry policy is defined in exactly one place (#2588).
WEBHOOK_MAX_DELIVERY_ATTEMPTS: int = 4

