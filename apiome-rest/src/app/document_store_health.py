"""Document store settings, health and the connection test — COA-5.9 (#7085).

The REST server's environment (``APIOME_DOCUMENT_STORE*``) is the only place the document store
is configured: credentials are never stored in, or edited from, the UI. This module turns that
configuration into what operators need to see and check:

* :func:`initialize_document_store` runs at startup. It builds the configured store and, for
  ``s3`` and ``filesystem``, checks it can be reached. An unusable store stops startup with a
  redacted, actionable :class:`~app.document_store.DocumentStoreConfigError` — unless
  ``APIOME_DOCUMENT_STORE_FALLBACK=db`` is set, in which case the server starts on the
  database backend and reports the fallback.
* :func:`store_health` is a cached reachability check (``GET /health`` reports it).
* :func:`describe_store` is the settings-and-usage view ``GET /v1/ops/document-store`` returns.
* :func:`probe_store` writes, reads back and deletes one probe object
  (``POST /v1/ops/document-store/test``).

Nothing here returns or logs a credential: provider errors arrive already redacted from
:mod:`app.document_store`, and messages built here are redacted again with the configured keys.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .config import settings
from .document_store import (
    BACKEND_DB,
    BACKENDS,
    DbDocumentStore,
    DocumentStore,
    DocumentStoreConfigError,
    DocumentStoreError,
    FilesystemDocumentStore,
    S3DocumentStore,
    _redact,
    build_document_store,
    get_document_store,
    normalize_prefix,
    set_document_store,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FALLBACK_DB",
    "HEALTH_TTL_SECONDS",
    "PROBE_TENANT",
    "StoreHealth",
    "StoreResolution",
    "check_reachable",
    "current_resolution",
    "describe_store",
    "health_detail",
    "initialize_document_store",
    "probe_store",
    "reset_document_store_health",
    "store_health",
]

#: The only accepted value of ``APIOME_DOCUMENT_STORE_FALLBACK`` (besides empty).
FALLBACK_DB = "db"
#: A reachability result is reused for this long, so a polled ``/health`` costs one check per window.
HEALTH_TTL_SECONDS = 30.0
#: The tenant key segment probe objects are written under; no real tenant has this id (tenant ids
#: are UUIDs or slugs created by the platform).
PROBE_TENANT = "apiome-probe"
#: Media type of a probe object.
PROBE_MEDIA_TYPE = "text/plain"

#: Encryption modes as the S3 client sends them → the name shown to operators.
_ENCRYPTION_NAMES = {None: "none", "AES256": "sse-s3", "aws:kms": "sse-kms"}


@dataclass(frozen=True)
class StoreResolution:
    """Which store startup chose.

    Attributes:
        configured_backend: The backend ``APIOME_DOCUMENT_STORE`` names (lower-cased).
        active_backend: The backend the server runs on.
        fallback_reason: Why startup fell back to ``db`` (redacted), or ``None`` when it did not.
    """

    configured_backend: str
    active_backend: str
    fallback_reason: Optional[str] = None

    @property
    def fallback(self) -> bool:
        """Whether the server runs on the database backend because the configured one failed."""
        return self.fallback_reason is not None


@dataclass(frozen=True)
class StoreHealth:
    """One reachability check of the active store.

    Attributes:
        ok: Whether the store answered.
        checked_at: When the check ran (epoch seconds).
        error: The redacted failure, or ``None`` when ``ok``.
    """

    ok: bool
    checked_at: float
    error: Optional[str] = None


_lock = threading.Lock()
_resolution: Optional[StoreResolution] = None
_health: Optional[StoreHealth] = None


def _secrets_of(config: Any) -> tuple:
    """The configured credentials, for redacting messages built in this module."""
    return (
        getattr(config, "document_store_secret_access_key", "") or "",
        getattr(config, "document_store_access_key_id", "") or "",
    )


def _error_text(exc: BaseException, config: Any = None) -> str:
    """A message for ``exc`` that is safe to show: store errors as written, others by type only."""
    if isinstance(exc, DocumentStoreError):
        return _redact(str(exc), _secrets_of(config if config is not None else settings))
    return f"The document store failed ({type(exc).__name__})."


def check_reachable(store: DocumentStore, *, include_db: bool = True) -> None:
    """Check the store answers, without writing anything.

    * ``s3`` — ``HeadBucket`` on the configured bucket (the bucket exists and the key may use it).
    * ``filesystem`` — the storage directory exists (it is created if missing) and is writable.
    * ``db`` — the ``apiome.document_store_blob`` table can be read (skipped when
      ``include_db`` is false: at startup the database readiness check already covers it).

    Args:
        store: The store to check.
        include_db: Whether to check the database backend too.

    Raises:
        DocumentStoreError: with a redacted, actionable message when the store does not answer.
    """
    if isinstance(store, S3DocumentStore):
        try:
            store.client.head_bucket(Bucket=store.bucket)
        except DocumentStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - every provider error is redacted by _failure
            raise store._failure("reach", exc) from None
        return
    if isinstance(store, FilesystemDocumentStore):
        try:
            store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise DocumentStoreError(
                f"The storage directory could not be created ({type(exc).__name__}: "
                f"{exc.strerror or 'I/O error'}). Check APIOME_DOCUMENT_STORE_PATH and its permissions."
            ) from None
        if not store.root.is_dir() or not os.access(store.root, os.W_OK | os.X_OK):
            raise DocumentStoreError(
                "The storage directory is not a writable directory. Check APIOME_DOCUMENT_STORE_PATH "
                "and its permissions."
            )
        return
    if isinstance(store, DbDocumentStore) and include_db:
        try:
            store._db.execute_query("SELECT 1 AS ok FROM apiome.document_store_blob LIMIT 1")
        except Exception as exc:  # noqa: BLE001 - reported, never raised raw
            raise DocumentStoreError(
                f"The database document store could not be read ({type(exc).__name__}). Check the "
                "database connection and that migration V402 has been applied."
            ) from None


def _fallback_store(config: Any) -> DbDocumentStore:
    """The database store startup falls back to (an unusable prefix falls back to none)."""
    try:
        prefix = normalize_prefix(getattr(config, "document_store_prefix", ""))
    except DocumentStoreConfigError:
        prefix = ""
    return DbDocumentStore(prefix=prefix, max_bytes=config.document_store_db_max_bytes)


def initialize_document_store(
    config: Any = None,
    *,
    log: Optional[logging.Logger] = None,
    install: Callable[[Optional[DocumentStore]], None] = set_document_store,
) -> StoreResolution:
    """Build and check the configured store, and make it the process-wide store.

    Args:
        config: An object with the ``document_store*`` settings; the process settings when omitted.
        log: Where to log the outcome (this module's logger when omitted).
        install: Makes the chosen store the process-wide one (tests pass a stub).

    Returns:
        Which backend was configured and which one the server now runs on.

    Raises:
        DocumentStoreConfigError: when the store is unusable and no fallback is set, or when
            ``APIOME_DOCUMENT_STORE_FALLBACK`` holds anything but empty or ``db``. The message is
            redacted and names the setting to fix.
    """
    global _resolution, _health
    cfg = config if config is not None else settings
    out = log or logger
    configured = str(getattr(cfg, "document_store", "") or BACKEND_DB).strip().lower()
    fallback = str(getattr(cfg, "document_store_fallback", "") or "").strip().lower()
    if fallback not in ("", FALLBACK_DB):
        raise DocumentStoreConfigError("APIOME_DOCUMENT_STORE_FALLBACK must be empty or 'db'.")

    try:
        store: DocumentStore = build_document_store(cfg)
        check_reachable(store, include_db=False)
    except DocumentStoreError as exc:
        reason = _error_text(exc, cfg)
        if fallback != FALLBACK_DB or configured == BACKEND_DB:
            raise DocumentStoreConfigError(
                f"The document store (APIOME_DOCUMENT_STORE={configured or BACKEND_DB}) is not usable: "
                f"{reason} Fix the APIOME_DOCUMENT_STORE_* settings, or set "
                "APIOME_DOCUMENT_STORE_FALLBACK=db to start on the database store instead."
            ) from None
        out.error(
            "document store: %s is not usable, starting on the database store "
            "(APIOME_DOCUMENT_STORE_FALLBACK=db): %s",
            configured,
            reason,
        )
        store = _fallback_store(cfg)
        resolution = StoreResolution(configured, BACKEND_DB, reason)
    else:
        resolution = StoreResolution(configured, store.backend)
        out.info("document store: %s backend ready", store.backend)

    install(store)
    with _lock:
        _resolution = resolution
        _health = None
    return resolution


def current_resolution() -> StoreResolution:
    """What startup chose; before startup ran, the configured backend as built on first use."""
    with _lock:
        if _resolution is not None:
            return _resolution
    configured = str(settings.document_store or BACKEND_DB).strip().lower()
    return StoreResolution(configured, configured)


def reset_document_store_health() -> None:
    """Forget the startup resolution and the cached health (tests and reconfiguration)."""
    global _resolution, _health
    with _lock:
        _resolution = None
        _health = None


def _record(health: StoreHealth) -> StoreHealth:
    """Cache ``health`` as the latest reachability result."""
    global _health
    with _lock:
        _health = health
    return health


def store_health(*, force: bool = False, now: Callable[[], float] = time.time) -> StoreHealth:
    """Return the active store's reachability, checking at most once per :data:`HEALTH_TTL_SECONDS`.

    Blocking (a network call for ``s3``): call it from a worker thread in async code.

    Args:
        force: Check now even if a recent result is cached.
        now: Clock (tests).

    Returns:
        The latest result.
    """
    with _lock:
        cached = _health
    if not force and cached is not None and now() - cached.checked_at < HEALTH_TTL_SECONDS:
        return cached
    try:
        check_reachable(get_document_store())
    except Exception as exc:  # noqa: BLE001 - a broken store is a health result, not a crash
        return _record(StoreHealth(ok=False, checked_at=now(), error=_error_text(exc)))
    return _record(StoreHealth(ok=True, checked_at=now()))


def health_detail(health: Optional[StoreHealth] = None) -> Dict[str, Any]:
    """The ``document_store`` block ``GET /health`` embeds — no error text, no settings.

    Args:
        health: A result to report; a (cached) :func:`store_health` check when omitted.

    Returns:
        ``{"status", "backend", "fallback"}``: ``status`` is ``ok``, ``degraded`` (running on the
        ``db`` fallback) or ``unavailable`` (the store did not answer).
    """
    result = health if health is not None else store_health()
    resolution = current_resolution()
    if not result.ok:
        status = "unavailable"
    elif resolution.fallback:
        status = "degraded"
    else:
        status = "ok"
    return {"status": status, "backend": resolution.active_backend, "fallback": resolution.fallback}


def _settings_of(store: DocumentStore) -> Dict[str, Any]:
    """The non-secret settings of ``store``; fields that do not apply to its backend are ``None``."""
    view: Dict[str, Any] = {
        "bucket": None,
        "prefix": getattr(store, "prefix", "") or "",
        "region": None,
        "endpointUrl": None,
        "addressingStyle": None,
        "path": None,
        "encryption": None,
        "kmsKeyId": None,
        "credentials": None,
        "presignTtlSeconds": None,
        "maxObjectBytes": None,
    }
    if isinstance(store, S3DocumentStore):
        view.update(
            bucket=store.bucket,
            region=store.region,
            endpointUrl=store.endpoint_url or None,
            addressingStyle=store.addressing_style,
            encryption=_ENCRYPTION_NAMES.get(store.sse, str(store.sse)),
            kmsKeyId=store.kms_key_id or None,
            # Where the keys come from, never the keys.
            credentials="static" if store._access_key_id else "default-chain",
            presignTtlSeconds=store.presign_ttl_seconds,
        )
    elif isinstance(store, FilesystemDocumentStore):
        view.update(path=str(store.root))
    elif isinstance(store, DbDocumentStore):
        view.update(maxObjectBytes=store.max_bytes)
    return view


def _usage_of(database: Any) -> Optional[Dict[str, Any]]:
    """Index totals and the latest integrity verification, or ``None`` when the index is unreadable."""
    try:
        rows: List[Dict[str, Any]] = list(database.document_store_usage())
    except Exception as exc:  # noqa: BLE001 - an unmigrated or unreachable index is shown as unknown
        logger.warning("document store usage unavailable: %s", type(exc).__name__)
        return None
    by_backend = [
        {"backend": str(row["backend"]), "objects": int(row["objects"]), "bytes": int(row["bytes"])} for row in rows
    ]
    verified = [row["last_verified_at"] for row in rows if row.get("last_verified_at") is not None]
    last = max(verified) if verified else None
    return {
        "objects": sum(item["objects"] for item in by_backend),
        "bytes": sum(item["bytes"] for item in by_backend),
        "byBackend": by_backend,
        "integrity": {
            "lastVerifiedAt": last.isoformat() if hasattr(last, "isoformat") else last,
            "verifiedObjects": sum(int(row.get("verified_objects") or 0) for row in rows),
        },
    }


def _health_view(health: StoreHealth) -> Dict[str, Any]:
    """JSON-ready view of a reachability result."""
    return {"ok": health.ok, "checkedAt": health.checked_at, "error": health.error}


def describe_store(database: Any, *, store: Optional[DocumentStore] = None) -> Dict[str, Any]:
    """The settings, health and usage of the active store (``GET /v1/ops/document-store``).

    Blocking (a reachability check and a database query): call it from a worker thread.

    Args:
        database: The database handle (its ``document_store_usage`` is read).
        store: The store to describe; the process-wide store when omitted.

    Returns:
        ``backend``, ``configuredBackend``, ``fallback`` / ``fallbackReason``, the non-secret
        settings (``bucket``, ``prefix``, ``region``, ``endpointUrl``, ``addressingStyle``,
        ``path``, ``encryption``, ``kmsKeyId``, ``credentials``, ``presignTtlSeconds``,
        ``maxObjectBytes``), ``health`` and ``usage`` (``None`` when the index is unreadable).
    """
    active = store if store is not None else get_document_store()
    resolution = current_resolution()
    body: Dict[str, Any] = {
        "backend": active.backend,
        "configuredBackend": resolution.configured_backend,
        "fallback": resolution.fallback,
        "fallbackReason": resolution.fallback_reason,
        "backends": list(BACKENDS),
    }
    body.update(_settings_of(active))
    body["health"] = _health_view(store_health() if store is None else _check_now(active))
    body["usage"] = _usage_of(database)
    return body


def _check_now(store: DocumentStore) -> StoreHealth:
    """Check a store that is not the process-wide one (not cached)."""
    try:
        check_reachable(store)
    except Exception as exc:  # noqa: BLE001
        return StoreHealth(ok=False, checked_at=time.time(), error=_error_text(exc))
    return StoreHealth(ok=True, checked_at=time.time())


def _step(name: str, action: Callable[[], Any]) -> Dict[str, Any]:
    """Run one probe step and time it; a failure is recorded, not raised."""
    started = time.perf_counter()
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - every failure becomes the step's redacted error
        return {"name": name, "ok": False, "skipped": False, "durationMs": _ms(started), "error": _error_text(exc)}
    return {"name": name, "ok": True, "skipped": False, "durationMs": _ms(started), "error": None}


def _ms(started: float) -> float:
    """Milliseconds since ``started`` (``time.perf_counter``), to 0.1 ms."""
    return round((time.perf_counter() - started) * 1000, 1)


def probe_store(store: Optional[DocumentStore] = None) -> Dict[str, Any]:
    """Write, read back and delete one probe object (``POST /v1/ops/document-store/test``).

    The probe is a few random bytes under the :data:`PROBE_TENANT` key segment, so it never
    collides with a real object and every run writes a new one. The read step fails when the
    bytes come back different. The delete step runs whenever the write succeeded, so a failed
    read leaves nothing behind. Blocking: call it from a worker thread.

    Args:
        store: The store to test; the process-wide store when omitted (its cached health is
            then refreshed with the outcome).

    Returns:
        ``{"ok", "backend", "checkedAt", "durationMs", "steps"}`` — ``steps`` lists ``write``,
        ``read`` and ``delete`` with ``ok``, ``durationMs`` and a redacted ``error``; a step that
        could not run is ``{"ok": False, "skipped": True}``.
    """
    active = store if store is not None else get_document_store()
    payload = f"apiome document store probe {secrets.token_hex(16)} {time.time():.3f}\n".encode("ascii")
    started = time.perf_counter()
    written: Dict[str, Any] = {}

    def write() -> None:
        written["ref"] = active.put(PROBE_TENANT, payload, PROBE_MEDIA_TYPE)

    def read() -> None:
        if active.get(PROBE_TENANT, written["ref"].sha256) != payload:
            raise DocumentStoreError("The probe object was read back with different bytes.")

    def delete() -> None:
        if not active.delete(PROBE_TENANT, written["ref"].sha256):
            raise DocumentStoreError("The probe object was not found when it was deleted.")

    steps = [_step("write", write)]
    if steps[0]["ok"]:
        steps.append(_step("read", read))
        steps.append(_step("delete", delete))
    else:
        for name in ("read", "delete"):
            steps.append({"name": name, "ok": False, "skipped": True, "durationMs": 0.0, "error": None})
    ok = all(step["ok"] for step in steps)
    checked_at = time.time()
    if store is None:
        first_error = next((step["error"] for step in steps if step.get("error")), None)
        _record(StoreHealth(ok=ok, checked_at=checked_at, error=first_error))
    return {
        "ok": ok,
        "backend": active.backend,
        "checkedAt": checked_at,
        "durationMs": _ms(started),
        "steps": steps,
    }
