"""Catalog item refresh sweep — scheduling, bounds and kill switches (MFI-31.1, #4398).

The store is :class:`FakeRefreshStore` and discovery runners are fakes. The tests pin the
acceptance criteria: a daily item is re-discovered on schedule and not again until a day has
passed; a failure shows as ``failed`` without touching history; turning an item off (or
deleting its setting) stops the sweep; the tenant and deployment kill switches stop it; and the
concurrency cap and per-host politeness delay hold.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Dict, List

import pytest
from catalog_refresh_fakes import FakeRefreshStore

from app import catalog_refresh
from app.catalog_refresh import DiscoveryResult, register_discovery_runner
from app.catalog_refresh_sweep import AsyncHostPoliteness, process_catalog_refresh_sweep
from app.config import settings

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "44444444-4444-4444-8444-444444444444"


class _LockDb:
    """Answers the sweep's advisory-lock queries; ``locked=False`` simulates another holder."""

    def __init__(self, locked: bool = True) -> None:
        self.locked = locked
        self.queries: List[str] = []

    def execute_query(self, query: str, params: Any = None) -> List[Dict[str, Any]]:
        self.queries.append(query)
        return [{"locked": self.locked, "unlocked": True}]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    runners = dict(catalog_refresh._RUNNERS)
    monkeypatch.setattr(settings, "catalog_refresh_enabled", True)
    monkeypatch.setattr(settings, "catalog_refresh_max_concurrency", 4)
    monkeypatch.setattr(settings, "catalog_refresh_host_delay_seconds", 0.0)
    monkeypatch.setattr(settings, "catalog_refresh_timeout_seconds", 5)
    yield
    catalog_refresh._RUNNERS.clear()
    catalog_refresh._RUNNERS.update(runners)


@pytest.fixture
def store(monkeypatch) -> FakeRefreshStore:
    return FakeRefreshStore().install(monkeypatch)


@pytest.fixture
def calls() -> List[str]:
    seen: List[str] = []

    def _run(endpoint, options, auth_type, auth_payload, timeout):
        seen.append(endpoint)
        return DiscoveryResult(fingerprint="fp-" + endpoint, model=None, native=None)

    register_discovery_runner("graphql", _run)
    return seen


def _tick(store: FakeRefreshStore, db: Any = None, **kwargs: Any):
    return asyncio.run(process_catalog_refresh_sweep(db or _LockDb(), store=store, **kwargs))


def _item(n: int) -> str:
    return f"22222222-2222-4222-8222-{n:012d}"


def test_a_daily_item_is_checked_on_schedule(store, calls):
    store.add(_item(1), _TENANT, cadence="daily", endpoint="https://a.example.com")
    assert _tick(store) == 1
    assert calls == ["https://a.example.com"]
    assert store.rows[_item(1)]["status"] == "unchanged"

    # Not again within the day …
    store.now += timedelta(hours=23)
    assert _tick(store) == 0
    # … and again once the day has passed.
    store.now += timedelta(hours=1)
    assert _tick(store) == 1
    assert len(calls) == 2


@pytest.mark.parametrize("cadence", ["off", "manual"])
def test_off_and_manual_items_are_never_swept(store, calls, cadence):
    store.add(_item(1), _TENANT, cadence=cadence)
    assert _tick(store) == 0 and calls == []


def test_turning_an_item_off_or_removing_it_stops_the_sweep(store, calls):
    store.add(_item(1), _TENANT, cadence="hourly")
    store.add(_item(2), _TENANT, cadence="hourly")
    _tick(store)
    store.rows[_item(1)]["cadence"] = "off"
    store.delete_refresh(None, _item(2), _TENANT)
    store.now += timedelta(hours=2)
    assert _tick(store) == 0
    assert len(calls) == 2


