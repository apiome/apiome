"""Bounded, per-key-fair worker pool for sweep ticks (DBP-1.18, #7201).

A sweep that does slow, blocking work per row (an HTTP POST to a customer's webhook receiver, a
repository rescan against a Git provider) used to do it one row at a time, so one slow destination
held up every tenant behind it and a tick handled a fixed handful of rows. :func:`drain_keyed`
runs that work on a small thread pool instead:

* **Bounded.** At most ``workers`` items run at once.
* **Fair per key.** At most ``per_key`` items of one key (a tenant) run at once, and the claim is
  told which keys are saturated so it can skip their rows. A slow receiver therefore occupies at
  most ``per_key`` workers; every other tenant keeps flowing through the rest.
* **Drains.** It keeps claiming as workers free up until the claim comes back empty, so a backlog
  clears in one tick rather than ten rows per tick. After ``deadline_seconds`` it stops claiming,
  lets the items in flight finish, and returns — the next tick picks up the rest.

Items a claim returned but that cannot start yet (their key is saturated) wait in a local queue and
always run before the call returns: once claimed, an item is never dropped.

The work and claim callables run on pool threads and on the calling thread respectively; anything
they share (a quota tracker) must be thread-safe. Use :func:`run_keyed` for a list that is already
known (no claim).
"""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, FrozenSet, Iterable, List, Optional, Sequence, TypeVar
from typing import Counter as CounterType

__all__ = ["DrainResult", "drain_keyed", "run_keyed", "thread_connection_release"]

_logger = logging.getLogger(__name__)

T = TypeVar("T")

#: ``claim(limit, saturated_keys) -> rows``: return at most ``limit`` due rows, skipping rows whose
#: key is in ``saturated_keys``. An empty list means nothing (else) is due.
ClaimFn = Callable[[int, FrozenSet[str]], Sequence[T]]


@dataclass
class DrainResult:
    """What one :func:`drain_keyed` call did.

    Attributes:
        processed: Items whose work ran (successfully or not).
        failed: Items whose work raised (``on_error`` was called for each).
        claims: Claim calls made.
        drained: True when the last claim came back empty (the queue was empty), False when the
            deadline stopped claiming first.
    """

    processed: int = 0
    failed: int = 0
    claims: int = 0
    drained: bool = False


