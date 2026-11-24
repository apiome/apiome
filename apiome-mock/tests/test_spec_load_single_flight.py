"""Spec loading: single flight, constant statements, revalidation, no held connection (#7208, DBP-1.25)."""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from apiome_mock import spec_loader
from apiome_mock.canonical_loader import LoadedCanonicalSpec
from apiome_mock.canonical_resolve import resolve_compiled_canonical
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.handler import resolve_compiled_spec
from apiome_mock.spec_cache import SpecCache
from spec_load_fakes import FakeSpecPool

#: access + resolve + the set-based loader's eleven statements (apiome-mcp, DBP-1.22).
FIRST_LOAD_STATEMENTS = 13


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _resolve(pool: FakeSpecPool, cache: SpecCache) -> Any:
    return resolve_compiled_spec(pool, cache, tenant=pool.tenant, project=pool.project, version=pool.version)  # type: ignore[arg-type]


# ── single flight ────────────────────────────────────────────────────────────────────────────


def test_100_concurrent_requests_for_an_uncached_version_trigger_exactly_one_load() -> None:
    pool = FakeSpecPool(operations=20, statement_delay=0.001)
    cache = SpecCache(max_entries=8, ttl_seconds=300.0)

    async def run() -> list[Any]:
        return await asyncio.gather(*(_resolve(pool, cache) for _ in range(100)))

    results = asyncio.run(run())

    assert pool.count("resolve") == 1
    assert pool.count("access") == 1
    assert len(pool.kinds) == FIRST_LOAD_STATEMENTS
    assert pool.max_checked_out == 1, "one load holds one connection, not one per waiter"
    assert all(result is results[0] for result in results)
    assert len(results[0].operations) == 20


@pytest.mark.parametrize("operations", [2, 100, 500])
def test_a_load_runs_the_same_statements_whatever_the_size_of_the_spec(operations: int) -> None:
    pool = FakeSpecPool(operations=operations)
    compiled = asyncio.run(_resolve(pool, SpecCache(max_entries=8, ttl_seconds=300.0)))

    assert len(compiled.operations) == operations
    assert pool.kinds == [
        "access",
        "resolve",
        "classes",
        "properties",
        "paths",
        "operations",
        "descriptions",
        "parameters",
        "request_bodies",
        "responses",
        "security",
        "pins",
        "servers",
    ]


def test_waiters_of_a_failed_load_see_its_error_and_nothing_is_cached() -> None:
    cache = SpecCache(max_entries=8, ttl_seconds=300.0)
    calls = 0

    async def failing_load() -> Any:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        raise RuntimeError("database unavailable")

    async def stamp() -> Any:
        return None

    async def run() -> list[Any]:
        return await asyncio.gather(
            *(cache.get_or_load("a", "b", "c", load=failing_load, revalidate=stamp) for _ in range(10)),
            return_exceptions=True,
        )

    results = asyncio.run(run())
    assert calls == 1
    assert all(isinstance(result, RuntimeError) for result in results)
    assert len(cache) == 0


# ── revalidation instead of blind expiry ──────────────────────────────────────────────────────


def test_an_unchanged_spec_is_not_reloaded_at_ttl_expiry() -> None:
    pool = FakeSpecPool(operations=10)
    clock = FakeClock()
    cache = SpecCache(max_entries=8, ttl_seconds=300.0, clock=clock)

    async def run() -> tuple[Any, Any, Any]:
        first = await _resolve(pool, cache)
        clock.now += 301
        second = await _resolve(pool, cache)
        clock.now += 100  # inside the extended lifetime: no statement at all
        third = await _resolve(pool, cache)
        return first, second, third

    first, second, third = asyncio.run(run())

    assert first is second is third
    assert pool.count("resolve") == 1
    assert pool.count("stamp") == 1
    assert len(pool.kinds) == FIRST_LOAD_STATEMENTS + 1


