"""Document object lifecycle: reference counts, garbage collection and integrity — COA-5.10 (#7086).

Stored objects are content-addressed, so one object can serve many revisions (two imports of the
same file share it). Deleting a revision therefore cannot delete its objects outright. Instead:

* **Reference counts.** Migration V406 keeps ``document_objects.ref_count`` equal to the object's
  *live* references: ``version_documents`` links whose revision and tenant are not deleted. Its
  triggers recount on every link insert or delete and whenever a revision or tenant is deleted
  or restored, and stamp ``unreferenced_at`` when the count reaches zero. A soft-deleted project
  keeps its references, because a project can be restored.
* **Delete at zero.** :func:`release_versions` runs right after a version is deleted or pruned:
  every object those revisions linked to that is now unreferenced is deleted from the store and
  the index (:func:`purge_object`). Each purge recounts under a row lock first, so an object
  another revision still uses is kept.
* **Garbage collection.** :func:`run_document_lifecycle` (scheduled, and
  ``scripts/document_lifecycle.py``) deletes objects unreferenced for longer than the grace period
  (including rows a crashed writer never linked), drops rendered documents a newer render of the
  same revision replaced (:func:`prune_stale_renders`), and empties the store prefix of tenants
  deleted longer than the grace period ago (:func:`purge_deleted_tenants`).
* **Integrity.** :func:`run_integrity` re-hashes a sample of objects (or all of them) and stamps
  ``verified_at``. A mismatch or a missing object is audited and logged at ``ERROR`` with the
  fixed text ``document integrity failure`` (alert on it); a rendered document is dropped so the
  next request renders it again, and an original or frozen schema is flagged
  (``integrity_failed_at``).

Every purge and integrity failure writes an ``apiome.document_lifecycle_events`` row. One run at a
time across instances (a Postgres advisory lock).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Sequence

from .config import settings
from .document_store import (
    BACKEND_DB,
    BACKEND_TENANT_S3,
    DbDocumentStore,
    DocumentNotFound,
    DocumentStoreError,
    get_document_store,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LifecycleOptions",
    "LifecycleReport",
    "ROLES_RENDERED",
    "purge_deleted_tenants",
    "purge_object",
    "prune_stale_renders",
    "release_versions",
    "release_versions_safely",
    "run_document_lifecycle",
    "run_integrity",
]

#: ``version_documents.role`` values that can be rendered again from the revision.
ROLES_RENDERED = frozenset({"rendered_openapi", "rendered_openapi_members", "rendered_canonical"})

#: Audit events (``document_lifecycle_events.event``).
EVENT_PURGED = "object_purged"
EVENT_PURGE_FAILED = "object_purge_failed"
EVENT_TENANT_PURGED = "tenant_purged"
EVENT_INTEGRITY_FAILED = "integrity_failed"
EVENT_RENDERED_DROPPED = "rendered_dropped"

#: Purge reasons.
REASON_VERSION_DELETED = "version-deleted"
REASON_UNREFERENCED = "unreferenced"
REASON_STALE_RENDER = "stale-render"
REASON_TENANT_DELETED = "tenant-deleted"

#: Integrity failure reasons.
REASON_MISMATCH = "mismatch"
REASON_MISSING = "missing"

#: The fixed log text an alert can match on.
INTEGRITY_ALERT = "document integrity failure"

_LOCK_KEY = "apiome.document_lifecycle"
_BATCH = 500
_HASH_CHUNK = 1024 * 1024


@dataclass
class LifecycleOptions:
    """What one lifecycle run does.

    Attributes:
        grace: How long an object (or a replaced render, or a deleted tenant) waits before it is
            deleted.
        integrity_sample: How many objects the integrity run re-hashes (least recently verified
            first); 0 skips it. Ignored when ``integrity_all``.
        integrity_all: Re-hash every indexed object.
        gc: Run garbage collection (unreferenced objects, stale renders, deleted tenants).
        dry_run: Report what would be deleted; delete, flag and stamp nothing.
    """

    grace: timedelta = field(default_factory=lambda: timedelta(hours=24))
    integrity_sample: int = 100
    integrity_all: bool = False
    gc: bool = True
    dry_run: bool = False

    @classmethod
    def from_settings(cls, config: Any = None) -> "LifecycleOptions":
        """The scheduled run's options (``APIOME_DOCUMENT_GC_GRACE_HOURS``, ``…_INTEGRITY_SAMPLE``)."""
        cfg = config if config is not None else settings
        return cls(
            grace=timedelta(hours=float(cfg.document_gc_grace_hours)),
            integrity_sample=int(cfg.document_integrity_sample),
        )


