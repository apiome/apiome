"""Daily mock usage rollups (#4420, SIM-1.5), batched in process (#7207, DBP-1.24).

Every served mock request (and every streamed SSE / WebSocket / gRPC / Kafka message) counts once in
``apiome.mock_usage``; every broker publish outcome also counts in
``apiome.mock_event_publish_usage``. Writing each count as its own statement made the counter the
hottest row in the database — all traffic for one version updates the same
``(tenant, project, version, day)`` row — and gave every request a pooled connection of its own.

Counts now accumulate in a :class:`UsageRecorder` per pool and are written every
``APIOME_MOCK_USAGE_FLUSH_INTERVAL_SECONDS`` (default 2 s) with **one multi-row upsert per table**,
however many requests were served in between. The recorder flushes once more on shutdown. A failed
flush keeps its counts and retries them with the next one, so a short database outage loses
nothing; only a process crash loses the counts of the current interval.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable
from uuid import UUID

import structlog
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)

DEFAULT_FLUSH_INTERVAL_SECONDS = 2.0
"""Flush interval for a recorder created without settings (tests, tooling)."""

MAX_PENDING_KEYS = 100_000
"""Distinct counter rows held between flushes; beyond it new rows are dropped with a warning."""

_UPSERT_MOCK_USAGE = """
    INSERT INTO apiome.mock_usage (tenant_id, project_slug, version_label, usage_date, request_count)
    SELECT * FROM unnest(%s::uuid[], %s::text[], %s::text[], %s::date[], %s::bigint[])
    ON CONFLICT (tenant_id, project_slug, version_label, usage_date)
    DO UPDATE SET request_count = apiome.mock_usage.request_count + EXCLUDED.request_count
"""

_UPSERT_EVENT_PUBLISH_USAGE = """
    INSERT INTO apiome.mock_event_publish_usage (
      tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date,
      published_count, rejected_count
    )
    SELECT * FROM unnest(
      %s::uuid[], %s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::date[],
      %s::bigint[], %s::bigint[]
    )
    ON CONFLICT (tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date)
    DO UPDATE SET
      published_count = apiome.mock_event_publish_usage.published_count + EXCLUDED.published_count,
      rejected_count = apiome.mock_event_publish_usage.rejected_count + EXCLUDED.rejected_count
