"""RDG-1.7 / SGD-3.1 (#4736) against a live Postgres: the SDK beacon SQL and its retention.

Runs :func:`app.sdk_beacon_store.ingest_beacons` / :func:`list_beacon_counts` over the real
:class:`~app.database.Database` and apiome-db V380, and the ``purge_usage_sdk_beacons`` retention
function the usage sweep calls. One rolled-back transaction per test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database
from app.sdk_beacon import SdkBeaconBatch
from app.sdk_beacon_store import ingest_beacons, list_beacon_counts
from app.usage_ingest import UsageIngestError
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db

NOW = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def seeded() -> Iterator[Tuple[Database, Any, Dict[str, str]]]:
    """A tenant with a project, a published and a draft revision, and an sdk_beacon source."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.usage_sdk_beacon_daily') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("V380 not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    suffix = uuid.uuid4().hex[:10]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO apiome.users (name, email, password, verified) VALUES ('o', %s, '', true) RETURNING id::text AS id",
                (f"owner-{suffix}@example.com",),
            )
            user = cur.fetchone()["id"]
            cur.execute("INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id", (suffix, f"t-{suffix}"))
            tenant = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, 'Pets', %s) RETURNING id::text AS id",
                (tenant, user, f"pets-{suffix}"),
            )
            project = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at) VALUES (%s, %s, '1.0.0', true, now()) RETURNING id::text AS id",
                (project, user),
            )
            published = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.versions (project_id, creator_id, version_id, published) VALUES (%s, %s, '2.0.0', false) RETURNING id::text AS id",
                (project, user),
            )
            draft = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.usage_source (tenant_id, project_id, kind, environment) VALUES (%s, %s, 'sdk_beacon', 'prod') RETURNING id::text AS id",
                (tenant, project),
            )
            source = cur.fetchone()["id"]
            yield db, cur, {"tenant": tenant, "project": project, "published": published, "draft": draft, "source": source}
    finally:
        conn.rollback()
        conn.close()


def _batch(revision: str, **overrides: Any) -> SdkBeaconBatch:
    event = {
        "sdk_name": "pets-go", "sdk_version": "1.0.0", "api_version": "1.0.0", "spec_revision_id": revision,
        "operation_id": "GET /pets/{petId}", "outcome": "incompatible", "count": 2,
    }
    event.update(overrides)
    return SdkBeaconBatch(events=[event])


def test_reports_upsert_daily_counters_and_read_back(seeded):
    db, _, ids = seeded
    for _ in range(2):
        ingest_beacons(db, tenant_id=ids["tenant"], source_ref=ids["source"], batch=_batch(ids["published"]), now=NOW)
    outcome = ingest_beacons(db, tenant_id=ids["tenant"], source_ref=ids["source"], batch=_batch(ids["draft"]), now=NOW)
    assert [r.reason for r in outcome.rejected] == ["revision-unknown"]
    (row,) = list_beacon_counts(db, tenant_id=ids["tenant"], project_id=ids["project"], days=1, today=NOW.date())
    assert row["calls"] == 4 and row["spec_revision_id"] == ids["published"] and row["operation_id"] == "GET /pets/{petId}"


def test_switching_the_source_off_stops_reports(seeded):
    db, cur, ids = seeded
    cur.execute("UPDATE apiome.usage_source SET enabled = false WHERE id = %s::uuid", (ids["source"],))
    with pytest.raises(UsageIngestError) as exc:
        ingest_beacons(db, tenant_id=ids["tenant"], source_ref=ids["source"], batch=_batch(ids["published"]), now=NOW)
    assert exc.value.code == "usage-source-disabled"


def test_the_database_refuses_anything_outside_the_vocabulary(seeded):
    _, cur, ids = seeded
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            """INSERT INTO apiome.usage_sdk_beacon_daily (tenant_id, project_id, source_id, day, spec_revision_id,
                   api_version, sdk_name, sdk_version, operation_id, outcome, calls, first_seen_at, last_seen_at)
               VALUES (%s, %s, %s, CURRENT_DATE, %s, '1.0.0', 'Jane Doe <jane@example.com>', '1', 'op', 'ok', 1, now(), now())""",
            (ids["tenant"], ids["project"], ids["source"], ids["published"]),
        )


def test_rows_age_out_with_the_tier_rollup_retention(seeded):
    db, cur, ids = seeded
    old = NOW - timedelta(days=200)
    ingest_beacons(db, tenant_id=ids["tenant"], source_ref=ids["source"], batch=_batch(ids["published"]), now=old)
    ingest_beacons(db, tenant_id=ids["tenant"], source_ref=ids["source"], batch=_batch(ids["published"]), now=NOW)
    cur.execute("SELECT apiome.purge_usage_sdk_beacons(%s, 10000) AS n", (NOW,))
    assert cur.fetchone()["n"] >= 1
    cur.execute("SELECT day FROM apiome.usage_sdk_beacon_daily WHERE tenant_id = %s::uuid", (ids["tenant"],))
    assert [row["day"] for row in cur.fetchall()] == [NOW.date()]
