"""One bounded, batched writer for the MCP server's append-only audit rows (DBP-1.21, #7204).

Recording what happened must not slow down what happened. Before this module every agent call
awaited one ``agent_invocations`` INSERT and one ``upstream_credential_uses`` INSERT on its
latency path, and every private catalog read and capability denial started its own background
task with its own pool checkout and commit. Now each of those rows is handed to the
:class:`AuditWriter` of the pool it would have used, which writes them a few at a time:

* :meth:`AuditWriter.submit` only appends to an in-memory queue — no I/O, no ``await``;
* every ``audit_flush_interval_ms`` (or as soon as ``audit_batch_max_rows`` rows wait) the writer
  takes one connection and writes the queue as **one multi-row INSERT per table**, inside one
  transaction;
* :meth:`AuditWriter.close` (called by the lifespan on shutdown) stops the timer and writes what is
  still queued, so a graceful shutdown loses nothing.

**Bounded, with a defined overflow.** The queue holds at most ``audit_queue_max_rows`` rows. A
submission that does not fit is **dropped whole** (never a partial group), counted in
:attr:`AuditWriterStats.dropped` and logged as ``audit_rows_dropped`` (at most once per second per
table). Calls are never delayed by a full queue.

**Failures.** If a batch fails (a row breaks a constraint, the connection drops), its groups are
retried one transaction each, so one bad row does not take its neighbours with it. A group that
fails again is counted in :attr:`AuditWriterStats.failed` and logged — the same best-effort
promise the fire-and-forget writes made before.

**Groups keep order.** A group is rows that belong together, such as an invocation and its body
sample: they are written in one transaction, parents first (:data:`TABLES` order), so a sample's
foreign key always finds its invocation.

Callers reach the writer through :func:`audit_writer_for` with the pool they hold. Without a
registered writer (CLI commands, unit tests that build no lifespan) they write directly, as before.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from collections import deque
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)

__all__ = [
    "TABLES",
    "AuditTable",
    "AuditWriter",
    "AuditWriterStats",
    "audit_writer_for",
    "register_audit_writer",
    "running_audit_writer",
    "unregister_audit_writer",
]


@dataclass(frozen=True)
class AuditTable:
    """How one audit table's rows are inserted.

    Attributes:
        name: Short table name (the :meth:`AuditWriter.submit` key).
        columns: Column list of the INSERT, in row order.
        placeholders: One row's ``VALUES`` tuple, with casts (e.g. ``(%s::uuid, %s)``).
    """

    name: str
    columns: str
    placeholders: str

    def insert_sql(self, rows: int) -> str:
        """A multi-row ``INSERT`` for ``rows`` rows."""
        values = ", ".join([self.placeholders] * rows)
        return f"INSERT INTO apiome.{self.name} ({self.columns}) VALUES {values}"


#: Every table the writer serves, parents before children (the order a flush writes them in).
TABLES: dict[str, AuditTable] = {
    table.name: table
    for table in (
        AuditTable(
            "agent_invocations",
            "id, tenant_id, key_id, toolset_id, tool_name, target, invoked_at, latency_ms, "
            "outcome, error_code, http_status, request_bytes, response_bytes, sampled",
            "(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ),
        AuditTable(
            "agent_invocation_samples",
            "invocation_id, tenant_id, request_body, response_body, request_truncated, response_truncated",
            "(%s::uuid, %s::uuid, %s, %s, %s, %s)",
        ),
        AuditTable(
            "upstream_credential_uses",
            "tenant_id, credential_id, toolset_id, outcome, used_at",
            "(%s::uuid, %s::uuid, %s::uuid, %s, %s)",
        ),
        AuditTable(
            "mcp_access_audit",
            "key_id, tool, spec_id, at, success, error",
            "(%s::uuid, %s, %s::uuid, %s, %s, %s)",
        ),
        AuditTable(
            "mcp_capability_denials",
            "key_id, tenant_id, tool_id, at, transport, reason",
            "(%s::uuid, %s::uuid, %s, %s, %s, %s)",
        ),
    )
}

#: One row: a table name and its values in :attr:`AuditTable.columns` order.
Row = tuple[str, tuple[Any, ...]]


@dataclass
class AuditWriterStats:
    """Running counts for one writer (exposed for tests and logs).

    Attributes:
        submitted: Rows accepted into the queue.
        written: Rows committed.
        dropped: Rows refused because the queue was full (or the writer was closed).
        failed: Rows that could not be written even one group at a time.
        flushes: Batches attempted.
    """

    submitted: int = 0
    written: int = 0
    dropped: int = 0
    failed: int = 0
    flushes: int = 0
    dropped_by_table: dict[str, int] = field(default_factory=dict)


class AuditWriter:
    """Queue audit rows in memory and write them in multi-row INSERTs on a timer."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        flush_interval_seconds: float = 0.25,
        max_queue_rows: int = 10_000,
        batch_max_rows: int = 500,
    ) -> None:
        """Create a stopped writer; :meth:`start` begins the timer.

        Args:
            pool: Where the rows go.
            flush_interval_seconds: Longest a row waits before a flush starts.
            max_queue_rows: Most rows held; beyond that submissions are dropped (see module docstring).
            batch_max_rows: Most rows one flush writes (a backlog is written over several flushes).
        """
        self._pool = pool
        self._interval = max(0.001, float(flush_interval_seconds))
        self._max_rows = max(1, int(max_queue_rows))
        self._batch_rows = max(1, int(batch_max_rows))
        self._queue: deque[tuple[Row, ...]] = deque()
        self._queued_rows = 0
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._lock = asyncio.Lock()
        self._last_drop_log: dict[str, float] = {}
        self.stats = AuditWriterStats()

    @property
    def queued_rows(self) -> int:
        """Rows waiting to be written."""
        return self._queued_rows

    def submit(self, table: str, values: Sequence[Any]) -> bool:
        """Queue one row. Never blocks and never raises for a full queue.

        Args:
            table: A key of :data:`TABLES`.
            values: The row, in the table's column order.

        Returns:
            ``True`` when queued, ``False`` when dropped (queue full or writer closed).

        Raises:
            KeyError: ``table`` is not an audit table (a programming error).
        """
        return self.submit_group([(table, tuple(values))])

    def submit_group(self, rows: Sequence[Row]) -> bool:
        """Queue rows that must be written together (one transaction, parents first).

        Args:
            rows: ``(table, values)`` pairs.

        Returns:
            ``True`` when queued, ``False`` when the whole group was dropped.

        Raises:
            KeyError: A table is not an audit table.
        """
        group = tuple((table, tuple(values)) for table, values in rows)
        for table, _ in group:
            TABLES[table]  # noqa: B018 — reject unknown tables before queueing anything
        if not group:
            return True
        if self._closed or self._queued_rows + len(group) > self._max_rows:
            self._dropped(group)
            return False
        self._queue.append(group)
        self._queued_rows += len(group)
        self.stats.submitted += len(group)
        if self._queued_rows >= self._batch_rows:
            self._wake.set()
        return True

    def _dropped(self, group: tuple[Row, ...]) -> None:
        """Count and (rate-limited) log a refused group."""
        self.stats.dropped += len(group)
        now = time.monotonic()
        for table, _ in group:
            self.stats.dropped_by_table[table] = self.stats.dropped_by_table.get(table, 0) + 1
            if now - self._last_drop_log.get(table, -10.0) >= 1.0:
                self._last_drop_log[table] = now
                _log.warning(
                    "audit_rows_dropped",
                    table=table,
                    dropped_total=self.stats.dropped_by_table[table],
                    queued_rows=self._queued_rows,
                    closed=self._closed,
                )

    def start(self) -> None:
        """Start the flush timer on the running loop (idempotent)."""
        if self._task is None and not self._closed:
            self._task = asyncio.get_running_loop().create_task(self._run(), name="apiome-mcp-audit-writer")

    async def _run(self) -> None:
        """Flush on the interval, or early when a full batch is waiting, until closed."""
        while not self._closed:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            self._wake.clear()
            if self._queue:
                try:
                    await self.flush()
                except Exception:  # flush() logs per group; never let the timer die
                    _log.warning("audit_writer_flush_failed", exc_info=True)

    def _take_batch(self) -> list[tuple[Row, ...]]:
        """Pop whole groups until the batch is full (always at least one group)."""
        batch: list[tuple[Row, ...]] = []
        rows = 0
        while self._queue and (not batch or rows + len(self._queue[0]) <= self._batch_rows):
            group = self._queue.popleft()
            rows += len(group)
            batch.append(group)
        self._queued_rows -= rows
        return batch

    async def flush(self) -> int:
        """Write everything queued right now, one batch after another.

        Returns:
            Rows written.
        """
        written = 0
        async with self._lock:
            while self._queue:
                batch = self._take_batch()
                written += await self._write_batch(batch)
        return written

    async def _write_batch(self, batch: list[tuple[Row, ...]]) -> int:
        """One transaction, one multi-row INSERT per table; on failure, group by group."""
        self.stats.flushes += 1
        by_table: dict[str, list[tuple[Any, ...]]] = {}
        for group in batch:
            for table, values in group:
                by_table.setdefault(table, []).append(values)
        count = sum(len(rows) for rows in by_table.values())
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    for name in TABLES:
                        rows = by_table.get(name)
                        if rows:
                            await conn.execute(
                                TABLES[name].insert_sql(len(rows)),
                                [value for row in rows for value in row],
                            )
        except Exception:
            _log.warning("audit_batch_failed_retrying_by_group", rows=count, exc_info=True)
            return await self._write_groups(batch)
        self.stats.written += count
        return count

    async def _write_groups(self, batch: list[tuple[Row, ...]]) -> int:
        """Write each group in its own transaction; count the ones that still fail."""
        written = 0
        for group in batch:
            ordered = sorted(group, key=lambda row: list(TABLES).index(row[0]))
            try:
                async with self._pool.connection() as conn:
                    async with conn.transaction():
                        for table, values in ordered:
                            await conn.execute(TABLES[table].insert_sql(1), list(values))
            except Exception:
                self.stats.failed += len(group)
                _log.warning(
                    "audit_rows_failed",
                    tables=sorted({table for table, _ in group}),
                    rows=len(group),
                    exc_info=True,
                )
                continue
            written += len(group)
        self.stats.written += written
        return written

    async def close(self) -> None:
        """Stop the timer and write what is still queued. Later submissions are dropped."""
        self._closed = True
        self._wake.set()
        task, self._task = self._task, None
        if task is not None:
            try:
                await task
            except Exception:
                _log.warning("audit_writer_stop_failed", exc_info=True)
        await self.flush()


