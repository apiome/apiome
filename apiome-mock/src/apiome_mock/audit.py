"""Mock audit rows in the tenant access ledger (#4420, SIM-1.5).

Two kinds of entry share one hash-chained writer:

* ``mock.request`` — a *sampled* record that traffic was served (SIM-1.5). Sampling is right here:
  the value is a statistical picture of usage, and a mock can serve thousands of requests a minute.
* ``mock.capture`` — an *unsampled* record that traffic was **recorded** (PMR-2.4, #4747). Every
  capture is written, because "which upstream did this deployment fetch, under whose key, and how
  much of it was redacted" is exactly the question an auditor asks after the fact, and a sampled
  answer to it is no answer at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)

_MOCK_AUDIT_ACTION = "mock.request"


AUDIT_LOCK_PREFIX = "apiome.access_audit:"
"""Advisory-lock namespace that serializes chain appends for one tenant (#7207)."""

AUDIT_DRAIN_TIMEOUT_SECONDS = 5.0
"""Longest shutdown waits for queued audit samples to be written."""

AUDIT_QUEUE_MAX = 1_000
"""Sampled audit entries buffered per process; beyond it new samples are dropped with a warning."""


def _entry_hash(
    prev_hash: str | None, tenant_id: UUID, actor_label: str, action: str, target: str, detail_json: str
) -> str:
    payload = "|".join([prev_hash or "", str(tenant_id), actor_label, action, target, detail_json])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def append_mock_audit_entry(
    conn: Any,
    *,
    tenant_id: UUID,
    actor_label: str,
    action: str,
    target: str,
    detail: dict[str, Any],
) -> None:
    """Append one hash-chained ledger row on ``conn``, inside the caller's open transaction.

    The chain is what makes the ledger tamper-evident: each row hashes the previous row's hash
    together with its own tenant, actor, action, target, and detail, so a removed or edited row
    breaks every hash after it. Reading the previous hash and inserting must therefore be one
    serialized step per tenant, or two concurrent writers link to the same parent and fork the
    chain. The transaction-scoped advisory lock makes it one: every mock replica takes the same
    per-tenant lock before reading the tail (#7207, DBP-1.24).

    Args:
        conn: A connection with an open transaction (``async with conn.transaction()``); the lock
            is released when that transaction ends.
        tenant_id: Tenant whose ledger receives the row.
        actor_label: Who acted — a client IP for served traffic, an API key id for a capture.
        action: The ledger action (``mock.request``, ``mock.capture``).
        target: Human-readable subject of the action.
        detail: JSON detail stored with the row. Never captured content: coordinates, counts,
            and outcomes only.
    """
    detail_json = json.dumps(detail, sort_keys=True, default=str)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{AUDIT_LOCK_PREFIX}{tenant_id}",))
        await cur.execute(
            """
            SELECT entry_hash FROM apiome.access_audit
            WHERE tenant_id = %s::uuid
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (tenant_id,),
        )
        prev_row = await cur.fetchone()
        prev_hash = prev_row["entry_hash"] if prev_row else None
        await cur.execute(
            """
            INSERT INTO apiome.access_audit
              (tenant_id, actor_label, action, target, source, detail, prev_hash, entry_hash)
            VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                tenant_id,
                actor_label,
                action,
                target,
                "mock",
                detail_json,
                prev_hash,
                _entry_hash(prev_hash, tenant_id, actor_label, action, target, detail_json),
            ),
        )


async def insert_mock_audit_entry(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    actor_label: str,
    action: str,
    target: str,
    detail: dict[str, Any],
) -> None:
    """Append one hash-chained row to the tenant's access ledger in its own transaction.

    Args:
        pool: The runtime's database pool.
        tenant_id: Tenant whose ledger receives the row.
        actor_label: Who acted.
        action: The ledger action.
        target: Human-readable subject of the action.
        detail: JSON detail stored with the row.
    """
    async with pool.connection() as conn:
        async with conn.transaction():
            await append_mock_audit_entry(
                conn, tenant_id=tenant_id, actor_label=actor_label, action=action, target=target, detail=detail
            )


async def insert_mock_access_audit(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    client_ip: str,
    project_slug: str,
    version_label: str,
    method: str,
    path: str,
    status_code: int,
    api_key_id: UUID | None = None,
) -> None:
    """Record that one mock request was served (#4420, SIM-1.5)."""
    detail: dict[str, Any] = {
        "projectSlug": project_slug,
        "versionLabel": version_label,
        "method": method.upper(),
        "path": path,
        "statusCode": status_code,
        "clientIp": client_ip,
    }
    if api_key_id is not None:
        detail["apiKeyId"] = str(api_key_id)
    await insert_mock_audit_entry(
        pool,
        tenant_id=tenant_id,
        actor_label=client_ip,
        action=_MOCK_AUDIT_ACTION,
        target=f"{project_slug}/{version_label} {method.upper()} {path}",
        detail=detail,
    )


