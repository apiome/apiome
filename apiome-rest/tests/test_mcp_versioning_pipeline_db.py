"""The MCP versioning pipeline against a fully migrated database — V2-MCP-EPIC-18 (#3641).

The epic's children each proved their own part: the canonical fingerprint (#3668), the
surface diff engine (#3669), version-on-change (#3670), date/time tags (#3671) and the
compare API (#3672). Their engine tests replace the database with a mock, so what none of
them shows is the pipeline end to end on the real schema. This module drives the real
discovery job — :func:`app.mcp_discovery_engine._drive_discovery_job` with only the
network replaced by canned surfaces — through the real :class:`~app.database.Database`
against a database migrated from empty by apiome-db, and checks the epic's diagram:

* **First run.** Version 1 is created with its date/time tag; every capability is recorded as
  ``added``; the endpoint points at it; the job completes with the tag; the snapshot is
  scored and its conformance evidence recorded (the dependent systems).
* **Same surface.** No new version — the endpoint stamps ``unchanged`` and keeps pointing
  at version 1.
* **Changed surface.** Version 2 holds exactly the ``added`` / ``removed`` / ``modified``
  rows, the endpoint advances to it, and the compare API agrees with what was persisted.
* **Empty state.** A server that declares nothing still gets a version 1 with no items.
* **Error state.** A failing run marks the job failed with its error code, counts the
  failure, and creates no version.
* **Concurrent access.** A second enqueue while a job is active coalesces onto it, and two
  snapshots in the same minute get distinct tags (``…Z`` and ``…Z-2``) and sequences.

Concurrency is checked the way a single transaction can: the advisory-lock coalescing and
the in-minute tag/sequence collision. Two truly parallel committing transactions are out of
reach of a rolled-back test.

Everything runs inside one transaction on a dedicated connection that is always rolled back,
so the database is left exactly as it was found. Skipped when no migrated database is
reachable. To run against a throwaway server::

    createdb apiome && node --import tsx apiome-db/src/cli.ts --database-url "$URL" -y migrate
    DATABASE_URL="$URL" uv run pytest tests/test_mcp_versioning_pipeline_db.py -m requires_db
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_discovery_engine
from app.config import settings
from app.database import Database
from app.lint_evidence import MCP_CONFORMANCE_SCANNER_ID, MCP_SCANNER_ID
from app.mcp_client import (
    DiscoveryListings,
    DiscoverySurface,
    InitializeResult,
    McpHttpStatusError,
    ServerInfo,
)

pytestmark = pytest.mark.requires_db

#: When the first two runs happen; the third is a day later. Fixed so tags are predictable.
FIRST_RUN = datetime(2026, 11, 8, 14, 3, 12, tzinfo=timezone.utc)
SAME_MINUTE = datetime(2026, 11, 8, 14, 3, 48, tzinfo=timezone.utc)
NEXT_DAY = datetime(2026, 11, 9, 9, 30, 0, tzinfo=timezone.utc)


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
def pipeline(monkeypatch: pytest.MonkeyPatch) -> Iterator["Pipeline"]:
    """The discovery engine wired to a real database inside one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(
            settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3
        )
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute(
            "SELECT to_regclass('apiome.mcp_endpoint_versions') AS versions, "
            "EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'mcp_endpoint_versions' AND column_name = 'version_tag') AS tagged"
        )
        found = probe.fetchone()
    if not found["versions"] or not found["tagged"]:
        conn.close()
        pytest.skip("the MCP catalog migrations (V126-V131) are not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(mcp_discovery_engine, "db", db)
    # Credentials are read on their own connection; the seeded endpoint has none.
    monkeypatch.setattr(mcp_discovery_engine, "load_endpoint_auth_headers", lambda _endpoint_id: {})
    try:
        yield Pipeline(db, conn, monkeypatch)
    finally:
        conn.rollback()
        conn.close()


class Pipeline:
    """Seeds a tenant, user and endpoint, and runs discovery jobs against them."""

    def __init__(self, db: Database, conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db = db
        self.conn = conn
        self.monkeypatch = monkeypatch
        suffix = uuid.uuid4().hex[:8]
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"Versioning {suffix}", f"versioning-{suffix}"),
            )
            self.tenant_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES (%s, %s, 'x') "
                "RETURNING id::text AS id",
                ("Ada", f"ada-{suffix}@example.com"),
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoint = db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name="Weather",
            base_slug="weather",
            endpoint_url="https://mcp.example.com/mcp",
            transport="streamable_http",
        )
        self.endpoint_id = str(self.endpoint["id"])

    def run(self, outcome: Any, at: datetime) -> Dict[str, Any]:
        """Enqueue and drive one discovery job; return the finished job row.

        Args:
            outcome: The surface the "server" returns, or an exception it raises.
            at: The run's clock (drives ``discovered_at`` and the version tag).

        Returns:
            The finished ``mcp_discovery_jobs`` row.
        """

        async def runner(_endpoint: Dict[str, Any], _headers: Dict[str, str]) -> Any:
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        self.monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", runner)
        self.monkeypatch.setattr(mcp_discovery_engine, "_utcnow", lambda: at)
        enqueued = self.db.enqueue_mcp_discovery_job(self.endpoint_id, self.tenant_id, "manual")
        assert enqueued["deduplicated"] is False
        job_id = str(enqueued["job"]["id"])
        asyncio.run(mcp_discovery_engine._drive_discovery_job(job_id, self.endpoint))
        job = self.db.get_mcp_discovery_job(self.tenant_id, job_id)
        assert job is not None
        return job

    def versions(self) -> List[Dict[str, Any]]:
        """The endpoint's versions, oldest first."""
        return sorted(self.db.list_mcp_endpoint_versions(self.endpoint_id), key=lambda v: v["version_seq"])

    def endpoint_row(self) -> Dict[str, Any]:
        """The endpoint as it is now."""
        row = self.db.get_mcp_endpoint(self.tenant_id, self.endpoint_id)
        assert row is not None
        return row

    def changes(self, version_id: str) -> List[tuple]:
        """A version's change rows as sorted ``(change_type, item_type, item_name)``."""
        return sorted(
            (c["change_type"], c["item_type"], c["item_name"])
            for c in self.db.get_mcp_version_changes(version_id)
        )

    def evidence_scanners(self, version_id: str) -> List[str]:
        """The scanners that recorded an evidence run for a version, sorted."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT scanner_id FROM apiome.lint_evidence_runs WHERE mcp_version_id = %s::uuid "
                "ORDER BY scanner_id",
                (version_id,),
            )
            return [row["scanner_id"] for row in cursor.fetchall()]

    def count(self, sql: str, *params: Any) -> int:
        """Run a ``SELECT count(*) AS n …`` and return ``n``."""
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return int(cursor.fetchone()["n"])


def surface(*tools: Dict[str, Any], server_version: str = "1.0") -> DiscoverySurface:
    """A normalized surface declaring ``tools``."""
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="weather", title="Weather", version=server_version),
        capabilities={"tools": {}} if tools else {},
        instructions=None,
        raw={},
    )
    return DiscoverySurface.from_discovery(init, DiscoveryListings(tools=list(tools)))


def tool(name: str, description: str = "Get it.") -> Dict[str, Any]:
    """A tool definition as a server lists it."""
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}},
    }


# ===========================================================================
# The pipeline end to end
# ===========================================================================


def test_first_discovery_creates_version_one_with_its_tag_score_and_evidence(pipeline: Pipeline) -> None:
    job = pipeline.run(surface(tool("forecast"), tool("alerts")), FIRST_RUN)

    assert job["state"] == "completed"
    result = job["result"]
    assert result["changed"] is True
    assert result["version_seq"] == 1
    assert result["version_tag"] == "2026-11-08T14:03Z"
    assert result["counts"]["tool"] == 2

    (version,) = pipeline.versions()
    assert version["version_tag"] == "2026-11-08T14:03Z"
    assert version["discovery_trigger"] == "manual"
    assert pipeline.changes(str(version["id"])) == [
        ("added", "tool", "alerts"),
        ("added", "tool", "forecast"),
    ]
    endpoint = pipeline.endpoint_row()
    assert str(endpoint["current_version_id"]) == str(version["id"])
    assert endpoint["last_discovery_status"] == "changed"

    # The dependent systems the job feeds: the version's score, mirrored into the evidence log
    # under the MCP lint scanner, and its conformance report under its own scanner. Both captures
    # are best-effort and swallow their errors, so only their rows prove they ran.
    assert pipeline.count(
        "SELECT count(*) AS n FROM apiome.mcp_version_scores WHERE version_id = %s::uuid "
        "AND score IS NOT NULL",
        str(version["id"]),
    ) == 1
    assert pipeline.evidence_scanners(str(version["id"])) == [
        MCP_CONFORMANCE_SCANNER_ID,
        MCP_SCANNER_ID,
    ]


def test_the_same_surface_creates_no_new_version(pipeline: Pipeline) -> None:
    first = pipeline.run(surface(tool("forecast")), FIRST_RUN)
    again = pipeline.run(surface(tool("forecast")), NEXT_DAY)

    assert again["state"] == "completed"
    assert again["result"]["changed"] is False
    assert again["result"]["version_id"] == first["result"]["version_id"]
    assert again["result"]["fingerprint"] == first["result"]["fingerprint"]
    assert len(pipeline.versions()) == 1
    endpoint = pipeline.endpoint_row()
    assert str(endpoint["current_version_id"]) == first["result"]["version_id"]
    assert endpoint["last_discovery_status"] == "unchanged"


def test_a_changed_surface_creates_the_next_version_with_its_diff(pipeline: Pipeline) -> None:
    pipeline.run(surface(tool("forecast"), tool("alerts")), FIRST_RUN)
    job = pipeline.run(
        surface(tool("forecast", "Get the forecast, hourly."), tool("radar"), server_version="1.1"),
        NEXT_DAY,
    )

    assert job["result"]["changed"] is True
    assert job["result"]["version_seq"] == 2
    assert job["result"]["version_tag"] == "2026-11-09T09:30Z"
    first, second = pipeline.versions()
    assert pipeline.changes(str(second["id"])) == sorted(
        [
            ("added", "tool", "radar"),
            ("modified", "tool", "forecast"),
            ("modified", "server", "server_version"),
            ("removed", "tool", "alerts"),
        ]
    )
    assert job["result"]["change_count"] == 4
    assert str(pipeline.endpoint_row()["current_version_id"]) == str(second["id"])

    # The compare API recomputes the same diff from the two persisted snapshots.
    base = pipeline.db.get_mcp_endpoint_version(pipeline.endpoint_id, str(first["id"]))
    target = pipeline.db.get_mcp_endpoint_version(pipeline.endpoint_id, str(second["id"]))
    diff = mcp_discovery_engine.compare_endpoint_versions(base, target)
    recomputed = sorted(
        (row["change_type"], row["item_type"], row["item_name"]) for row in diff.to_change_rows(None)
    )
    assert recomputed == pipeline.changes(str(second["id"]))


def test_a_server_that_declares_nothing_still_gets_a_version(pipeline: Pipeline) -> None:
    job = pipeline.run(surface(), FIRST_RUN)

    assert job["state"] == "completed"
    assert job["result"]["counts"]["total"] == 0
    (version,) = pipeline.versions()
    assert pipeline.changes(str(version["id"])) == []
    assert pipeline.db.get_mcp_capability_items(str(version["id"])) == []


def test_a_failing_run_records_the_failure_and_creates_no_version(pipeline: Pipeline) -> None:
    job = pipeline.run(McpHttpStatusError(503, "down for maintenance"), FIRST_RUN)

    assert job["state"] == "failed"
    assert job["result"]["error"]["code"] == "http_status"
    assert pipeline.versions() == []
    endpoint = pipeline.endpoint_row()
    assert endpoint["current_version_id"] is None
    assert endpoint["last_discovery_status"] == "http_status"
    assert endpoint["consecutive_failures"] == 1


def test_a_success_after_a_failure_clears_the_failure_count(pipeline: Pipeline) -> None:
    pipeline.run(McpHttpStatusError(503), FIRST_RUN)
    pipeline.run(surface(tool("forecast")), NEXT_DAY)

    endpoint = pipeline.endpoint_row()
    assert endpoint["consecutive_failures"] == 0
    assert endpoint["last_discovery_status"] == "changed"


# ===========================================================================
# Concurrent access
# ===========================================================================


def test_a_second_enqueue_while_a_job_is_active_coalesces_onto_it(pipeline: Pipeline) -> None:
    first = pipeline.db.enqueue_mcp_discovery_job(pipeline.endpoint_id, pipeline.tenant_id, "manual")
    second = pipeline.db.enqueue_mcp_discovery_job(pipeline.endpoint_id, pipeline.tenant_id, "sweep")

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert str(second["job"]["id"]) == str(first["job"]["id"])
    assert pipeline.count(
        "SELECT count(*) AS n FROM apiome.mcp_discovery_jobs WHERE endpoint_id = %s::uuid",
        pipeline.endpoint_id,
    ) == 1


def test_two_snapshots_in_the_same_minute_get_distinct_tags_and_sequences(pipeline: Pipeline) -> None:
    pipeline.run(surface(tool("forecast")), FIRST_RUN)
    pipeline.run(surface(tool("forecast"), tool("radar")), SAME_MINUTE)

    first, second = pipeline.versions()
    assert (first["version_seq"], second["version_seq"]) == (1, 2)
    assert first["version_tag"] == "2026-11-08T14:03Z"
    assert second["version_tag"] == "2026-11-08T14:03Z-2"