@dataclass
class LifecycleReport:
    """What a run did (or, in a dry run, would do)."""

    objects_purged: int = 0
    bytes_purged: int = 0
    purge_failures: int = 0
    stale_renders_dropped: int = 0
    tenants_purged: int = 0
    tenant_objects_deleted: int = 0
    objects_verified: int = 0
    integrity_failures: int = 0
    integrity_skipped: int = 0
    dry_run: bool = False
    locked: bool = False

    def as_dict(self) -> Dict[str, Any]:
        """JSON-ready view."""
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(db: Any, **values: Any) -> None:
    """Write an audit row; an audit failure is logged, never raised (the work is already done)."""
    try:
        db.insert_document_lifecycle_event(**values)
    except Exception:  # noqa: BLE001
        logger.warning("document lifecycle audit failed event=%s", values.get("event"), exc_info=True)


def _store_for(row: Dict[str, Any], store: Any, db: Any) -> Optional[Any]:
    """The store holding ``row``'s bytes: the active one, or the database backend; else ``None``.

    An object in its tenant's own bucket (``tenant_s3``, COA-5.15) is reached through the routing
    store, which finds the tenant's bucket itself.
    """
    backend = str(row.get("backend") or "")
    if backend == getattr(store, "backend", None):
        return store
    if backend == BACKEND_TENANT_S3 and hasattr(store, "tenant_store"):
        return store
    if backend == BACKEND_DB:
        return DbDocumentStore(database=db)
    return None


def purge_object(
    db: Any, store: Any, object_id: str, *, reason: str, dry_run: bool = False
) -> Optional[Dict[str, Any]]:
    """Delete one object from the index and the store when nothing live uses it.

    The index row goes first (recounted under a row lock, see
    :meth:`~app.database.Database.purge_unreferenced_document_object`); the bytes go second, and
    only when no writer has re-created the row meanwhile. If the bytes cannot be deleted the row is
    gone anyway and an ``object_purge_failed`` row records the key, so an operator can remove it.

    Args:
        db: Database handle.
        store: The active document store.
        object_id: ``document_objects.id``.
        reason: Why it is purged (``version-deleted``, ``unreferenced``, ``stale-render``,
            ``tenant-deleted``), for the audit row.
        dry_run: Delete nothing.

    Returns:
        The purged row (``id``, ``tenant_id``, ``sha256``, ``backend``, ``storage_key``,
        ``size_bytes``), or ``None`` when the object is still referenced or already gone.
    """
    if dry_run:
        return None
    row = db.purge_unreferenced_document_object(object_id)
    if row is None:
        return None
    audit = {
        "tenant_id": row["tenant_id"],
        "object_id": row["id"],
        "sha256": row["sha256"],
        "backend": row["backend"],
        "storage_key": row["storage_key"],
    }
    if db.document_object_indexed(row["tenant_id"], row["sha256"]):
        # A writer stored the same bytes again between the two steps: they are in use.
        _audit(db, event=EVENT_PURGED, reason=reason, detail={"bytesKept": True}, **audit)
        return row
    target = _store_for(row, store, db)
    try:
        if target is None:
            raise DocumentStoreError(f"The {row['backend']} backend that holds the object is not the active store.")
        target.delete(row["tenant_id"], row["sha256"])
    except Exception as exc:  # noqa: BLE001 - recorded for the operator, never raised
        message = str(exc) if isinstance(exc, DocumentStoreError) else type(exc).__name__
        logger.warning("document lifecycle: object %s not deleted from the store: %s", row["storage_key"], message)
        _audit(db, event=EVENT_PURGE_FAILED, reason=reason, detail={"error": message}, **audit)
        return row
    _audit(db, event=EVENT_PURGED, reason=reason, detail={"sizeBytes": int(row.get("size_bytes") or 0)}, **audit)
    return row


def _purge_many(
    db: Any, store: Any, rows: Sequence[Dict[str, Any]], reason: str, report: LifecycleReport, dry_run: bool
) -> None:
    """Purge each listed object and add it to the report."""
    for row in rows:
        if dry_run:
            report.objects_purged += 1
            report.bytes_purged += int(row.get("size_bytes") or 0)
            continue
        purged = purge_object(db, store, row["id"], reason=reason)
        if purged is not None:
            report.objects_purged += 1
            report.bytes_purged += int(purged.get("size_bytes") or 0)


def release_versions(db: Any, version_ids: Sequence[str], *, store: Any = None) -> int:
    """Delete the objects deleted or pruned revisions used, when no live revision uses them.

    Call it after the revisions' ``deleted_at`` is set (V406 has recounted by then).

    Args:
        db: Database handle.
        version_ids: The revisions just deleted or pruned.
        store: The document store; the process-wide one when omitted.

    Returns:
        How many objects were deleted.
    """
    object_ids = db.document_object_ids_for_versions(list(version_ids))
    if not object_ids:
        return 0
    active = store if store is not None else get_document_store()
    rows = db.list_unreferenced_document_objects(cutoff=_now(), object_ids=object_ids, limit=len(object_ids))
    report = LifecycleReport()
    _purge_many(db, active, rows, REASON_VERSION_DELETED, report, dry_run=False)
    return report.objects_purged


