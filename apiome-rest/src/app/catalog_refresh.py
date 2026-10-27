"""Catalog item refresh — per-item cadence, live discovery and outcome rules (MFI-31.1, #4398).

A catalog item can opt in to being re-checked against the live source it describes. The settings
live on ``apiome.catalog_item_refresh`` (V333): a cadence, the import adapter that discovers the
source, the endpoint, adapter options and a sealed credential. This module holds the rules; the
SQL is :mod:`app.catalog_refresh_store` and the scheduler is :mod:`app.catalog_refresh_sweep`.

**Cadence.** ``off`` (the default: stored, never checked), ``manual`` (checked only on request),
``hourly`` / ``daily`` / ``weekly`` (checked by the sweep once that long has passed since the last
check).

**Discovery runners.** A check runs the adapter's own live discovery — GraphQL introspection
(:meth:`GraphQlImportSource.introspect`) or gRPC Server Reflection
(:meth:`GrpcImportSource.discover`) — then the adapter's ``normalize`` and ``fingerprint``, so the
fingerprint is the one a manual import of the same surface would carry. Each adapter needs a
runner registered with :func:`register_discovery_runner`; an adapter that declares
``supports_live_discovery`` but has no runner yet is refused when settings are saved
(``adapter-not-refreshable``). Every network call goes through the adapter's SSRF-guarded client,
unchanged.

**Apply hook.** After a successful discovery the outcome is handed to the hook registered with
:func:`register_refresh_apply`. MFI-31.2 (#4399) registers the hook that drives the import
pipeline in refresh mode (version on change). Until then no hook is registered and a check only
records whether the fingerprint changed. A failed check never calls the hook, so it can never
create a version.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

import httpx

from .import_source import get_import_source, resolve_import_source_key
from .mcp_auth import (
    AUTH_TYPE_BEARER,
    AUTH_TYPE_HEADER,
    AUTH_TYPE_NONE,
    AUTH_TYPE_OAUTH2,
    CredentialPayloadError,
    validate_credential_payload,
)
from .mcp_discovery_backoff import compute_backoff_seconds
from .ssrf_guard import SSRFError, validate_url_policy

_logger = logging.getLogger(__name__)

__all__ = [
    "AUTH_TYPES",
    "CADENCES",
    "CADENCE_SECONDS",
    "CODE_ADAPTER_NOT_REFRESHABLE",
    "CODE_ENCRYPTION_UNCONFIGURED",
    "CODE_INVALID_CREDENTIAL",
    "CODE_INVALID_ENDPOINT",
    "CODE_REFRESH_DISABLED",
    "CODE_REFRESH_OFF",
    "CheckOutcome",
    "DiscoveryResult",
    "RefreshSettingsError",
    "backoff_seconds",
    "endpoint_host",
    "get_discovery_runner",
    "refreshable_adapters",
    "register_discovery_runner",
    "register_refresh_apply",
    "run_refresh_check",
    "validate_refresh_settings",
]

# ---------------------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------------------

CADENCE_OFF = "off"
CADENCE_MANUAL = "manual"
#: Scheduled cadences and how long after the last check each is due again.
CADENCE_SECONDS: Dict[str, int] = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
}
#: Every cadence the V333 CHECK accepts, in display order.
CADENCES = (CADENCE_OFF, CADENCE_MANUAL, "hourly", "daily", "weekly")

#: Credential types a refresh may use: the HTTP/metadata subset of the vault model (``env`` is for
#: stdio MCP servers and has no meaning against a network endpoint).
AUTH_TYPES = (AUTH_TYPE_NONE, AUTH_TYPE_BEARER, AUTH_TYPE_HEADER, AUTH_TYPE_OAUTH2)

#: Check outcomes stored in ``catalog_item_refresh.status``.
STATUS_NEVER = "never"
STATUS_UNCHANGED = "unchanged"
STATUS_CHANGED = "changed"
STATUS_FAILED = "failed"

#: Longest error text kept on the row; discovery errors can embed whole response bodies.
MAX_ERROR_LENGTH = 500

# Stable refusal codes (the REST layer maps them to 422 / 409).
CODE_ADAPTER_NOT_REFRESHABLE = "adapter-not-refreshable"
CODE_INVALID_ENDPOINT = "invalid-endpoint"
CODE_INVALID_CREDENTIAL = "invalid-credential"
CODE_INVALID_CADENCE = "invalid-cadence"
CODE_REFRESH_OFF = "refresh-off"
CODE_REFRESH_DISABLED = "refresh-disabled"
CODE_ENCRYPTION_UNCONFIGURED = "encryption-unconfigured"


class RefreshSettingsError(ValueError):
    """A refresh setting or request the caller must fix.

    Attributes:
        code: A stable machine-readable refusal code (one of the ``CODE_*`` constants).
        message: A human-readable reason, safe to show (never contains a credential).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------------------
