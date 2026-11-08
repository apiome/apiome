"""MCP linting, grading and scoring against a migrated database — V2-MCP-EPIC-21 (#3644).

The epic's children built the pieces: the pure lint rule engine (#3682), the hygiene rules
(#3683), the annotation and error-design rules (#3684), score / grade / fingerprint persistence
(#3685) and the lint REST + re-lint routes (#3686). Their route tests replace the database with a
mock, so the round trip on the real schema — a score upserted into ``mcp_version_scores``, read
back, mirrored into the evidence log — was never shown. This module drives the real routes over
HTTP (``TestClient``) against a database migrated from empty by apiome-db, on version snapshots
persisted by the real :meth:`Database.record_mcp_discovery_version`, and checks the epic's
acceptance criteria:

* **End to end.** ``POST …/lint`` scores a snapshot and stores it; ``GET …/lint`` then serves
  that stored report (same score, grade and fingerprint); before any re-lint, ``GET`` computes
  the report live and writes nothing.
* **Dependent systems.** A re-lint records an ``apiome.mcp-lint`` evidence run that
  ``GET …/lint/evidence`` lists — once per distinct report, since the append-only log skips a
  report fingerprint it already holds.
* **Edge cases.** A snapshot that declares nothing still scores; re-linting twice keeps exactly
  one score row with a stable fingerprint; a poorly described tool scores below a well
  described one.
* **Errors and isolation.** Another tenant gets 404 and writes nothing; an unknown version, or a
  version of another endpoint, is 404.

Everything runs inside one transaction on a dedicated connection that is always rolled back, so the
database is left exactly as it was found. Skipped without a reachable migrated database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_catalog_routes
from app.auth import validate_authentication
from app.config import settings
from app.database import Database
from app.lint_evidence import MCP_SCANNER_ID
from app.main import app
from app.mcp_client import DiscoveryListings, DiscoverySurface, InitializeResult, ServerInfo

pytestmark = pytest.mark.requires_db

DISCOVERED_AT = datetime(2026, 11, 8, 14, 3, 0, tzinfo=timezone.utc)

#: A tool a lint rule set should be happy with: described, titled, with a typed input schema.
GOOD_TOOL = {
    "name": "get_forecast",
    "title": "Get forecast",
    "description": "Return the hourly weather forecast for a city for the next 48 hours.",
    "inputSchema": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name, e.g. Lisbon."}},
        "required": ["city"],
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": True},
}

#: The same tool with nothing to go on: no title, no description, an untyped schema.
POOR_TOOL = {"name": "do", "inputSchema": {"type": "object"}}


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


def _surface(*tools: Dict[str, Any]) -> DiscoverySurface:
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="weather", title="Weather", version="1.0"),
        capabilities={"tools": {}} if tools else {},
        instructions=None,
        raw={},
    )
    return DiscoverySurface.from_discovery(init, DiscoveryListings(tools=list(tools)))


class Catalog:
    """Two tenants, an endpoint with snapshots, and an HTTP client acting as a chosen tenant."""

    def __init__(self, db: Database, conn: Any) -> None:
        self.db = db
        self.conn = conn
        self.client = TestClient(app)
        suffix = uuid.uuid4().hex[:8]
        with conn.cursor() as cursor:
            self.tenant_id = self._tenant(cursor, f"lint-{suffix}")
            self.other_tenant_id = self._tenant(cursor, f"lint-other-{suffix}")
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', %s, 'x') "
                "RETURNING id::text AS id",
                (f"ada-{suffix}@example.com",),
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoint_id = self.endpoint("weather")
        self.act_as(self.tenant_id)

    @staticmethod
    def _tenant(cursor: Any, slug: str) -> str:
        cursor.execute(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (slug, slug),
        )
        return cursor.fetchone()["id"]

    def endpoint(self, slug: str) -> str:
        """Catalog an endpoint for the main tenant and return its id."""
        row = self.db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name=slug,
            base_slug=slug,
            endpoint_url=f"https://{slug}.example.com/mcp",
            transport="streamable_http",
        )
        return str(row["id"])

    def snapshot(self, surface: DiscoverySurface, endpoint_id: str = "") -> str:
        """Persist a version snapshot of ``surface`` the way discovery does; return its id."""
        persisted = self.db.record_mcp_discovery_version(
            endpoint_id or self.endpoint_id,
            version_row=surface.to_version_row(),
            capability_rows=surface.to_capability_rows(None),
            change_rows=[],
            discovered_at=DISCOVERED_AT,
        )
        return persisted["version_id"]

    def act_as(self, tenant_id: str) -> None:
        """Authenticate following requests as ``tenant_id``."""
        auth = {"tenant_id": tenant_id, "user_id": self.user_id, "auth_method": "jwt"}
        app.dependency_overrides[validate_authentication] = lambda: auth

    def url(self, version_id: str, suffix: str = "lint", endpoint_id: str = "") -> str:
        return (
            f"/v1/mcp/acme/endpoints/{endpoint_id or self.endpoint_id}"
            f"/versions/{version_id}/{suffix}"
        )

    def score_rows(self, version_id: str) -> List[Dict[str, Any]]:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT score, grade, report_fingerprint FROM apiome.mcp_version_scores "
                "WHERE version_id = %s::uuid",
                (version_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def evidence_runs(self, version_id: str) -> int:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS n FROM apiome.lint_evidence_runs "
                "WHERE mcp_version_id = %s::uuid AND scanner_id = %s",
                (version_id, MCP_SCANNER_ID),
            )
            return int(cursor.fetchone()["n"])


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> Iterator[Catalog]:
    """The lint routes wired to a real, migrated database inside one rolled-back transaction."""
    try:
        conn = psycopg2.connect(
            settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3
        )
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.mcp_version_scores') IS NOT NULL AS ok")
        ready = probe.fetchone()["ok"]
    if not ready:
        conn.close()
        pytest.skip("the MCP catalog migrations are not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(mcp_catalog_routes, "db", db)
    try:
        yield Catalog(db, conn)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        conn.rollback()
        conn.close()


# ===========================================================================
# End to end
# ===========================================================================


def test_before_a_relint_get_computes_live_and_writes_nothing(catalog: Catalog) -> None:
    version_id = catalog.snapshot(_surface(GOOD_TOOL))

    response = catalog.client.get(catalog.url(version_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "computed"
    assert body["reportFingerprint"]
    assert catalog.score_rows(version_id) == []
    assert catalog.evidence_runs(version_id) == 0


def test_a_relint_is_stored_and_then_served_from_storage(catalog: Catalog) -> None:
    version_id = catalog.snapshot(_surface(GOOD_TOOL, POOR_TOOL))

    relinted = catalog.client.post(catalog.url(version_id))
    assert relinted.status_code == 200, relinted.text
    computed = relinted.json()
    assert computed["source"] == "computed"
    assert computed["scoredAt"] is not None

    (row,) = catalog.score_rows(version_id)
    assert row["score"] == computed["score"]
    assert row["grade"] == computed["grade"]
    assert row["report_fingerprint"] == computed["reportFingerprint"]

    served = catalog.client.get(catalog.url(version_id)).json()
    assert served["source"] == "stored"
    for key in ("score", "grade", "reportFingerprint", "severityCounts", "ruleHits"):
        assert served[key] == computed[key], key
    assert len(served["findings"]) == len(computed["findings"])


def test_a_relint_is_recorded_as_lint_evidence_once_per_report(catalog: Catalog) -> None:
    version_id = catalog.snapshot(_surface(GOOD_TOOL))

    catalog.client.post(catalog.url(version_id))
    # The same snapshot re-linted again produces the same report fingerprint, which the
    # append-only evidence log already holds, so no duplicate run is added (CLX-1.1).
    catalog.client.post(catalog.url(version_id))

    assert catalog.evidence_runs(version_id) == 1
    evidence = catalog.client.get(catalog.url(version_id, "lint/evidence"))
    assert evidence.status_code == 200, evidence.text
    scanners = [run["scannerId"] for run in evidence.json()["runs"]]
    assert scanners == [MCP_SCANNER_ID]


# ===========================================================================
# Edge cases
# ===========================================================================


def test_relinting_twice_keeps_one_score_with_a_stable_fingerprint(catalog: Catalog) -> None:
    version_id = catalog.snapshot(_surface(GOOD_TOOL, POOR_TOOL))

    first = catalog.client.post(catalog.url(version_id)).json()
    second = catalog.client.post(catalog.url(version_id)).json()

    assert second["reportFingerprint"] == first["reportFingerprint"]
    assert (second["score"], second["grade"]) == (first["score"], first["grade"])
    assert len(catalog.score_rows(version_id)) == 1


def test_a_snapshot_that_declares_nothing_still_scores(catalog: Catalog) -> None:
    version_id = catalog.snapshot(_surface())

    response = catalog.client.post(catalog.url(version_id))

    assert response.status_code == 200, response.text
    assert 0 <= response.json()["score"] <= 100
    assert len(catalog.score_rows(version_id)) == 1


def test_a_poorly_described_tool_scores_below_a_well_described_one(catalog: Catalog) -> None:
    good = catalog.client.post(catalog.url(catalog.snapshot(_surface(GOOD_TOOL)))).json()
    other_endpoint = catalog.endpoint("terse")
    poor_version = catalog.snapshot(_surface(POOR_TOOL), other_endpoint)
    poor = catalog.client.post(catalog.url(poor_version, endpoint_id=other_endpoint)).json()

    assert poor["score"] < good["score"]
    assert len(poor["findings"]) > len(good["findings"])


# ===========================================================================
# Errors and tenant isolation
# ===========================================================================


def test_another_tenant_gets_404_and_writes_nothing(catalog: Catalog) -> None:
    version_id = catalog.snapshot(_surface(GOOD_TOOL))
    catalog.act_as(catalog.other_tenant_id)

    for method in ("get", "post"):
        assert getattr(catalog.client, method)(catalog.url(version_id)).status_code == 404
    assert catalog.client.get(catalog.url(version_id, "lint/evidence")).status_code == 404
    assert catalog.score_rows(version_id) == []
    assert catalog.evidence_runs(version_id) == 0


def test_an_unknown_version_or_one_from_another_endpoint_is_404(catalog: Catalog) -> None:
    other_endpoint = catalog.endpoint("elsewhere")
    foreign_version = catalog.snapshot(_surface(GOOD_TOOL), other_endpoint)

    assert catalog.client.post(catalog.url(str(uuid.uuid4()))).status_code == 404
    # A real version, but addressed under the wrong endpoint.
    assert catalog.client.post(catalog.url(foreign_version)).status_code == 404
    assert catalog.score_rows(foreign_version) == []