def release_versions_safely(db: Any, version_ids: Sequence[str], *, store: Any = None) -> int:
    """:func:`release_versions` that never raises: the deletion already succeeded, and garbage
    collection retries anything left behind after the grace period."""
    try:
        return release_versions(db, version_ids, store=store)
    except Exception:  # noqa: BLE001
        logger.warning("document release failed for versions %s", list(version_ids), exc_info=True)
        return 0


def collect_unreferenced(db: Any, store: Any, options: LifecycleOptions, report: LifecycleReport) -> None:
    """Delete every object unreferenced for longer than the grace period."""
    cutoff = _now() - options.grace
    seen: set = set()
    while True:
        rows = [r for r in db.list_unreferenced_document_objects(cutoff=cutoff, limit=_BATCH) if r["id"] not in seen]
        if not rows:
            return
        seen.update(r["id"] for r in rows)
        _purge_many(db, store, rows, REASON_UNREFERENCED, report, options.dry_run)
        if options.dry_run:
            return


def prune_stale_renders(db: Any, store: Any, options: LifecycleOptions, report: LifecycleReport) -> None:
    """Drop rendered documents replaced longer than the grace period ago, then purge their objects."""
    if options.dry_run:
        return
    cutoff = _now() - options.grace
    while True:
        object_ids = db.delete_stale_rendered_documents(cutoff=cutoff, limit=_BATCH)
        if not object_ids:
            return
        report.stale_renders_dropped += len(object_ids)
        rows = db.list_unreferenced_document_objects(cutoff=_now(), object_ids=object_ids, limit=len(object_ids))
        _purge_many(db, store, rows, REASON_STALE_RENDER, report, dry_run=False)


def purge_deleted_tenants(db: Any, store: Any, options: LifecycleOptions, report: LifecycleReport) -> None:
    """Empty the store prefix of each tenant deleted longer than the grace period ago.

    Every indexed object of the tenant is purged, then everything left under
    ``<prefix>/tenants/<tenant id>/`` (and under its slug, where export downloads are kept, unless
    a live tenant now has that slug) is deleted, and the tenant is recorded as purged.
    """
    cutoff = _now() - options.grace
    for tenant in db.list_purgeable_tenants(cutoff=cutoff):
        tenant_id = tenant["id"]
        if options.dry_run:
            report.tenants_purged += 1
            continue
        rows = [{"id": object_id} for object_id in db.tenant_document_object_ids(tenant_id)]
        before = report.objects_purged
        _purge_many(db, store, rows, REASON_TENANT_DELETED, report, dry_run=False)
        deleted = report.objects_purged - before
        segments = [tenant_id]
        slug = tenant.get("slug")
        if slug and slug != tenant_id and not tenant.get("slug_in_use"):
            segments.append(slug)
        try:
            for segment in segments:
                deleted += _delete_prefix(db, store, segment)
        except Exception as exc:  # noqa: BLE001 - retried on the next run (the tenant is not recorded)
            message = str(exc) if isinstance(exc, DocumentStoreError) else type(exc).__name__
            logger.warning("document lifecycle: tenant %s prefix not emptied: %s", tenant_id, message)
            _audit(
                db,
                event=EVENT_PURGE_FAILED,
                reason=REASON_TENANT_DELETED,
                tenant_id=tenant_id,
                detail={"error": message},
            )
            continue
        db.record_document_tenant_purge(tenant_id, deleted)
        report.tenants_purged += 1
        report.tenant_objects_deleted += deleted
        _audit(
            db,
            event=EVENT_TENANT_PURGED,
            reason=REASON_TENANT_DELETED,
            tenant_id=tenant_id,
            backend=getattr(store, "backend", None),
            detail={"objectsDeleted": deleted, "segments": segments},
        )


def _delete_prefix(db: Any, store: Any, segment: str) -> int:
    """Delete everything under a tenant key segment in the active store (and in the database store)."""
    try:
        deleted = int(store.delete_tenant_objects(segment))
    except ValueError:
        return 0  # not a key segment this store could ever have written
    if getattr(store, "backend", None) != BACKEND_DB:
        # Objects written before a switch to s3/filesystem can still sit in the database store.
        deleted += int(DbDocumentStore(database=db).delete_tenant_objects(segment))
    return deleted