def drain_keyed(
    claim: ClaimFn,
    work: Callable[[T], Any],
    key: Callable[[T], str],
    *,
    workers: int,
    per_key: int,
    batch_size: int,
    deadline_seconds: float,
    on_error: Optional[Callable[[T, BaseException], None]] = None,
    after_each: Optional[Callable[[], None]] = None,
    thread_name_prefix: str = "sweep-worker",
    clock: Callable[[], float] = time.monotonic,
) -> DrainResult:
    """Claim and process rows on a bounded pool until the queue is empty or the deadline passes.

    Args:
        claim: Returns up to ``limit`` due rows, skipping the saturated keys (see :data:`ClaimFn`).
            Called on the calling thread. An exception from it stops claiming (it is logged), and
            the items already claimed still run.
        work: Processes one row on a pool thread.
        key: The row's fairness key (a tenant id).
        workers: Items in flight at once; values below 1 count as 1.
        per_key: Items of one key in flight at once; values below 1 count as 1.
        batch_size: The most rows one claim asks for; values below 1 count as 1.
        deadline_seconds: How long to keep claiming. Items in flight when it passes still finish.
        on_error: Called (on the pool thread) when ``work`` raises; its own exceptions are logged.
            Without it the exception is only logged.
        after_each: Called on the pool thread after every item, e.g. to hand that thread's database
            connection back to the pool.
        thread_name_prefix: Names the pool threads (shows in logs and thread dumps).
        clock: Monotonic clock (tests).

    Returns:
        A :class:`DrainResult`.
    """
    workers = max(1, int(workers))
    per_key = max(1, int(per_key))
    batch_size = max(1, int(batch_size))
    #: Claimed items waiting for their key to free up; bounded so a claim never runs far ahead.
    max_waiting = workers * 4
    started = clock()
    result = DrainResult()
    waiting: Deque[T] = deque()
    in_flight: Dict[Future, str] = {}
    running: CounterType[str] = Counter()
    claim_idle = False

    def _run(item: T) -> None:
        try:
            work(item)
        except BaseException as exc:  # noqa: BLE001 - one item's failure never stops the tick
            if on_error is None:
                _logger.exception("%s: item failed", thread_name_prefix)
            else:
                try:
                    on_error(item, exc)
                except Exception:  # noqa: BLE001
                    _logger.exception("%s: error handler failed", thread_name_prefix)
            raise
        finally:
            if after_each is not None:
                try:
                    after_each()
                except Exception:  # noqa: BLE001
                    _logger.exception("%s: after_each failed", thread_name_prefix)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=thread_name_prefix) as pool:

        def _dispatch() -> None:
            """Start waiting items whose key has room, oldest first, while workers are free."""
            for _ in range(len(waiting)):
                if len(in_flight) >= workers:
                    return
                item = waiting.popleft()
                item_key = str(key(item))
                if running[item_key] >= per_key:
                    waiting.append(item)
                    continue
                running[item_key] += 1
                in_flight[pool.submit(_run, item)] = item_key

        while True:
            _dispatch()
            free = workers - len(in_flight)
            claiming = not claim_idle and (clock() - started) < deadline_seconds
            if claiming and free > 0 and len(waiting) < max_waiting:
                saturated = frozenset(k for k, n in running.items() if n >= per_key)
                rows: Optional[List[T]]
                try:
                    rows = list(claim(min(batch_size, free), saturated))
                except Exception:  # noqa: BLE001 - stop claiming; what is claimed still runs
                    _logger.exception("%s: claim failed", thread_name_prefix)
                    rows = None
                result.claims += 1
                if rows is None:
                    claim_idle = True
                    deadline_seconds = 0.0
                elif rows:
                    waiting.extend(rows)
                    continue
                else:
                    claim_idle = True
                    if not saturated:
                        result.drained = True
            if not in_flight:
                if waiting:
                    # Nothing runs, so no key is saturated: the next _dispatch starts them.
                    continue
                if claim_idle and not result.drained and (clock() - started) < deadline_seconds:
                    # The empty claim skipped keys that have since freed up: ask once more.
                    claim_idle = False
                    continue
                break
            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                item_key = in_flight.pop(future)
                running[item_key] -= 1
                if running[item_key] <= 0:
                    del running[item_key]
                result.processed += 1
                if future.exception() is not None:
                    result.failed += 1
            # A finished item may unblock a saturated key the last claim skipped.
            if not result.drained:
                claim_idle = False
    return result


def run_keyed(
    items: Iterable[T],
    work: Callable[[T], Any],
    key: Callable[[T], str],
    *,
    workers: int,
    per_key: int = 1,
    on_error: Optional[Callable[[T, BaseException], None]] = None,
    after_each: Optional[Callable[[], None]] = None,
    thread_name_prefix: str = "sweep-worker",
) -> DrainResult:
    """Process a known list on a bounded pool, at most ``per_key`` items of one key at a time.

    Items of one key run in list order when ``per_key`` is 1.

    Args:
        items: The rows.
        work: Processes one row on a pool thread.
        key: The row's fairness key.
        workers: Items in flight at once.
        per_key: Items of one key in flight at once.
        on_error: See :func:`drain_keyed`.
        after_each: See :func:`drain_keyed`.
        thread_name_prefix: Names the pool threads.

    Returns:
        A :class:`DrainResult` (``drained`` is always True).
    """
    remaining: List[T] = list(items)

    def _claim(limit: int, _saturated: FrozenSet[str]) -> List[T]:
        taken, remaining[:] = remaining[:limit], remaining[limit:]
        return taken

    return drain_keyed(
        _claim,
        work,
        key,
        workers=workers,
        per_key=per_key,
        batch_size=max(1, len(remaining)),
        deadline_seconds=float("inf"),
        on_error=on_error,
        after_each=after_each,
        thread_name_prefix=thread_name_prefix,
    )


def thread_connection_release(database: Any) -> Optional[Callable[[], None]]:
    """An ``after_each`` callback handing the calling thread's connection back to ``database``'s pool.

    Pool threads borrow a connection from the sweep's handle the first time they touch it; handing
    it back after every item keeps the connections a pool holds at once down to the items that are
    writing right now, instead of one per worker for the whole tick.

    Args:
        database: A :class:`~app.database.Database` (or a test double without connection leases).

    Returns:
        The callback, or ``None`` when ``database`` cannot release a single thread's connection.
    """
    release = getattr(database, "release_connections", None)
    if not callable(release):
        return None
    return lambda: release(this_thread_only=True)