#: The writer serving each pool, set by the lifespans.
_WRITERS: weakref.WeakKeyDictionary[Any, AuditWriter] = weakref.WeakKeyDictionary()


def register_audit_writer(pool: Any, writer: AuditWriter) -> None:
    """Route audit rows written through ``pool`` to ``writer``."""
    _WRITERS[pool] = writer


def unregister_audit_writer(pool: Any) -> None:
    """Stop routing ``pool``'s audit rows to a writer (direct writes resume)."""
    _WRITERS.pop(pool, None)


def audit_writer_for(pool: Any) -> AuditWriter | None:
    """The writer registered for ``pool``, or ``None`` (write directly)."""
    try:
        return _WRITERS.get(pool)
    except TypeError:  # an unhashable / non-weakrefable test double
        return None


def writer_from_settings(pool: AsyncConnectionPool, settings: Any) -> AuditWriter:
    """Build (not start) a writer with the ``audit_*`` settings.

    Args:
        pool: The pool the writer writes through.
        settings: :class:`~apiome_mcp.settings.Settings`.

    Returns:
        The writer.
    """
    return AuditWriter(
        pool,
        flush_interval_seconds=settings.audit_flush_interval_ms / 1000.0,
        max_queue_rows=settings.audit_queue_max_rows,
        batch_max_rows=settings.audit_batch_max_rows,
    )


@asynccontextmanager
async def running_audit_writer(pool: AsyncConnectionPool, settings: Any) -> AsyncIterator[AuditWriter]:
    """Run a writer for ``pool`` for the life of the block (what both lifespans use).

    On exit the writer is closed — its queue flushed — and unregistered, *before* the caller closes
    the pool, so a graceful shutdown loses no row.

    Args:
        pool: The open pool.
        settings: :class:`~apiome_mcp.settings.Settings`.

    Yields:
        The started, registered writer.
    """
    writer = writer_from_settings(pool, settings)
    register_audit_writer(pool, writer)
    writer.start()
    try:
        yield writer
    finally:
        try:
            await writer.close()
        finally:
            unregister_audit_writer(pool)
            if writer.stats.dropped or writer.stats.failed:
                _log.warning(
                    "audit_writer_closed_with_losses",
                    dropped=writer.stats.dropped,
                    failed=writer.stats.failed,
                    written=writer.stats.written,
                )
