"""The MCP public-endpoints read view against a real server — V2-MCP-15.6 / MCAT-1.6 (#3656).

``apiome.mcp_v_public_endpoints`` (V134) is the read model apiome-browse's public MCP pages sit
on. ``apiome-db/test/mcp-public-endpoints-view.test.ts`` pins the migration's SQL; what a text
check cannot prove is the ticket's acceptance criteria, which are about what a live server does:

* **Only published, public endpoints.** Of a tenant's endpoints, exactly the enabled, published,
  public-visible, non-deleted ones come back — a private, unpublished, disabled or soft-deleted
  endpoint never does.
* **No credentials.** The view's columns are an explicit allow-list with no secret-bearing column
  in it, the vault (``mcp_endpoint_credentials``) is never reachable through it, and a password
  embedded in an endpoint URL does not appear in any row — only the userinfo-stripped host does.
* **The query plan uses indexes.** With a realistic catalog — thousands of private endpoints and a
  handful of public ones — the planner answers the view from ``idx_mcp_endpoints_published_visibility``
  (V126), not a sequential scan.

V134's file name and header cite ``#3671``; that is a mislabel (the work is MCAT-1.6, this issue).
The migration is left unchanged because it has already been applied.

Marked ``requires_db`` and skipped without ``DATABASE_URL``. To run against an ephemeral server, no
installation required::

    pg_virtualenv -v 16 bash -c 'DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/$PGDATABASE" \\
        uv run pytest tests/test_mcp_public_endpoints_view_db.py -m requires_db'

Everything happens inside a transaction that is always rolled back, so a live database is left
exactly as it was found — which is also why the tables the MCP migrations reference are created
here rather than assumed. The MCP migrations themselves (V126–V130, V134) are applied verbatim.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

_db_url = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.requires_db,
    pytest.mark.skipif(
        not _db_url, reason="DATABASE_URL not set – skipping live-DB integration tests"
    ),
]

#: The migrations the view depends on, applied in order: endpoints (V126), capability items (V127,
#: which V128 constrains), versions (V128), the credential vault (V129, so the test can prove the
#: view never reaches it), scores (V130), and the view itself (V134).
MIGRATIONS = (
    "apiome-db/scripts/V126__mcp_catalog_endpoints_data_model_3651.sql",
    "apiome-db/scripts/V127__mcp_catalog_capability_items_3652.sql",
    "apiome-db/scripts/V128__mcp_catalog_versions_changes_3653.sql",
    "apiome-db/scripts/V129__mcp_catalog_credential_vault_3654.sql",
    "apiome-db/scripts/V130__mcp_catalog_scores_jobs_invocations_3655.sql",
    "apiome-db/scripts/V134__mcp_catalog_public_endpoints_view_3671.sql",
)

TENANT = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-0000000000aa"

#: The index the published/public filter must be answered from (V126).
PUBLIC_INDEX = "idx_mcp_endpoints_published_visibility"

#: Every column the view exposes, in order. An allow-list: adding a column to the view is a
#: deliberate act that has to be made here too, so nothing secret-bearing slips in unnoticed.
PUBLIC_COLUMNS = [
    "id",
    "tenant_id",
    "name",
    "slug",
    "category",
    "transport",
    "description",
    "current_version_id",
    "host",
    "score",
    "grade",
    "scored_at",
    "last_discovered_at",
    "updated_at",
]

#: Columns that hold, or could hold, secrets or internal-only state. None may be exposed.
FORBIDDEN_COLUMNS = {
    "endpoint_url",
    "metadata",
    "creator_id",
    "auth_type",
    "encrypted_payload",
    "key_version",
    "oauth_metadata",
}

#: A password embedded in an endpoint URL. It must never appear in anything the view returns.
URL_SECRET = "s3cret-hunter2"

#: How many private endpoints the plan test seeds around the public ones. Enough that a sequential
#: scan is the expensive choice, so the planner's pick reflects the index rather than a tiny table.
PRIVATE_ROWS = 5_000

#: The tables the MCP migrations reference but do not create, reduced to what they need: the
#: ``uuid_generate_v4`` default, the ``tenants`` and ``users`` foreign keys, and ``visibility_type``
#: (V006).
_PREREQUISITE_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS apiome;
SET search_path TO apiome, public;

CREATE TYPE apiome.visibility_type AS ENUM ('public', 'private');

CREATE TABLE apiome.tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL
);

CREATE TABLE apiome.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL
);
"""


def _migration_sql(relative: str) -> str:
    """One migration's SQL, read from the repository so the test applies exactly what ships.

    :param relative: The migration's path from the repository root.
    :returns: The file's contents.
    """
    root = Path(__file__).resolve().parents[2]
    return (root / relative).read_text("utf-8")


