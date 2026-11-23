"""Usage ingest: batched upserts and a shorter tenant lock — DBP-1.8 (#7191), against Postgres.

What only the real schema can prove:

* an ingest batch runs a **fixed number of statements** — the same at 10 grains as at 5,000;
* the batched upserts add up exactly like the per-row ones did (histograms, field denominators,
  the ledger), and the per-tenant-day counter (``usage_tenant_day``, V410) always equals the
  day's ledger;
* a day finalized, or a binding deleted, **between planning and the lock** is seen by the write
  phase, which plans again instead of failing or attributing to a dead binding;
* two concurrent batches for one tenant overlap except while they write — the second plans while
  the first holds the lock — and their totals equal serial ingestion.

Most tests run inside the always-rolled-back ``tx`` transaction of ``test_usage_index_db``; the
concurrency test needs two real connections, so it commits into two throwaway tenants and deletes
them afterwards. Skipped when no database is reachable or V410 is not applied.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import usage_ingest_store
from app.config import settings
from app.database import Database
from app.statement_stats import CountingDictCursor, capture
from app.usage_ingest_store import ingest_batch
from tests import test_usage_index_db as index_db
from tests.test_usage_ingest_db import NOW, PUBLISHED_DOC, _event, _ingest, _rows

#: The always-rolled-back transaction fixture, shared with the RDG-1.1 schema tests.
tx = index_db.tx

pytestmark = pytest.mark.requires_db

#: Statuses that spread a batch over many ``usage_hourly`` grains (one grain per status and hour).
_STATUSES = list(range(200, 600))


def _publish(cursor: Any, seed: Dict[str, str]) -> str:
    """Publish one revision of :data:`PUBLISHED_DOC` in the seed's project; return its id."""
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
           VALUES (%s, %s, '1.0.0', true, %s) RETURNING id::text AS id""",
        (seed["project"], user, NOW - timedelta(days=1)),
    )
    return cursor.fetchone()["id"]


def _stub_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every revision renders as :data:`PUBLISHED_DOC`; the revision index cache starts empty."""
    monkeypatch.setattr("app.blast_radius.version_document", lambda _db, _tenant_id, _version: PUBLISHED_DOC)
    usage_ingest_store._index_cache.clear()


@pytest.fixture
def seeded(tx: Tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Tuple[Any, Any, Dict[str, str]]]:
    """A tenant with one published revision and field capture on; skipped before V410."""
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.usage_tenant_day') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V410 not applied")
    seed = index_db._tenant(cursor)
    seed["published"] = _publish(cursor, seed)
    cursor.execute("UPDATE apiome.usage_source SET field_capture = true WHERE id = %s", (seed["source"],))
    _stub_documents(monkeypatch)
    yield db, cursor, seed


def _grains(count: int) -> List[Dict[str, Any]]:
    """Matched events spread over exactly ``count`` hourly grains, plus one unmatched event.

    Every event also reports fields, so each batch writes every counter table.
    """
    events = []
    for index in range(count):
        hour, status = divmod(index, len(_STATUSES))
        observed = NOW - timedelta(hours=hour, minutes=1)
        events.append(
            _event(
                f"/pets/{index}",
                status=_STATUSES[status],
                observed_at=observed.isoformat(),
                fields={"response": ["/id"] if index % 2 else ["/id", "/name"]},
            )
        )
    events.append(_event("/stores/1/shelves"))
    return events


def _counted_ingest(db: Any, seed: Dict[str, str], events: List[Dict[str, Any]]) -> Tuple[Any, List[str]]:
    """Ingest ``events`` and return the outcome and every SQL statement it ran."""
    raw = db.connection._conn
    previous = raw.cursor_factory
    raw.cursor_factory = CountingDictCursor
    try:
        with capture() as stats:
            outcome = _ingest(db, seed, events)
    finally:
        raw.cursor_factory = previous
    return outcome, list(stats.statements)


# ---------------------------------------------------------------------------------------------
# A fixed number of statements
# ---------------------------------------------------------------------------------------------


