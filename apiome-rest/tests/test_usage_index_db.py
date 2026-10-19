"""The usage index (V290) against a live Postgres — RDG-1.1 (#5759).

The acceptance criteria only the real schema can prove:

* **no column in any ``usage_*`` table can store a body, a header value or an IP address** — every
  column is pinned with its type, no column has an address type, the one JSON column is the opt-in
  redacted sample, and every text column is a bounded, pattern-checked identifier that refuses a
  header, a query string or free text;
* ``rollup_usage_days`` is idempotent and a finalized day is never recomputed (nor takes new counts);
* ``purge_usage`` on a Free tenant removes hourly rows older than 7 days — only on finalized days —
  and leaves ``usage_daily`` intact; a Paid tenant keeps 30 days; samples go after 7 days; rollup
  rows go after the tier's rollup retention;
* the tier keys are seeded into ``licenses.seats``, the histogram bounds match
  :data:`app.usage_events.LATENCY_BOUNDS_MS`, and the sweep runs end to end.

Everything runs inside one transaction on a dedicated connection that is always rolled back.
Skipped when no database is reachable or V290 is not applied.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database
from app.usage_events import LATENCY_BOUNDS_MS, SOURCE_KINDS
from app.usage_sweep import run_usage_sweep

pytestmark = pytest.mark.requires_db

#: "Now" for every test: noon UTC, so day arithmetic never straddles midnight.
NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
TODAY = NOW.date()
BUCKETS = len(LATENCY_BOUNDS_MS) + 1
OPERATION = "/paths/~1pets~1{petId}/get"


class _NoCommitConnection:
    """A real connection whose commits and rollbacks are swallowed, so one test is one transaction."""

    closed = False

    class _Info:
        transaction_status = TRANSACTION_STATUS_IDLE

    info = _Info()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return False

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


@pytest.fixture
def tx() -> Iterator[Tuple[Database, Any]]:
    """A :class:`Database` and a raw cursor over one always-rolled-back transaction.

    The rollup bookkeeping is global, so it is emptied (inside the transaction) to start every test
    from a clean index.
    """
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.usage_hourly') AS t, (SELECT id FROM apiome.users LIMIT 1) AS u")
        found = probe.fetchone()
    if not found["t"] or not found["u"]:
        conn.close()
        pytest.skip("V290 not applied or no user to own the seed projects")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM apiome.usage_rollup_days")
            yield db, cursor
    finally:
        conn.rollback()
        conn.close()


def _tenant(cursor: Any, license_type: Optional[str] = None) -> Dict[str, str]:
    """A tenant (on ``license_type``, or unlicensed) with one project and one OTLP source."""
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"usage {suffix}", f"usage-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]
    cursor.execute("DELETE FROM apiome.tenant_licenses WHERE tenant_id = %s", (tenant,))
    if license_type:
        cursor.execute(
            """INSERT INTO apiome.tenant_licenses (tenant_id, license_id)
               SELECT %s, id FROM apiome.licenses WHERE license_type = %s ORDER BY created_at LIMIT 1""",
            (tenant, license_type),
        )
    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'Pets', %s, true) RETURNING id::text AS id""",
        (tenant, user, f"pets-{suffix}"),
    )
    project = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.usage_source (tenant_id, project_id, kind)
           VALUES (%s, %s, 'otlp') RETURNING id::text AS id""",
        (tenant, project),
    )
    return {"tenant": tenant, "project": project, "source": cursor.fetchone()["id"]}


def _buckets(**counts: int) -> List[int]:
    """A histogram with ``counts`` keyed ``b<index>``."""
    values = [0] * BUCKETS
    for key, count in counts.items():
        values[int(key[1:])] = count
    return values


def _hourly(
    cursor: Any,
    seed: Dict[str, str],
    hour: datetime,
    *,
    calls: int = 10,
    status: int = 200,
    buckets: Optional[List[int]] = None,
    operation: str = OPERATION,
    **counters: int,
) -> None:
    """One ``usage_hourly`` row (posture counters default to 0)."""
    row = {
        "auth_present_calls": 0,
        "auth_unknown_calls": 0,
        "versioned_calls": 0,
        "version_unknown_calls": 0,
        "https_calls": 0,
        "request_bytes": 0,
        "response_bytes": 0,
        **counters,
    }
    cursor.execute(
        f"""INSERT INTO apiome.usage_hourly (
                tenant_id, project_id, source_id, environment, hour, operation_key, status_code,
                calls, latency_buckets, latency_sum_ms, latency_max_ms, {", ".join(row)})
            VALUES (%s, %s, %s, 'prod', %s, %s, %s, %s, %s, %s, %s, {", ".join(["%s"] * len(row))})""",
        (
            seed["tenant"],
            seed["project"],
            seed["source"],
            hour,
            operation,
            status,
            calls,
            buckets if buckets is not None else _buckets(b0=calls),
            calls * 3,
            9,
            *row.values(),
        ),
    )


def _at(day: date, hour: int = 0) -> datetime:
    """The start of ``hour`` on UTC ``day``."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def _refused(cursor: Any, sql: str, params: Tuple[Any, ...] = ()) -> str:
    """Run ``sql`` expecting the database to refuse it; return the error text."""
    cursor.execute("SAVEPOINT refused")
    try:
        cursor.execute(sql, params)
    except psycopg2.Error as exc:
        cursor.execute("ROLLBACK TO SAVEPOINT refused")
        return str(exc)
    cursor.execute("RELEASE SAVEPOINT refused")
    raise AssertionError(f"accepted: {sql} {params}")