# Discovery runners
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryResult:
    """What one successful live discovery produced.

    Attributes:
        fingerprint: The adapter's fingerprint of the normalized model — the same value a manual
            import of this surface records, so "changed" means what it means for an import.
        model: The normalized :class:`~app.canonical_model.CanonicalApi`, for the apply hook.
        native: The adapter's native AST (schema / descriptor set), for the apply hook.
    """

    fingerprint: str
    model: Any
    native: Any


#: A runner discovers one live source. It is synchronous (the adapters' discovery clients are) and
#: is run in a worker thread by :func:`run_refresh_check`.
#: Args: ``(endpoint, options, auth_type, auth_payload, timeout_seconds)``.
DiscoveryRunner = Callable[[str, Mapping[str, Any], str, Optional[Mapping[str, Any]], float], DiscoveryResult]

_RUNNERS: Dict[str, DiscoveryRunner] = {}


def register_discovery_runner(adapter_key: str, runner: DiscoveryRunner) -> None:
    """Register (or replace) the live-discovery runner for an import adapter.

    Args:
        adapter_key: The import adapter's registry key (e.g. ``graphql``).
        runner: The callable that discovers one endpoint and returns a :class:`DiscoveryResult`.
    """
    _RUNNERS[adapter_key] = runner


def get_discovery_runner(adapter_key: str) -> Optional[DiscoveryRunner]:
    """The runner registered for ``adapter_key`` (aliases resolved), or ``None``."""
    return _RUNNERS.get(resolve_import_source_key(adapter_key) or adapter_key)


def refreshable_adapters() -> list[str]:
    """Adapter keys that can be refreshed: live-capable and with a runner, sorted."""
    keys = []
    for key in sorted(_RUNNERS):
        source = get_import_source(key)
        if source is not None and source.supports_live_discovery:
            keys.append(key)
    return keys