@pytest.fixture
def catalog() -> Iterator[Any]:
    """A connection holding the MCP catalog schema, inside a transaction that is always rolled back.

    :returns: A psycopg2 connection (``RealDictCursor`` rows) with V126–V130 and V134 applied and
        one tenant and one user seeded.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(_db_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cursor:
            cursor.execute(_PREREQUISITE_SCHEMA)
            for migration in MIGRATIONS:
                cursor.execute(_migration_sql(migration))
            cursor.execute(
                "INSERT INTO apiome.tenants (id, name) VALUES (%s::uuid, 'Acme')", (TENANT,)
            )
            cursor.execute(
                "INSERT INTO apiome.users (id, email) VALUES (%s::uuid, 'ada@example.com')", (USER,)
            )
        yield conn
    finally:
        conn.rollback()
        conn.close()


def add_endpoint(
    conn: Any,
    slug: str,
    *,
    published: bool = True,
    visibility: str = "public",
    enabled: bool = True,
    deleted: bool = False,
    url: Optional[str] = None,
    score: Optional[int] = None,
    grade: Optional[str] = None,
) -> str:
    """Catalog one endpoint, with a current version and — when ``score`` is given — its score.

    :param conn: The fixture's connection.
    :param slug: The endpoint's slug (also its name).
    :param published: Whether the endpoint is published.
    :param visibility: ``'public'`` or ``'private'``.
    :param enabled: Whether discovery is enabled for it.
    :param deleted: Whether it is soft-deleted.
    :param url: Its endpoint URL; defaults to ``https://<slug>.example.com/mcp``.
    :param score: The current version's 0-100 score; ``None`` leaves the version unscored.
    :param grade: The current version's letter grade, stored with ``score``.
    :returns: The new endpoint's id.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO apiome.mcp_endpoints
                (tenant_id, creator_id, name, slug, endpoint_url, transport,
                 visibility, published, enabled, deleted_at)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, 'streamable_http',
                    %s::apiome.visibility_type, %s, %s,
                    CASE WHEN %s THEN CURRENT_TIMESTAMP END)
            RETURNING id
            """,
            (
                TENANT,
                USER,
                slug,
                slug,
                url or f"https://{slug}.example.com/mcp",
                visibility,
                published,
                enabled,
                deleted,
            ),
        )
        endpoint_id = str(cursor.fetchone()["id"])
        cursor.execute(
            """
            INSERT INTO apiome.mcp_endpoint_versions (endpoint_id, version_seq)
            VALUES (%s::uuid, 1) RETURNING id
            """,
            (endpoint_id,),
        )
        version_id = str(cursor.fetchone()["id"])
        cursor.execute(
            "UPDATE apiome.mcp_endpoints SET current_version_id = %s::uuid WHERE id = %s::uuid",
            (version_id, endpoint_id),
        )
        if score is not None:
            cursor.execute(
                """
                INSERT INTO apiome.mcp_version_scores (version_id, score, grade)
                VALUES (%s::uuid, %s, %s)
                """,
                (version_id, score, grade),
            )
    return endpoint_id


def public_rows(conn: Any) -> List[Dict[str, Any]]:
    """Everything the view returns, ordered by slug.

    :param conn: The fixture's connection.
    :returns: The view's rows as dictionaries.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM apiome.mcp_v_public_endpoints ORDER BY slug")
        return [dict(row) for row in cursor.fetchall()]


class TestOnlyPublishedPublicEndpoints:
    """The filter: enabled, published, public-visible and live — nothing else."""

    def test_returns_exactly_the_published_public_endpoints(self, catalog: Any) -> None:
        add_endpoint(catalog, "listed")
        add_endpoint(catalog, "listed-too")
        add_endpoint(catalog, "private", visibility="private")
        add_endpoint(catalog, "unpublished", published=False)
        add_endpoint(catalog, "private-unpublished", visibility="private", published=False)
        add_endpoint(catalog, "disabled", enabled=False)
        add_endpoint(catalog, "deleted", deleted=True)

        assert [row["slug"] for row in public_rows(catalog)] == ["listed", "listed-too"]

    def test_unpublishing_or_hiding_an_endpoint_takes_it_out(self, catalog: Any) -> None:
        endpoint_id = add_endpoint(catalog, "listed")
        assert [row["slug"] for row in public_rows(catalog)] == ["listed"]

        with catalog.cursor() as cursor:
            cursor.execute(
                "UPDATE apiome.mcp_endpoints SET visibility = 'private' WHERE id = %s::uuid",
                (endpoint_id,),
            )
        assert public_rows(catalog) == []

        with catalog.cursor() as cursor:
            cursor.execute(
                """
                UPDATE apiome.mcp_endpoints SET visibility = 'public', published = false
                 WHERE id = %s::uuid
                """,
                (endpoint_id,),
            )
        assert public_rows(catalog) == []


