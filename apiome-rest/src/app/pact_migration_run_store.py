"""Where a migration run keeps its state — PFX-8.16 (#7313).

The rows of ``apiome.pact_migration_run`` (V458) and the done keys beside them. The job
(:mod:`app.pact_migration_job`) writes its progress here after every batch, so any apiome-rest worker
can answer how a run is doing, the **Past migrations** drawer has something to list, and a stopped
run resumes where it stopped.

* **One run at a time per workspace** — the database's partial unique index decides, so two workers
  cannot both start one (:data:`CODE_RUN_ACTIVE`).
* **A run whose worker went away is not stuck.** A ``running`` row whose heartbeat is older than
  :data:`STALE_AFTER_SECONDS` is closed as ``stopped`` the next time anyone starts, resumes or reads
  runs, and can be resumed.
* **No credential is written.** Nothing here takes one.

Every read and write is scoped to the tenant given; a run of another tenant does not exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import psycopg2
from psycopg2.extras import Json

from .consumer_contract_store import ConsumerActor
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_RUN_ACTIVE",
    "MAX_DONE_KEY_LENGTH",
    "STALE_AFTER_SECONDS",
    "STALE_MESSAGE",
    "RunActiveError",
    "add_done",
    "close_stale",
    "create_run",
    "done_keys",
    "finish_run",
    "get_run",
    "list_runs",
    "reopen_run",
    "request_stop",
    "save_progress",
]

#: The workspace already has a migration running (HTTP 409).
CODE_RUN_ACTIVE = "pact-migration-run-active"

#: A running row not heard from for this long has lost its worker.
STALE_AFTER_SECONDS = 180

#: What a run closed for a lost worker says.
STALE_MESSAGE = "The server stopped while this was running. Nothing is lost: resume it to carry on."

#: A source key longer than this is not remembered (the record is sent again; importing it twice changes nothing).
MAX_DONE_KEY_LENGTH = 1024

_COLUMNS = """
    id::text AS id, tenant_id::text AS tenant_id, source, auth_kind, mode, status, phase, options, counts, facts,
    findings, failures, failures_dropped, log, log_seq, error, stop_requested, started_by_label, created_at,
    heartbeat_at, finished_at
