"""The consumer-capture writer and sweeper against a real database — PFX-9.1 (#7319).

Runs when ``APIOME_MOCK_TEST_DATABASE_URL`` names a database migrated with apiome-db (V461 or
later); skips otherwise. Each case seeds two tenants of its own and deletes them afterwards (every
capture row goes with its tenant).

What only the real SQL proves:

* one flush opens a session per (version, consumer, consumer version), stores its calls redacted,
  and stamps every row with the tenant's retention;
* a second flush adds to the same session and keeps its refusals by reason;
* calls go to the tenant that owns the version, never another;
* an expired session is closed before its key is used again, so a new recording starts empty;
* the tenant's live-session cap counts the overflow on the tenant's settings row;
* the sweeper deletes expired calls and sessions only.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
from app.pact_capture import ConsumerTag
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock import consumer_capture
from apiome_mock.consumer_capture import ConsumerCaptureRecorder, PendingCall, sweep_expired_captures

DB_URL = os.environ.get("APIOME_MOCK_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DB_URL, reason="APIOME_MOCK_TEST_DATABASE_URL not set")


async def _fetch(pool: AsyncConnectionPool, sql: str, params: Any = None) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall()) if cur.description else []


async def _seed(pool: AsyncConnectionPool) -> dict[str, Any]:
    """A tenant with one project and one version; returns their ids."""
    suffix = uuid.uuid4().hex[:10]
    user = (await _fetch(pool, "SELECT id FROM apiome.users LIMIT 1"))[0]["id"]
    tenant = (
        await _fetch(
            pool,
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id",
            (f"capture {suffix}", f"capture-{suffix}"),
        )
    )[0]["id"]
    project = (
        await _fetch(
            pool,
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, 'Billing', %s) RETURNING id",
            (tenant, user, f"billing-{suffix}"),
        )
    )[0]["id"]
    version = (
        await _fetch(
            pool,
            "INSERT INTO apiome.versions (project_id, creator_id, version_id) VALUES (%s, %s, '2.7.0') RETURNING id",
            (project, user),
        )
    )[0]["id"]
    return {"tenant": tenant, "project": project, "version": version, "slug": f"billing-{suffix}"}


def _call(
    seed: dict[str, Any], consumer: str = "orders-ui", *, path: str = "/invoices/42", at: datetime | None = None
) -> PendingCall:
    return PendingCall(
        version_id=seed["version"],
        project_slug=seed["slug"],
        version_label="2.7.0",
        tag=ConsumerTag(consumer, "3.4.0"),
        via="header",
        link_id=None,
        api_key_id=None,
        captured_at=at or datetime.now(timezone.utc),
        method="GET",
        path=path,
        query=[("access_token", "secret")],
        request_headers={"Authorization": "Bearer abc.def.ghi", "Accept": "application/json"},
        request_body=None,
        request_media_type=None,
        status=200,
        response_headers={"content-type": "application/json"},
        response_body=b'{"id": 42, "amount": 1250}',
        response_media_type="application/json",
        path_template="/invoices/{id}",
        operation_key="GET /invoices/{id}",
        origin="spec",
        origin_detail="Served the example.",
        scenario=None,
        mock_session=None,
    )


def _run(body: Any) -> None:
    async def _main() -> None:
        assert DB_URL is not None
        pool = AsyncConnectionPool(DB_URL, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
        await pool.open()
        seeds = [await _seed(pool), await _seed(pool)]
        try:
            await body(pool, *seeds)
        finally:
            await _fetch(pool, "DELETE FROM apiome.tenants WHERE id = ANY(%s)", ([s["tenant"] for s in seeds],))
            await pool.close()

    asyncio.run(_main())


def test_a_flush_stores_redacted_calls_in_one_session_with_the_tenants_retention() -> None:
    async def body(pool: AsyncConnectionPool, seed: dict[str, Any], other: dict[str, Any]) -> None:
        await _fetch(
            pool,
            "INSERT INTO apiome.mock_consumer_capture_settings (tenant_id, retention_days) VALUES (%s, 3)",
            (seed["tenant"],),
        )
        recorder = ConsumerCaptureRecorder(pool, flush_interval_seconds=60)
        for path in ("/invoices/42", "/invoices/43"):
            recorder.submit(_call(seed, path=path))
        recorder.submit(_call(seed, "billing-ui"))
        recorder.submit(_call(other))
        await recorder.flush()

        sessions = await _fetch(
            pool,
            """SELECT tenant_id, consumer, call_count, refused, expires_at - last_call_at AS kept
               FROM apiome.mock_consumer_capture_session WHERE tenant_id = ANY(%s) ORDER BY tenant_id, consumer""",
            ([seed["tenant"], other["tenant"]],),
        )
        mine = [s for s in sessions if s["tenant_id"] == seed["tenant"]]
        assert [(s["consumer"], s["call_count"]) for s in mine] == [("billing-ui", 1), ("orders-ui", 2)]
        assert all(s["kept"] == timedelta(days=3) for s in mine)
        theirs = [s for s in sessions if s["tenant_id"] == other["tenant"]]
        assert [(s["consumer"], s["call_count"], s["kept"]) for s in theirs] == [("orders-ui", 1, timedelta(days=7))]

        calls = await _fetch(
            pool,
            """SELECT c.tenant_id, c.request, c.response, c.redaction_count, c.expires_at - c.captured_at AS kept
               FROM apiome.mock_consumer_capture_call c WHERE c.tenant_id = %s ORDER BY c.id""",
            (seed["tenant"],),
        )
        assert len(calls) == 3
        first = calls[0]
        assert "Authorization" not in first["request"]["headers"]
        assert first["request"]["query"] == []
        assert first["response"]["body"] == {"id": 42, "amount": 1250}
        assert first["redaction_count"] >= 2
        assert first["kept"] == timedelta(days=3)

        # A second flush adds to the session; a full session counts the overflow by reason.
        with patch.object(consumer_capture, "MAX_CALLS_PER_SESSION", 3):
            recorder.submit(_call(seed))
            recorder.submit(_call(seed))
            await recorder.flush()
        row = (
            await _fetch(
                pool,
                "SELECT call_count, refused_count, refused FROM apiome.mock_consumer_capture_session "
                "WHERE tenant_id = %s AND consumer = 'orders-ui'",
                (seed["tenant"],),
            )
        )[0]
        assert (row["call_count"], row["refused_count"], row["refused"]) == (3, 1, {"session-full": 1})

    _run(body)


def test_an_expired_session_is_closed_before_its_key_is_used_again() -> None:
    async def body(pool: AsyncConnectionPool, seed: dict[str, Any], other: dict[str, Any]) -> None:
        recorder = ConsumerCaptureRecorder(pool, flush_interval_seconds=60)
        recorder.submit(_call(seed))
        await recorder.flush()
        await _fetch(
            pool,
            "UPDATE apiome.mock_consumer_capture_session SET expires_at = now() - interval '1 minute' WHERE tenant_id = %s",
            (seed["tenant"],),
        )
        recorder.submit(_call(seed, path="/new"))
        await recorder.flush()
        rows = await _fetch(
            pool,
            """SELECT s.call_count, array_agg(c.path) AS paths
               FROM apiome.mock_consumer_capture_session s
               JOIN apiome.mock_consumer_capture_call c ON c.session_id = s.id
               WHERE s.tenant_id = %s GROUP BY s.id""",
            (seed["tenant"],),
        )
        assert [(r["call_count"], r["paths"]) for r in rows] == [(1, ["/new"])]

    _run(body)


def test_the_session_cap_counts_the_overflow_on_the_tenant() -> None:
    async def body(pool: AsyncConnectionPool, seed: dict[str, Any], other: dict[str, Any]) -> None:
        recorder = ConsumerCaptureRecorder(pool, flush_interval_seconds=60)
        with patch.object(consumer_capture, "MAX_LIVE_SESSIONS_PER_TENANT", 1):
            recorder.submit(_call(seed, "a"))
            await recorder.flush()
            recorder.submit(_call(seed, "b"))
            recorder.submit(_call(seed, "b"))
            await recorder.flush()
        sessions = await _fetch(
            pool, "SELECT consumer FROM apiome.mock_consumer_capture_session WHERE tenant_id = %s", (seed["tenant"],)
        )
        assert [s["consumer"] for s in sessions] == ["a"]
        settings = (
            await _fetch(
                pool,
                "SELECT retention_days, refused_calls, last_refused_reason FROM apiome.mock_consumer_capture_settings "
                "WHERE tenant_id = %s",
                (seed["tenant"],),
            )
        )[0]
        assert (settings["retention_days"], settings["refused_calls"], settings["last_refused_reason"]) == (
            7,
            2,
            "too-many-sessions",
        )

    _run(body)


def test_the_sweeper_deletes_only_what_expired() -> None:
    async def body(pool: AsyncConnectionPool, seed: dict[str, Any], other: dict[str, Any]) -> None:
        recorder = ConsumerCaptureRecorder(pool, flush_interval_seconds=60)
        recorder.submit(_call(seed, "old"))
        recorder.submit(_call(seed, "kept", path="/a"))
        recorder.submit(_call(seed, "kept", path="/b"))
        await recorder.flush()
        await _fetch(
            pool,
            "UPDATE apiome.mock_consumer_capture_session SET expires_at = now() - interval '1 minute' "
            "WHERE tenant_id = %s AND consumer = 'old'",
            (seed["tenant"],),
        )
        await _fetch(
            pool,
            "UPDATE apiome.mock_consumer_capture_call SET expires_at = now() - interval '1 minute' "
            "WHERE tenant_id = %s AND path = '/a'",
            (seed["tenant"],),
        )
        await sweep_expired_captures(pool, batch_size=1)
        sessions = await _fetch(
            pool, "SELECT consumer FROM apiome.mock_consumer_capture_session WHERE tenant_id = %s", (seed["tenant"],)
        )
        calls = await _fetch(
            pool, "SELECT path FROM apiome.mock_consumer_capture_call WHERE tenant_id = %s", (seed["tenant"],)
        )
        assert [s["consumer"] for s in sessions] == ["kept"]
        assert [c["path"] for c in calls] == ["/b"]

    _run(body)