@pytest.mark.parametrize("change", ["content_stamp", "updated_at"])
def test_a_changed_spec_is_reloaded_at_ttl_expiry(change: str) -> None:
    pool = FakeSpecPool(operations=10)
    clock = FakeClock()
    cache = SpecCache(max_entries=8, ttl_seconds=300.0, clock=clock)

    async def run() -> tuple[Any, Any]:
        first = await _resolve(pool, cache)
        if change == "content_stamp":
            pool.content_stamp += 1
        else:
            pool.updated_at += timedelta(seconds=1)
        # Not before the TTL: the NOTIFY is what makes it sooner.
        assert await _resolve(pool, cache) is first
        clock.now += 301
        return first, await _resolve(pool, cache)

    first, second = asyncio.run(run())

    assert second is not first
    assert second.freshness.content_stamp == pool.content_stamp
    assert pool.count("stamp") == 1
    assert pool.count("resolve") == 2


def test_concurrent_requests_at_expiry_share_one_revalidation() -> None:
    pool = FakeSpecPool(operations=10, statement_delay=0.001)
    clock = FakeClock()
    cache = SpecCache(max_entries=8, ttl_seconds=300.0, clock=clock)

    async def run() -> None:
        await _resolve(pool, cache)
        clock.now += 301
        await asyncio.gather(*(_resolve(pool, cache) for _ in range(50)))

    asyncio.run(run())
    assert pool.count("stamp") == 1
    assert pool.count("resolve") == 1


def test_a_notify_is_served_on_the_next_request() -> None:
    pool = FakeSpecPool(operations=10)
    cache = SpecCache(max_entries=8, ttl_seconds=300.0)

    async def run() -> tuple[Any, Any]:
        first = await _resolve(pool, cache)
        pool.content_stamp += 1
        cache.invalidate(pool.tenant, pool.project, pool.version)
        return first, await _resolve(pool, cache)

    first, second = asyncio.run(run())
    assert second is not first
    assert pool.count("resolve") == 2
    assert pool.count("stamp") == 0


def test_a_load_overtaken_by_a_notify_is_not_stored() -> None:
    pool = FakeSpecPool(operations=10, statement_delay=0.002)
    cache = SpecCache(max_entries=8, ttl_seconds=300.0)

    async def run() -> Any:
        task = asyncio.create_task(_resolve(pool, cache))
        await asyncio.sleep(0.005)  # the load is reading rows
        cache.invalidate(pool.tenant, pool.project, pool.version)
        return await task

    compiled = asyncio.run(run())
    assert compiled is not None, "the request that loaded is still answered"
    assert cache.get(pool.tenant, pool.project, pool.version) is None


def test_a_version_gone_at_revalidation_is_dropped() -> None:
    clock = FakeClock()
    cache = SpecCache(max_entries=8, ttl_seconds=300.0, clock=clock)
    pool = FakeSpecPool(operations=4)

    async def gone() -> Any:
        return None

    async def nothing() -> Any:
        return None

    async def run() -> Any:
        compiled = await _resolve(pool, cache)
        clock.now += 301
        return compiled, await cache.get_or_load(pool.tenant, pool.project, pool.version, load=nothing, revalidate=gone)

    compiled, after = asyncio.run(run())
    assert compiled is not None
    assert after is None
    assert len(cache) == 0


def test_an_entry_without_a_stamp_is_reloaded_at_expiry() -> None:
    clock = FakeClock()
    cache = SpecCache(max_entries=8, ttl_seconds=300.0, clock=clock)
    loads = 0
    stamps = 0
    item = SimpleNamespace(cache_key=("a", "b", "c"), freshness=None)

    async def load() -> Any:
        nonlocal loads
        loads += 1
        return item

    async def stamp() -> Any:
        nonlocal stamps
        stamps += 1
        return None

    async def run() -> None:
        await cache.get_or_load("a", "b", "c", load=load, revalidate=stamp)
        clock.now += 301
        await cache.get_or_load("a", "b", "c", load=load, revalidate=stamp)

    asyncio.run(run())
    assert loads == 2
    assert stamps == 0


# ── no pooled connection held while compiling ─────────────────────────────────────────────────


def test_no_pooled_connection_is_held_while_the_spec_compiles() -> None:
    pool = FakeSpecPool(operations=50, size=10)
    seen: list[tuple[int, bool]] = []
    real = spec_loader.generate_openapi_spec

    def recording_generate(*args: Any, **kwargs: Any) -> Any:
        seen.append((pool.get_stats()["pool_available"], threading.current_thread() is threading.main_thread()))
        return real(*args, **kwargs)

    with patch("apiome_mock.spec_loader.generate_openapi_spec", side_effect=recording_generate):
        compiled = asyncio.run(_resolve(pool, SpecCache(max_entries=8, ttl_seconds=300.0)))

    assert len(compiled.operations) == 50
    assert seen == [(10, False)], "compiled in a worker thread with every connection idle"