@dataclass
class _AuditJob:
    tenant_id: UUID
    client_ip: str
    project_slug: str
    version_label: str
    method: str
    path: str
    status_code: int
    api_key_id: UUID | None


class MockAuditWriter:
    """The process's one writer of sampled ``mock.request`` rows (#7207, DBP-1.24).

    Samples go into a bounded queue drained by a single task, so served traffic never waits on the
    ledger, the number of concurrent audit writes is one (not one task per sampled request), and
    rows for a tenant are appended in order. The advisory lock in
    :func:`append_mock_audit_entry` extends that ordering across replicas.

    Args:
        pool: The pool the writer appends through.
        max_queue: Queue bound.
    """

    def __init__(self, pool: AsyncConnectionPool, *, max_queue: int = AUDIT_QUEUE_MAX) -> None:
        self.pool = pool
        self._max_queue = max_queue
        self._queue: asyncio.Queue[_AuditJob] | None = None
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def submit(self, job: _AuditJob) -> bool:
        """Queue one sample; ``False`` when it was dropped (no loop, or the queue is full)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        if self._queue is None or self._loop is not loop or self._task is None or self._task.done():
            if self._queue is None or self._loop is not loop:
                self._queue = asyncio.Queue(maxsize=self._max_queue)
            self._loop = loop
            self._task = loop.create_task(self._run(self._queue))
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            _log.warning("mock_access_audit_queue_full", tenant_id=str(job.tenant_id))
            return False
        return True

    async def _run(self, queue: asyncio.Queue[_AuditJob]) -> None:
        while True:
            job = await queue.get()
            try:
                await self._write(job)
            finally:
                queue.task_done()

    async def _write(self, job: _AuditJob) -> None:
        try:
            await insert_mock_access_audit(
                self.pool,
                tenant_id=job.tenant_id,
                client_ip=job.client_ip,
                project_slug=job.project_slug,
                version_label=job.version_label,
                method=job.method,
                path=job.path,
                status_code=job.status_code,
                api_key_id=job.api_key_id,
            )
        except Exception:
            _log.warning(
                "mock_access_audit_insert_failed",
                tenant_id=str(job.tenant_id),
                project_slug=job.project_slug,
                version_label=job.version_label,
                exc_info=True,
            )

    async def drain(self, *, timeout_seconds: float = AUDIT_DRAIN_TIMEOUT_SECONDS) -> None:
        """Write everything queued, then stop the worker (shutdown).

        Args:
            timeout_seconds: Longest the drain waits; samples still queued after it are dropped
                (logged), so an unreachable database cannot hold shutdown open.
        """
        queue, task = self._queue, self._task
        if queue is not None and task is not None and not task.done():
            try:
                await asyncio.wait_for(queue.join(), timeout=timeout_seconds)
            except TimeoutError:
                _log.warning("mock_access_audit_drain_timed_out", dropped=queue.qsize())
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None


_WRITERS: dict[int, MockAuditWriter] = {}


def audit_writer_for(pool: AsyncConnectionPool) -> MockAuditWriter:
    """Return the process's audit writer for ``pool``, creating it on first use."""
    writer = _WRITERS.get(id(pool))
    if writer is None or writer.pool is not pool:
        writer = MockAuditWriter(pool)
        _WRITERS[id(pool)] = writer
    return writer


async def close_audit_writer(pool: AsyncConnectionPool) -> None:
    """Drain and forget ``pool``'s audit writer; call before the pool closes."""
    writer = _WRITERS.pop(id(pool), None)
    if writer is not None and writer.pool is pool:
        await writer.drain()


def schedule_mock_access_audit(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    client_ip: str,
    project_slug: str,
    version_label: str,
    method: str,
    path: str,
    status_code: int,
    sample_rate: float,
    api_key_id: UUID | None = None,
) -> None:
    """Record a sampled mock hit to ``access_audit`` through the process's audit writer."""
    if sample_rate <= 0.0:
        return
    if sample_rate < 1.0 and random.random() >= sample_rate:
        return
    accepted = audit_writer_for(pool).submit(
        _AuditJob(
            tenant_id=tenant_id,
            client_ip=client_ip,
            project_slug=project_slug,
            version_label=version_label,
            method=method,
            path=path,
            status_code=status_code,
            api_key_id=api_key_id,
        )
    )
    if not accepted:
        _log.debug(
            "mock_access_audit_skipped",
            tenant_id=str(tenant_id),
            project_slug=project_slug,
            version_label=version_label,
        )
