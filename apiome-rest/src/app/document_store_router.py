"""Route every document store call to the right store for its tenant — COA-5.15 (#7092).

:func:`app.document_store.get_document_store` returns a :class:`TenantRoutingDocumentStore` around
the platform store. It meets the same :class:`~app.document_store.DocumentStore` contract, so no
caller changes:

* A tenant **without** settings (the usual case) goes straight to the platform store. The only
  cost is a cached "this tenant has no row" answer.
* ``put`` goes to the tenant's **target**: its own bucket when its settings say ``tenant``, the
  platform store otherwise.
* ``get`` / ``open_stream`` / ``head`` / ``exists`` / ``presign_get`` / ``delete`` go where the
  object **is**: ``apiome.document_objects.backend`` says ``tenant_s3`` for an object in the
  tenant's bucket and anything else for one in the platform store. While a move is running some
  of a tenant's objects are in each place, and both keep answering. An object with no index row
  yet (a writer stores the bytes before it records them) is looked for at the target, then at
  the other location.

**Failure.** Any failure of a tenant's bucket — unreachable, credential revoked, credential
deleted — is raised as :class:`~app.tenant_document_store.TenantDocumentStoreUnavailable` with a
redacted reason, and flags the tenant for the ops health check and its administrators
(:func:`~app.tenant_document_store.record_outage`). The next call that succeeds clears the flag.
A failing tenant bucket never falls back to the platform store for writes: that would put the
tenant's documents somewhere it did not choose.

**When routing is on.** Only when the install allows tenant buckets
(``APIOME_DOCUMENT_STORE_ALLOW_TENANT_BUCKETS``) or a tenant already has one
(:func:`refresh_routing`, run at startup — so turning the setting off later does not strand a
tenant's documents). Otherwise every call goes straight to the platform store and the database is
never asked.

**Staleness.** Settings and built stores are cached per tenant for :data:`CACHE_TTL_SECONDS`, so
another instance sees a change at most that much later. The move job accounts for it (it rescans
after the TTL has passed), and :meth:`TenantRoutingDocumentStore.invalidate` drops a tenant's
entry in this process as soon as its settings change here.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, BinaryIO, Callable, Dict, Optional, Tuple, Union

from .db_cursor import db_cursor
from .document_store import (
    BACKEND_DB,
    BACKEND_TENANT_S3,
    DEFAULT_MEDIA_TYPE,
    DbDocumentStore,
    DocumentNotFound,
    DocumentStoreError,
    ObjectRef,
)
from .tenant_document_store import (
    TenantDocumentStoreUnavailable,
    TenantStoreSettings,
    build_tenant_store,
    load_settings,
    record_outage,
    record_recovery,
    tenant_buckets_allowed,
)

logger = logging.getLogger(__name__)

__all__ = ["CACHE_TTL_SECONDS", "TenantRoutingDocumentStore", "refresh_routing", "routing_active"]

#: How long a tenant's settings (or the fact that it has none) are trusted without re-reading.
CACHE_TTL_SECONDS = 5.0

TenantStoreBuilder = Callable[[Any, TenantStoreSettings], Any]

#: Whether some tenant had a bucket configured when :func:`refresh_routing` last looked.
_tenant_rows_seen = False


def refresh_routing(db: Any) -> bool:
    """Look for tenants that already have a bucket, so they keep resolving with the setting off.

    Called once at startup. A failed lookup turns routing on: asking the database per tenant is
    the safe side of not knowing.

    Args:
        db: Database handle.

    Returns:
        Whether routing is active after the check.
    """
    global _tenant_rows_seen
    try:
        with db_cursor(db) as cursor:
            cursor.execute("SELECT 1 FROM apiome.tenant_document_stores WHERE bucket IS NOT NULL LIMIT 1")
            _tenant_rows_seen = cursor.fetchone() is not None
    except Exception:  # noqa: BLE001
        logger.warning("document store: could not check for tenant buckets; routing per tenant", exc_info=True)
        _tenant_rows_seen = True
    return routing_active()


def routing_active() -> bool:
    """Whether calls are resolved per tenant (see the module docstring)."""
    return _tenant_rows_seen or tenant_buckets_allowed()


class _Entry:
    """A tenant's cached settings and, once needed, the store built from them."""

    __slots__ = ("settings", "store", "error", "expires")

    def __init__(self, store_settings: Optional[TenantStoreSettings], expires: float) -> None:
        self.settings = store_settings
        self.store: Any = None
        self.error: Optional[TenantDocumentStoreUnavailable] = None
        self.expires = expires


