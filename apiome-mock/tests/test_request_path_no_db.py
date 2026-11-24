"""The mock data plane serves a cached mock with no database work per request — DBP-1.24 (#7207).

The pool here is a stand-in that records every checkout and statement and answers the few queries
the request path can issue (access row, tenant limits, monthly usage, API keys) from a responder a
test controls. That makes the acceptance criteria directly checkable:

* after one warm-up request, REST, GraphQL and gRPC requests take no connection at all;
* usage totals written at shutdown equal the number of requests served;
* 10,000 streamed messages produce one usage statement;
* with the pool wedged, cached mocks keep serving;
* a disabled mock or revoked key stops being served within the cache TTL;
* a dropped NOTIFY listener reconnects and flushes the caches.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterator
from unittest.mock import patch
from uuid import UUID, uuid4

import bcrypt
import pytest
from fastapi.testclient import TestClient

from apiome_mock import audit as audit_module
from apiome_mock.api_key import configure_api_key_cache, validate_api_key_for_tenant
from apiome_mock.canonical_loader import LoadedCanonicalSpec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.capture_store import QUEUE_FULL, store_capture_exchange
from apiome_mock.database_pool import create_async_pool, pool_connection_kwargs
from apiome_mock.guard import record_mock_transport_event
from apiome_mock.settings import Settings
from apiome_mock.spec_cache import SpecCache, run_notify_listener
from apiome_mock.spec_loader import configure_access_cache, get_mock_access_status
from apiome_mock.tenant_limits import resolve_tenant_limits
from apiome_mock.ttl_cache import TtlCache
from apiome_mock.usage import UsageRecorder, usage_recorder_for
from test_graphql_transport import _api as graphql_api
from test_grpc_transport import _rpc_loaded
from test_mock_request_integration import _compiled as rest_compiled

TENANT_ID = uuid4()
SECRET = "sk_" + "ab" * 32

Responder = Callable[[str, Any], list[dict[str, Any]]]


# ---------------------------------------------------------------------------------------------
# A pool that counts
# ---------------------------------------------------------------------------------------------


@dataclass
class CountingPool:
    """Records checkouts and statements; ``wedged`` makes every checkout hang (pool saturated)."""

    responder: Responder
    checkouts: int = 0
    statements: list[tuple[str, Any]] = field(default_factory=list)
    transactions: int = 0
    wedged: bool = False

    @asynccontextmanager
    async def connection(self) -> Any:
        self.checkouts += 1
        if self.wedged:
            await asyncio.Event().wait()
        yield _Conn(self)

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _Cursor:
    def __init__(self, pool: CountingPool) -> None:
        self._pool = pool
        self._rows: list[dict[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> None:
        self._pool.statements.append((sql, params))
        self._rows = self._pool.responder(sql, params)

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Conn:
    def __init__(self, pool: CountingPool) -> None:
        self._pool = pool

    async def execute(self, sql: str, params: Any = None) -> None:
        self._pool.statements.append((sql, params))
        self._pool.responder(sql, params)

    @asynccontextmanager
    async def cursor(self, row_factory: Any = None) -> Any:
        yield _Cursor(self._pool)

    @asynccontextmanager
    async def transaction(self) -> Any:
        self._pool.transactions += 1
        yield


@dataclass
class World:
    """What the responder answers; tests flip fields to change the database."""

    mock_enabled: bool = True
    published: bool = True
    mode: str | None = None
    source_format: str = "openapi"
    key_rows: list[dict[str, Any]] = field(default_factory=list)
    usage_rows: list[tuple[Any, ...]] = field(default_factory=list)

    def respond(self, sql: str, params: Any) -> list[dict[str, Any]]:
        if "AS mock_mode" in sql:
            return [
                {
                    "mock_enabled": self.mock_enabled,
                    "published": self.published,
                    "mock_mode": self.mode,
                    "source_format": self.source_format,
                    "is_public_spec": self.published,
                }
            ]
        if "AS seats" in sql:
            return [{"tenant_id": TENANT_ID, "seats": {"mock_rps": 1_000_000, "mock_requests_per_month": 0}}]
        if "monthly_count" in sql:
            return [{"monthly_count": 0}]
        if "apiome.api_keys" in sql:
            return self.key_rows
        if "INSERT INTO apiome.mock_usage" in sql:
            self.usage_rows.extend(zip(*params, strict=True))
        return []

    def served(self) -> int:
        return sum(int(row[4]) for row in self.usage_rows)


def _pool(world: World) -> CountingPool:
    return CountingPool(responder=world.respond)


def _settings(**overrides: Any) -> Settings:
    return Settings(database_url="postgresql://localhost/db", **overrides)


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MOCK_AUDIT_SAMPLE_RATE", "0")
    # Only the shutdown flush writes usage, so a test can count request-path statements exactly.
    monkeypatch.setenv("APIOME_MOCK_USAGE_FLUSH_INTERVAL_SECONDS", "60")
    from apiome_mock.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------------------------
# Acceptance: REST / GraphQL / gRPC cache hits issue no statement
# ---------------------------------------------------------------------------------------------


def test_a_cached_rest_mock_takes_no_connection_and_usage_equals_requests_served(app_env: None) -> None:
    world = World()
    pool = _pool(world)
    from apiome_mock.server import create_app

    with (
        patch("apiome_mock.server.create_async_pool", return_value=pool),
        patch("apiome_mock.handler.load_compiled_spec", return_value=rest_compiled()) as load,
    ):
        app = create_app()
        with TestClient(app) as client:
            assert client.get("/demo/petstore/1.0.0/pets").status_code == 200  # warm-up
            warm = pool.checkouts
            for _ in range(200):
                assert client.get("/demo/petstore/1.0.0/pets").status_code == 200
            assert pool.checkouts == warm, "a cache-hit REST request took a pooled connection"

            # Pool saturated by slow queries: cached mocks keep serving.
            pool.wedged = True
            for _ in range(20):
                assert client.get("/demo/petstore/1.0.0/pets").status_code == 200
            pool.wedged = False

    assert load.await_count == 1
    # Shutdown flushed every count, as one multi-row upsert.
    assert world.served() == 221
    assert sum("INSERT INTO apiome.mock_usage" in sql for sql, _ in pool.statements) == 1


def test_a_cached_graphql_mock_takes_no_connection(app_env: None) -> None:
    world = World(source_format="graphql")
    pool = _pool(world)
    loaded = LoadedCanonicalSpec(
        revision_id=uuid4(),
        tenant_slug="demo",
        project_slug="people",
        version_label="1.0.0",
        updated_at=rest_compiled().updated_at,
        api=graphql_api(),
        source_format="graphql",
    )
    from apiome_mock.server import create_app

    with (
        patch("apiome_mock.server.create_async_pool", return_value=pool),
        patch("apiome_mock.graphql_transport.load_canonical_spec", return_value=loaded),
    ):
        app = create_app()
        with TestClient(app) as client:
            url = "/demo/people/1.0.0/graphql"
            assert client.post(url, json={"query": "{ greeting }"}).status_code == 200
            warm = pool.checkouts
            for _ in range(50):
                response = client.post(url, json={"query": "{ greeting }"})
                assert response.status_code == 200
                assert isinstance(response.json()["data"]["greeting"], str)
            assert pool.checkouts == warm
    assert world.served() == 51


class _GrpcContext:
    def __init__(self, metadata: dict[str, str]) -> None:
        self._metadata = metadata

    def invocation_metadata(self) -> list[tuple[str, str]]:
        return list(self._metadata.items())

    def peer(self) -> str:
        return "ipv4:127.0.0.1:5000"

    async def abort(self, code: Any, details: str) -> None:
        raise AssertionError(f"aborted: {code} {details}")


def test_a_cached_grpc_mock_takes_no_connection() -> None:
    from apiome_mock.grpc_transport import GrpcMockRuntime

    world = World(source_format="protobuf")
    pool = _pool(world)
    runtime = GrpcMockRuntime(
        pool=pool,  # type: ignore[arg-type]
        cache=CanonicalSpecCache(max_entries=8, ttl_seconds=300.0),
        settings=_settings(audit_sample_rate=0.0),
    )
    context = _GrpcContext({"x-apiome-tenant": "demo", "x-apiome-project": "echo", "x-apiome-version": "1.0.0"})

    async def scenario() -> tuple[int, int]:
        await runtime._serve_unary(b"", context, service_name="echo.v1.EchoService", method_name="Echo")  # type: ignore[arg-type]
        warm = pool.checkouts
        for _ in range(50):
            await runtime._serve_unary(b"", context, service_name="echo.v1.EchoService", method_name="Echo")  # type: ignore[arg-type]
        after = pool.checkouts
        await usage_recorder_for(pool).close()  # type: ignore[arg-type]
        return warm, after

    with patch("apiome_mock.grpc_transport.load_canonical_spec", return_value=_rpc_loaded()):
        warm, after = asyncio.run(scenario())
    assert after == warm
    assert world.served() == 51


# ---------------------------------------------------------------------------------------------
# Acceptance: streamed messages produce a bounded number of usage statements
# ---------------------------------------------------------------------------------------------


def test_ten_thousand_streamed_messages_are_one_usage_statement() -> None:
    world = World()
    pool = _pool(world)
    settings = _settings(audit_sample_rate=0.0)

    async def scenario() -> None:
        for _ in range(10_000):
            record_mock_transport_event(
                pool=pool,  # type: ignore[arg-type]
                tenant="demo",
                project="events",
                version="1.0.0",
                transport="sse",
                channel="user/signedup",
                direction="outbound",
                tenant_id=TENANT_ID,
                settings=settings,
            )
        await usage_recorder_for(pool).close()  # type: ignore[arg-type]

    asyncio.run(scenario())
    assert len(pool.statements) == 1
    assert world.served() == 10_000


# ---------------------------------------------------------------------------------------------
# The usage recorder
# ---------------------------------------------------------------------------------------------


def test_the_recorder_sums_counts_per_row_and_writes_one_statement_per_table() -> None:
    world = World()
    pool = _pool(world)
    other = uuid4()
    recorder = UsageRecorder(pool=pool, today=lambda: date(2026, 11, 23))  # type: ignore[arg-type]

    async def scenario() -> None:
        for _ in range(3):
            recorder.add_request(tenant_id=TENANT_ID, project_slug="p", version_label="v1")
        recorder.add_request(tenant_id=other, project_slug="p", version_label="v2", count=5)
        recorder.add_event_publish(
            tenant_id=TENANT_ID,
            project_slug="p",
            version_label="v1",
            channel_key="c",
            encoding="json",
            trigger="periodic",
            published=True,
        )
        recorder.add_event_publish(
            tenant_id=TENANT_ID,
            project_slug="p",
            version_label="v1",
            channel_key="c",
            encoding="json",
            trigger="periodic",
            published=False,
        )
        await recorder.close()

    asyncio.run(scenario())
    assert len(pool.statements) == 2
    assert sorted(world.usage_rows, key=lambda r: r[4]) == [
        (TENANT_ID, "p", "v1", date(2026, 11, 23), 3),
        (other, "p", "v2", date(2026, 11, 23), 5),
    ]
    event_sql, event_params = pool.statements[1]
    assert "mock_event_publish_usage" in event_sql
    assert event_params[7] == [1] and event_params[8] == [1]


def test_a_failed_flush_keeps_its_counts_for_the_next_one() -> None:
    calls = {"n": 0}

    def flaky(sql: str, params: Any) -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("postgres is away")
        return []

    pool = CountingPool(responder=flaky)
    recorder = UsageRecorder(pool=pool)  # type: ignore[arg-type]

    async def scenario() -> None:
        recorder.add_request(tenant_id=TENANT_ID, project_slug="p", version_label="v1", count=4)
        await recorder.flush()
        assert recorder.pending_requests() == 4
        recorder.add_request(tenant_id=TENANT_ID, project_slug="p", version_label="v1")
        await recorder.close()

    asyncio.run(scenario())
    assert recorder.pending_requests() == 0
    assert pool.statements[-1][1][4] == [5]


def test_the_recorder_flushes_on_its_interval() -> None:
    world = World()
    pool = _pool(world)
    recorder = UsageRecorder(pool=pool, flush_interval_seconds=0.02)  # type: ignore[arg-type]

    async def scenario() -> None:
        recorder.add_request(tenant_id=TENANT_ID, project_slug="p", version_label="v1")
        await asyncio.sleep(0.08)
        assert world.served() == 1
        await recorder.close()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------------------------
# Acceptance: a disabled mock or a revoked key stops within the TTL
# ---------------------------------------------------------------------------------------------


def test_a_disabled_mock_stops_being_served_within_the_access_ttl() -> None:
    world = World()
    pool = _pool(world)
    configure_access_cache(0.05)

    async def scenario() -> list[str]:
        seen = [await get_mock_access_status(pool, tenant="demo", project="p", version="v1")]  # type: ignore[arg-type]
        world.mock_enabled = False
        seen.append(await get_mock_access_status(pool, tenant="demo", project="p", version="v1"))  # type: ignore[arg-type]
        await asyncio.sleep(0.07)
        seen.append(await get_mock_access_status(pool, tenant="demo", project="p", version="v1"))  # type: ignore[arg-type]
        return seen

    assert asyncio.run(scenario()) == ["ok", "ok", "disabled"]


def test_the_access_query_reads_the_mode_not_the_whole_settings_document() -> None:
    world = World()
    pool = _pool(world)
    asyncio.run(get_mock_access_status(pool, tenant="demo", project="p", version="v1"))  # type: ignore[arg-type]
    (sql, _params), *_ = pool.statements
    assert "mock_settings->>'mode' AS mock_mode" in sql
    assert "mcp_v_public_specs" not in sql
    assert "v.mock_settings,\n" not in sql


def test_a_private_draft_needs_its_tenants_key_even_from_the_cached_row() -> None:
    from apiome_mock.api_key import ValidatedApiKey

    world = World(published=False, mode="private")
    pool = _pool(world)
    key = ValidatedApiKey(id=uuid4(), tenant_id=TENANT_ID, tenant_slug="demo")

    async def scenario() -> list[str]:
        return [
            await get_mock_access_status(pool, tenant="demo", project="p", version="v1", api_key=key),  # type: ignore[arg-type]
            await get_mock_access_status(pool, tenant="demo", project="p", version="v1"),  # type: ignore[arg-type]
        ]

    assert asyncio.run(scenario()) == ["ok", "missing"]
    assert len(pool.statements) == 1


def _key_row() -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "tenant_id": str(TENANT_ID),
        "key_hash": bcrypt.hashpw(SECRET.encode(), bcrypt.gensalt(rounds=4)).decode(),
        "tenant_slug": "demo",
    }


def test_a_verified_key_is_cached_and_a_revoked_key_stops_within_the_ttl() -> None:
    world = World(key_rows=[_key_row()])
    pool = _pool(world)
    configure_api_key_cache(ttl_seconds=0.05, negative_ttl_seconds=0.05)

    async def scenario() -> list[bool]:
        seen = []
        for _ in range(5):
            seen.append(await validate_api_key_for_tenant(pool, api_key=SECRET, tenant_slug="demo") is not None)  # type: ignore[arg-type]
        world.key_rows = []  # revoked
        await asyncio.sleep(0.07)
        seen.append(await validate_api_key_for_tenant(pool, api_key=SECRET, tenant_slug="demo") is not None)  # type: ignore[arg-type]
        return seen

    assert asyncio.run(scenario()) == [True] * 5 + [False]
    assert len(pool.statements) == 2


def test_a_rejected_key_is_negatively_cached_and_bcrypt_runs_off_the_loop() -> None:
    world = World(key_rows=[_key_row()])
    pool = _pool(world)
    threads: list[str] = []
    real_to_thread = asyncio.to_thread

    async def spy(func: Any, *args: Any) -> Any:
        threads.append(func.__name__)
        return await real_to_thread(func, *args)

    async def scenario() -> None:
        for _ in range(3):
            wrong = "sk_" + "ab" * 31 + "zz"
            assert await validate_api_key_for_tenant(pool, api_key=wrong, tenant_slug="demo") is None  # type: ignore[arg-type]

    with patch("apiome_mock.api_key.asyncio.to_thread", new=spy):
        asyncio.run(scenario())
    assert len(pool.statements) == 1
    assert threads == ["_verify_rows"]


def test_the_key_cache_never_holds_the_raw_key() -> None:
    from apiome_mock import api_key as api_key_module

    world = World(key_rows=[_key_row()])
    asyncio.run(validate_api_key_for_tenant(_pool(world), api_key=SECRET, tenant_slug="demo"))  # type: ignore[arg-type]
    keys = list(api_key_module._KEY_CACHE._entries)
    assert keys and all(SECRET not in str(k) for k in keys)


# ---------------------------------------------------------------------------------------------
# Unknown tenants
# ---------------------------------------------------------------------------------------------


def test_an_unknown_tenant_is_negatively_cached() -> None:
    pool = CountingPool(responder=lambda sql, params: [])
    settings = _settings()

    async def scenario() -> None:
        for _ in range(10):
            assert await resolve_tenant_limits(pool, tenant_slug="nobody", settings=settings) is None  # type: ignore[arg-type]

    asyncio.run(scenario())
    assert len(pool.statements) == 1


def test_unknown_tenants_share_an_address_keyed_bucket() -> None:
    from starlette.requests import Request

    from apiome_mock.guard import enforce_mock_limits

    pool = CountingPool(responder=lambda sql, params: [])
    settings = _settings(unknown_tenant_rps=1.0)
    ip = f"198.51.100.{uuid4().int % 250}"

    def request() -> Request:
        return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": (ip, 1)})

    async def scenario() -> list[int | None]:
        out = []
        for slug in ("ghost-a", "ghost-b", "ghost-c"):
            blocked = await enforce_mock_limits(
                request(),
                tenant=slug,
                project="p",
                version="v",
                pool=pool,  # type: ignore[arg-type]
                settings=settings,
            )
            out.append(blocked.status_code if blocked is not None else None)
        return out

    statuses = asyncio.run(scenario())
    assert statuses[0] is None
    assert 429 in statuses[1:]


# ---------------------------------------------------------------------------------------------
# Single flight
# ---------------------------------------------------------------------------------------------


def test_concurrent_misses_share_one_load() -> None:
    cache: TtlCache[int] = TtlCache(ttl_seconds=60.0)
    loads = {"n": 0}

    async def load() -> int:
        loads["n"] += 1
        await asyncio.sleep(0.01)
        return 7

    async def scenario() -> list[int | None]:
        return list(await asyncio.gather(*(cache.get_or_load("k", load) for _ in range(50))))

    assert asyncio.run(scenario()) == [7] * 50
    assert loads["n"] == 1


def test_a_failed_load_is_not_cached() -> None:
    cache: TtlCache[int] = TtlCache(ttl_seconds=60.0)
    attempts = {"n": 0}

    async def load() -> int:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("boom")
        return 1

    async def scenario() -> int | None:
        with pytest.raises(RuntimeError):
            await cache.get_or_load("k", load)
        return await cache.get_or_load("k", load)

    assert asyncio.run(scenario()) == 1


def test_entries_expire() -> None:
    now = {"t": 0.0}
    cache: TtlCache[int] = TtlCache(ttl_seconds=1.0, negative_ttl_seconds=0.5, clock=lambda: now["t"])
    cache.put("a", 1)
    cache.put("b", None)
    now["t"] = 0.6
    assert cache.peek("a") == (True, 1)
    assert cache.peek("b") == (False, None)
    now["t"] = 1.1
    assert cache.peek("a") == (False, None)


# ---------------------------------------------------------------------------------------------
# Pool configuration
# ---------------------------------------------------------------------------------------------


def test_the_pool_is_autocommit_with_a_timeout_a_name_and_a_bounded_queue() -> None:
    settings = _settings(database_statement_timeout_ms=1234, database_pool_max_waiting=7)
    assert pool_connection_kwargs(settings) == {
        "autocommit": True,
        "application_name": "apiome-mock",
        "options": "-c statement_timeout=1234",
    }
    pool = create_async_pool(settings)
    assert pool.max_waiting == 7
    assert pool.kwargs["autocommit"] is True


def test_a_zero_statement_timeout_sets_no_option() -> None:
    assert "options" not in pool_connection_kwargs(_settings(database_statement_timeout_ms=0))


# ---------------------------------------------------------------------------------------------
# Audit and capture
# ---------------------------------------------------------------------------------------------


def test_an_audit_append_locks_the_tenant_chain_inside_a_transaction() -> None:
    pool = CountingPool(responder=lambda sql, params: [])
    asyncio.run(
        audit_module.insert_mock_audit_entry(
            pool,  # type: ignore[arg-type]
            tenant_id=TENANT_ID,
            actor_label="1.2.3.4",
            action="mock.request",
            target="p/v GET /",
            detail={},
        )
    )
    assert pool.transactions == 1
    lock_sql, lock_params = pool.statements[0]
    assert "pg_advisory_xact_lock" in lock_sql
    assert lock_params == (f"apiome.access_audit:{TENANT_ID}",)
    assert "INSERT INTO apiome.access_audit" in pool.statements[2][0]


def test_the_audit_writer_appends_one_row_at_a_time() -> None:
    active = {"now": 0, "max": 0}
    written: list[UUID] = []

    async def fake_insert(pool: Any, **kwargs: Any) -> None:
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.001)
        written.append(kwargs["tenant_id"])
        active["now"] -= 1

    pool = CountingPool(responder=lambda sql, params: [])

    async def scenario() -> None:
        for _ in range(20):
            audit_module.schedule_mock_access_audit(
                pool,  # type: ignore[arg-type]
                tenant_id=TENANT_ID,
                client_ip="1.2.3.4",
                project_slug="p",
                version_label="v",
                method="GET",
                path="/",
                status_code=200,
                sample_rate=1.0,
            )
        await audit_module.close_audit_writer(pool)  # type: ignore[arg-type]

    with patch.object(audit_module, "insert_mock_access_audit", new=fake_insert):
        asyncio.run(scenario())
    assert len(written) == 20
    assert active["max"] == 1


def _capture_kwargs() -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "tenant_id": TENANT_ID,
        "version_id": uuid4(),
        "project": "p",
        "version": "v",
        "upstream": "https://api.example.com/pets",
        "allowlist_entry": "https://api.example.com",
        "policy_digest": "sha256:x",
        "api_key_id": uuid4(),
        "operation_key": "GET /pets",
        "method": "GET",
        "path": "/pets",
        "status_code": 200,
        "record": {"a": 1},
        "digest": "sha256:y",
        "redactions": [],
        "schema_valid": True,
        "validation_errors": [],
        "expires_at": datetime.now(timezone.utc),
    }


def test_a_capture_is_one_checkout_and_one_transaction() -> None:
    def respond(sql: str, params: Any) -> list[dict[str, Any]]:
        if "AS pending" in sql:
            return [{"pending": 0}]
        if "INSERT INTO apiome.mock_capture_exchange" in sql:
            return [{"id": "cap-1"}]
        return []

    pool = CountingPool(responder=respond)
    result = asyncio.run(store_capture_exchange(pool, max_pending=500, **_capture_kwargs()))  # type: ignore[arg-type]
    assert result == ("cap-1", None)
    assert pool.checkouts == 1 and pool.transactions == 1
    count_sql, count_params = pool.statements[0]
    assert "LIMIT %(cap)s" in count_sql and count_params["cap"] == 500
    assert "INSERT INTO apiome.access_audit" in pool.statements[-1][0]
    assert not any("t.slug" in sql for sql, _ in pool.statements)


def test_a_full_queue_stores_nothing() -> None:
    pool = CountingPool(responder=lambda sql, params: [{"pending": 3}] if "AS pending" in sql else [])
    result = asyncio.run(store_capture_exchange(pool, max_pending=3, **_capture_kwargs()))  # type: ignore[arg-type]
    assert result == (None, QUEUE_FULL)
    assert len(pool.statements) == 1


# ---------------------------------------------------------------------------------------------
# Acceptance: a killed listener connection is recovered without a restart
# ---------------------------------------------------------------------------------------------


class _Notify:
    def __init__(self, payload: str) -> None:
        self.payload = payload


class _ListenConn:
    def __init__(self, payloads: list[str], then_fail: bool) -> None:
        self._payloads = payloads
        self._then_fail = then_fail

    async def __aenter__(self) -> _ListenConn:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, *_args: Any) -> None:
        return None

    async def notifies(self) -> Any:
        for payload in self._payloads:
            yield _Notify(payload)
        if self._then_fail:
            raise ConnectionError("server closed the connection")
        await asyncio.Event().wait()


def test_the_listener_reconnects_with_backoff_and_flushes_on_every_connect() -> None:
    cache = SpecCache(max_entries=8, ttl_seconds=300.0)
    cache.put(rest_compiled())
    connects: list[float] = []
    flushed: list[int] = []
    invalidated: list[tuple[str, str, str]] = []
    stop = asyncio.Event()

    async def connect(_url: str) -> Any:
        connects.append(time.monotonic())
        if len(connects) == 1:
            raise OSError("connection refused")
        if len(connects) == 2:
            return _ListenConn(["demo/p/v1"], then_fail=True)
        return _ListenConn(["demo/p/v2"], then_fail=False)

    async def scenario() -> None:
        task = asyncio.create_task(
            run_notify_listener(
                "postgresql://x",
                "chan",
                cache,
                stop_event=stop,
                on_invalidate=lambda *k: invalidated.append(k),
                on_connected=lambda: flushed.append(len(connects)),
                initial_backoff_seconds=0.01,
                max_backoff_seconds=0.02,
                connect=connect,
            )
        )
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(invalidated) >= 2:
                break
        stop.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(connects) >= 3
    assert flushed[:2] == [2, 3]
    assert invalidated[:2] == [("demo", "p", "v1"), ("demo", "p", "v2")]
    assert cache.get("demo", "petstore", "1.0.0") is None  # flushed on connect


# ---------------------------------------------------------------------------------------------
# Kafka producer
# ---------------------------------------------------------------------------------------------


def test_an_unchanged_binding_reuses_the_adapter_without_reading_the_binding() -> None:
    from apiome_mock.broker_bindings import binding_state_key
    from apiome_mock.broker_producer import BrokerPublisher

    row = {
        "id": "b-1",
        "rotated_at": None,
        "key_version": None,
        "bootstrap": ["kafka:9092"],
        "tls_enabled": False,
        "tls_verify": True,
        "protocol": "kafka",
    }
    reads = {"n": 0}

    async def load(_pool: Any, _version_id: Any) -> dict[str, Any]:
        reads["n"] += 1
        return row

    class _Adapter:
        def __init__(self, _connection: Any) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    publisher = BrokerPublisher(
        pool=CountingPool(responder=lambda s, p: []), settings=_settings(), adapter_factory=_Adapter
    )  # type: ignore[arg-type]
    state = binding_state_key(row)

    async def scenario() -> None:
        first = await publisher.adapter_for("v-1", binding_state=state)
        for _ in range(5):
            assert await publisher.adapter_for("v-1", binding_state=state) is first

    with patch("apiome_mock.broker_producer.load_kafka_binding", new=load):
        asyncio.run(scenario())
    assert reads["n"] == 1