"""

RequestKey = tuple[UUID, str, str, date]
"""``(tenant_id, project_slug, version_label, usage_date)``."""

EventKey = tuple[UUID, str, str, str, str, str, date]
"""``(tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date)``."""


def _utc_today() -> date:
    """The UTC calendar day a count belongs to (the day ``record_mock_usage`` used)."""
    return datetime.now(tz=timezone.utc).date()


@dataclass
class UsageRecorder:
    """Accumulates usage counts for one pool and writes them in batches.

    Attributes:
        pool: The pool the flushes write through.
        flush_interval_seconds: Seconds between flushes.
        today: Returns the UTC day a count is attributed to (tests inject one).
    """

    pool: AsyncConnectionPool
    flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS
    today: Callable[[], date] = _utc_today
    _requests: dict[RequestKey, int] = field(default_factory=dict)
    _events: dict[EventKey, list[int]] = field(default_factory=dict)
    _task: asyncio.Task[None] | None = None
    _task_loop: asyncio.AbstractEventLoop | None = None
    _flush_lock: asyncio.Lock | None = None
    _closed: bool = False

    # -- counting ---------------------------------------------------------------------------------

    def add_request(self, *, tenant_id: UUID, project_slug: str, version_label: str, count: int = 1) -> None:
        """Count ``count`` served requests (or streamed messages) for a version, today (UTC).

        Args:
            tenant_id: Tenant that owns the version.
            project_slug: Project slug.
            version_label: Version label.
            count: How many to add (default one).
        """
        key: RequestKey = (tenant_id, project_slug, version_label, self.today())
        if key not in self._requests and self._full():
            _log.warning("mock_usage_pending_full", tenant_id=str(tenant_id), project_slug=project_slug)
            return
        self._requests[key] = self._requests.get(key, 0) + count
        self._ensure_running()

    def add_event_publish(
        self,
        *,
        tenant_id: UUID,
        project_slug: str,
        version_label: str,
        channel_key: str,
        encoding: str,
        trigger: str,
        published: bool,
    ) -> None:
        """Count one broker publish outcome (sent, or refused for failing its schema).

        Args:
            tenant_id: Tenant that owns the version.
            project_slug: Project slug.
            version_label: Version label.
            channel_key: The AsyncAPI channel key.
            encoding: ``json``, ``avro`` or ``protobuf``.
            trigger: ``periodic`` or ``on-demand``.
            published: ``True`` when the record was sent, ``False`` when it was refused.
        """
        key: EventKey = (tenant_id, project_slug, version_label, channel_key, encoding, trigger, self.today())
        if key not in self._events and self._full():
            _log.warning("mock_event_publish_usage_pending_full", tenant_id=str(tenant_id), channel=channel_key)
            return
        counts = self._events.setdefault(key, [0, 0])
        counts[0 if published else 1] += 1
        self._ensure_running()

    def pending_requests(self) -> int:
        """Total request counts not yet written (tests and diagnostics)."""
        return sum(self._requests.values())

    def _full(self) -> bool:
        return len(self._requests) + len(self._events) >= MAX_PENDING_KEYS

    # -- flushing ---------------------------------------------------------------------------------

    async def flush(self) -> None:
        """Write every pending count in at most one statement per table.

        Counts are taken out of the pending maps before the write; when it fails they are merged
        back, so the next flush retries them.
        """
        if self._flush_lock is None:
            self._flush_lock = asyncio.Lock()
        async with self._flush_lock:
            requests, self._requests = self._requests, {}
            events, self._events = self._events, {}
            if not requests and not events:
                return
            try:
                async with self.pool.connection() as conn:
                    if requests:
                        await conn.execute(_UPSERT_MOCK_USAGE, _request_columns(requests))
                    if events:
                        await conn.execute(_UPSERT_EVENT_PUBLISH_USAGE, _event_columns(events))
            except Exception:
                _log.warning(
                    "mock_usage_flush_failed",
                    request_rows=len(requests),
                    event_rows=len(events),
                    exc_info=True,
                )
                self._merge_back(requests, events)

    def _merge_back(self, requests: dict[RequestKey, int], events: dict[EventKey, list[int]]) -> None:
        for key, count in requests.items():
            self._requests[key] = self._requests.get(key, 0) + count
        for event_key, (published, rejected) in events.items():
            counts = self._events.setdefault(event_key, [0, 0])
            counts[0] += published
            counts[1] += rejected

    def _ensure_running(self) -> None:
        """Start the periodic flush task on the running loop (once per loop)."""
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is not None and not self._task.done() and self._task_loop is loop:
            return
        self._task_loop = loop
        self._flush_lock = None
        self._task = loop.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush()

    async def close(self) -> None:
        """Stop the periodic task and write whatever is still pending."""
        self._closed = True
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.flush()


def _request_columns(rows: dict[RequestKey, int]) -> tuple[list[Any], ...]:
    keys = list(rows)
    return (
        [k[0] for k in keys],
        [k[1] for k in keys],
        [k[2] for k in keys],
        [k[3] for k in keys],
        [rows[k] for k in keys],
    )


def _event_columns(rows: dict[EventKey, list[int]]) -> tuple[list[Any], ...]:
    keys = list(rows)
    return (
        [k[0] for k in keys],
        [k[1] for k in keys],
        [k[2] for k in keys],
        [k[3] for k in keys],
        [k[4] for k in keys],
        [k[5] for k in keys],
        [k[6] for k in keys],
        [rows[k][0] for k in keys],
        [rows[k][1] for k in keys],
    )


# -- process registry -----------------------------------------------------------------------------

_RECORDERS: dict[int, UsageRecorder] = {}


def configure_usage_recorder(pool: AsyncConnectionPool, *, flush_interval_seconds: float) -> UsageRecorder:
    """Create (or retune) the recorder for ``pool``; called once at startup.

    Args:
        pool: The runtime's pool.
        flush_interval_seconds: Seconds between flushes.

    Returns:
        The pool's recorder.
    """
    recorder = usage_recorder_for(pool)
    recorder.flush_interval_seconds = flush_interval_seconds
    recorder._closed = False
    return recorder


def usage_recorder_for(pool: AsyncConnectionPool) -> UsageRecorder:
    """Return the recorder that batches counts for ``pool``, creating it on first use."""
    recorder = _RECORDERS.get(id(pool))
    if recorder is None or recorder.pool is not pool:
        recorder = UsageRecorder(pool=pool)
        _RECORDERS[id(pool)] = recorder
    return recorder


async def close_usage_recorder(pool: AsyncConnectionPool) -> None:
    """Flush and forget ``pool``'s recorder; call before the pool closes."""
    recorder = _RECORDERS.pop(id(pool), None)
    if recorder is not None and recorder.pool is pool:
        await recorder.close()


def reset_usage_recorders_for_tests() -> None:
    """Forget every recorder without flushing (tests only)."""
    for recorder in _RECORDERS.values():
        if recorder._task is not None:
            recorder._task.cancel()
    _RECORDERS.clear()


def schedule_mock_usage(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    project_slug: str,
    version_label: str,
) -> None:
    """Count one served mock request; the pool's recorder writes it with the next batch."""
    usage_recorder_for(pool).add_request(
        tenant_id=tenant_id,
        project_slug=project_slug,
        version_label=version_label,
    )