def _auth(auth_type: str, auth_payload: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The ``auth_type`` / ``auth_payload`` keyword pair the adapters' discovery methods take."""
    if auth_type == AUTH_TYPE_NONE or not auth_payload:
        return {"auth_type": None, "auth_payload": None}
    return {"auth_type": auth_type, "auth_payload": dict(auth_payload)}


def _graphql_runner(
    endpoint: str,
    options: Mapping[str, Any],
    auth_type: str,
    auth_payload: Optional[Mapping[str, Any]],
    timeout_seconds: float,
) -> DiscoveryResult:
    """Introspect a GraphQL endpoint and fingerprint the normalized schema."""
    source = get_import_source("graphql")
    schema = source.introspect(endpoint, **_auth(auth_type, auth_payload))
    model = source.normalize(schema, include_raw=True)
    return DiscoveryResult(fingerprint=source.fingerprint(model), model=model, native=schema)


def _grpc_runner(
    endpoint: str,
    options: Mapping[str, Any],
    auth_type: str,
    auth_payload: Optional[Mapping[str, Any]],
    timeout_seconds: float,
) -> DiscoveryResult:
    """Crawl a gRPC server's reflection surface and fingerprint the normalized descriptor set."""
    source = get_import_source("grpc")
    compiled = source.discover(
        endpoint,
        secure=bool(options.get("secure", False)),
        timeout=timeout_seconds,
        **_auth(auth_type, auth_payload),
    )
    model = source.normalize(compiled, include_raw=True)
    return DiscoveryResult(fingerprint=source.fingerprint(model), model=model, native=compiled)


register_discovery_runner("graphql", _graphql_runner)
register_discovery_runner("grpc", _grpc_runner)


# ---------------------------------------------------------------------------------------
# Apply hook (MFI-31.2 registers the real one)
# ---------------------------------------------------------------------------------------

#: Called after a successful discovery as ``hook(db, row, result, changed)``. Its return value is
#: ignored; an exception it raises fails the check (recorded, backed off) like a discovery error.
RefreshApplyHook = Callable[[Any, Mapping[str, Any], DiscoveryResult, bool], None]

_APPLY_HOOK: Optional[RefreshApplyHook] = None


def register_refresh_apply(hook: Optional[RefreshApplyHook]) -> None:
    """Register the hook that applies a successful check (``None`` clears it).

    MFI-31.2 (#4399) registers the hook that runs the import pipeline in refresh mode. With no hook
    a check only records the fingerprint and whether it changed.
    """
    global _APPLY_HOOK
    _APPLY_HOOK = hook


# ---------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------


def endpoint_host(adapter_key: str, endpoint: str) -> str:
    """The host an endpoint talks to, used for the politeness delay and the URL-shape check.

    Args:
        adapter_key: The adapter key; ``grpc`` takes a ``host:port`` target, every other adapter
            takes an http(s) URL.
        endpoint: The stored endpoint.

    Returns:
        The lower-cased host.

    Raises:
        RefreshSettingsError: ``invalid-endpoint`` when no host can be read, or the URL breaks the
            SSRF shape policy (scheme, embedded credentials).
    """
    if (resolve_import_source_key(adapter_key) or adapter_key) == "grpc":
        from .grpc_reflection import GrpcReflectionError, _host_of

        try:
            return _host_of(endpoint).lower()
        except GrpcReflectionError as exc:
            raise RefreshSettingsError(CODE_INVALID_ENDPOINT, str(exc)) from exc
    try:
        return validate_url_policy(endpoint).lower()
    except SSRFError as exc:
        raise RefreshSettingsError(CODE_INVALID_ENDPOINT, str(exc)) from exc


def validate_refresh_settings(
    *,
    cadence: str,
    adapter_key: str,
    endpoint: str,
    auth_type: Optional[str] = None,
    auth_payload: Optional[Mapping[str, Any]] = None,
) -> str:
    """Check a refresh setting before it is stored, and return the canonical adapter key.

    The endpoint is checked for shape only (scheme, credentials, a host). The host's addresses are
    resolved and checked by the adapter's guarded client on every call, so a DNS change after the
    setting was saved is still caught.

    Args:
        cadence: One of :data:`CADENCES`.
        adapter_key: The import adapter key (aliases accepted, e.g. ``protobuf`` → ``grpc``).
        endpoint: The live endpoint.
        auth_type: The credential type when a new credential is supplied, else ``None``.
        auth_payload: The plaintext credential payload when one is supplied.

    Returns:
        The canonical adapter key to store.

    Raises:
        RefreshSettingsError: With ``invalid-cadence``, ``adapter-not-refreshable``,
            ``invalid-endpoint`` or ``invalid-credential``.
    """
    if cadence not in CADENCES:
        raise RefreshSettingsError(
            CODE_INVALID_CADENCE, f"Unknown cadence {cadence!r}; use one of {', '.join(CADENCES)}."
        )

    key = resolve_import_source_key(adapter_key) or adapter_key
    source = get_import_source(key)
    if source is None or not source.supports_live_discovery or key not in _RUNNERS:
        allowed = ", ".join(refreshable_adapters()) or "none"
        raise RefreshSettingsError(
            CODE_ADAPTER_NOT_REFRESHABLE,
            f"Adapter {adapter_key!r} cannot be refreshed from a live source; use one of: {allowed}.",
        )

    if not (endpoint or "").strip():
        raise RefreshSettingsError(CODE_INVALID_ENDPOINT, "An endpoint is required.")
    endpoint_host(key, endpoint)

    if auth_type is not None:
        if auth_type not in AUTH_TYPES:
            raise RefreshSettingsError(
                CODE_INVALID_CREDENTIAL,
                f"Unknown credential type {auth_type!r}; use one of {', '.join(AUTH_TYPES)}.",
            )
        if auth_type != AUTH_TYPE_NONE:
            try:
                validate_credential_payload(auth_type, auth_payload or {})
            except CredentialPayloadError as exc:
                raise RefreshSettingsError(CODE_INVALID_CREDENTIAL, str(exc)) from exc
    return key


def backoff_seconds(consecutive_failures: int, *, base_seconds: float, max_seconds: float) -> float:
    """The delay before the next scheduled check after ``consecutive_failures`` failures.

    Reuses the MCP discovery backoff curve: ``base * 2**(n-1)``, capped at ``max_seconds``.
    """
    return compute_backoff_seconds(consecutive_failures, base_seconds=base_seconds, max_seconds=max_seconds)


# ---------------------------------------------------------------------------------------
# One check
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """The recorded result of one check.

    Attributes:
        status: ``unchanged``, ``changed`` or ``failed``.
        fingerprint: The new fingerprint on success, else ``None``.
        error: The failure reason on failure (trimmed, credential-free), else ``None``.
    """

    status: str
    fingerprint: Optional[str] = None
    error: Optional[str] = None


def _error_text(exc: BaseException) -> str:
    """A short, single-line failure reason for the row."""
    if isinstance(exc, asyncio.TimeoutError):
        return "The check timed out."
    if isinstance(exc, httpx.HTTPError):
        text = f"{type(exc).__name__}: {exc}"
    else:
        text = str(exc) or type(exc).__name__
    text = " ".join(text.split())
    return text[:MAX_ERROR_LENGTH]


async def run_refresh_check(
    db: Any,
    row: Mapping[str, Any],
    *,
    timeout_seconds: float,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
    store: Any = None,
) -> CheckOutcome:
    """Run one live check for a refresh row and record its outcome.

    Shared by the scheduled sweep and the manual "check now" route. The sequence is:

    1. unseal the credential (a row whose credential cannot be unsealed fails the check rather
       than running unauthenticated);
    2. run the adapter's discovery runner in a worker thread, bounded by ``timeout_seconds``;
    3. compare the fingerprint with the last one and call the apply hook, if any;
    4. record ``unchanged`` / ``changed``, or ``failed`` with exponential backoff.

    A failure only updates the row's status columns: no hook runs, so no version is created.

    Args:
        db: Database handle.
        row: The ``catalog_item_refresh`` row, including ``encrypted_payload`` / ``key_version``.
        timeout_seconds: Wall-clock ceiling on the discovery.
        backoff_base_seconds: First-failure backoff.
        backoff_max_seconds: Backoff ceiling.
        store: The storage module (tests inject a fake); defaults to :mod:`app.catalog_refresh_store`.

    Returns:
        The :class:`CheckOutcome` that was recorded.
    """
    if store is None:
        from . import catalog_refresh_store as store

    project_id = str(row["project_id"])
    try:
        runner = get_discovery_runner(str(row["adapter_key"]))
        if runner is None:
            raise RefreshSettingsError(
                CODE_ADAPTER_NOT_REFRESHABLE,
                f"No live-discovery runner for adapter {row['adapter_key']!r}.",
            )
        auth_type = str(row.get("auth_type") or AUTH_TYPE_NONE)
        auth_payload: Optional[Dict[str, Any]] = None
        if auth_type != AUTH_TYPE_NONE:
            from .mcp_credential_crypto import unseal_credential_payload

            auth_payload = unseal_credential_payload(row.get("encrypted_payload"), row.get("key_version"))
            if auth_payload is None:
                raise RefreshSettingsError(
                    CODE_INVALID_CREDENTIAL,
                    "The stored credential could not be unsealed; save it again.",
                )

        result = await asyncio.wait_for(
            asyncio.to_thread(
                runner,
                str(row["endpoint"]),
                dict(row.get("options") or {}),
                auth_type,
                auth_payload,
                float(timeout_seconds),
            ),
            timeout=float(timeout_seconds),
        )
        changed = row.get("last_fingerprint") is not None and row.get("last_fingerprint") != result.fingerprint
        if _APPLY_HOOK is not None:
            await asyncio.to_thread(_APPLY_HOOK, db, row, result, changed)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — every failure is recorded on the row, never raised.
        failures = int(row.get("consecutive_failures") or 0) + 1
        delay = backoff_seconds(failures, base_seconds=backoff_base_seconds, max_seconds=backoff_max_seconds)
        error = _error_text(exc)
        _logger.info("catalog refresh check failed project_id=%s failures=%d: %s", project_id, failures, error)
        await asyncio.to_thread(store.record_failure, db, project_id, error=error, backoff_seconds=delay)
        return CheckOutcome(status=STATUS_FAILED, error=error)

    status = STATUS_CHANGED if changed else STATUS_UNCHANGED
    await asyncio.to_thread(store.record_success, db, project_id, status=status, fingerprint=result.fingerprint)
    return CheckOutcome(status=status, fingerprint=result.fingerprint)