def test_the_generator_gets_component_pins_and_opens_no_connection_of_its_own() -> None:
    pool = FakeSpecPool(operations=4)
    captured: dict[str, Any] = {}
    real = spec_loader.generate_openapi_spec

    def recording_generate(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return real(*args, **kwargs)

    with patch("apiome_mock.spec_loader.generate_openapi_spec", side_effect=recording_generate):
        asyncio.run(_resolve(pool, SpecCache(max_entries=8, ttl_seconds=300.0)))

    # ``None`` would make apiome-rest's generator read the pins on its own synchronous connection.
    assert captured["component_pin_rows"] == []


# ── canonical (event / gRPC / GraphQL) path ───────────────────────────────────────────────────


def _fake_compile(pool: FakeSpecPool, seen: list[tuple[int, bool]]) -> Any:
    def compile_(loaded: LoadedCanonicalSpec) -> Any:
        seen.append((pool.get_stats()["pool_available"], threading.current_thread() is threading.main_thread()))
        return SimpleNamespace(loaded=loaded, cache_key=loaded.cache_key)

    return compile_


def _resolve_canonical(pool: FakeSpecPool, cache: CanonicalSpecCache, **kwargs: Any) -> Any:
    return resolve_compiled_canonical(
        pool,  # type: ignore[arg-type]
        cache,
        tenant=pool.tenant,
        project=pool.project,
        version=pool.version,
        api_key=None,
        **kwargs,
    )


def test_100_concurrent_canonical_requests_run_one_load_compiled_off_the_loop() -> None:
    pool = FakeSpecPool(operations=4, statement_delay=0.001)
    cache = CanonicalSpecCache(max_entries=8, ttl_seconds=300.0)
    seen: list[tuple[int, bool]] = []
    loaded_hook: list[Any] = []

    async def run() -> list[Any]:
        return await asyncio.gather(
            *(_resolve_canonical(pool, cache, on_loaded=loaded_hook.append) for _ in range(100))
        )

    with (
        patch("apiome_mock.canonical_loader._build_canonical_from_row", return_value=SimpleNamespace()),
        patch("apiome_mock.canonical_resolve.compile_canonical_spec", side_effect=_fake_compile(pool, seen)),
    ):
        results = asyncio.run(run())

    assert pool.kinds == ["access", "canonical_resolve"]
    assert all(result is results[0] for result in results)
    assert seen == [(10, False)]
    assert loaded_hook == [results[0]], "the on_loaded hook (gRPC reflection) runs once per load"
    assert results[0].loaded.freshness.revision_id == pool.spec_id


def test_an_unchanged_canonical_spec_is_revalidated_not_reloaded() -> None:
    pool = FakeSpecPool(operations=4)
    clock = FakeClock()
    cache = CanonicalSpecCache(max_entries=8, ttl_seconds=300.0, clock=clock)

    async def run() -> tuple[Any, Any, Any]:
        first = await _resolve_canonical(pool, cache)
        clock.now += 301
        second = await _resolve_canonical(pool, cache)
        pool.content_stamp += 1
        clock.now += 301
        return first, second, await _resolve_canonical(pool, cache)

    with (
        patch("apiome_mock.canonical_loader._build_canonical_from_row", return_value=SimpleNamespace()),
        patch("apiome_mock.canonical_resolve.compile_canonical_spec", side_effect=_fake_compile(pool, [])),
    ):
        first, second, third = asyncio.run(run())

    assert first is second
    assert third is not first
    assert pool.count("canonical_resolve") == 2
    assert pool.count("stamp") == 2


def test_a_supplied_access_row_is_used_instead_of_a_lookup() -> None:
    pool = FakeSpecPool(operations=4)
    access_row = {"mock_enabled": True, "published": True, "mock_mode": None, "is_public_spec": True}

    compiled = asyncio.run(
        spec_loader.load_compiled_spec(
            pool,  # type: ignore[arg-type]
            tenant=pool.tenant,
            project=pool.project,
            version=pool.version,
            access_row=access_row,
        )
    )
    assert compiled is not None
    assert "access" not in pool.kinds