def test_a_batch_runs_the_same_statements_at_10_and_5000_grains(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    small, small_sql = _counted_ingest(db, seed, _grains(10))
    assert len(_rows(cursor, "usage_hourly", seed["tenant"])) == 10

    usage_ingest_store._index_cache.clear()
    large, large_sql = _counted_ingest(db, seed, _grains(5_000))
    assert len(_rows(cursor, "usage_hourly", seed["tenant"])) == 5_000

    assert (small.plan.accepted, large.plan.accepted) == (10, 5_000)
    assert len(small_sql) == len(large_sql), "\n".join(large_sql)
    # Source, revisions, finalized days, bindings — then lock, admission, binding re-read, hourly,
    # unmatched, fields (2) and the ledger statement.
    assert len(large_sql) <= 13, "\n".join(large_sql)
    writes = [sql for sql in large_sql if "usage_hourly" in sql and sql.lstrip().upper().startswith("INSERT")]
    assert len(writes) == 1


def test_the_ledger_and_the_day_counter_are_one_statement(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, _cursor, seed = seeded
    _outcome, statements = _counted_ingest(db, seed, _grains(3))
    assert sum("usage_ingest_batch" in sql for sql in statements) == 1
    # No statement of its own adds to the counter or stamps the source.
    assert not any(
        sql.lstrip().startswith(("INSERT INTO apiome.usage_tenant_day", "UPDATE apiome.usage_source"))
        for sql in statements
    )
    # The old per-batch sum over the ledger is gone.
    assert not any("sum(received - rejected)" in sql for sql in statements)


# ---------------------------------------------------------------------------------------------
# The batched upserts add up
# ---------------------------------------------------------------------------------------------


def test_batched_upserts_add_into_existing_rows(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    events = _grains(600)
    first = _ingest(db, seed, events)
    second = _ingest(db, seed, events)
    hourly = _rows(cursor, "usage_hourly", seed["tenant"])
    assert len(hourly) == 600
    assert all(row["calls"] == 2 and sum(row["latency_buckets"]) == 2 for row in hourly)
    assert sum(row["calls"] for row in hourly) == first.plan.accepted + second.plan.accepted

    (unmatched,) = _rows(cursor, "usage_unmatched_daily", seed["tenant"])
    assert unmatched["calls"] == 2

    by_grain: Dict[Tuple[Any, ...], Dict[str, Tuple[int, int]]] = {}
    for row in _rows(cursor, "usage_field_daily", seed["tenant"]):
        grain = (row["day"], row["operation_key"], row["direction"], row["status_code"])
        by_grain.setdefault(grain, {})[row["pointer"]] = (row["calls_with_field"], row["calls_sampled"])
    # Every event reports /id and every even-indexed one /name, in both batches.
    assert sum(pointers["/id"][0] for pointers in by_grain.values()) == 2 * 600
    assert sum(pointers["/name"][0] for pointers in by_grain.values() if "/name" in pointers) == 2 * 300
    for pointers in by_grain.values():
        with_id, sampled = pointers["/id"]
        # The denominator counts every inspected call of the grain, whichever pointers it carried.
        assert with_id == sampled
        if "/name" in pointers:
            assert pointers["/name"][1] == sampled


def test_the_day_counter_matches_the_ledger_and_keeps_two_days(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    cursor.execute(
        "INSERT INTO apiome.usage_tenant_day (tenant_id, day, events_used) VALUES (%s, %s, 7), (%s, %s, 9)",
        (seed["tenant"], NOW.date() - timedelta(days=1), seed["tenant"], NOW.date() - timedelta(days=5)),
    )
    _ingest(db, seed, [_event("/pets/1"), _event("/pets/2"), "not an event"])
    _ingest(db, seed, [_event("/pets/3")])

    cursor.execute(
        "SELECT day, events_used FROM apiome.usage_tenant_day WHERE tenant_id = %s ORDER BY day", (seed["tenant"],)
    )
    assert [(row["day"], row["events_used"]) for row in cursor.fetchall()] == [
        (NOW.date() - timedelta(days=1), 7),
        (NOW.date(), 3),
    ]
    ledger = _rows(cursor, "usage_ingest_batch", seed["tenant"])
    assert sum(row["received"] - row["rejected"] for row in ledger) == 3


def test_deleting_a_source_does_not_give_the_days_quota_back(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    cursor.execute(
        """INSERT INTO apiome.licenses (name, license_type, seats)
           VALUES (%s, 'free', '{"usage_events_per_day": 2}'::jsonb) RETURNING id""",
        (f"usage cap {uuid.uuid4().hex[:8]}",),
    )
    cursor.execute(
        "INSERT INTO apiome.tenant_licenses (tenant_id, license_id) VALUES (%s, %s)",
        (seed["tenant"], cursor.fetchone()["id"]),
    )
    _ingest(db, seed, [_event("/pets/1"), _event("/pets/2")])
    cursor.execute(
        """INSERT INTO apiome.usage_source (tenant_id, project_id, kind)
           SELECT tenant_id, project_id, kind FROM apiome.usage_source WHERE id = %s
           RETURNING id::text AS id""",
        (seed["source"],),
    )
    second = cursor.fetchone()["id"]
    cursor.execute("DELETE FROM apiome.usage_source WHERE id = %s", (seed["source"],))
    with pytest.raises(usage_ingest_store.UsageIngestError) as caught:
        _ingest(db, {**seed, "source": second}, [_event("/pets/3")])
    assert caught.value.status == 429


# ---------------------------------------------------------------------------------------------
# Planning outside the lock, checked inside it
# ---------------------------------------------------------------------------------------------


def _after_first_plan(monkeypatch: pytest.MonkeyPatch, action: Any) -> List[int]:
    """Run ``action`` right after the first ``plan_batch`` call; return a call counter."""
    real = usage_ingest_store.plan_batch
    calls: List[int] = []

    def planned(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            action()
        return result

    monkeypatch.setattr(usage_ingest_store, "plan_batch", planned)
    return calls


def test_a_day_finalized_after_planning_is_rejected_not_failed(
    seeded: Tuple[Any, Any, Dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, cursor, seed = seeded
    old = NOW - timedelta(days=3)
    calls = _after_first_plan(
        monkeypatch,
        lambda: cursor.execute(
            "INSERT INTO apiome.usage_rollup_days (day, rolled_up_at, finalized_at) VALUES (%s, %s, %s)",
            (old.date(), NOW, NOW),
        ),
    )
    outcome = _ingest(db, seed, [_event("/pets/1", observed_at=old.isoformat()), _event("/pets/2")])
    assert len(calls) == 2
    assert outcome.plan.rejections == [(0, "day-finalized")] and outcome.plan.accepted == 1
    hours = {row["hour"].date() for row in _rows(cursor, "usage_hourly", seed["tenant"])}
    assert hours == {NOW.date()}


def _user_agent_binding(cursor: Any, seed: Dict[str, str]) -> Tuple[str, str]:
    """A consumer with one ``user_agent`` binding ``billing/*``; return (consumer, binding)."""
    cursor.execute(
        """INSERT INTO apiome.consumer (tenant_id, project_id, slug, name)
           VALUES (%s, %s, 'billing', 'Billing') RETURNING id::text AS id""",
        (seed["tenant"], seed["project"]),
    )
    consumer = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.usage_consumer_binding (tenant_id, project_id, consumer_id, kind, name)
           VALUES (%s, %s, %s, 'user_agent', 'billing/*') RETURNING id::text AS id""",
        (seed["tenant"], seed["project"], consumer),
    )
    return consumer, cursor.fetchone()["id"]


def test_a_binding_deleted_after_planning_attributes_nothing(
    seeded: Tuple[Any, Any, Dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, cursor, seed = seeded
    _consumer, binding = _user_agent_binding(cursor, seed)
    calls = _after_first_plan(
        monkeypatch,
        lambda: cursor.execute(
            "UPDATE apiome.usage_consumer_binding SET deleted_at = %s WHERE id = %s", (NOW, binding)
        ),
    )
    outcome = _ingest(db, seed, [_event("/pets/1", user_agent="billing/1.0")])
    assert len(calls) == 2 and outcome.plan.attributed == 0
    (hourly,) = _rows(cursor, "usage_hourly", seed["tenant"])
    assert hourly["consumer_binding_id"] is None
    cursor.execute("SELECT last_matched_at FROM apiome.usage_consumer_binding WHERE id = %s", (binding,))
    assert cursor.fetchone()["last_matched_at"] is None


def test_unchanged_inputs_plan_once_and_stamp_in_one_statement(
    seeded: Tuple[Any, Any, Dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, cursor, seed = seeded
    consumer, binding = _user_agent_binding(cursor, seed)
    calls = _after_first_plan(monkeypatch, lambda: None)
    later = NOW + timedelta(minutes=5)
    _outcome, statements = _counted_ingest(
        db,
        seed,
        [
            _event("/pets/1", user_agent="billing/1.0"),
            _event("/pets/2", user_agent="billing/2.0", observed_at=later.isoformat()),
        ],
    )
    assert len(calls) == 1
    assert sum("UPDATE apiome.usage_consumer_binding" in sql for sql in statements) == 1
    assert sum("UPDATE apiome.consumer" in sql for sql in statements) == 1
    cursor.execute("SELECT last_matched_at FROM apiome.usage_consumer_binding WHERE id = %s", (binding,))
    assert cursor.fetchone()["last_matched_at"] == later
    cursor.execute("SELECT runtime_last_seen_at FROM apiome.consumer WHERE id = %s", (consumer,))
    assert cursor.fetchone()["runtime_last_seen_at"] == later


# ---------------------------------------------------------------------------------------------
# Two concurrent batches for one tenant
# ---------------------------------------------------------------------------------------------


def _connect() -> Any:
    try:
        return psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")


def _totals(cursor: Any, tenant: str) -> Dict[str, Any]:
    """Everything a tenant's batches added, keyed by grain (ids of the tenant's own rows left out)."""
    cursor.execute(
        """SELECT environment, hour, operation_key, status_code, calls, latency_buckets, latency_sum_ms,
                  latency_max_ms, https_calls
           FROM apiome.usage_hourly WHERE tenant_id = %s ORDER BY hour, operation_key, status_code""",
        (tenant,),
    )
    hourly = [tuple(row.values()) for row in cursor.fetchall()]
    cursor.execute(
        """SELECT pointer, day, status_code, calls_with_field, calls_sampled FROM apiome.usage_field_daily
           WHERE tenant_id = %s ORDER BY pointer, day, status_code""",
        (tenant,),
    )
    fields = [tuple(row.values()) for row in cursor.fetchall()]
    cursor.execute("SELECT events_used FROM apiome.usage_tenant_day WHERE tenant_id = %s", (tenant,))
    counter = [row["events_used"] for row in cursor.fetchall()]
    cursor.execute(
        "SELECT sum(received) AS received, sum(accepted) AS accepted FROM apiome.usage_ingest_batch "
        "WHERE tenant_id = %s",
        (tenant,),
    )
    return {"hourly": hourly, "fields": fields, "counter": counter, "ledger": dict(cursor.fetchone())}


def test_concurrent_batches_overlap_outside_the_write_phase_and_match_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    setup = _connect()
    setup.autocommit = True
    with setup.cursor() as cursor:
        cursor.execute("SELECT to_regclass('apiome.usage_tenant_day') AS t, (SELECT id FROM apiome.users LIMIT 1) AS u")
        found = cursor.fetchone()
        if not found["t"] or not found["u"]:
            setup.close()
            pytest.skip("V410 not applied or no user to own the seed projects")
        seeds = [index_db._tenant(cursor), index_db._tenant(cursor)]
        for seed in seeds:
            _publish(cursor, seed)
            cursor.execute("UPDATE apiome.usage_source SET field_capture = true WHERE id = %s", (seed["source"],))
    _stub_documents(monkeypatch)

    batch_a = _grains(300)
    batch_b = [_event(f"/pets/{i}", status=_STATUSES[i % 50], fields={"response": ["/id"]}) for i in range(400)]

    holding = threading.Event()  # A is in its write phase, under the tenant lock
    release = threading.Event()  # let A finish
    order: List[str] = []
    real_plan, real_write = usage_ingest_store.plan_batch, usage_ingest_store._write_plan

    def plan(*args: Any, **kwargs: Any) -> Any:
        result = real_plan(*args, **kwargs)
        order.append(f"plan:{threading.current_thread().name}")
        return result

    def write(cursor: Any, source: Any, plan_: Any) -> None:
        name = threading.current_thread().name
        order.append(f"write:{name}")
        if name == "A":
            holding.set()
            assert release.wait(30), "B never planned while A held the lock"
        real_write(cursor, source, plan_)

    monkeypatch.setattr(usage_ingest_store, "plan_batch", plan)
    monkeypatch.setattr(usage_ingest_store, "_write_plan", write)

    errors: List[BaseException] = []

    def run(seed: Dict[str, str], events: List[Dict[str, Any]]) -> None:
        connection = _connect()
        database = Database()
        database.connection = connection
        try:
            ingest_batch(
                database,
                tenant_id=seed["tenant"],
                source_ref=seed["source"],
                raw_events=events,
                digest="0" * 64,
                api_key_id=None,
                now=NOW,
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised on the test thread
            errors.append(exc)
        finally:
            connection.close()

    try:
        concurrent = seeds[0]
        thread_a = threading.Thread(target=run, args=(concurrent, batch_a), name="A")
        thread_b = threading.Thread(target=run, args=(concurrent, batch_b), name="B")
        thread_a.start()
        assert holding.wait(30), "A never reached its write phase"
        thread_b.start()
        # B plans while A holds the lock, then waits for it: it cannot write yet.
        deadline = datetime.now() + timedelta(seconds=30)
        while "plan:B" not in order and datetime.now() < deadline:
            thread_b.join(0.05)
        assert "plan:B" in order and "write:B" not in order
        release.set()
        thread_a.join(30)
        thread_b.join(30)
        assert not errors, errors
        assert order.index("write:B") > order.index("write:A")

        # The same two batches, one after the other, into the second tenant.
        monkeypatch.setattr(usage_ingest_store, "_write_plan", real_write)
        serial = seeds[1]
        for events in (batch_a, batch_b):
            database = Database()
            database.connection = _connect()
            try:
                ingest_batch(
                    database,
                    tenant_id=serial["tenant"],
                    source_ref=serial["source"],
                    raw_events=events,
                    digest="0" * 64,
                    api_key_id=None,
                    now=NOW,
                )
            finally:
                database.connection.close()

        with setup.cursor() as cursor:
            assert _totals(cursor, concurrent["tenant"]) == _totals(cursor, serial["tenant"])
            assert _totals(cursor, concurrent["tenant"])["counter"] == [len(batch_a) + len(batch_b)]
    finally:
        release.set()
        with setup.cursor() as cursor:
            for seed in seeds:
                cursor.execute("DELETE FROM apiome.tenants WHERE id = %s", (seed["tenant"],))
        setup.close()
