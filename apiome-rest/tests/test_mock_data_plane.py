"""The mock data plane's hot path (DBP-1.13, #7196): one narrow statement, no write.

The statement budget is checked here against a scripted connection, so it runs in every test job:
a warm request to ``/mock/{id}/…`` runs exactly one statement, that statement does not select the
frozen ``spec`` document, and nothing is written until the flush.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import mock_data_plane, mock_routes
from app.main import app
from app.mock_data_plane import ActivityBuffer, SpecCache, flush_activity
from tests.scripted_connection import ScriptedConnection, database_with

MOCK_ID = "11111111-2222-4333-8444-555555555555"
OTHER_ID = "99999999-2222-4333-8444-555555555555"
SPEC = {"openapi": "3.1.0", "info": {"title": "Pets", "version": "1"}, "paths": {}}
T0 = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

client = TestClient(app)


def _serving_row(**overrides: Any) -> Dict[str, Any]:
    row = {
        "id": MOCK_ID,
        "tenant_id": "t1",
        "version_id": "v1",
        "tenant_slug": "acme",
        "project_slug": "petstore",
        "version_slug": "1.0.0",
        "settings": {},
        "rate_limit_per_minute": 1000,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "config": {"seed": 7},
    }
    row.update(overrides)
    return row


@pytest.fixture
def plane(monkeypatch):
    """The data plane on fresh buffers, a stubbed engine and a scripted database."""
    cache, buffer = SpecCache(), ActivityBuffer()
    monkeypatch.setattr(mock_routes, "spec_cache", cache)
    monkeypatch.setattr(mock_routes, "activity_buffer", buffer)
    monkeypatch.setattr(mock_routes, "sandbox_is_configured", lambda: True)
    monkeypatch.setattr(mock_routes.settings, "mock_server_enabled", True)
    calls: List[Dict[str, Any]] = []

    async def _serve(**kwargs: Any) -> Dict[str, Any]:
        calls.append(kwargs)
        return {
            "status": 200,
            "headers": {},
            "mediaType": "application/json",
            "body": {"ok": True},
            "bodyEncoding": "json",
            "operation": "GET /pets",
            "schemaValid": True,
        }

    monkeypatch.setattr(mock_routes, "request_sandbox_serve", _serve)

    def use(responses):
        conn = ScriptedConnection(responses)
        monkeypatch.setattr(mock_routes, "db", database_with(monkeypatch, conn))
        return conn

    return type("Plane", (), {"cache": cache, "buffer": buffer, "calls": calls, "use": staticmethod(use)})


# --- the budget ------------------------------------------------------------------------------


def test_a_cold_request_reads_the_serving_row_then_the_spec_once(plane):
    conn = plane.use([[_serving_row()], [{"spec": SPEC}]])
    assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 200
    assert len(conn.statements) == 2
    assert "SELECT spec FROM apiome.mock_instances" in conn.statements[1][0]
    assert plane.calls[0]["bundle"]


def test_a_warm_request_runs_one_narrow_statement_and_writes_nothing(plane):
    plane.cache.get(MOCK_ID, lambda _id: SPEC)
    conn = plane.use([[_serving_row()]])

    assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 200

    assert len(conn.statements) == 1, conn.statements
    sql, params = conn.statements[0]
    assert sql.startswith("SELECT id, tenant_id")
    select_list = sql.split(" FROM ")[0]
    assert "spec" not in select_list and "request_count" not in select_list
    assert params == (MOCK_ID,)
    assert not any(word in sql.upper() for word in ("UPDATE", "INSERT", "DELETE"))
    assert conn.commits == 0 or "UPDATE" not in sql  # nothing to commit but the read itself


def test_the_request_is_counted_in_memory_and_written_by_the_flush(plane):
    plane.cache.get(MOCK_ID, lambda _id: SPEC)
    plane.use([[_serving_row()], [_serving_row()], [_serving_row()]])
    for _ in range(3):
        assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 200

    batch = plane.buffer.drain()
    assert [(mock_id, count) for mock_id, count, _ in batch] == [(MOCK_ID, 3)]


def test_the_stored_seed_still_reaches_the_engine(plane):
    plane.cache.get(MOCK_ID, lambda _id: SPEC)
    plane.use([[_serving_row()]])
    client.get(f"/v1/mock/{MOCK_ID}/pets")
    assert plane.calls[0]["request"]["seed"] == 7


def test_an_unknown_instance_is_a_404_after_one_statement(plane):
    conn = plane.use([[]])
    assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 404
    assert len(conn.statements) == 1
    assert len(plane.buffer) == 0


def test_an_expired_instance_is_a_410_and_its_spec_is_dropped(plane):
    plane.cache.get(MOCK_ID, lambda _id: SPEC)
    plane.use([[_serving_row(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))]])
    assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 410
    assert len(plane.cache) == 0 and len(plane.buffer) == 0


def test_an_unfolded_legacy_instance_is_read_whole_once(plane):
    legacy = _serving_row(settings=None)
    full = {**legacy, "spec": SPEC, "config": {"seed": 0}, "migration_notes": []}
    conn = plane.use([[legacy], [full], []])
    assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 200
    assert "spec" in conn.statements[1][0].split(" FROM ")[0]


def test_an_instance_deleted_between_the_row_and_the_spec_is_a_404(plane):
    plane.use([[_serving_row()], []])
    assert client.get(f"/v1/mock/{MOCK_ID}/pets").status_code == 404


# --- the spec cache --------------------------------------------------------------------------


def test_a_spec_is_loaded_once_until_it_ages_out():
    now = [0.0]
    loads: List[str] = []

    def load(mock_id: str):
        loads.append(mock_id)
        return SPEC

    cache = SpecCache(ttl_seconds=10, clock=lambda: now[0])
    assert cache.get(MOCK_ID, load) is SPEC
    now[0] = 9.9
    assert cache.get(MOCK_ID, load) is SPEC
    assert loads == [MOCK_ID]
    now[0] = 10.0
    cache.get(MOCK_ID, load)
    assert loads == [MOCK_ID, MOCK_ID]


def test_a_missing_spec_is_not_cached():
    cache = SpecCache()
    assert cache.get(MOCK_ID, lambda _id: None) is None
    assert len(cache) == 0
    assert cache.get(MOCK_ID, lambda _id: SPEC) is SPEC


def test_the_cache_keeps_only_the_most_recently_used_specs():
    cache = SpecCache(max_entries=2)
    cache.get("a", lambda _id: {"n": "a"})
    cache.get("b", lambda _id: {"n": "b"})
    cache.get("a", lambda _id: pytest.fail("a should be cached"))
    cache.get("c", lambda _id: {"n": "c"})
    assert len(cache) == 2
    assert cache.get("b", lambda _id: {"n": "b2"}) == {"n": "b2"}  # b was the one dropped


def test_forget_and_clear_drop_entries():
    cache = SpecCache()
    cache.get("a", lambda _id: SPEC)
    cache.get("b", lambda _id: SPEC)
    cache.forget("a")
    assert len(cache) == 1
    cache.clear()
    assert len(cache) == 0


# --- the activity buffer ---------------------------------------------------------------------


def test_requests_add_up_per_instance_with_the_latest_time():
    buffer = ActivityBuffer()
    buffer.record(MOCK_ID, at=T0)
    buffer.record(MOCK_ID, at=T0 + timedelta(seconds=2))
    buffer.record(MOCK_ID, at=T0 + timedelta(seconds=1))
    buffer.record(OTHER_ID, at=T0)
    assert sorted(buffer.drain()) == [
        (MOCK_ID, 3, T0 + timedelta(seconds=2)),
        (OTHER_ID, 1, T0),
    ]
    assert buffer.drain() == [] and len(buffer) == 0


def test_the_buffer_is_bounded_between_flushes():
    buffer = ActivityBuffer(max_instances=1)
    buffer.record(MOCK_ID, at=T0)
    buffer.record(OTHER_ID, at=T0)
    buffer.record(MOCK_ID, at=T0)
    assert buffer.drain() == [(MOCK_ID, 2, T0)]


class _ActivityDb:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.batches: List[Any] = []

    def add_mock_instance_activity(self, batch):
        if self.fail:
            raise RuntimeError("database is away")
        self.batches.append(list(batch))
        return len(batch)


def test_a_flush_writes_everything_in_one_call_and_empties_the_buffer():
    buffer, database = ActivityBuffer(), _ActivityDb()
    buffer.record(MOCK_ID, at=T0)
    buffer.record(OTHER_ID, at=T0)
    assert flush_activity(database, buffer) == 2
    assert len(database.batches) == 1 and len(buffer) == 0
    assert flush_activity(database, buffer) == 0
    assert len(database.batches) == 1  # an idle flush does not touch the database


def test_a_failed_flush_keeps_the_counts_for_the_next_one():
    buffer = ActivityBuffer()
    buffer.record(MOCK_ID, at=T0)
    assert flush_activity(_ActivityDb(fail=True), buffer) == 0
    buffer.record(MOCK_ID, at=T0 + timedelta(seconds=5))
    database = _ActivityDb()
    assert flush_activity(database, buffer) == 1
    assert database.batches == [[(MOCK_ID, 2, T0 + timedelta(seconds=5))]]


def test_the_default_flush_uses_the_process_wide_buffer():
    database = _ActivityDb()
    with patch.object(mock_data_plane, "activity_buffer", ActivityBuffer()) as buffer:
        buffer.record(MOCK_ID, at=T0)
        assert flush_activity(database) == 1


# --- the statements --------------------------------------------------------------------------


def test_the_batched_counter_is_one_update_over_unnested_arrays(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)
    database.add_mock_instance_activity([(MOCK_ID, 3, T0), (OTHER_ID, 1, T0)])
    assert len(conn.statements) == 1
    sql, params = conn.statements[0]
    assert sql.startswith("UPDATE apiome.mock_instances m")
    assert "unnest(%s::uuid[], %s::bigint[], %s::timestamptz[])" in sql
    assert params == ([MOCK_ID, OTHER_ID], [3, 1], [T0, T0])


def test_an_empty_batch_runs_nothing(monkeypatch):
    conn = ScriptedConnection([])
    assert database_with(monkeypatch, conn).add_mock_instance_activity([]) == 0
    assert conn.statements == []
