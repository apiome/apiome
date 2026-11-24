"""Compiled-spec cache (single flight, revalidation at expiry) and its NOTIFY listener."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import structlog

from apiome_mock.revalidating_cache import RevalidatingSpecCache

if TYPE_CHECKING:
    from apiome_mock.spec_loader import CompiledSpec

_log = structlog.get_logger(__name__)


def _compiled_spec_stamp(compiled: CompiledSpec) -> Hashable | None:
    return compiled.freshness


class SpecCache(RevalidatingSpecCache["CompiledSpec"]):
    """LRU of :class:`CompiledSpec` by ``(tenant, project, version)`` (#7208, DBP-1.25).

    See :class:`~apiome_mock.revalidating_cache.RevalidatingSpecCache`: concurrent misses share one
    load, and an expired entry whose ``freshness`` stamp is unchanged is kept rather than reloaded.
    """

    def __init__(self, *, max_entries: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(
            max_entries=max_entries,
            ttl_seconds=ttl_seconds,
            stamp_of=_compiled_spec_stamp,
            event_prefix="spec_cache",
            clock=clock,
        )


ConnectFn = Callable[[str], Awaitable[Any]]
"""Opens an autocommit connection for the listener (tests inject one)."""


async def _default_connect(database_url: str) -> Any:
    import psycopg

    return await psycopg.AsyncConnection.connect(database_url, autocommit=True)


def _apply_payload(
    payload: str,
    cache: SpecCache,
    on_invalidate: Callable[[str, str, str], None] | None,
) -> None:
    payload = payload.strip()
    if not payload:
        return
    parts = payload.split("/", 2)
    if len(parts) != 3:
        _log.warning("spec_notify_invalid_payload", payload=payload)
        return
    cache.invalidate(parts[0], parts[1], parts[2])
    if on_invalidate is not None:
        on_invalidate(parts[0], parts[1], parts[2])


async def run_notify_listener(
    database_url: str,
    channel: str,
    cache: SpecCache,
    *,
    stop_event: asyncio.Event,
    on_invalidate: Callable[[str, str, str], None] | None = None,
    on_connected: Callable[[], None] | None = None,
    initial_backoff_seconds: float = 0.5,
    max_backoff_seconds: float = 30.0,
    connect: ConnectFn = _default_connect,
) -> None:
    """Listen for publish NOTIFY payloads and invalidate matching cache keys, reconnecting forever.

    Payload format: ``tenant/project/version`` (three slash-separated slugs).

    A lost connection is reopened with exponential backoff (``initial_backoff_seconds`` doubling up
    to ``max_backoff_seconds``, reset after a successful connect) until ``stop_event`` is set
    (#7207, DBP-1.24). Notifications sent while disconnected are lost, so every successful
    (re)connect flushes ``cache`` and calls ``on_connected`` to flush the caches beside it — the
    process never keeps serving entries it can no longer hear invalidations for.

    Args:
        database_url: Connection URI for the dedicated listener connection.
        channel: NOTIFY channel name.
        cache: Compiled spec cache to invalidate.
        stop_event: Set at shutdown; the loop exits instead of reconnecting.
        on_invalidate: Called with ``(tenant, project, version)`` for every valid payload.
        on_connected: Called after each successful ``LISTEN`` (flush the other caches here).
        initial_backoff_seconds: First reconnect delay.
        max_backoff_seconds: Reconnect delay ceiling.
        connect: Connection factory (tests inject one).
    """
    from psycopg import sql

    _log.info("spec_notify_listener_starting", channel=channel)
    backoff = initial_backoff_seconds
    try:
        while not stop_event.is_set():
            try:
                async with await connect(database_url) as conn:
                    await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
                    cache.clear()
                    if on_connected is not None:
                        on_connected()
                    backoff = initial_backoff_seconds
                    _log.info("spec_notify_listener_connected", channel=channel)
                    async for notify in conn.notifies():
                        if stop_event.is_set():
                            break
                        _apply_payload(notify.payload or "", cache, on_invalidate)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning("spec_notify_listener_disconnected", error=str(exc), retry_in=backoff)
            if stop_event.is_set():
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(max_backoff_seconds, backoff * 2)
    finally:
        _log.info("spec_notify_listener_stopped")
