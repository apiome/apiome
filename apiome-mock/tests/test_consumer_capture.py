"""Consumer-tagged capture in the hosted mock runtime — PFX-9.1 (#7319).

The pool here is the counting stand-in from :mod:`test_request_path_no_db`, so the acceptance
criteria are checked directly:

* untagged calls are served exactly as before, with no capture header and no extra statement;
* a tagged call (header or private capture URL) is served the same response and answered
  ``queued``; the request path takes no connection, and the shutdown flush writes every call in
  one transaction;
* a tag that cannot be read, an unknown or foreign capture URL, or a full queue is answered
  ``not-recorded`` with the reason — nothing is silently ignored;
* what only the writer can know (session full, too many sessions, credential residue, a version
  deleted meanwhile) is counted by reason on the session or the tenant;
* a failed flush is retried, then dropped with a warning; expired captures are swept in batches.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from app.pact_capture import (
    MAX_CALLS_PER_SESSION,
    MAX_LIVE_SESSIONS_PER_TENANT,
    CaptureHeaderProblem,
    ConsumerTag,
    new_link_token,
)
from fastapi.testclient import TestClient

from apiome_mock import consumer_capture as capture_module
from apiome_mock.consumer_capture import (
    MAX_FLUSH_ATTEMPTS,
    ConsumerCaptureRecorder,
    PendingCall,
    SessionState,
    allocate_calls,
    configure_capture_link_cache,
    resolve_capture_link,
    sweep_expired_captures,
)
from apiome_mock.handler import _consumer_capture_for
from test_mock_request_integration import _compiled as rest_compiled
from test_request_path_no_db import TENANT_ID, CountingPool, World

COMPILED = rest_compiled()
VERSION_ID = COMPILED.revision_id
OTHER_VERSION = uuid4()
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------
# A database the flush can talk to
# ---------------------------------------------------------------------------------------------


class CaptureWorld(World):
    """:class:`World` plus the capture tables, answered from memory."""

    def __init__(self) -> None:
        super().__init__()
        self.versions: dict[UUID, dict[str, Any]] = {
            VERSION_ID: {"version_id": VERSION_ID, "tenant_id": TENANT_ID, "retention_days": 7}
        }
        self.sessions: dict[tuple[UUID, str, str], dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self.links: dict[str, dict[str, Any]] = {}
        self.tenant_refusals: list[tuple[Any, ...]] = []
        self.live_sessions: int | None = None
        self.fail_inserts = 0

    def respond(self, sql: str, params: Any) -> list[dict[str, Any]]:  # noqa: C901 - one branch per statement
        if "FROM apiome.mock_consumer_capture_link" in sql:
            row = self.links.get(params["token_hash"])
            return [row] if row else []
        if "LEFT JOIN apiome.mock_consumer_capture_settings" in sql:
            return [self.versions[v] for v in params["version_ids"] if v in self.versions]
        if sql.lstrip().startswith("DELETE FROM apiome.mock_consumer_capture_session\n    WHERE (version_id"):
            return []
        if "FROM apiome.mock_consumer_capture_session" in sql and "FOR UPDATE" in sql:
            keys = set(zip(params["k_version"], params["k_consumer"], params["k_cversion"], strict=True))
            return [row for key, row in self.sessions.items() if key in keys]
        if "COUNT(*) AS live" in sql:
            if self.live_sessions is None:
                return []
            return [{"tenant_id": t, "live": self.live_sessions} for t in params["tenant_ids"]]
        if "INSERT INTO apiome.mock_consumer_capture_session" in sql:
            for i, version in enumerate(params["version_id"]):
                key = (version, params["consumer"][i], params["consumer_version"][i])
                self.sessions.setdefault(
                    key,
                    {
                        "id": uuid4(),
                        "tenant_id": params["tenant_id"][i],
                        "version_id": version,
                        "consumer": key[1],
                        "consumer_version": key[2],
                        "call_count": 0,
                        "refused": {},
                    },
                )
            return []
        if "INSERT INTO apiome.mock_consumer_capture_call" in sql:
            if self.fail_inserts:
                self.fail_inserts -= 1
                raise RuntimeError("database went away")
            names = list(params)
            self.calls.extend(dict(zip(names, row, strict=True)) for row in zip(*params.values(), strict=True))
            return []
        if "UPDATE apiome.mock_consumer_capture_session" in sql:
            by_id = {row["id"]: row for row in self.sessions.values()}
            for i, sid in enumerate(params["id"]):
                row = by_id[sid]
                row["call_count"] += params["stored"][i]
                row["refused"] = json.loads(params["reasons"][i])
            return []
        if "INSERT INTO apiome.mock_consumer_capture_settings" in sql:
            self.tenant_refusals.extend(zip(*params.values(), strict=True))
            return []
        return super().respond(sql, params)


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MOCK_AUDIT_SAMPLE_RATE", "0")
    monkeypatch.setenv("APIOME_MOCK_USAGE_FLUSH_INTERVAL_SECONDS", "60")
    # Only the shutdown flush writes captures, so request-path statements can be counted.
    monkeypatch.setenv("APIOME_MOCK_CONSUMER_CAPTURE_FLUSH_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("APIOME_MOCK_CONSUMER_CAPTURE_PURGE_INTERVAL_SECONDS", "86400")
    from apiome_mock.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _run_app(world: CaptureWorld, requests: Any) -> tuple[CountingPool, list[Any]]:
    """Serve ``requests(client)`` through the real app; return the pool and what it returned."""
    pool = CountingPool(responder=world.respond)
    from apiome_mock.server import create_app

    with (
        patch("apiome_mock.server.create_async_pool", return_value=pool),
        patch("apiome_mock.handler.load_compiled_spec", return_value=COMPILED),
    ):
        with TestClient(create_app()) as client:
            results = requests(client, pool)
    return pool, results


def _capture_statements(pool: CountingPool) -> list[str]:
    return [sql for sql, _ in pool.statements if "mock_consumer_capture" in sql]


# ---------------------------------------------------------------------------------------------
# Untagged calls are unaffected
# ---------------------------------------------------------------------------------------------


def test_untagged_calls_are_served_as_before_and_never_recorded(app_env: None) -> None:
    world = CaptureWorld()

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        plain = client.get("/demo/petstore/1.0.0/pets")
        off = client.get("/demo/petstore/1.0.0/pets", headers={"X-Mock-Capture": "off"})
        return [plain, off]

    pool, (plain, off) = _run_app(world, calls)
    for response in (plain, off):
        assert response.status_code == 200
        assert "x-mock-capture" not in response.headers
    assert plain.content == off.content
    # Nothing was queued, so shutdown wrote nothing to the capture tables.
    assert _capture_statements(pool) == []
    assert world.calls == []


def test_the_proxys_own_opt_in_values_are_not_consumer_tags() -> None:
    class _Req:
        def __init__(self, value: str) -> None:
            self.headers = {"X-Mock-Capture": value}

    for value in ("on", "record", "true"):
        assert _consumer_capture_for(_Req(value), None) is None  # type: ignore[arg-type]
    assert _consumer_capture_for(_Req("orders-ui@3.4.0"), None) == ConsumerTag("orders-ui", "3.4.0")


# ---------------------------------------------------------------------------------------------
# Tagged calls
# ---------------------------------------------------------------------------------------------


def test_tagged_calls_get_the_same_response_queue_with_no_connection_and_flush_in_one_transaction(
    app_env: None,
) -> None:
    world = CaptureWorld()

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        untagged = client.get("/demo/petstore/1.0.0/pets")  # warm-up: access row and spec
        warm = pool.checkouts
        tagged = [
            client.get("/demo/petstore/1.0.0/pets?limit=2", headers={"X-Mock-Capture": "orders-ui@3.4.0"})
            for _ in range(50)
        ]
        return [untagged, tagged, pool.checkouts - warm, pool.transactions]

    pool, (untagged, tagged, request_checkouts, transactions_before) = _run_app(world, calls)
    assert request_checkouts == 0, "a tagged call took a pooled connection on the request path"
    assert transactions_before == 0
    for response in tagged:
        assert response.status_code == untagged.status_code
        assert response.content == untagged.content
        assert response.headers["x-mock-capture"] == "queued"
        assert response.headers["x-mock-capture-session"] == "orders-ui@3.4.0"

    # Shutdown flushed all 50 in one transaction: one session, 50 calls.
    assert pool.transactions == 1
    assert sum("INSERT INTO apiome.mock_consumer_capture_call" in sql for sql in _capture_statements(pool)) == 1
    assert len(world.sessions) == 1
    session = next(iter(world.sessions.values()))
    assert session["call_count"] == 50
    first = world.calls[0]
    assert first["via"] == "header"
    assert first["method"] == "GET"
    assert first["path"] == "/pets"
    assert first["path_template"] == "/pets"
    assert first["operation_key"] == "GET /pets"
    assert first["origin"] == "spec"
    assert first["status"] == 200
    assert json.loads(first["request"])["query"] == [{"name": "limit", "value": "2"}]


def test_an_off_spec_call_is_recorded_with_its_origin(app_env: None) -> None:
    world = CaptureWorld()

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        return [client.get("/demo/petstore/1.0.0/health", headers={"X-Mock-Capture": "orders-ui@3.4.0"})]

    _, (response,) = _run_app(world, calls)
    assert response.status_code == 404
    assert response.headers["x-mock-capture"] == "queued"
    assert world.calls[0]["origin"] == "off-spec"
    assert world.calls[0]["path_template"] is None


def test_credentials_are_redacted_before_they_are_stored(app_env: None) -> None:
    world = CaptureWorld()

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        return [
            client.get(
                "/demo/petstore/1.0.0/pets?access_token=abc",
                headers={
                    "X-Mock-Capture": "orders-ui@3.4.0",
                    "Authorization": "Bearer abc.def.ghi",
                    "X-Mock-Session": "my-session",
                },
            )
        ]

    _run_app(world, calls)
    call = world.calls[0]
    stored = json.dumps(json.loads(call["request"]))
    assert "abc.def.ghi" not in stored and "access_token" not in stored
    assert "my-session" not in stored
    assert call["mock_session"] and call["mock_session"] != "my-session"
    assert call["redaction_count"] >= 2


@pytest.mark.parametrize(
    "value, says",
    [
        ("orders-ui", "must be <consumer>@<version>"),
        ("orders-ui@", "The version is empty."),
    ],
)
def test_a_tag_that_cannot_be_read_is_answered_not_recorded(app_env: None, value: str, says: str) -> None:
    world = CaptureWorld()

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        return [client.get("/demo/petstore/1.0.0/pets", headers={"X-Mock-Capture": value})]

    _, (response,) = _run_app(world, calls)
    assert response.status_code == 200
    assert response.headers["x-mock-capture"] == "not-recorded"
    assert says in response.headers["x-mock-capture-reason"]
    assert world.calls == []


def test_a_full_queue_is_answered_not_recorded(app_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MOCK_CONSUMER_CAPTURE_MAX_PENDING", "2")
    world = CaptureWorld()

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        return [
            client.get("/demo/petstore/1.0.0/pets", headers={"X-Mock-Capture": "orders-ui@3.4.0"}) for _ in range(3)
        ]

    _, responses = _run_app(world, calls)
    assert [r.headers["x-mock-capture"] for r in responses] == ["queued", "queued", "not-recorded"]
    assert "Too many calls are waiting" in responses[2].headers["x-mock-capture-reason"]
    assert len(world.calls) == 2


# ---------------------------------------------------------------------------------------------
# Private capture URLs
# ---------------------------------------------------------------------------------------------


def _link(world: CaptureWorld, *, version_id: UUID = VERSION_ID) -> tuple[str, UUID]:
    token, digest, _ = new_link_token()
    link_id = uuid4()
    world.links[digest] = {
        "id": link_id,
        "version_id": version_id,
        "consumer": "Orders UI",
        "consumer_version": "3.4.0",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
    }
    return token, link_id


def test_a_capture_url_serves_the_path_after_the_token_and_records_for_its_consumer(app_env: None) -> None:
    world = CaptureWorld()
    token, link_id = _link(world)
    configure_capture_link_cache(30.0)

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        plain = client.get("/demo/petstore/1.0.0/pets")
        via_url = client.get(f"/demo/petstore/1.0.0/~capture/{token}/pets")
        again = client.get(f"/demo/petstore/1.0.0/~capture/{token}/pets")
        return [plain, via_url, again]

    pool, (plain, via_url, again) = _run_app(world, calls)
    assert via_url.content == plain.content
    assert via_url.headers["x-mock-capture"] == "queued"
    assert via_url.headers["x-mock-capture-session"] == "Orders UI@3.4.0"
    assert again.headers["x-mock-capture"] == "queued"
    # The link was looked up once and then cached.
    assert sum("FROM apiome.mock_consumer_capture_link" in sql for sql, _ in pool.statements) == 1
    assert [call["via"] for call in world.calls] == ["url", "url"]
    assert world.calls[0]["link_id"] == link_id
    assert world.calls[0]["path"] == "/pets"


def test_an_unknown_or_foreign_capture_url_is_served_but_not_recorded(app_env: None) -> None:
    world = CaptureWorld()
    foreign, _ = _link(world, version_id=OTHER_VERSION)
    unknown, _, _ = new_link_token()
    configure_capture_link_cache(30.0)

    def calls(client: TestClient, pool: CountingPool) -> list[Any]:
        return [
            client.get(f"/demo/petstore/1.0.0/~capture/{unknown}/pets"),
            client.get(f"/demo/petstore/1.0.0/~capture/{foreign}/pets"),
            client.get("/demo/petstore/1.0.0/~capture/not-a-token/pets"),
        ]

    _, (unknown_r, foreign_r, malformed_r) = _run_app(world, calls)
    for response in (unknown_r, foreign_r, malformed_r):
        assert response.status_code == 200
        assert response.headers["x-mock-capture"] == "not-recorded"
    assert "unknown, revoked or expired" in unknown_r.headers["x-mock-capture-reason"]
    assert "another mock version" in foreign_r.headers["x-mock-capture-reason"]
    assert "unknown, revoked or expired" in malformed_r.headers["x-mock-capture-reason"]
    assert world.calls == []


def test_a_malformed_token_is_refused_without_a_lookup() -> None:
    world = CaptureWorld()
    pool = CountingPool(responder=world.respond)
    assert asyncio.run(resolve_capture_link(pool, "mcap_short")) is None  # type: ignore[arg-type]
    assert pool.statements == []


def test_a_revoked_link_stops_once_its_cache_entry_expires() -> None:
    world = CaptureWorld()
    token, _ = _link(world)
    pool = CountingPool(responder=world.respond)
    configure_capture_link_cache(0.0)  # no caching: every lookup reads the table

    async def scenario() -> tuple[Any, Any]:
        live = await resolve_capture_link(pool, token)  # type: ignore[arg-type]
        world.links.clear()  # revoked
        gone = await resolve_capture_link(pool, token)  # type: ignore[arg-type]
        return live, gone

    live, gone = asyncio.run(scenario())
    configure_capture_link_cache(30.0)
    assert live is not None and live.tag == ConsumerTag("Orders UI", "3.4.0")
    assert gone is None


# ---------------------------------------------------------------------------------------------
# Allocation: what only the writer can know
# ---------------------------------------------------------------------------------------------


def _pending(consumer: str = "orders-ui", version: str = "3.4.0", *, version_id: UUID = VERSION_ID) -> PendingCall:
    return PendingCall(
        version_id=version_id,
        project_slug="petstore",
        version_label="1.0.0",
        tag=ConsumerTag(consumer, version),
        via="header",
        link_id=None,
        api_key_id=None,
        captured_at=NOW,
        method="GET",
        path="/pets",
        query=[],
        request_headers={},
        request_body=None,
        request_media_type=None,
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=b"[]",
        response_media_type="application/json",
        path_template="/pets",
        operation_key="GET /pets",
        origin="spec",
        origin_detail=None,
        scenario=None,
        mock_session=None,
    )


def _record() -> Any:
    from app.pact_capture import RedactedCall

    return RedactedCall(request={"method": "GET"}, response={"status": 200}, redactions=[])


def test_allocation_fills_a_session_to_its_cap_and_counts_the_rest() -> None:
    sid = uuid4()
    call = _pending()
    sessions = {
        call.session_key: SessionState(id=sid, tenant_id=TENANT_ID, call_count=MAX_CALLS_PER_SESSION - 2, refused={})
    }
    result = allocate_calls([(call, _record())] * 5, sessions=sessions, tenant_of={VERSION_ID: TENANT_ID})
    assert len(result.stored) == 2
    assert result.session_refusals == {sid: Counter({"session-full": 3})}
    assert result.tenant_refusals == {}


def test_allocation_counts_residue_on_the_session_and_unopened_sessions_on_the_tenant() -> None:
    sid = uuid4()
    opened, unopened = _pending("orders-ui"), _pending("billing-ui")
    sessions = {opened.session_key: SessionState(id=sid, tenant_id=TENANT_ID, call_count=0, refused={})}
    residue = CaptureHeaderProblem("credential-residual", "…")
    result = allocate_calls(
        [
            (opened, residue),
            (opened, _record()),
            (unopened, _record()),
            (_pending(version_id=OTHER_VERSION), _record()),
        ],
        sessions=sessions,
        tenant_of={VERSION_ID: TENANT_ID},
    )
    assert [stored[1] for stored in result.stored] == [opened]
    assert result.session_refusals == {sid: Counter({"credential-residual": 1})}
    assert result.tenant_refusals == {TENANT_ID: Counter({"too-many-sessions": 1})}


# ---------------------------------------------------------------------------------------------
# The recorder against the counting pool
# ---------------------------------------------------------------------------------------------


def _recorder(world: CaptureWorld, **kwargs: Any) -> tuple[ConsumerCaptureRecorder, CountingPool]:
    pool = CountingPool(responder=world.respond)
    return ConsumerCaptureRecorder(pool, flush_interval_seconds=60, **kwargs), pool  # type: ignore[arg-type]


def test_a_flush_opens_one_session_per_consumer_and_version() -> None:
    world = CaptureWorld()
    recorder, pool = _recorder(world)

    async def scenario() -> None:
        for call in (_pending("a"), _pending("a"), _pending("a", "2.0"), _pending("b")):
            assert recorder.submit(call)
        await recorder.flush()

    asyncio.run(scenario())
    assert pool.transactions == 1
    assert sorted((key[1], key[2], row["call_count"]) for key, row in world.sessions.items()) == [
        ("a", "2.0", 1),
        ("a", "3.4.0", 2),
        ("b", "3.4.0", 1),
    ]
    assert recorder.pending() == 0


def test_a_tenant_at_its_session_cap_has_the_calls_counted_on_it() -> None:
    world = CaptureWorld()
    world.live_sessions = MAX_LIVE_SESSIONS_PER_TENANT
    recorder, _ = _recorder(world)

    async def scenario() -> None:
        recorder.submit(_pending())
        recorder.submit(_pending())
        await recorder.flush()

    asyncio.run(scenario())
    assert world.sessions == {} and world.calls == []
    assert world.tenant_refusals == [(TENANT_ID, 2, "too-many-sessions")]


def test_calls_of_a_deleted_version_are_not_written() -> None:
    world = CaptureWorld()
    recorder, pool = _recorder(world)

    async def scenario() -> None:
        recorder.submit(_pending(version_id=OTHER_VERSION))
        await recorder.flush()

    asyncio.run(scenario())
    assert world.calls == [] and world.sessions == {}
    assert not any("INSERT" in sql for sql, _ in pool.statements)


def test_a_failed_flush_is_retried_then_dropped() -> None:
    world = CaptureWorld()
    world.fail_inserts = MAX_FLUSH_ATTEMPTS
    recorder, _ = _recorder(world)

    async def scenario() -> list[int]:
        recorder.submit(_pending())
        pending = []
        for _ in range(MAX_FLUSH_ATTEMPTS):
            await recorder.flush()
            pending.append(recorder.pending())
        return pending

    assert asyncio.run(scenario()) == [1, 1, 0]
    assert world.calls == []


def test_a_retried_flush_writes_the_calls_once_the_database_is_back() -> None:
    world = CaptureWorld()
    world.fail_inserts = 1
    recorder, _ = _recorder(world)

    async def scenario() -> None:
        recorder.submit(_pending())
        await recorder.flush()
        await recorder.flush()

    asyncio.run(scenario())
    assert len(world.calls) == 1


def test_the_session_keeps_its_refusals_by_reason() -> None:
    world = CaptureWorld()
    call = _pending()
    world.sessions[call.session_key] = {
        "id": uuid4(),
        "tenant_id": TENANT_ID,
        "version_id": VERSION_ID,
        "consumer": "orders-ui",
        "consumer_version": "3.4.0",
        "call_count": MAX_CALLS_PER_SESSION,
        "refused": {"session-full": 4},
    }
    recorder, _ = _recorder(world)

    async def scenario() -> None:
        recorder.submit(call)
        await recorder.flush()

    asyncio.run(scenario())
    assert world.calls == []
    assert world.sessions[call.session_key]["refused"] == {"session-full": 5}


# ---------------------------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------------------------


class _SweepConn:
    def __init__(self, counts: list[int], seen: list[str]) -> None:
        self._counts = counts
        self._seen = seen

    async def execute(self, sql: str, params: Any = None) -> Any:
        self._seen.append(sql)

        class _Cur:
            rowcount = self._counts.pop(0)

        return _Cur()


class _SweepPool:
    def __init__(self, counts: list[int]) -> None:
        self.counts = counts
        self.seen: list[str] = []

    def connection(self) -> Any:
        pool = self

        class _Ctx:
            async def __aenter__(self) -> _SweepConn:
                return _SweepConn(pool.counts, pool.seen)

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _Ctx()


def test_the_sweeper_deletes_calls_then_sessions_in_batches() -> None:
    pool = _SweepPool([10, 10, 3, 2])
    deleted = asyncio.run(sweep_expired_captures(pool, batch_size=10))  # type: ignore[arg-type]
    assert deleted == 25
    assert [("call" in sql, "ANY(ARRAY(" in sql) for sql in pool.seen] == [
        (True, True),
        (True, True),
        (True, True),
        (False, True),
    ]


def test_the_module_never_reads_the_database_on_submit() -> None:
    world = CaptureWorld()
    recorder, pool = _recorder(world)
    for _ in range(100):
        assert recorder.submit(_pending())
    assert pool.checkouts == 0 and pool.statements == []
    assert capture_module.REFUSAL_REASONS["queue-full"]