"""


class RunActiveError(Exception):
    """The workspace already has a migration running."""

    code = CODE_RUN_ACTIVE


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a uuid (an API key has none)."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def close_stale(db: Any, tenant_id: str) -> int:
    """Close the tenant's running runs that lost their worker.

    Args:
        db: The database.
        tenant_id: The tenant.

    Returns:
        How many runs were closed as ``stopped``.
    """

    def work(cursor: Any) -> int:
        cursor.execute(
            """
            UPDATE apiome.pact_migration_run
            SET status = 'stopped', finished_at = CURRENT_TIMESTAMP, error = %s
            WHERE tenant_id = %s::uuid AND status = 'running'
              AND heartbeat_at < CURRENT_TIMESTAMP - make_interval(secs => %s)
            """,
            (STALE_MESSAGE, tenant_id, STALE_AFTER_SECONDS),
        )
        return int(cursor.rowcount or 0)

    return int(db._guarded_tx(work) or 0)


def create_run(
    db: Any,
    tenant_id: str,
    *,
    source: str,
    auth_kind: str,
    mode: str,
    options: Dict[str, Any],
    facts: Dict[str, Any],
    actor: ConsumerActor,
) -> Dict[str, Any]:
    """Record a new running run.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        source: The source broker's base URL (no credentials).
        auth_kind: ``token``, ``basic`` or ``none``.
        mode: ``dry-run`` or ``copy``.
        options: What was chosen.
        facts: What is known before the run starts (the source's host and product).
        actor: Who started it.

    Returns:
        The run's row.

    Raises:
        RunActiveError: When the tenant already has a run going.
    """
    close_stale(db, tenant_id)

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            f"""
            INSERT INTO apiome.pact_migration_run (tenant_id, source, auth_kind, mode, options, facts, started_by,
                                                   started_by_label)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s)
            RETURNING {_COLUMNS}
            """,
            (tenant_id, source, auth_kind, mode, Json(options), Json(facts), _user_id(actor), actor.label),
        )
        return dict(cursor.fetchone())

    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise RunActiveError("this workspace already has a migration running; stop it or wait for it") from exc


def get_run(db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """One run of the tenant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        run_id: The run.

    Returns:
        Its row, or ``None`` when the tenant has no such run (a malformed id included).
    """
    if not is_uuid_string(str(run_id or "")) or not is_uuid_string(str(tenant_id or "")):
        return None
    rows = db.execute_query(
        f"SELECT {_COLUMNS} FROM apiome.pact_migration_run WHERE tenant_id = %s::uuid AND id = %s::uuid",
        (tenant_id, run_id),
    )
    return dict(rows[0]) if rows else None


def list_runs(db: Any, tenant_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    """The tenant's runs, newest first — the **Past migrations** drawer.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        limit: The most rows.

    Returns:
        The rows (without findings, failures or log: a list does not need them).
    """
    if not is_uuid_string(str(tenant_id or "")):
        return []
    rows = db.execute_query(
        """
        SELECT id::text AS id, tenant_id::text AS tenant_id, source, auth_kind, mode, status, phase, options, counts,
               facts, '[]'::jsonb AS findings, '[]'::jsonb AS failures, failures_dropped, '[]'::jsonb AS log, log_seq,
               error, stop_requested, started_by_label, created_at, heartbeat_at, finished_at
        FROM apiome.pact_migration_run
        WHERE tenant_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (tenant_id, max(1, min(int(limit), 200))),
    )
    return [dict(row) for row in rows or []]


def save_progress(
    db: Any,
    run_id: str,
    *,
    phase: str,
    counts: Dict[str, Any],
    facts: Dict[str, Any],
    findings: Sequence[Dict[str, Any]],
    failures: Sequence[Dict[str, Any]],
    failures_dropped: int,
    log: Sequence[Dict[str, Any]],
    log_seq: int,
) -> bool:
    """Write where a running run is, and learn whether it should stop.

    Args:
        db: The database.
        run_id: The run.
        phase: ``reading``, the kind being copied, or ``done``.
        counts: Per-kind counts.
        facts: What the run learned.
        findings: What cannot be carried over.
        failures: The refused records kept.
        failures_dropped: Refused records not kept in ``failures``.
        log: The newest log lines.
        log_seq: Lines written in all.

    Returns:
        ``True`` when the run should stop: someone asked, or it is no longer running (it was closed
        as stale while its worker was busy).
    """

    def work(cursor: Any) -> bool:
        cursor.execute(
            """
            UPDATE apiome.pact_migration_run
            SET phase = %s, counts = %s, facts = %s, findings = %s, failures = %s, failures_dropped = %s, log = %s,
                log_seq = %s, heartbeat_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND status = 'running'
            RETURNING stop_requested
            """,
            (
                phase,
                Json(counts),
                Json(facts),
                Json(list(findings)),
                Json(list(failures)),
                failures_dropped,
                Json(list(log)),
                log_seq,
                run_id,
            ),
        )
        row = cursor.fetchone()
        return True if row is None else bool(dict(row)["stop_requested"])

    return bool(db._guarded_tx(work))


def finish_run(db: Any, run_id: str, status: str, *, error: Optional[str] = None) -> None:
    """Close a running run.

    Args:
        db: The database.
        run_id: The run.
        status: ``completed``, ``stopped`` or ``failed``.
        error: Why, for ``failed`` (or a note for ``stopped``).
    """

    def work(cursor: Any) -> bool:
        cursor.execute(
            """
            UPDATE apiome.pact_migration_run
            SET status = %s, error = %s, finished_at = CURRENT_TIMESTAMP, heartbeat_at = CURRENT_TIMESTAMP,
                phase = CASE WHEN %s = 'completed' THEN 'done' ELSE phase END
            WHERE id = %s::uuid AND status = 'running'
            """,
            (status, error, status, run_id),
        )
        return True

    db._guarded_tx(work)