class TenantRoutingDocumentStore:
    """The platform store, with tenants that keep documents in their own bucket routed there."""

    def __init__(
        self,
        platform: Any,
        *,
        database: Any = None,
        build: TenantStoreBuilder = build_tenant_store,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        active: Callable[[], bool] = routing_active,
    ) -> None:
        """
        Args:
            platform: The install's own store.
            database: Database handle; the process-wide one when omitted.
            build: Builds a tenant's store from its settings (tests inject one).
            ttl_seconds: How long cached settings are trusted.
            active: Whether calls are resolved per tenant at all (tests force it on).
        """
        self.platform = platform
        self._database = database
        self._build = build
        self._ttl = float(ttl_seconds)
        self._active = active
        self._entries: Dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"TenantRoutingDocumentStore({self.platform!r})"

    def __getattr__(self, name: str) -> Any:
        # Settings the platform store exposes (bucket, region, path, …) read through.
        if name.startswith("_") or name == "platform":
            raise AttributeError(name)
        return getattr(self.platform, name)

    @property
    def backend(self) -> str:
        """The platform store's backend — what an object outside any tenant bucket is recorded as."""
        return self.platform.backend

    def _db(self) -> Any:
        if self._database is not None:
            return self._database
        from .database import db

        return db

    # -- resolution ------------------------------------------------------------------------

    def invalidate(self, tenant_id: Optional[str] = None) -> None:
        """Drop cached settings — one tenant's, or everyone's — so the next call re-reads them."""
        with self._lock:
            if tenant_id is None:
                self._entries.clear()
            else:
                self._entries.pop(str(tenant_id), None)

    def _entry(self, tenant_id: str) -> _Entry:
        if not self._active():
            return _PLATFORM_ONLY
        tenant = str(tenant_id)
        now = time.monotonic()
        entry = self._entries.get(tenant)
        if entry is not None and entry.expires > now:
            return entry
        try:
            store_settings = load_settings(self._db(), tenant)
        except Exception:  # noqa: BLE001 - never guess where a tenant's documents are
            if entry is not None:
                return entry  # keep serving the last known answer
            raise
        fresh = _Entry(store_settings, now + self._ttl)
        if entry is not None and entry.settings == store_settings:
            fresh.store, fresh.error = entry.store, entry.error
        with self._lock:
            self._entries[tenant] = fresh
        return fresh

    def settings_for(self, tenant_id: str) -> Optional[TenantStoreSettings]:
        """The tenant's cached settings, or ``None`` when it uses the platform store and always has."""
        return self._entry(tenant_id).settings

    def tenant_store(self, tenant_id: str) -> Any:
        """The store for the tenant's own bucket.

        Raises:
            TenantDocumentStoreUnavailable: if the tenant has no bucket configured, or its
                credential cannot be opened. The outage is recorded.
        """
        entry = self._entry(tenant_id)
        if entry.store is not None:
            return entry.store
        if entry.error is not None:
            raise entry.error
        store_settings = entry.settings
        try:
            if store_settings is None:
                raise TenantDocumentStoreUnavailable(str(tenant_id), "No bucket is configured for this workspace.")
            entry.store = self._build(self._db(), store_settings)
        except TenantDocumentStoreUnavailable as exc:
            entry.error = exc
            if store_settings is not None:
                record_outage(self._db(), str(tenant_id), exc.reason)
            raise
        return entry.store

    def target_backend(self, tenant_id: str) -> str:
        """The backend new objects of this tenant are recorded with."""
        store_settings = self.settings_for(tenant_id)
        if store_settings is not None and store_settings.uses_tenant_bucket:
            return BACKEND_TENANT_S3
        return self.platform.backend

    def platform_store_for(self, row_backend: Optional[str]) -> Any:
        """The platform-side store that holds an object recorded with ``row_backend``.

        The active platform store, or the database backend for an object written before the
        install moved off it.
        """
        if row_backend == BACKEND_DB and self.platform.backend != BACKEND_DB:
            return DbDocumentStore(database=self._db())
        return self.platform

    def _indexed_backend(self, tenant_id: str, sha256: str) -> Optional[str]:
        """``document_objects.backend`` of the object, or ``None`` when it has no index row."""
        with db_cursor(self._db()) as cursor:
            cursor.execute(
                "SELECT backend FROM apiome.document_objects WHERE tenant_id = %s AND sha256 = %s",
                (str(tenant_id), str(sha256)),
            )
            row = cursor.fetchone()
        return str(row["backend"]) if row else None

    def _locations(self, tenant_id: str, sha256: str) -> Tuple[Tuple[bool, Optional[str]], ...]:
        """Where to look for an object, in order: ``(in the tenant bucket?, row backend)`` pairs."""
        store_settings = self.settings_for(tenant_id)
        if store_settings is None:
            return ((False, None),)
        indexed = self._indexed_backend(tenant_id, sha256)
        if indexed is not None:
            return ((indexed == BACKEND_TENANT_S3, indexed),)
        if not store_settings.has_bucket:
            return ((False, None),)
        first = store_settings.uses_tenant_bucket
        return ((first, None), (not first, None))

    # -- running a call --------------------------------------------------------------------

    def _on_tenant(self, tenant_id: str, call: Callable[[Any], Any]) -> Any:
        """Run ``call`` against the tenant's bucket, turning any failure into an outage."""
        store = self.tenant_store(tenant_id)
        try:
            result = call(store)
        except DocumentNotFound:
            raise
        except TenantDocumentStoreUnavailable as exc:
            record_outage(self._db(), str(tenant_id), exc.reason)
            raise
        except DocumentStoreError as exc:
            reason = str(exc)
            record_outage(self._db(), str(tenant_id), reason)
            raise TenantDocumentStoreUnavailable(str(tenant_id), reason) from None
        store_settings = self.settings_for(tenant_id)
        record_recovery(
            self._db(),
            str(tenant_id),
            flagged=bool(store_settings is not None and store_settings.unavailable_since),
        )
        return result

    def _read(self, tenant_id: str, sha256: str, call: Callable[[Any], Any], *, missing: Any = None) -> Any:
        """Run a read where the object is; ``missing`` is what "not there" looks like for ``call``.

        A read that raises :class:`DocumentNotFound` (or returns ``missing``) at the first
        location is retried at the next one, when there is one.
        """
        locations = self._locations(tenant_id, sha256)
        last_missing: Optional[DocumentNotFound] = None
        result: Any = missing
        for in_tenant_bucket, row_backend in locations:
            try:
                if in_tenant_bucket:
                    result = self._on_tenant(tenant_id, call)
                else:
                    result = call(self.platform_store_for(row_backend))
            except DocumentNotFound as exc:
                last_missing = exc
                continue
            if result is not missing or missing is _RAISES:
                return result
        if last_missing is not None:
            raise last_missing
        return result

    # -- contract --------------------------------------------------------------------------

    def put(
        self,
        tenant_id: str,
        data: Union[bytes, BinaryIO],
        media_type: str = DEFAULT_MEDIA_TYPE,
    ) -> ObjectRef:
        """Store an object in the tenant's target store; idempotent."""
        store_settings = self.settings_for(tenant_id)
        if store_settings is not None and store_settings.uses_tenant_bucket:
            return self._on_tenant(tenant_id, lambda store: store.put(tenant_id, data, media_type))
        return self.platform.put(tenant_id, data, media_type)

    def get(self, tenant_id: str, sha256: str) -> bytes:
        """Return the whole object from wherever it is stored."""
        return self._read(tenant_id, sha256, lambda store: store.get(tenant_id, sha256), missing=_RAISES)

    def open_stream(self, tenant_id: str, sha256: str) -> BinaryIO:
        """Return a readable stream of the object from wherever it is stored."""
        return self._read(tenant_id, sha256, lambda store: store.open_stream(tenant_id, sha256), missing=_RAISES)

    def head(self, tenant_id: str, sha256: str) -> Optional[ObjectRef]:
        """Return the object's reference, or ``None`` when it is stored nowhere."""
        return self._read(tenant_id, sha256, lambda store: store.head(tenant_id, sha256), missing=None)

    def exists(self, tenant_id: str, sha256: str) -> bool:
        """Report whether the object is stored for the tenant, in either location."""
        return self.head(tenant_id, sha256) is not None

    def delete(self, tenant_id: str, sha256: str) -> bool:
        """Remove the object from wherever it is stored."""
        return bool(self._read(tenant_id, sha256, lambda store: store.delete(tenant_id, sha256), missing=False))

    def presign_get(
        self,
        tenant_id: str,
        sha256: str,
        ttl: Optional[int] = None,
        *,
        content_disposition: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Return a download link from the store that holds the object, or ``None``."""

        def call(store: Any) -> Optional[str]:
            return store.presign_get(
                tenant_id, sha256, ttl, content_disposition=content_disposition, content_type=content_type
            )

        in_tenant_bucket, row_backend = self._locations(tenant_id, sha256)[0]
        if in_tenant_bucket:
            return self._on_tenant(tenant_id, call)
        return call(self.platform_store_for(row_backend))

    # -- keys and tenant-wide operations -----------------------------------------------------

    def key_for(self, tenant_id: str, sha256: str) -> str:
        """The key a new object of this tenant is written under."""
        store_settings = self.settings_for(tenant_id)
        if store_settings is not None and store_settings.uses_tenant_bucket:
            return self.tenant_store(tenant_id).key_for(tenant_id, sha256)
        return self.platform.key_for(tenant_id, sha256)

    def tenant_prefix(self, tenant_id: str) -> str:
        """The platform store's folder for the tenant."""
        return self.platform.tenant_prefix(tenant_id)

    def delete_tenant_objects(self, tenant_id: str) -> int:
        """Delete every object of a tenant: its platform folder, and Apiome's folder in its bucket.

        Only keys under ``<prefix>/tenants/<tenant_id>/`` are removed from a tenant's bucket —
        never the bucket, and never anything else in it.

        Raises:
            DocumentStoreError: if a store fails. A tenant bucket that cannot be reached is a
                :class:`TenantDocumentStoreUnavailable`, after the platform folder is emptied.
        """
        deleted = int(self.platform.delete_tenant_objects(tenant_id))
        store_settings = self.settings_for(tenant_id)
        if store_settings is not None and store_settings.has_bucket:
            deleted += int(self._on_tenant(tenant_id, lambda store: store.delete_tenant_objects(tenant_id)))
        return deleted


#: Sentinel: the call signals "not there" by raising :class:`DocumentNotFound`, not by a value.
_RAISES = object()

#: The answer for every tenant while routing is off: no settings, so the platform store.
_PLATFORM_ONLY = _Entry(None, float("inf"))