def _count(cursor: Any, table: str, tenant: str, where: str = "true", params: Tuple[Any, ...] = ()) -> int:
    cursor.execute(f"SELECT count(*) AS n FROM apiome.{table} WHERE tenant_id = %s AND {where}", (tenant, *params))
    return int(cursor.fetchone()["n"])


# ---------------------------------------------------------------------------------------------
# The privacy invariant
# ---------------------------------------------------------------------------------------------

#: Every column of every usage_* table, with its type. A new column must be reviewed against the
#: privacy model (no header value, body, query value or address), so the list is pinned.
EXPECTED_COLUMNS: Dict[str, Dict[str, str]] = {
    # CDG-3.5 (V293): a client key is a scrubbed user-agent product token or a consumer_hint HMAC.
    "usage_unattributed_client_daily": {
        "tenant_id": "uuid",
        "project_id": "uuid",
        "day": "date",
        "client_kind": "character varying",
        "client_key": "character varying",
        "calls": "bigint",
        "first_seen_at": "timestamp with time zone",
        "last_seen_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
    },
    # RDG-1.8 (V292): a bound value is only ever stored as its 64-hex HMAC; `name` is a header or
    # claim *name*, or a user-agent glob — never a value.
    "usage_consumer_binding": {
        "id": "uuid",
        "tenant_id": "uuid",
        "project_id": "uuid",
        "consumer_id": "uuid",
        "kind": "character varying",
        "name": "character varying",
        "value_hmac": "character",
        "key_version": "integer",
        "last_matched_at": "timestamp with time zone",
        "created_by": "uuid",
        "created_at": "timestamp with time zone",
        "deleted_at": "timestamp with time zone",
        "deleted_by": "uuid",
    },
    "usage_source": {
        "id": "uuid",
        "tenant_id": "uuid",
        "project_id": "uuid",
        "kind": "character varying",
        "environment": "character varying",
        "sampling_rate": "numeric",
        "field_capture": "boolean",
        "body_sample_rate": "numeric",
        "body_sample_until": "timestamp with time zone",
        "enabled": "boolean",
        "last_received_at": "timestamp with time zone",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
    },
    "usage_ingest_batch": {
        "id": "uuid",
        "tenant_id": "uuid",
        "source_id": "uuid",
        "api_key_id": "uuid",
        "received_at": "timestamp with time zone",
        "received_day": "date",
        "received": "integer",
        "accepted": "integer",
        "sampled_out": "integer",
        "unmatched": "integer",
        "rejected": "integer",
        "scrub_findings": "integer",
        "batch_digest": "character",
    },
    "usage_rollup_days": {
        "day": "date",
        "rolled_up_at": "timestamp with time zone",
        "finalized_at": "timestamp with time zone",
    },
    **{
        table: {
            "tenant_id": "uuid",
            "project_id": "uuid",
            "source_id": "uuid",
            "environment": "character varying",
            **({"hour": "timestamp with time zone"} if table == "usage_hourly" else {}),
            "day": "date",
            "version_record_id": "uuid",
            "operation_key": "character varying",
            "status_code": "smallint",
            "consumer_binding_id": "uuid",
            "calls": "bigint",
            "errors": "bigint",
            "latency_buckets": "ARRAY",
            "latency_sum_ms": "bigint",
            "latency_max_ms": "integer",
            "auth_present_calls": "bigint",
            "auth_unknown_calls": "bigint",
            "versioned_calls": "bigint",
            "version_unknown_calls": "bigint",
            "https_calls": "bigint",
            "request_bytes": "bigint",
            "response_bytes": "bigint",
            ("updated_at" if table == "usage_hourly" else "computed_at"): "timestamp with time zone",
        }
        for table in ("usage_hourly", "usage_daily")
    },
    "usage_field_daily": {
        "tenant_id": "uuid",
        "project_id": "uuid",
        "source_id": "uuid",
        "environment": "character varying",
        "day": "date",
        "operation_key": "character varying",
        "direction": "character varying",
        "status_code": "smallint",
        "pointer": "character varying",
        "calls_with_field": "bigint",
        "calls_sampled": "bigint",
        "updated_at": "timestamp with time zone",
    },
    "usage_unmatched_daily": {
        "tenant_id": "uuid",
        "project_id": "uuid",
        "source_id": "uuid",
        "environment": "character varying",
        "day": "date",
        "method": "character varying",
        "path_template": "character varying",
        "calls": "bigint",
        "first_seen_at": "timestamp with time zone",
        "last_seen_at": "timestamp with time zone",
        "calls_1xx": "bigint",
        "calls_2xx": "bigint",
        "calls_3xx": "bigint",
        "calls_4xx": "bigint",
        "calls_5xx": "bigint",
        "updated_at": "timestamp with time zone",
    },
    "usage_sample": {
        "id": "uuid",
        "tenant_id": "uuid",
        "project_id": "uuid",
        "source_id": "uuid",
        "environment": "character varying",
        "captured_at": "timestamp with time zone",
        "operation_key": "character varying",
        "status_code": "smallint",
        "exchange": "jsonb",
    },
}