def _hash_stored(store: Any, tenant_id: str, sha256: str) -> str:
    """Return the SHA-256 of an object's stored bytes, read in chunks."""
    digest = hashlib.sha256()
    stream = store.open_stream(tenant_id, sha256)
    try:
        while True:
            chunk = stream.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return digest.hexdigest()


def _check_one(db: Any, store: Any, row: Dict[str, Any], report: LifecycleReport, dry_run: bool) -> None:
    """Re-hash one object; stamp it, or audit and handle the failure."""
    target = _store_for(row, store, db)
    if target is None:
        report.integrity_skipped += 1
        return
    try:
        actual = _hash_stored(target, row["tenant_id"], row["sha256"])
        reason = None if actual == row["sha256"] else REASON_MISMATCH
    except DocumentNotFound:
        actual, reason = None, REASON_MISSING
    except Exception as exc:  # noqa: BLE001 - an unreachable store is not evidence of corruption
        logger.warning("document integrity: %s could not be read: %s", row["storage_key"], type(exc).__name__)
        report.integrity_skipped += 1
        return
    if reason is None:
        report.objects_verified += 1
        if not dry_run:
            db.mark_document_object_verified(row["id"])
        return

    report.integrity_failures += 1
    roles = sorted(set(row.get("roles") or []))
    logger.error(
        "%s: object %s (%s) %s; roles=%s",
        INTEGRITY_ALERT,
        row["storage_key"],
        row["backend"],
        "is missing" if reason == REASON_MISSING else "hashes to a different SHA-256",
        ",".join(roles) or "none",
    )
    if dry_run:
        return
    audit = {
        "tenant_id": row["tenant_id"],
        "object_id": row["id"],
        "sha256": row["sha256"],
        "backend": row["backend"],
        "storage_key": row["storage_key"],
    }
    _audit(db, event=EVENT_INTEGRITY_FAILED, reason=reason, detail={"actualSha256": actual, "roles": roles}, **audit)
    if roles and set(roles) <= ROLES_RENDERED and db.drop_rendered_document_object(row["id"]):
        # The next request renders the document again and writes fresh bytes.
        try:
            target.delete(row["tenant_id"], row["sha256"])
        except Exception:  # noqa: BLE001 - a bad object left in the store is overwritten by the re-render
            logger.warning("document integrity: bad rendered object %s not deleted", row["storage_key"])
        _audit(db, event=EVENT_RENDERED_DROPPED, reason=reason, **audit)
        return
    db.flag_document_object_integrity(row["id"])


def run_integrity(db: Any, store: Any, options: LifecycleOptions, report: LifecycleReport) -> None:
    """Re-hash a sample of objects (least recently verified first), or every object."""
    if options.integrity_all:
        after: Optional[str] = None
        while True:
            rows = db.list_document_objects_for_integrity(limit=_BATCH, after_id=after, oldest_first=False)
            if not rows:
                return
            for row in rows:
                _check_one(db, store, row, report, options.dry_run)
            after = rows[-1]["id"]
    if options.integrity_sample <= 0:
        return
    for row in db.list_document_objects_for_integrity(limit=options.integrity_sample):
        _check_one(db, store, row, report, options.dry_run)


def run_document_lifecycle(
    db: Any,
    options: Optional[LifecycleOptions] = None,
    *,
    store: Any = None,
    lock: Optional[Callable[[Any], bool]] = None,
    unlock: Optional[Callable[[Any], None]] = None,
) -> LifecycleReport:
    """Run garbage collection and the integrity check once.

    Args:
        db: Database handle (its own connection: the advisory lock is per session).
        options: What to do; the scheduled defaults when omitted.
        store: The document store; the process-wide one when omitted.
        lock: Takes the cross-instance lock (tests pass a stub); ``False`` skips the run.
        unlock: Releases it.

    Returns:
        The report. ``locked`` is ``True`` when another run held the lock and nothing was done.
    """
    opts = options or LifecycleOptions.from_settings()
    active = store if store is not None else get_document_store()
    report = LifecycleReport(dry_run=opts.dry_run)
    take = lock or _try_lock
    release = unlock or _unlock
    if not take(db):
        report.locked = True
        return report
    try:
        if opts.gc:
            prune_stale_renders(db, active, opts, report)
            collect_unreferenced(db, active, opts, report)
            purge_deleted_tenants(db, active, opts, report)
        run_integrity(db, active, opts, report)
    finally:
        release(db)
    if report.objects_purged or report.tenants_purged or report.integrity_failures:
        logger.info("document lifecycle: %s", report.as_dict())
    return report


def _try_lock(db: Any) -> bool:
    """Take the run's session advisory lock; ``False`` when another run holds it."""
    rows = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (_LOCK_KEY,))
    return bool(rows and rows[0].get("locked"))


def _unlock(db: Any) -> None:
    """Release the run's session advisory lock."""
    db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (_LOCK_KEY,))
