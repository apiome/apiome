"""Unit tests for the batched usage ingest writes — DBP-1.8 (#7191). No database.

A recording cursor stands in for psycopg2, so these pin the shape of what is sent: one statement
per table whatever the number of grains, rows sorted by key, histograms as array literals, and
nothing sent for an empty table. ``test_usage_ingest_batching_db`` proves the same against Postgres.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Tuple

from app import consumer_binding_store, usage_ingest_store
from app.usage_ingest import BatchPlan, FieldGroup, HourlyCounter, SourceConfig, UnattributedCounter, UnmatchedCounter

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
SOURCE = SourceConfig(
    id="00000000-0000-4000-8000-000000000003",
    tenant_id="00000000-0000-4000-8000-000000000001",
    project_id="00000000-0000-4000-8000-000000000002",
    kind="otlp",
    environment="production",
    sampling_rate=1.0,
    field_capture=True,
    body_sample_rate=0.0,
    body_sample_until=None,
    enabled=True,
)


class RecordingCursor:
    """Records every ``execute``; ``fetchone`` / ``fetchall`` answer from ``rows``."""

    def __init__(self, rows: Any = None) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []
        self.rows = rows

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((" ".join(sql.split()), tuple(params or ())))

    def fetchone(self) -> Any:
        return self.rows

    def fetchall(self) -> Any:
        return self.rows or []


def _hourly(plan: BatchPlan, operation: str, status: int, binding: Any = None, hour: datetime = NOW) -> None:
    counter = HourlyCounter()
    counter.events = 1
    counter.buckets[0] = 1
    plan.hourly[("production", hour, None, operation, status, binding)] = counter


def _plan_with(grains: int) -> BatchPlan:
    plan = BatchPlan(received=grains)
    for index in range(grains):
        _hourly(plan, f"/paths/~1r{index}/get", 200)
    return plan


def test_hourly_is_one_statement_at_any_size() -> None:
    for grains in (1, 10, 5_000):
        cursor = RecordingCursor()
        usage_ingest_store._write_hourly(cursor, SOURCE, _plan_with(grains))
        assert len(cursor.calls) == 1
        sql, params = cursor.calls[0]
        assert sql.startswith("INSERT INTO apiome.usage_hourly") and "unnest(" in sql
        # Three source ids, then one array per column, each as long as the batch.
        assert params[:3] == (SOURCE.tenant_id, SOURCE.project_id, SOURCE.id)
        assert all(len(column) == grains for column in params[3:])


def test_hourly_rows_are_sorted_and_histograms_travel_as_literals() -> None:
    plan = BatchPlan()
    _hourly(plan, "/paths/~1b/get", 500)
    _hourly(plan, "/paths/~1a/get", 200, binding="00000000-0000-4000-8000-00000000000b")
    _hourly(plan, "/paths/~1a/get", 200)
    cursor = RecordingCursor()
    usage_ingest_store._write_hourly(cursor, SOURCE, plan)
    _sql, params = cursor.calls[0]
    operations, bindings, buckets = params[3 + 3], params[3 + 5], params[3 + 7]
    assert operations == ["/paths/~1a/get", "/paths/~1a/get", "/paths/~1b/get"]
    # None sorts before a binding id within the same grain.
    assert bindings == [None, "00000000-0000-4000-8000-00000000000b", None]
    assert all(literal.startswith("{1,0") and literal.endswith("}") for literal in buckets)


def test_empty_tables_send_nothing() -> None:
    cursor = RecordingCursor()
    plan = BatchPlan()
    usage_ingest_store._write_plan(cursor, SOURCE, plan)
    assert cursor.calls == []


def test_unattributed_skips_rows_that_scale_to_zero() -> None:
    plan = BatchPlan()
    plan.unattributed_clients[(NOW.date(), "user_agent", "curl")] = UnattributedCounter(NOW, NOW, 0)
    cursor = RecordingCursor()
    usage_ingest_store._write_unattributed(cursor, SOURCE, plan)
    assert cursor.calls == []


def test_fields_update_every_group_then_upsert_every_pointer() -> None:
    plan = BatchPlan()
    for status in (404, 200):
        group = FieldGroup()
        group.inspected = 3
        group.pointers = {"/name": 1, "/id": 3}
        plan.field_groups[("production", NOW.date(), "/paths/~1a/get", "response", status)] = group
    cursor = RecordingCursor()
    usage_ingest_store._write_fields(cursor, SOURCE, plan)
    (update_sql, update), (insert_sql, insert) = cursor.calls
    assert update_sql.startswith("UPDATE apiome.usage_field_daily") and "NOT (g.pointers ? f.pointer)" in update_sql
    assert update[4] == [200, 404]  # status column, sorted
    assert [json.loads(pointers) for pointers in update[6]] == [["/id", "/name"], ["/id", "/name"]]
    assert insert_sql.startswith("INSERT INTO apiome.usage_field_daily")
    assert insert[3 + 5] == ["/id", "/name", "/id", "/name"]  # pointer column
    assert insert[3 + 6] == [3, 1, 3, 1] and insert[3 + 7] == [3, 3, 3, 3]


def test_unmatched_and_samples_are_one_statement_each() -> None:
    plan = BatchPlan()
    for template in ("/b", "/a"):
        counter = UnmatchedCounter(NOW, NOW)
        counter.by_class[1] = 2
        plan.unmatched_rows[("production", NOW.date(), "GET", template)] = counter
    plan.samples = [("production", NOW, None, 200, {"request": {}}), ("production", NOW, None, 500, {})]
    cursor = RecordingCursor()
    usage_ingest_store._write_unmatched(cursor, SOURCE, plan)
    usage_ingest_store._write_samples(cursor, SOURCE, plan)
    (_unmatched_sql, unmatched), (samples_sql, samples) = cursor.calls
    assert unmatched[3 + 3] == ["/a", "/b"] and unmatched[3 + 4] == [2, 2]
    assert "usage_sample" in samples_sql and samples[3 + 4] == ['{"request": {}}', "{}"]


def test_stamp_matches_is_one_statement_per_table_in_id_order() -> None:
    later = NOW + timedelta(minutes=5)
    cursor = RecordingCursor()
    consumer_binding_store.stamp_matches(
        cursor,
        {"b2": NOW, "b1": later, "b3": NOW},
        {"b1": "c1", "b2": "c1", "b3": "c2"},
    )
    (binding_sql, bindings), (consumer_sql, consumers) = cursor.calls
    assert binding_sql.startswith("UPDATE apiome.usage_consumer_binding")
    assert bindings == (["b1", "b2", "b3"], [later, NOW, NOW])
    assert consumer_sql.startswith("UPDATE apiome.consumer")
    # A consumer is stamped with the newest time of any of its bindings.
    assert consumers == (["c1", "c2"], [later, NOW])


def test_stamp_matches_sends_nothing_without_matches() -> None:
    cursor = RecordingCursor()
    consumer_binding_store.stamp_matches(cursor, {}, {})
    assert cursor.calls == []


def test_plan_days_cover_every_counter_table() -> None:
    plan = BatchPlan()
    _hourly(plan, "/paths/~1a/get", 200, hour=datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc))
    plan.unmatched_rows[("production", date(2026, 11, 19), "GET", "/x")] = UnmatchedCounter(NOW, NOW)
    plan.field_groups[("production", date(2026, 11, 21), "/paths/~1a/get", "response", 200)] = FieldGroup()
    plan.unattributed_clients[(date(2026, 11, 22), "user_agent", "curl")] = UnattributedCounter(NOW, NOW, 1)
    assert usage_ingest_store._plan_days(plan) == [date(2026, 11, day) for day in (19, 20, 21, 22)]


def test_admission_admits_up_to_the_cap_and_always_when_unlimited() -> None:
    admission = usage_ingest_store._Admission(cap=10, used=7, finalized=frozenset())
    assert admission.admits(3) and not admission.admits(4)
    assert usage_ingest_store._Admission(cap=0, used=10**9, finalized=frozenset()).admits(1)
    assert usage_ingest_store._Admission(cap=-1, used=10**9, finalized=frozenset()).admits(1)


def test_admission_reads_the_cap_the_counter_and_finalized_days_in_one_statement() -> None:
    cursor = RecordingCursor({"cap": None, "used": 5, "finalized": [date(2026, 11, 19)]})
    admission = usage_ingest_store._admission(cursor, SOURCE.tenant_id, NOW.date(), [date(2026, 11, 19)])
    assert len(cursor.calls) == 1 and "usage_tenant_day" in cursor.calls[0][0]
    assert admission == usage_ingest_store._Admission(
        cap=usage_ingest_store.DEFAULT_EVENTS_PER_DAY, used=5, finalized=frozenset({date(2026, 11, 19)})
    )


def test_key_order_puts_none_first_without_comparing_it() -> None:
    keys = [("b", None), ("a", "x"), ("a", None)]
    assert sorted(keys, key=usage_ingest_store._key_order) == [("a", None), ("a", "x"), ("b", None)]