def request_stop(db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Ask a run to stop; it does before its next batch.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        run_id: The run.

    Returns:
        The run's row afterwards, or ``None`` when the tenant has no such run. Stopping a run that is
        not running changes nothing.
    """
    if get_run(db, tenant_id, run_id) is None:
        return None
    close_stale(db, tenant_id)

    def work(cursor: Any) -> bool:
        cursor.execute(
            """
            UPDATE apiome.pact_migration_run SET stop_requested = TRUE
            WHERE tenant_id = %s::uuid AND id = %s::uuid AND status = 'running'
            """,
            (tenant_id, run_id),
        )
        return True

    db._guarded_tx(work)
    return get_run(db, tenant_id, run_id)


def reopen_run(db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Set a finished copy running again (a resume, or a retry of what failed).

    Its counts, failures and log start over — the run reads the source again and skips what its done
    keys say was imported.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        run_id: The run.

    Returns:
        The run's row, running; ``None`` when the tenant has no such finished copy.

    Raises:
        RunActiveError: When the tenant already has a run going (this one included).
    """
    if not is_uuid_string(str(run_id or "")) or not is_uuid_string(str(tenant_id or "")):
        return None
    close_stale(db, tenant_id)

    def work(cursor: Any) -> Any:
        cursor.execute(
            f"""
            UPDATE apiome.pact_migration_run
            SET status = 'running', phase = 'reading', stop_requested = FALSE, error = NULL, finished_at = NULL,
                heartbeat_at = CURRENT_TIMESTAMP, counts = '{{}}'::jsonb, failures = '[]'::jsonb, failures_dropped = 0
            WHERE tenant_id = %s::uuid AND id = %s::uuid AND status <> 'running' AND mode = 'copy'
            RETURNING {_COLUMNS}
            """,
            (tenant_id, run_id),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else False

    try:
        row = db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise RunActiveError("this workspace already has a migration running; stop it or wait for it") from exc
    if row:
        return row
    current = get_run(db, tenant_id, run_id)
    if current is not None and current["status"] == "running":
        raise RunActiveError("this migration is already running")
    return None


def add_done(db: Any, run_id: str, keys: Iterable[str]) -> None:
    """Remember the source keys a run imported.

    Args:
        db: The database.
        run_id: The run.
        keys: The keys; one longer than :data:`MAX_DONE_KEY_LENGTH` is left out.
    """
    kept = sorted({key for key in keys if key and len(key) <= MAX_DONE_KEY_LENGTH})
    if not kept:
        return

    def work(cursor: Any) -> bool:
        cursor.execute(
            """
            INSERT INTO apiome.pact_migration_run_done (run_id, source_key)
            SELECT %s::uuid, key FROM unnest(%s::text[]) AS key
            ON CONFLICT DO NOTHING
            """,
            (run_id, kept),
        )
        return True

    db._guarded_tx(work)


def done_keys(db: Any, tenant_id: str, source: str) -> Set[str]:
    """Every source key the tenant's copies from ``source`` imported.

    Args:
        db: The database.
        tenant_id: The tenant.
        source: The source broker's base URL.

    Returns:
        The keys — of this run when it is resumed, and of earlier runs from the same source.
    """
    rows = db.execute_query(
        """
        SELECT d.source_key
        FROM apiome.pact_migration_run r
        JOIN apiome.pact_migration_run_done d ON d.run_id = r.id
        WHERE r.tenant_id = %s::uuid AND r.source = %s
        """,
        (tenant_id, source),
    )
    return {str(dict(row)["source_key"]) for row in rows or []}


def as_utc(value: Any) -> Optional[datetime]:
    """A stored timestamp as an aware UTC datetime (``None`` stays ``None``)."""
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