#: The one column allowed to hold exchange content: the opt-in, reducer-redacted sample.
SAMPLE_COLUMN = ("usage_sample", "exchange")


def _columns(cursor: Any) -> List[Dict[str, Any]]:
    cursor.execute(
        """SELECT table_name, column_name, data_type, character_maximum_length, is_nullable
           FROM information_schema.columns
           WHERE table_schema = 'apiome' AND table_name LIKE 'usage\\_%'
           ORDER BY table_name, ordinal_position"""
    )
    return list(cursor.fetchall())


def test_every_usage_column_is_pinned(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    found: Dict[str, Dict[str, str]] = {}
    for column in _columns(cursor):
        found.setdefault(column["table_name"], {})[column["column_name"]] = column["data_type"]
    assert found == EXPECTED_COLUMNS


def test_no_column_can_hold_an_address_binary_or_free_json(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    for column in _columns(cursor):
        key = (column["table_name"], column["column_name"])
        assert column["data_type"] not in ("inet", "cidr", "macaddr", "macaddr8", "bytea", "text", "json"), key
        if column["data_type"] == "jsonb":
            assert key == SAMPLE_COLUMN


def test_every_text_column_is_bounded_and_pattern_checked(tx: Tuple[Database, Any]) -> None:
    """A text column that is not a short checked identifier could hold a header or a body."""
    _, cursor = tx
    cursor.execute(
        """SELECT rel.relname AS table_name, att.attname AS column_name
           FROM pg_constraint con
           JOIN pg_class rel ON rel.oid = con.conrelid
           JOIN pg_namespace ns ON ns.oid = rel.relnamespace AND ns.nspname = 'apiome'
           JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY (con.conkey)
           WHERE con.contype = 'c' AND rel.relname LIKE 'usage\\_%'"""
    )
    checked = {(row["table_name"], row["column_name"]) for row in cursor.fetchall()}
    for column in _columns(cursor):
        if column["data_type"] in ("character varying", "character"):
            key = (column["table_name"], column["column_name"])
            assert column["character_maximum_length"] and column["character_maximum_length"] <= 1024, key
            assert key in checked, f"{key} has no CHECK constraint"


def test_every_tenant_scoped_table_carries_tenant_id(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    for column in _columns(cursor):
        if column["column_name"] == "tenant_id":
            assert column["is_nullable"] == "NO", column["table_name"]
    tables = {column["table_name"] for column in _columns(cursor)}
    with_tenant = {column["table_name"] for column in _columns(cursor) if column["column_name"] == "tenant_id"}
    # usage_rollup_days is global bookkeeping (one row per UTC day, no traffic data).
    assert tables - with_tenant == {"usage_rollup_days"}


@pytest.mark.parametrize(
    "column, value",
    [
        ("environment", "Authorization: Bearer abc"),
        ("environment", "10.0.0.1"),
        ("operation_key", "/paths/~1pets/get?token=abc"),
        ("operation_key", "Bearer eyJhbGciOiJIUzI1NiJ9.e30.x"),
        ("operation_key", '/paths/~1pets/get {"card": "4111"}'),
    ],
)
def test_counter_text_columns_refuse_headers_queries_and_bodies(
    tx: Tuple[Database, Any], column: str, value: str
) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    values = {"environment": "prod", "operation_key": OPERATION, column: value}
    error = _refused(
        cursor,
        """INSERT INTO apiome.usage_hourly (tenant_id, project_id, source_id, environment, hour,
               operation_key, status_code, calls, latency_buckets, latency_sum_ms, latency_max_ms)
           VALUES (%s, %s, %s, %s, %s, %s, 200, 0, %s, 0, 0)""",
        (
            seed["tenant"],
            seed["project"],
            seed["source"],
            values["environment"],
            _at(TODAY),
            values["operation_key"],
            _buckets(),
        ),
    )
    assert "violates check constraint" in error


@pytest.mark.parametrize(
    "column, value",
    [
        ("method", "GET /x"),
        ("path_template", "/users?email=alice@example.com"),
        ("path_template", "/users/alice@example.com /x"),
        ("path_template", "users"),
    ],
)
def test_unmatched_text_columns_refuse_queries_and_free_text(tx: Tuple[Database, Any], column: str, value: str) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    values = {"method": "GET", "path_template": "/users/{param}", column: value}
    error = _refused(
        cursor,
        """INSERT INTO apiome.usage_unmatched_daily (tenant_id, project_id, source_id, environment, day,
               method, path_template, calls, first_seen_at, last_seen_at)
           VALUES (%s, %s, %s, 'prod', %s, %s, %s, 0, %s, %s)""",
        (seed["tenant"], seed["project"], seed["source"], TODAY, values["method"], values["path_template"], NOW, NOW),
    )
    assert "violates check constraint" in error


@pytest.mark.parametrize("pointer", ["/name value", "name", "/a~2b"])
def test_field_pointers_refuse_values(tx: Tuple[Database, Any], pointer: str) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    _refused(
        cursor,
        """INSERT INTO apiome.usage_field_daily (tenant_id, project_id, source_id, environment, day,
               operation_key, direction, status_code, pointer, calls_with_field, calls_sampled)
           VALUES (%s, %s, %s, 'prod', %s, %s, 'response', 200, %s, 1, 1)""",
        (seed["tenant"], seed["project"], seed["source"], TODAY, OPERATION, pointer),
    )


def test_samples_are_capped_at_16_kib(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    sql = """INSERT INTO apiome.usage_sample (tenant_id, project_id, source_id, environment, status_code, exchange)
             VALUES (%s, %s, %s, 'prod', 200, jsonb_build_object('response', %s::text))"""
    cursor.execute(sql, (seed["tenant"], seed["project"], seed["source"], "x" * 16000))
    _refused(cursor, sql, (seed["tenant"], seed["project"], seed["source"], "x" * 16400))


# ---------------------------------------------------------------------------------------------
# Sources, ledger and histogram rules
# ---------------------------------------------------------------------------------------------


def test_source_kinds_match_the_contract(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    for kind in SOURCE_KINDS:
        environment = "mock" if kind == "mock" else "prod"
        cursor.execute(
            "INSERT INTO apiome.usage_source (tenant_id, project_id, kind, environment) VALUES (%s, %s, %s, %s)",
            (seed["tenant"], seed["project"], kind, environment),
        )
    _refused(
        cursor,
        "INSERT INTO apiome.usage_source (tenant_id, project_id, kind) VALUES (%s, %s, 'syslog')",
        (seed["tenant"], seed["project"]),
    )


def test_source_defaults(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    cursor.execute("SELECT * FROM apiome.usage_source WHERE id = %s", (seed["source"],))
    source = cursor.fetchone()
    assert source["environment"] == "prod" and source["enabled"] is True and source["field_capture"] is False
    assert float(source["sampling_rate"]) == 1 and float(source["body_sample_rate"]) == 0


def test_the_mock_environment_is_reserved(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    _refused(
        cursor,
        "INSERT INTO apiome.usage_source (tenant_id, project_id, kind, environment) VALUES (%s, %s, 'otlp', 'mock')",
        (seed["tenant"], seed["project"]),
    )


@pytest.mark.parametrize("rate", [0, 1.5, -0.1])
def test_sampling_rate_is_in_zero_to_one(tx: Tuple[Database, Any], rate: float) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    _refused(cursor, "UPDATE apiome.usage_source SET sampling_rate = %s WHERE id = %s", (rate, seed["source"]))


def test_body_sampling_is_bounded_in_rate_and_window(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    update = "UPDATE apiome.usage_source SET body_sample_rate = %s, body_sample_until = %s WHERE id = %s"
    _refused(cursor, update, (0.06, NOW + timedelta(days=1), seed["source"]))
    _refused(cursor, update, (0.05, None, seed["source"]))
    assert "at most 7 days ahead" in _refused(
        cursor, update, (0.05, datetime.now(timezone.utc) + timedelta(days=8), seed["source"])
    )
    cursor.execute(update, (0.05, datetime.now(timezone.utc) + timedelta(days=6), seed["source"]))


def _batch(
    cursor: Any,
    seed: Dict[str, str],
    *,
    received: int,
    accepted: int,
    sampled_out: int = 0,
    unmatched: int = 0,
    rejected: int = 0,
    received_at: Optional[datetime] = None,
) -> str:
    cursor.execute(
        """INSERT INTO apiome.usage_ingest_batch (tenant_id, source_id, api_key_id, received_at, received,
               accepted, sampled_out, unmatched, rejected, batch_digest)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id""",
        (
            seed["tenant"],
            seed["source"],
            str(uuid.uuid4()),
            received_at or NOW,
            received,
            accepted,
            sampled_out,
            unmatched,
            rejected,
            "0" * 64,
        ),
    )
    return cursor.fetchone()["id"]


def test_the_ledger_accounts_for_every_event_and_is_write_once(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    batch = _batch(cursor, seed, received=10, accepted=6, sampled_out=2, unmatched=1, rejected=1)
    assert "usage_ingest_batch_total_ck" in _refused(
        cursor,
        """INSERT INTO apiome.usage_ingest_batch (tenant_id, source_id, received, accepted, sampled_out,
               unmatched, rejected, batch_digest) VALUES (%s, %s, 10, 9, 0, 0, 0, %s)""",
        (seed["tenant"], seed["source"], "0" * 64),
    )
    _refused(cursor, "UPDATE apiome.usage_ingest_batch SET accepted = 7 WHERE id = %s", (batch,))
    _refused(
        cursor,
        """INSERT INTO apiome.usage_ingest_batch (tenant_id, source_id, received, accepted, sampled_out,
               unmatched, rejected, batch_digest) VALUES (%s, %s, 0, 0, 0, 0, 0, 'not-a-digest')""",
        (seed["tenant"], seed["source"]),
    )


def test_latency_bounds_match_the_event_contract(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    cursor.execute("SELECT apiome.usage_latency_bounds() AS bounds")
    assert tuple(cursor.fetchone()["bounds"]) == LATENCY_BOUNDS_MS


@pytest.mark.parametrize(
    "buckets",
    [[10] * (BUCKETS - 1), [10] + [0] * BUCKETS, [11] + [0] * (BUCKETS - 1), [-1, 11] + [0] * (BUCKETS - 2)],
    ids=["too-few", "too-many", "wrong-sum", "negative"],
)
def test_histograms_must_have_every_bucket_and_sum_to_calls(tx: Tuple[Database, Any], buckets: List[int]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    cursor.execute("SAVEPOINT h")
    with pytest.raises(psycopg2.Error, match="latency_buckets_ck"):
        _hourly(cursor, seed, _at(TODAY), calls=10, buckets=buckets)
    cursor.execute("ROLLBACK TO SAVEPOINT h")


def test_posture_counters_cannot_exceed_calls(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    for counters in ({"https_calls": 11}, {"auth_present_calls": 6, "auth_unknown_calls": 5}, {"versioned_calls": 11}):
        cursor.execute("SAVEPOINT p")
        with pytest.raises(psycopg2.Error, match="posture_ck"):
            _hourly(cursor, seed, _at(TODAY), calls=10, **counters)
        cursor.execute("ROLLBACK TO SAVEPOINT p")


def test_hours_must_be_whole_and_grains_unique(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    cursor.execute("SAVEPOINT g")
    with pytest.raises(psycopg2.Error, match="usage_hourly_hour_ck"):
        _hourly(cursor, seed, _at(TODAY) + timedelta(minutes=30))
    cursor.execute("ROLLBACK TO SAVEPOINT g")
    _hourly(cursor, seed, _at(TODAY))
    # NULL version and consumer still make one grain (NULLS NOT DISTINCT).
    cursor.execute("SAVEPOINT g")
    with pytest.raises(psycopg2.Error, match="usage_hourly_grain_uq"):
        _hourly(cursor, seed, _at(TODAY))
    cursor.execute("ROLLBACK TO SAVEPOINT g")


def test_errors_count_4xx_and_5xx(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    for status in (200, 404, 503):
        _hourly(cursor, seed, _at(TODAY), status=status, calls=4)
    cursor.execute(
        "SELECT status_code, errors FROM apiome.usage_hourly WHERE tenant_id = %s ORDER BY status_code",
        (seed["tenant"],),
    )
    assert [(r["status_code"], r["errors"]) for r in cursor.fetchall()] == [(200, 0), (404, 4), (503, 4)]


# ---------------------------------------------------------------------------------------------
# Rollup
# ---------------------------------------------------------------------------------------------


def _rollup(cursor: Any, now: datetime, grace: str = "6 hours") -> int:
    cursor.execute("SELECT apiome.rollup_usage_days(%s, %s::interval) AS days", (now, grace))
    return int(cursor.fetchone()["days"])


def _daily(cursor: Any, tenant: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """SELECT day, operation_key, status_code, calls, errors, latency_buckets, latency_sum_ms,
                  latency_max_ms, auth_present_calls, auth_unknown_calls, versioned_calls,
                  version_unknown_calls, https_calls, request_bytes, response_bytes, computed_at
           FROM apiome.usage_daily WHERE tenant_id = %s ORDER BY day, operation_key, status_code""",
        (tenant,),
    )
    return [dict(row) for row in cursor.fetchall()]


def test_rollup_sums_the_hours_of_each_day(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    day = TODAY - timedelta(days=1)
    _hourly(
        cursor,
        seed,
        _at(day, 3),
        calls=4,
        buckets=_buckets(b0=1, b3=3),
        auth_present_calls=4,
        https_calls=4,
        request_bytes=100,
        response_bytes=400,
    )
    _hourly(
        cursor,
        seed,
        _at(day, 17),
        calls=6,
        buckets=_buckets(b3=2, b11=4),
        auth_unknown_calls=6,
        versioned_calls=5,
        version_unknown_calls=1,
        https_calls=2,
        request_bytes=50,
        response_bytes=60,
    )
    _hourly(cursor, seed, _at(day, 9), calls=2, status=500)
    _hourly(cursor, seed, _at(TODAY, 1), calls=7)

    assert _rollup(cursor, NOW) == 2
    rows = _daily(cursor, seed["tenant"])
    assert [(r["day"], r["status_code"], r["calls"]) for r in rows] == [(day, 200, 10), (day, 500, 2), (TODAY, 200, 7)]
    ok = rows[0]
    assert ok["latency_buckets"] == _buckets(b0=1, b3=5, b11=4)
    assert (ok["latency_sum_ms"], ok["latency_max_ms"]) == (30, 9)
    assert (ok["auth_present_calls"], ok["auth_unknown_calls"]) == (4, 6)
    assert (ok["versioned_calls"], ok["version_unknown_calls"], ok["https_calls"]) == (5, 1, 6)
    assert (ok["request_bytes"], ok["response_bytes"]) == (150, 460)
    assert rows[1]["errors"] == 2


def test_rollup_is_idempotent(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    _hourly(cursor, seed, _at(TODAY, 2), calls=3)
    _hourly(cursor, seed, _at(TODAY, 5), calls=8, status=404)
    _rollup(cursor, NOW)
    first = _daily(cursor, seed["tenant"])
    _rollup(cursor, NOW)
    assert _daily(cursor, seed["tenant"]) == first
    cursor.execute("SELECT count(*) AS n FROM apiome.usage_daily WHERE tenant_id = %s", (seed["tenant"],))
    assert cursor.fetchone()["n"] == 2


def test_an_open_day_picks_up_new_hours(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    _hourly(cursor, seed, _at(TODAY, 1), calls=3)
    _rollup(cursor, NOW)
    _hourly(cursor, seed, _at(TODAY, 2), calls=4)
    _rollup(cursor, NOW)
    assert [r["calls"] for r in _daily(cursor, seed["tenant"])] == [7]


def test_a_day_is_finalized_only_after_the_grace(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    yesterday = TODAY - timedelta(days=1)
    _hourly(cursor, seed, _at(yesterday, 23), calls=1)
    midnight = _at(TODAY)
    _rollup(cursor, midnight + timedelta(hours=5))
    cursor.execute("SELECT finalized_at FROM apiome.usage_rollup_days WHERE day = %s", (yesterday,))
    assert cursor.fetchone()["finalized_at"] is None
    _rollup(cursor, midnight + timedelta(hours=6))
    cursor.execute("SELECT finalized_at FROM apiome.usage_rollup_days WHERE day = %s", (yesterday,))
    assert cursor.fetchone()["finalized_at"] == midnight + timedelta(hours=6)


def test_a_finalized_day_is_never_recomputed_and_takes_no_new_counts(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    day = TODAY - timedelta(days=2)
    _hourly(cursor, seed, _at(day, 4), calls=5)
    _rollup(cursor, NOW)

    # Tamper with the final rollup: a recompute would overwrite this.
    cursor.execute(
        "UPDATE apiome.usage_daily SET request_bytes = 999 WHERE tenant_id = %s AND day = %s",
        (seed["tenant"], day),
    )
    _rollup(cursor, NOW + timedelta(days=1))
    cursor.execute("SELECT apiome.rollup_usage_day(%s, %s) AS groups", (day, NOW))
    assert cursor.fetchone()["groups"] == 0
    assert [r["request_bytes"] for r in _daily(cursor, seed["tenant"])] == [999]

    cursor.execute("SAVEPOINT late")
    with pytest.raises(psycopg2.Error, match="is finalized and takes no new counts"):
        _hourly(cursor, seed, _at(day, 6), calls=1)
    cursor.execute("ROLLBACK TO SAVEPOINT late")
    assert "is finalized" in _refused(
        cursor, "UPDATE apiome.usage_hourly SET calls = calls WHERE tenant_id = %s", (seed["tenant"],)
    )


def test_rollup_with_no_hours_does_nothing(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    cursor.execute("SELECT count(*) AS n FROM apiome.usage_hourly")
    if cursor.fetchone()["n"]:
        pytest.skip("the database already holds usage_hourly rows")
    assert _rollup(cursor, NOW) == 0


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


def _purge(cursor: Any, now: datetime = NOW) -> Dict[str, int]:
    cursor.execute("SELECT apiome.purge_usage(%s, 10000) AS purged", (now,))
    return dict(cursor.fetchone()["purged"])


@pytest.mark.parametrize("license_type", [None, "free"], ids=["unlicensed", "free"])
def test_free_purges_hourly_rows_older_than_7_days_and_keeps_daily(
    tx: Tuple[Database, Any], license_type: Optional[str]
) -> None:
    _, cursor = tx
    seed = _tenant(cursor, license_type)
    old, recent, unfinal = TODAY - timedelta(days=10), TODAY - timedelta(days=3), TODAY - timedelta(days=12)
    for day in (old, recent, unfinal):
        _hourly(cursor, seed, _at(day, 8), calls=2)
    _rollup(cursor, NOW)
    # A day whose finalization was lost keeps its hourly rows, however old (rule 6).
    cursor.execute("UPDATE apiome.usage_rollup_days SET finalized_at = NULL WHERE day = %s", (unfinal,))

    purged = _purge(cursor)
    assert purged["hourly"] >= 1
    cursor.execute("SELECT day FROM apiome.usage_hourly WHERE tenant_id = %s ORDER BY day", (seed["tenant"],))
    assert [r["day"] for r in cursor.fetchall()] == [unfinal, recent]
    assert [r["day"] for r in _daily(cursor, seed["tenant"])] == [unfinal, old, recent]


def test_paid_keeps_30_days_of_hourly_rows(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor, "paid")
    for days in (10, 29, 31):
        _hourly(cursor, seed, _at(TODAY - timedelta(days=days), 8), calls=1)
    _rollup(cursor, NOW)
    _purge(cursor)
    cursor.execute("SELECT day FROM apiome.usage_hourly WHERE tenant_id = %s ORDER BY day", (seed["tenant"],))
    assert [r["day"] for r in cursor.fetchall()] == [TODAY - timedelta(days=29), TODAY - timedelta(days=10)]


def test_samples_are_purged_after_7_days_whatever_the_tier(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor, "sponsor")
    for days in (1, 8):
        cursor.execute(
            """INSERT INTO apiome.usage_sample (tenant_id, project_id, source_id, environment, captured_at,
                   status_code, exchange) VALUES (%s, %s, %s, 'prod', %s, 200, '{}')""",
            (seed["tenant"], seed["project"], seed["source"], NOW - timedelta(days=days)),
        )
    _purge(cursor)
    assert _count(cursor, "usage_sample", seed["tenant"]) == 1


def test_rollup_rows_and_ledger_follow_the_rollup_retention(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    free, paid = _tenant(cursor), _tenant(cursor, "paid")
    for seed in (free, paid):
        for days in (30, 100):
            day = TODAY - timedelta(days=days)
            cursor.execute(
                """INSERT INTO apiome.usage_daily (tenant_id, project_id, source_id, environment, day,
                       operation_key, status_code, calls, latency_buckets, latency_sum_ms, latency_max_ms,
                       auth_present_calls, auth_unknown_calls, versioned_calls, version_unknown_calls,
                       https_calls, request_bytes, response_bytes)
                   VALUES (%s, %s, %s, 'prod', %s, %s, 200, 0, %s, 0, 0, 0, 0, 0, 0, 0, 0, 0)""",
                (seed["tenant"], seed["project"], seed["source"], day, OPERATION, _buckets()),
            )
            cursor.execute(
                """INSERT INTO apiome.usage_field_daily (tenant_id, project_id, source_id, environment, day,
                       operation_key, direction, status_code, pointer, calls_with_field, calls_sampled)
                   VALUES (%s, %s, %s, 'prod', %s, %s, 'response', 200, '/id', 1, 1)""",
                (seed["tenant"], seed["project"], seed["source"], day, OPERATION),
            )
            cursor.execute(
                """INSERT INTO apiome.usage_unmatched_daily (tenant_id, project_id, source_id, environment,
                       day, method, path_template, calls, first_seen_at, last_seen_at, calls_2xx)
                   VALUES (%s, %s, %s, 'prod', %s, 'GET', '/legacy/{param}', 1, %s, %s, 1)""",
                (seed["tenant"], seed["project"], seed["source"], day, _at(day), _at(day)),
            )
            _batch(cursor, seed, received=1, accepted=1, received_at=_at(day, 1))

    _purge(cursor)
    for table in ("usage_daily", "usage_field_daily", "usage_unmatched_daily"):
        assert _count(cursor, table, free["tenant"]) == 1, table  # 90 days: the 100-day row went
        assert _count(cursor, table, paid["tenant"]) == 2, table  # 395 days: both kept
    assert _count(cursor, "usage_ingest_batch", free["tenant"]) == 1
    assert _count(cursor, "usage_ingest_batch", paid["tenant"]) == 2


def test_retention_reads_the_tier_and_keeps_forever_when_negative(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor, "sponsor")
    cursor.execute("SELECT * FROM apiome.usage_retention(%s) WHERE tenant_id = %s", (NOW, seed["tenant"]))
    row = cursor.fetchone()
    assert row["hourly_cutoff"] == NOW - timedelta(days=90)
    assert row["rollup_cutoff"] == TODAY - timedelta(days=730)

    cursor.execute(
        """INSERT INTO apiome.licenses (name, license_type, seats)
           VALUES ('usage forever', 'paid', '{"usage_hourly_retention_days": -1,
                                               "usage_rollup_retention_days": -1}')
           RETURNING id""",
    )
    license_id = cursor.fetchone()["id"]
    cursor.execute(
        "UPDATE apiome.tenant_licenses SET license_id = %s WHERE tenant_id = %s", (license_id, seed["tenant"])
    )
    cursor.execute("SELECT * FROM apiome.usage_retention(%s) WHERE tenant_id = %s", (NOW, seed["tenant"]))
    row = cursor.fetchone()
    assert row["hourly_cutoff"] is None and row["rollup_cutoff"] is None


def test_tier_keys_are_seeded(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    cursor.execute(
        """SELECT DISTINCT license_type,
                  (seats ->> 'usage_hourly_retention_days')::int AS hourly,
                  (seats ->> 'usage_rollup_retention_days')::int AS rollup,
                  (seats ->> 'usage_events_per_day')::bigint AS events
           FROM apiome.licenses
           WHERE license_type IN ('free', 'paid', 'sponsor') AND name <> 'usage forever'"""
    )
    seeded = {(row["license_type"], row["hourly"], row["rollup"], row["events"]) for row in cursor.fetchall()}
    assert seeded == {
        ("free", 7, 90, 100_000),
        ("paid", 30, 395, 10_000_000),
        ("sponsor", 90, 730, 100_000_000),
    }


# ---------------------------------------------------------------------------------------------
# The sweep end to end
# ---------------------------------------------------------------------------------------------


def test_the_sweep_rolls_up_and_purges(tx: Tuple[Database, Any]) -> None:
    db, cursor = tx
    seed = _tenant(cursor)
    now = datetime.now(timezone.utc)
    _hourly(cursor, seed, _at(now.date() - timedelta(days=9), 4), calls=3)
    _hourly(cursor, seed, _at(now.date(), 0), calls=2)

    result = run_usage_sweep(db, finalize_grace=timedelta(hours=6))
    assert result is not None and result.days_rolled_up >= 10 and result.hourly_purged >= 1
    assert [r["calls"] for r in _daily(cursor, seed["tenant"])] == [3, 2]
    cursor.execute("SELECT count(*) AS n FROM apiome.usage_hourly WHERE tenant_id = %s", (seed["tenant"],))
    assert cursor.fetchone()["n"] == 1


def test_deleting_the_source_removes_its_counters(tx: Tuple[Database, Any]) -> None:
    _, cursor = tx
    seed = _tenant(cursor)
    _hourly(cursor, seed, _at(TODAY, 1))
    _batch(cursor, seed, received=1, accepted=1)
    cursor.execute("DELETE FROM apiome.usage_source WHERE id = %s", (seed["source"],))
    assert _count(cursor, "usage_hourly", seed["tenant"]) == 0
    assert _count(cursor, "usage_ingest_batch", seed["tenant"]) == 0