class TestCurrentVersionScore:
    """The current snapshot's quality score and grade travel with the endpoint."""

    def test_joins_the_current_versions_score_and_grade(self, catalog: Any) -> None:
        add_endpoint(catalog, "scored", score=94, grade="A")

        (row,) = public_rows(catalog)
        assert row["score"] == 94
        assert row["grade"] == "A"
        assert row["scored_at"] is not None
        assert row["current_version_id"] is not None

    def test_keeps_an_unscored_endpoint_with_no_score(self, catalog: Any) -> None:
        add_endpoint(catalog, "unscored")

        (row,) = public_rows(catalog)
        assert row["slug"] == "unscored"
        assert row["score"] is None
        assert row["grade"] is None
        assert row["scored_at"] is None


class TestNoCredentials:
    """Nothing secret-bearing is exposed, whichever way a secret is stored."""

    def test_exposes_only_the_allow_listed_columns(self, catalog: Any) -> None:
        with catalog.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                 WHERE table_schema = 'apiome' AND table_name = 'mcp_v_public_endpoints'
                 ORDER BY ordinal_position
                """
            )
            columns = [row["column_name"] for row in cursor.fetchall()]

        assert columns == PUBLIC_COLUMNS
        assert FORBIDDEN_COLUMNS.isdisjoint(columns)

    def test_never_reads_the_credential_vault(self, catalog: Any) -> None:
        with catalog.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT table_name FROM information_schema.view_table_usage
                 WHERE view_schema = 'apiome' AND view_name = 'mcp_v_public_endpoints'
                 ORDER BY table_name
                """
            )
            tables = [row["table_name"] for row in cursor.fetchall()]

        assert tables == ["mcp_endpoints", "mcp_version_scores"]

    def test_a_password_in_the_url_never_appears(self, catalog: Any) -> None:
        endpoint_id = add_endpoint(
            catalog, "with-userinfo", url=f"https://alice:{URL_SECRET}@mcp.acme.dev:8443/mcp"
        )
        with catalog.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.mcp_endpoint_credentials
                    (endpoint_id, auth_type, encrypted_payload, key_version)
                VALUES (%s::uuid, 'bearer', %s, 1)
                """,
                (endpoint_id, URL_SECRET.encode("utf-8")),
            )

        (row,) = public_rows(catalog)
        assert row["host"] == "mcp.acme.dev"
        serialized = json.dumps(row, default=str)
        assert URL_SECRET not in serialized
        assert "alice" not in serialized


class TestQueryPlan:
    """The published/public filter is answered from its index, not a scan of the catalog."""

    def test_the_view_uses_the_published_visibility_index(self, catalog: Any) -> None:
        with catalog.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.mcp_endpoints
                    (tenant_id, creator_id, name, slug, endpoint_url, transport)
                SELECT %s::uuid, %s::uuid, 'private-' || n, 'private-' || n,
                       'https://private-' || n || '.example.com/mcp', 'streamable_http'
                  FROM generate_series(1, %s) AS n
                """,
                (TENANT, USER, PRIVATE_ROWS),
            )
        for index in range(3):
            add_endpoint(catalog, f"public-{index}", score=80 + index, grade="B")

        with catalog.cursor() as cursor:
            cursor.execute("ANALYZE apiome.mcp_endpoints")
            cursor.execute("ANALYZE apiome.mcp_version_scores")
            cursor.execute("EXPLAIN (FORMAT JSON) SELECT * FROM apiome.mcp_v_public_endpoints")
            plan = json.dumps(cursor.fetchone()["QUERY PLAN"])

        assert PUBLIC_INDEX in plan, plan
        assert "Seq Scan" not in _endpoint_scan_nodes(plan), plan
        assert len(public_rows(catalog)) == 3


def _endpoint_scan_nodes(plan_json: str) -> str:
    """The node types that read ``mcp_endpoints`` in an ``EXPLAIN (FORMAT JSON)`` plan.

    :param plan_json: The plan, serialized as JSON.
    :returns: The node types (e.g. ``"Bitmap Heap Scan"``) of every plan node whose relation is
        ``mcp_endpoints``, joined with commas.
    """
    found: List[str] = []

    def walk(node: Dict[str, Any]) -> None:
        if node.get("Relation Name") == "mcp_endpoints":
            found.append(str(node.get("Node Type")))
        for child in node.get("Plans", []):
            walk(child)

    for root in json.loads(plan_json):
        walk(root["Plan"])
    return ", ".join(found)