def test_a_failure_shows_status_backs_off_and_keeps_history(store):
    register_discovery_runner("graphql", lambda *a: (_ for _ in ()).throw(RuntimeError("connection refused")))
    store.add(_item(1), _TENANT, cadence="hourly", last_fingerprint="fp-old", status="unchanged")
    _tick(store)
    row = store.rows[_item(1)]
    assert row["status"] == "failed" and row["last_error"] == "connection refused"
    assert row["last_fingerprint"] == "fp-old"

    # Backing off: the base is 300s by default, so an hour later it is due again, but not 1 minute later.
    store.now += timedelta(seconds=60)
    store.rows[_item(1)]["last_checked_at"] -= timedelta(hours=1)
    assert _tick(store) == 0


def test_the_tenant_kill_switch_stops_only_that_tenant(store, calls):
    store.add(_item(1), _TENANT, endpoint="https://a.example.com")
    store.add(_item(2), _OTHER_TENANT, endpoint="https://b.example.com")
    store.set_tenant_refresh_enabled(None, _TENANT, False)
    assert _tick(store) == 1
    assert calls == ["https://b.example.com"]


def test_the_deployment_kill_switch_halts_the_tick(store, calls, monkeypatch):
    monkeypatch.setattr(settings, "catalog_refresh_enabled", False)
    store.add(_item(1), _TENANT)
    db = _LockDb()
    assert _tick(store, db) == 0
    assert calls == [] and db.queries == []


def test_a_held_lock_skips_the_tick(store, calls):
    store.add(_item(1), _TENANT)
    assert _tick(store, _LockDb(locked=False)) is None
    assert calls == []


def test_the_lock_is_released_after_the_tick(store, calls):
    store.add(_item(1), _TENANT)
    db = _LockDb()
    _tick(store, db)
    assert "pg_advisory_unlock" in db.queries[-1]


def test_concurrency_never_exceeds_the_cap(store, monkeypatch):
    import threading
    import time

    monkeypatch.setattr(settings, "catalog_refresh_max_concurrency", 2)
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def _run(endpoint, *args):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return DiscoveryResult(fingerprint="fp", model=None, native=None)

    register_discovery_runner("graphql", _run)
    for n in range(6):
        store.add(_item(n), _TENANT, endpoint=f"https://h{n}.example.com")
    assert _tick(store) == 6
    assert state["peak"] == 2


def test_one_crashing_row_does_not_stop_the_others(store, calls, monkeypatch):
    real = store.record_success

    def _flaky(db, project_id, **kwargs):
        if project_id == _item(1):
            raise RuntimeError("write failed")
        real(db, project_id, **kwargs)

    monkeypatch.setattr("app.catalog_refresh_store.record_success", _flaky)
    store.record_success = _flaky
    store.add(_item(1), _TENANT, endpoint="https://a.example.com")
    store.add(_item(2), _TENANT, endpoint="https://b.example.com")
    assert _tick(store) == 2
    assert store.rows[_item(2)]["status"] == "unchanged"


# --- per-host politeness ---------------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: List[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def test_politeness_spaces_calls_to_one_host():
    clock = _FakeClock()
    gate = AsyncHostPoliteness(2.0, clock=clock, sleep=clock.sleep)

    async def _run():
        starts = []
        for _ in range(3):
            await gate.wait("api.example.com")
            starts.append(clock.t)
        return starts

    assert asyncio.run(_run()) == [0.0, 2.0, 4.0]


def test_politeness_does_not_delay_other_hosts():
    clock = _FakeClock()
    gate = AsyncHostPoliteness(2.0, clock=clock, sleep=clock.sleep)

    async def _run():
        await gate.wait("a.example.com")
        await gate.wait("b.example.com")

    asyncio.run(_run())
    assert clock.sleeps == []


def test_zero_delay_disables_politeness():
    clock = _FakeClock()
    gate = AsyncHostPoliteness(0, clock=clock, sleep=clock.sleep)
    asyncio.run(gate.wait("a"))
    asyncio.run(gate.wait("a"))
    assert clock.sleeps == []


def test_the_sweep_spaces_items_that_share_a_host(store, calls):
    clock = _FakeClock()
    gate = AsyncHostPoliteness(2.0, clock=clock, sleep=clock.sleep)
    for n in range(3):
        store.add(_item(n), _TENANT, endpoint=f"https://shared.example.com/graphql?n={n}")
    assert _tick(store, politeness=gate) == 3
    assert clock.sleeps == [2.0, 2.0]
