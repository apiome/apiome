"""Move a tenant's stored objects between the platform store and its own bucket — COA-5.15 (#7092).

When a tenant switches where its documents are kept, new objects go to the new place at once
(:mod:`app.document_store_router`). The objects it already has are moved by this job, in the
copy-and-verify style of COA-5.8's :mod:`app.document_migration`:

* **Copy, read back, verify, then re-point.** Each object is read from where it is, checked
  against its SHA-256, written to the target, read back from the target and checked again. Only
  then is its ``apiome.document_objects`` row re-pointed (``backend``, ``storage_key``) and
  stamped ``verified_at``. The copy in the old place is left alone.
* **Nothing fails during a move.** A read follows the object's row, so an object answers from
  the old place until the moment its row is re-pointed and from the new place after.
* **Resumable.** After each batch the job records the last object it finished and its counts on
  the tenant's settings row. A run that died is picked up from there.
* **One run per tenant.** A Postgres advisory lock keyed by the tenant; a second run exits.
* **Catches late writes.** Another instance may keep writing to the old target until its cached
  settings expire, so after the first pass the job waits out that window and scans again until a
  scan finds nothing left.
* **An object that cannot be moved keeps working.** It is counted as failed, its row is not
  touched, and the move ends ``failed`` with a reason; running the move again retries it.

Old copies are deleted by :func:`cleanup_old_copies`, and only after an explicit confirm.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .db_cursor import db_cursor
from .document_store import DocumentNotFound, DocumentStoreError
from .document_store_router import CACHE_TTL_SECONDS
from .tenant_document_store import (
    MODE_PLATFORM,
    MODE_TENANT,
    MOVE_COMPLETED,
    MOVE_FAILED,
    MOVE_RUNNING,
    TenantDocumentStoreUnavailable,
    load_settings,
    record_outage,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MoveBusy",
    "MoveReport",
    "begin_move",
    "cleanup_old_copies",
    "move_running_here",
    "run_move",
    "start_move_thread",
]

DEFAULT_BATCH_SIZE = 100
#: How long after its start a move rescans, so writes made on stale settings are caught.
SETTLE_SECONDS = CACHE_TTL_SECONDS + 1.0
_MAX_ERROR_CHARS = 500


class MoveBusy(Exception):
    """Another move or cleanup of the same tenant is in progress."""


@dataclass
class MoveReport:
    """What one run did.

    Attributes:
        tenant_id: The tenant.
        target: ``tenant`` or ``platform`` — where objects were moved to.
        total: Objects that needed moving when the run started.
        moved: Objects copied, verified and re-pointed.
        failed: Objects that could not be moved (their rows are unchanged).
        state: ``completed`` or ``failed``.
        error: Why the run failed, redacted.
    """

    tenant_id: str
    target: str
    total: int = 0
    moved: int = 0
    failed: int = 0
    state: str = MOVE_COMPLETED
    error: Optional[str] = None
    failed_ids: Set[str] = field(default_factory=set, repr=False)

    def counts(self) -> Dict[str, int]:
        """The counts recorded on the settings row."""
        return {"total": self.total, "moved": self.moved, "failed": self.failed}


# ── Locking ───────────────────────────────────────────────────────────────────────────────────


def _lock_key(tenant_id: str) -> str:
    return f"apiome-document-store-move:{tenant_id}"


def _try_lock(db: Any, tenant_id: str) -> bool:
    rows = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (_lock_key(tenant_id),))
    return bool(rows and rows[0]["locked"])


def _unlock(db: Any, tenant_id: str) -> None:
    try:
        db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (_lock_key(tenant_id),))
    except Exception:  # noqa: BLE001 - the session's end releases it anyway
        logger.warning("document store move: unlock failed for tenant %s", tenant_id, exc_info=True)


# ── State on the settings row ─────────────────────────────────────────────────────────────────


def begin_move(db: Any, tenant_id: str, target: str) -> None:
    """Mark a tenant's move as running towards ``target`` (it starts from the first object).

    Args:
        db: Database handle.
        tenant_id: The tenant.
        target: ``tenant`` or ``platform``.
    """
    if target not in (MODE_PLATFORM, MODE_TENANT):
        raise ValueError("target must be platform or tenant")
    with db_cursor(db) as cursor:
        cursor.execute(
            """
            UPDATE apiome.tenant_document_stores
               SET move_state = 'running', move_target = %s, move_last_key = NULL,
                   move_counts = '{}'::jsonb, move_error = NULL,
                   move_started_at = now(), move_finished_at = NULL
             WHERE tenant_id = %s::uuid
            """,
            (target, str(tenant_id)),
        )


def _save_progress(db: Any, report: MoveReport, last_key: Optional[str]) -> None:
    from psycopg2.extras import Json

    with db_cursor(db) as cursor:
        cursor.execute(
            """
            UPDATE apiome.tenant_document_stores
               SET move_last_key = %s, move_counts = %s
             WHERE tenant_id = %s::uuid
            """,
            (last_key, Json(report.counts()), report.tenant_id),
        )


def _finish(db: Any, report: MoveReport) -> None:
    from psycopg2.extras import Json

    with db_cursor(db) as cursor:
        cursor.execute(
            """
            UPDATE apiome.tenant_document_stores
               SET move_state = %s, move_error = %s, move_counts = %s, move_finished_at = now(),
                   cleanup_pending = cleanup_pending OR %s
             WHERE tenant_id = %s::uuid
            """,
            (report.state, report.error, Json(report.counts()), report.moved > 0, report.tenant_id),
        )


# ── One object ────────────────────────────────────────────────────────────────────────────────

_CANDIDATE = {
    # To the tenant's bucket: everything not already there.
    MODE_TENANT: "backend <> 'tenant_s3'",
    # Back to the platform store: everything in the tenant's bucket.
    MODE_PLATFORM: "backend = 'tenant_s3'",
}


def _candidates(db: Any, tenant_id: str, target: str, after: str, limit: int) -> List[Dict[str, Any]]:
    with db_cursor(db) as cursor:
        cursor.execute(
            f"""
            SELECT id::text AS id, sha256, media_type, backend
              FROM apiome.document_objects
             WHERE tenant_id = %s AND {_CANDIDATE[target]} AND id::text COLLATE "C" > %s
             ORDER BY id::text COLLATE "C" LIMIT %s
            """,
            (str(tenant_id), after, int(limit)),
        )
        return [dict(row) for row in cursor.fetchall()]


def _count_candidates(db: Any, tenant_id: str, target: str) -> int:
    with db_cursor(db) as cursor:
        cursor.execute(
            f"SELECT count(*) AS n FROM apiome.document_objects WHERE tenant_id = %s AND {_CANDIDATE[target]}",
            (str(tenant_id),),
        )
        row = cursor.fetchone()
    return int(row["n"]) if row else 0


def _move_one(db: Any, router: Any, tenant_id: str, target: str, row: Dict[str, Any]) -> None:
    """Copy one object to the target, verify it there and re-point its row.

    Raises:
        TenantDocumentStoreUnavailable: if the tenant's bucket fails (the run stops).
        DocumentStoreError: if the object cannot be read, written or verified.
    """
    sha256 = str(row["sha256"])
    tenant_bucket = router.tenant_store(tenant_id)
    platform = router.platform_store_for(row["backend"])
    source, destination = (platform, tenant_bucket) if target == MODE_TENANT else (tenant_bucket, router.platform)
    try:
        data = source.get(tenant_id, sha256)
    except DocumentNotFound:
        raise DocumentStoreError("the object is missing from where its record says it is") from None
    if hashlib.sha256(data).hexdigest() != sha256:
        raise DocumentStoreError("the stored bytes no longer match the object's SHA-256")
    ref = destination.put(tenant_id, data, row.get("media_type") or "application/octet-stream")
    if ref.sha256 != sha256 or hashlib.sha256(destination.get(tenant_id, sha256)).hexdigest() != sha256:
        raise DocumentStoreError("the copy did not read back identical")
    with db_cursor(db) as cursor:
        # Guarded by the backend it was read from: a row someone else re-pointed is left alone.
        cursor.execute(
            """
            UPDATE apiome.document_objects
               SET backend = %s, storage_key = %s, verified_at = now()
             WHERE id = %s::uuid AND backend = %s
            """,
            (ref.backend, ref.key, row["id"], row["backend"]),
        )


def _pass(db: Any, router: Any, report: MoveReport, after: str, batch_size: int) -> bool:
    """Move every remaining candidate after ``after``; return whether any object was moved."""
    moved_any = False
    while True:
        rows = _candidates(db, report.tenant_id, report.target, after, batch_size)
        if not rows:
            return moved_any
        for row in rows:
            after = row["id"]
            if row["id"] in report.failed_ids:
                continue
            try:
                _move_one(db, router, report.tenant_id, report.target, row)
            except TenantDocumentStoreUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - one object never stops the others
                message = str(exc) if isinstance(exc, DocumentStoreError) else type(exc).__name__
                logger.warning("document store move: tenant %s object %s not moved: %s",
                               report.tenant_id, row["sha256"], message)
                report.failed_ids.add(row["id"])
                report.failed += 1
                report.error = report.error or f"{message} (object {row['sha256'][:12]}…)"[:_MAX_ERROR_CHARS]
                continue
            report.moved += 1
            moved_any = True
        _save_progress(db, report, after)


def run_move(
    db: Any,
    router: Any,
    tenant_id: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    settle_seconds: float = SETTLE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[MoveReport]:
    """Run (or resume) the move a tenant's settings row says is running.

    Blocking: call it from a worker thread (:func:`start_move_thread`).

    Args:
        db: Database handle.
        router: The :class:`~app.document_store_router.TenantRoutingDocumentStore`.
        tenant_id: The tenant.
        batch_size: Objects per page.
        settle_seconds: How long after the run's start the last scan must begin.
        sleep: Waits (tests pass a no-op).

    Returns:
        The report; ``None`` when no move is running for the tenant.

    Raises:
        MoveBusy: if another run holds the tenant's lock.
    """
    tenant = str(tenant_id)
    if not _try_lock(db, tenant):
        raise MoveBusy("Another move of this workspace's documents is in progress.")
    try:
        router.invalidate(tenant)
        current = load_settings(db, tenant)
        if current is None or current.move_state != MOVE_RUNNING or current.move_target not in _CANDIDATE:
            return None
        target = str(current.move_target)
        counts = current.move_counts or {}
        report = MoveReport(tenant_id=tenant, target=target, moved=int(counts.get("moved") or 0))
        report.total = int(counts.get("total") or 0) or (report.moved + _count_candidates(db, tenant, target))
        started = time.monotonic()
        try:
            _pass(db, router, report, current.move_last_key or "", batch_size)
            # Writers on stale settings may still have added objects at the old place.
            while True:
                remaining = settle_seconds - (time.monotonic() - started)
                if remaining > 0:
                    sleep(remaining)
                if not _pass(db, router, report, "", batch_size):
                    break
        except TenantDocumentStoreUnavailable as exc:
            record_outage(db, tenant, exc.reason)
            report.error = exc.reason[:_MAX_ERROR_CHARS]
            report.state = MOVE_FAILED
        else:
            report.state = MOVE_FAILED if report.failed else MOVE_COMPLETED
        report.total = max(report.total, report.moved + report.failed)
        _finish(db, report)
        router.invalidate(tenant)
        logger.info("document store move: tenant %s to %s: %s moved, %s failed (%s)",
                    tenant, target, report.moved, report.failed, report.state)
        return report
    finally:
        _unlock(db, tenant)


# ── Background runs ───────────────────────────────────────────────────────────────────────────

_threads: Dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def move_running_here(tenant_id: str) -> bool:
    """Whether this process has a live move thread for the tenant."""
    with _threads_lock:
        thread = _threads.get(str(tenant_id))
        return thread is not None and thread.is_alive()


def start_move_thread(db: Any, router: Any, tenant_id: str) -> bool:
    """Run the tenant's move in a background thread of this process.

    Args:
        db: Database handle.
        router: The routing document store.
        tenant_id: The tenant whose settings row says a move is running.

    Returns:
        ``True`` when a thread was started, ``False`` when one is already running here.
    """
    tenant = str(tenant_id)

    def body() -> None:
        try:
            run_move(db, router, tenant)
        except MoveBusy:
            logger.info("document store move: tenant %s is being moved by another instance", tenant)
        except Exception:  # noqa: BLE001 - a crashed run stays 'running' and is resumed by the next start
            logger.exception("document store move: tenant %s run crashed", tenant)

    with _threads_lock:
        existing = _threads.get(tenant)
        if existing is not None and existing.is_alive():
            return False
        thread = threading.Thread(target=body, name=f"document-store-move-{tenant[:8]}", daemon=True)
        _threads[tenant] = thread
        thread.start()
    return True


# ── Cleanup of old copies ─────────────────────────────────────────────────────────────────────


def cleanup_old_copies(db: Any, router: Any, tenant_id: str, *, batch_size: int = DEFAULT_BATCH_SIZE) -> Dict[str, int]:
    """Delete the copies a finished move left in the old place.

    For every object whose row points at the tenant's current target, the copy on the *other*
    side is deleted. An object whose row still points at the old place (it failed to move) is
    never touched, so no object's only copy can be removed.

    Args:
        db: Database handle.
        router: The routing document store.
        tenant_id: The tenant.
        batch_size: Objects per page.

    Returns:
        ``{"checked", "deleted"}``.

    Raises:
        MoveBusy: if a move of the tenant is running.
        TenantDocumentStoreUnavailable: if the tenant's bucket cannot be reached.
    """
    tenant = str(tenant_id)
    if not _try_lock(db, tenant):
        raise MoveBusy("A move of this workspace's documents is in progress.")
    try:
        router.invalidate(tenant)
        current = load_settings(db, tenant)
        if current is None or not current.has_bucket:
            return {"checked": 0, "deleted": 0}
        if current.move_state == MOVE_RUNNING:
            raise MoveBusy("A move of this workspace's documents is in progress.")
        at_tenant = current.uses_tenant_bucket
        condition = "backend = 'tenant_s3'" if at_tenant else "backend <> 'tenant_s3'"
        old_place = router.platform if at_tenant else router.tenant_store(tenant)
        legacy_db = router.platform_store_for("db") if at_tenant else None
        checked = deleted = 0
        after = ""
        while True:
            with db_cursor(db) as cursor:
                cursor.execute(
                    f"""
                    SELECT id::text AS id, sha256 FROM apiome.document_objects
                     WHERE tenant_id = %s AND {condition} AND id::text COLLATE "C" > %s
                     ORDER BY id::text COLLATE "C" LIMIT %s
                    """,
                    (tenant, after, int(batch_size)),
                )
                rows = [dict(row) for row in cursor.fetchall()]
            if not rows:
                break
            for row in rows:
                after = row["id"]
                checked += 1
                removed = bool(old_place.delete(tenant, row["sha256"]))
                if legacy_db is not None and legacy_db is not old_place:
                    removed = bool(legacy_db.delete(tenant, row["sha256"])) or removed
                deleted += int(removed)
        with db_cursor(db) as cursor:
            cursor.execute(
                "UPDATE apiome.tenant_document_stores SET cleanup_pending = false WHERE tenant_id = %s::uuid",
                (tenant,),
            )
        router.invalidate(tenant)
        return {"checked": checked, "deleted": deleted}
    finally:
        _unlock(db, tenant)

