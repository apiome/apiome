"""The sweep worker pool — bounded, per-key fair, drains until empty (DBP-1.18, #7201)."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, FrozenSet, List, Sequence

import pytest

from app.sweep_worker_pool import drain_keyed, run_keyed, thread_connection_release


class Queue:
    """An in-memory due queue: ``claim`` honours the limit and the saturated keys, like the SQL."""

    def __init__(self, items: Sequence[Dict[str, Any]]) -> None:
        self.items: List[Dict[str, Any]] = list(items)
        self.lock = threading.Lock()
        self.claims: List[tuple] = []

    def claim(self, limit: int, saturated: FrozenSet[str]) -> List[Dict[str, Any]]:
        with self.lock:
            taken = [item for item in self.items if item["key"] not in saturated][:limit]
            for item in taken:
                self.items.remove(item)
            self.claims.append((limit, saturated, len(taken)))
            return taken


class Tracker:
    """Records how many items (and items per key) run at once."""

    def __init__(self, delay: float = 0.0, delays: Dict[str, float] | None = None) -> None:
        self.lock = threading.Lock()
        self.running = 0
        self.per_key: Dict[str, int] = {}
        self.peak = 0
        self.peak_per_key: Dict[str, int] = {}
        self.done: List[str] = []
        self.delay = delay
        self.delays = delays or {}

    def work(self, item: Dict[str, Any]) -> None:
        key = item["key"]
        with self.lock:
            self.running += 1
            self.per_key[key] = self.per_key.get(key, 0) + 1
            self.peak = max(self.peak, self.running)
            self.peak_per_key[key] = max(self.peak_per_key.get(key, 0), self.per_key[key])
        time.sleep(self.delays.get(key, self.delay))
        with self.lock:
            self.running -= 1
            self.per_key[key] -= 1
            self.done.append(item["id"])


def _items(spec: Dict[str, int]) -> List[Dict[str, Any]]:
    return [{"id": f"{key}{n}", "key": key} for key, count in spec.items() for n in range(count)]


def test_it_drains_the_whole_queue_and_reports_drained() -> None:
    queue, tracker = Queue(_items({"a": 7, "b": 5, "c": 3})), Tracker()
    result = drain_keyed(
        queue.claim, tracker.work, lambda i: i["key"], workers=4, per_key=2, batch_size=3, deadline_seconds=30
    )
    assert result.processed == 15 and result.failed == 0
    assert result.drained is True
    assert sorted(tracker.done) == sorted(i["id"] for i in _items({"a": 7, "b": 5, "c": 3}))
    assert queue.items == []
    # Every claim asked for at most one batch.
    assert all(limit <= 3 for limit, _sat, _n in queue.claims)


def test_concurrency_is_bounded_overall_and_per_key() -> None:
    queue, tracker = Queue(_items({"a": 10, "b": 10, "c": 10})), Tracker(delay=0.02)
    drain_keyed(queue.claim, tracker.work, lambda i: i["key"], workers=4, per_key=2, batch_size=10, deadline_seconds=30)
    assert tracker.peak <= 4
    assert max(tracker.peak_per_key.values()) <= 2
    # It actually ran things side by side.
    assert tracker.peak >= 2


def test_a_saturated_key_is_excluded_from_the_next_claim() -> None:
    queue, tracker = Queue(_items({"slow": 6, "fast": 4})), Tracker(delays={"slow": 0.1})
    drain_keyed(queue.claim, tracker.work, lambda i: i["key"], workers=4, per_key=1, batch_size=1, deadline_seconds=30)
    assert any("slow" in saturated for _limit, saturated, _n in queue.claims)


def test_one_slow_key_does_not_delay_the_others() -> None:
    queue = Queue(_items({"slow": 4}) + _items({"t1": 5, "t2": 5, "t3": 5}))
    tracker = Tracker(delay=0.005, delays={"slow": 0.5})
    started = time.monotonic()
    finished: Dict[str, float] = {}

    def work(item: Dict[str, Any]) -> None:
        tracker.work(item)
        finished[item["id"]] = time.monotonic() - started

    drain_keyed(queue.claim, work, lambda i: i["key"], workers=4, per_key=2, batch_size=8, deadline_seconds=30)
    fast = [t for item_id, t in finished.items() if not item_id.startswith("slow")]
    slow = [t for item_id, t in finished.items() if item_id.startswith("slow")]
    # Every fast item finished before the first slow one did: the slow key held only its two workers.
    assert max(fast) < min(slow)
    assert len(fast) == 15 and len(slow) == 4


def test_the_deadline_stops_claiming_but_in_flight_items_finish() -> None:
    queue, tracker = Queue(_items({"a": 50})), Tracker(delay=0.01)
    clock = iter([0.0, 0.0] + [100.0] * 1000)
    result = drain_keyed(
        queue.claim,
        tracker.work,
        lambda i: i["key"],
        workers=2,
        per_key=2,
        batch_size=2,
        deadline_seconds=10,
        clock=lambda: next(clock),
    )
    # One claim before the deadline; its two items still ran; the rest wait for the next tick.
    assert result.processed == 2
    assert result.drained is False
    assert len(queue.items) == 48


def test_a_failing_item_calls_on_error_and_the_rest_still_run() -> None:
    queue = Queue(_items({"a": 3}))
    errors: List[str] = []

    def work(item: Dict[str, Any]) -> None:
        if item["id"] == "a1":
            raise RuntimeError("boom")

    result = drain_keyed(
        queue.claim,
        work,
        lambda i: i["key"],
        workers=2,
        per_key=2,
        batch_size=3,
        deadline_seconds=30,
        on_error=lambda item, exc: errors.append(f"{item['id']}:{exc}"),
    )
    assert result.processed == 3 and result.failed == 1
    assert errors == ["a1:boom"]


def test_a_failing_claim_stops_claiming_without_losing_claimed_items() -> None:
    calls = {"n": 0}
    done: List[str] = []

    def claim(limit: int, saturated: FrozenSet[str]) -> List[Dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"id": "x", "key": "k"}]
        raise RuntimeError("database down")

    result = drain_keyed(
        claim,
        lambda i: done.append(i["id"]),
        lambda i: i["key"],
        workers=2,
        per_key=2,
        batch_size=2,
        deadline_seconds=30,
    )
    assert done == ["x"]
    assert result.drained is False
    assert calls["n"] == 2


def test_after_each_runs_on_the_worker_thread_for_every_item() -> None:
    queue = Queue(_items({"a": 4}))
    threads: List[str] = []
    drain_keyed(
        queue.claim,
        lambda i: None,
        lambda i: i["key"],
        workers=2,
        per_key=2,
        batch_size=4,
        deadline_seconds=30,
        after_each=lambda: threads.append(threading.current_thread().name),
        thread_name_prefix="test-pool",
    )
    assert len(threads) == 4
    assert all(name.startswith("test-pool") for name in threads)


def test_an_empty_queue_costs_one_claim() -> None:
    queue = Queue([])
    result = drain_keyed(
        queue.claim, lambda i: None, lambda i: i["key"], workers=4, per_key=1, batch_size=10, deadline_seconds=30
    )
    assert (result.processed, result.claims, result.drained) == (0, 1, True)


def test_run_keyed_keeps_one_keys_items_in_order_and_serial() -> None:
    items = _items({"a": 5, "b": 5})
    tracker = Tracker(delay=0.005)
    result = run_keyed(items, tracker.work, lambda i: i["key"], workers=4, per_key=1)
    assert result.processed == 10
    assert max(tracker.peak_per_key.values()) == 1
    assert [i for i in tracker.done if i.startswith("a")] == [f"a{n}" for n in range(5)]


@pytest.mark.parametrize("workers, per_key, batch", [(0, 0, 0), (-3, -1, -5)])
def test_non_positive_bounds_count_as_one(workers: int, per_key: int, batch: int) -> None:
    queue, tracker = Queue(_items({"a": 3})), Tracker()
    result = drain_keyed(
        queue.claim,
        tracker.work,
        lambda i: i["key"],
        workers=workers,
        per_key=per_key,
        batch_size=batch,
        deadline_seconds=30,
    )
    assert result.processed == 3
    assert tracker.peak == 1


def test_thread_connection_release_calls_this_thread_only() -> None:
    calls: List[Dict[str, Any]] = []

    class _Db:
        def release_connections(self, **kwargs: Any) -> int:
            calls.append(kwargs)
            return 1

    release = thread_connection_release(_Db())
    assert release is not None
    release()
    assert calls == [{"this_thread_only": True}]
    assert thread_connection_release(object()) is None
