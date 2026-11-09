"""MCP catalog categories & manual tags against a migrated database — V2-MCP-23.3 / MCAT-9.3 (#3693).

The unit tests pin the routes and the SQL text. What only a real schema shows is the acceptance
criterion — **endpoints can be categorized / tagged; facets filter browse / search** — so this module
drives the real :class:`~app.database.Database` on a database migrated by apiome-db and checks that:

* the built-in vocabulary is seeded and tenant categories sit beside it, counted and isolated;
* tag writes replace, keep and remove rows, and the per-tenant vocabulary counts live endpoints;
* the category and tag facets filter browse and faceted search (OR within, AND across, sentinels),
  and faceted search reports live tag buckets;
* the tag filter narrows full-text search;
* the V365 CHECK constraints reject unnormalized tags and slugs.

Everything runs inside one transaction on a dedicated connection that is always rolled back.
Skipped without a reachable database migrated to V365.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, List

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database
from app.mcp_categorization import BUILTIN_CATEGORIES

pytestmark = pytest.mark.requires_db


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


class Catalog:
    """Two tenants with MCP endpoints, read and written through the real Database."""

    def __init__(self, db: Database, conn: Any) -> None:
        self.db = db
        self.conn = conn
        suffix = uuid.uuid4().hex[:8]
        self.tenant_id = self._tenant(f"cat-{suffix}")
        self.other_tenant_id = self._tenant(f"other-{suffix}")
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', %s, 'x') "
                "RETURNING id::text AS id",
                (f"ada-{suffix}@example.com",),
            )
            self.user_id = cursor.fetchone()["id"]

    def _tenant(self, slug: str) -> str:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (slug, slug),
            )
            return cursor.fetchone()["id"]

    def add(
        self, slug: str, *, category: Any = None, description: str = "", tenant_id: Any = None
    ) -> str:
        row = self.db.insert_mcp_endpoint(
            tenant_id=tenant_id or self.tenant_id,
            creator_id=self.user_id,
            name=slug,
            base_slug=slug,
            endpoint_url=f"https://{slug}.example.com/mcp",
            transport="streamable_http",
            description=description or None,
            category=category,
        )
        return str(row["id"])

    def tag(self, endpoint_id: str, tags: List[str], *, tenant_id: Any = None) -> List[str]:
        return self.db.replace_mcp_endpoint_tags(
            tenant_id or self.tenant_id, endpoint_id, tags, self.user_id
        )

    def browse(self, **kwargs: Any) -> List[str]:
        return sorted(r["slug"] for r in self.db.browse_mcp_endpoints(self.tenant_id, **kwargs))

    def faceted(self, **kwargs: Any) -> Dict[str, Any]:
        return self.db.search_mcp_catalog_faceted(self.tenant_id, **kwargs)

    def sql(self, query: str, params: tuple = ()) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(query, params)


@pytest.fixture
def catalog() -> Iterator[Catalog]:
    """The Database wired to a real, migrated database inside one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(
            settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3
        )
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.mcp_endpoint_tags') IS NOT NULL AS ok")
        ready = probe.fetchone()["ok"]
    if not ready:
        conn.close()
        pytest.skip("V365 (mcp_categories / mcp_endpoint_tags) is not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        yield Catalog(db, conn)
    finally:
        conn.rollback()
        conn.close()


def test_builtins_are_seeded_and_tenant_categories_stay_in_their_tenant(catalog: Catalog) -> None:
    catalog.db.create_mcp_category(
        catalog.tenant_id, catalog.user_id, slug="weather", label="Weather",
        description=None, sort_order=5,
    )
    catalog.add("a", category="weather")
    catalog.add("b", category="Weather")
    catalog.add("c", category="databases")

    rows = catalog.db.list_mcp_categories(catalog.tenant_id)
    by_slug = {r["slug"]: r for r in rows}
    assert {s for s, _ in BUILTIN_CATEGORIES} <= set(by_slug)
    assert by_slug["weather"]["builtin"] is False
    assert by_slug["weather"]["endpoint_count"] == 2
    assert by_slug["databases"]["builtin"] is True
    assert by_slug["databases"]["endpoint_count"] == 1
    assert rows[0]["slug"] == "weather"  # sort_order 5 precedes every built-in

    other = {r["slug"] for r in catalog.db.list_mcp_categories(catalog.other_tenant_id)}
    assert "weather" not in other
    assert catalog.db.get_mcp_category(catalog.other_tenant_id, "weather") is None


def test_category_update_and_delete_never_touch_builtins(catalog: Catalog) -> None:
    catalog.db.create_mcp_category(
        catalog.tenant_id, None, slug="weather", label="Weather", description=None, sort_order=1
    )
    updated = catalog.db.update_mcp_category(
        catalog.tenant_id, "weather", {"label": "Forecasts", "description": "Sky"}
    )
    assert updated["label"] == "Forecasts" and updated["description"] == "Sky"
    assert catalog.db.update_mcp_category(catalog.tenant_id, "security", {"label": "X"}) is None
    assert catalog.db.delete_mcp_category(catalog.tenant_id, "security") is False
    assert catalog.db.get_mcp_category(catalog.tenant_id, "security")["builtin"] is True
    assert catalog.db.delete_mcp_category(catalog.tenant_id, "weather") is True
    assert catalog.db.get_mcp_category(catalog.tenant_id, "weather") is None


def test_duplicate_tenant_slug_is_a_unique_violation(catalog: Catalog) -> None:
    catalog.db.create_mcp_category(
        catalog.tenant_id, None, slug="weather", label="Weather", description=None, sort_order=1
    )
    with pytest.raises(psycopg2.errors.UniqueViolation):
        catalog.db.create_mcp_category(
            catalog.tenant_id, None, slug="weather", label="Other", description=None, sort_order=1
        )


def test_tag_writes_replace_and_remove(catalog: Catalog) -> None:
    ep = catalog.add("a")
    assert catalog.tag(ep, ["prod", "beta"]) == ["beta", "prod"]
    assert catalog.tag(ep, ["prod", "gold"]) == ["gold", "prod"]
    assert catalog.db.remove_mcp_endpoint_tag(ep, "gold") is True
    assert catalog.db.remove_mcp_endpoint_tag(ep, "gold") is False
    assert catalog.db.list_mcp_endpoint_tags(ep) == ["prod"]
    assert catalog.tag(ep, []) == []


def test_tag_vocabulary_counts_live_endpoints_of_the_tenant(catalog: Catalog) -> None:
    a, b, gone = catalog.add("a"), catalog.add("b"), catalog.add("gone")
    catalog.tag(a, ["prod", "beta"])
    catalog.tag(b, ["prod"])
    catalog.tag(gone, ["prod", "legacy"])
    catalog.sql("UPDATE apiome.mcp_endpoints SET deleted_at = now() WHERE id = %s::uuid", (gone,))
    foreign = catalog.add("x", tenant_id=catalog.other_tenant_id)
    catalog.tag(foreign, ["prod"], tenant_id=catalog.other_tenant_id)

    vocab = catalog.db.list_mcp_tag_vocabulary(catalog.tenant_id)
    assert vocab == [{"tag": "prod", "endpoint_count": 2}, {"tag": "beta", "endpoint_count": 1}]


def test_deleting_an_endpoint_row_removes_its_tags(catalog: Catalog) -> None:
    ep = catalog.add("a")
    catalog.tag(ep, ["prod"])
    catalog.sql("DELETE FROM apiome.mcp_endpoints WHERE id = %s::uuid", (ep,))
    assert catalog.db.list_mcp_endpoint_tags(ep) == []


def test_category_and_tag_facets_filter_browse(catalog: Catalog) -> None:
    a = catalog.add("a", category="weather")
    b = catalog.add("b", category="databases")
    catalog.add("c")
    catalog.tag(a, ["prod"])
    catalog.tag(b, ["prod", "beta"])

    assert catalog.browse() == ["a", "b", "c"]
    assert catalog.browse(tags=["prod"]) == ["a", "b"]
    assert catalog.browse(tags=["beta", "untagged"]) == ["b", "c"]
    assert catalog.browse(categories=["WEATHER", "uncategorized"]) == ["a", "c"]
    assert catalog.browse(categories=["weather"], tags=["beta"]) == []
    row = next(r for r in catalog.db.browse_mcp_endpoints(catalog.tenant_id) if r["slug"] == "b")
    assert row["tags"] == ["beta", "prod"]


def test_faceted_search_filters_on_tags_and_counts_tag_buckets(catalog: Catalog) -> None:
    a = catalog.add("a", category="weather")
    b = catalog.add("b", category="weather")
    catalog.add("c", category="databases")
    catalog.tag(a, ["prod"])
    catalog.tag(b, ["prod", "beta"])

    everything = catalog.faceted()
    assert everything["total"] == 3
    assert [(r["label"], r["count"]) for r in everything["tag_rows"]] == [("prod", 2), ("beta", 1)]
    assert everything["untagged_count"] == 1

    tagged = catalog.faceted(tags=["beta"])
    assert [e["slug"] for e in tagged["endpoints"]] == ["b"]
    assert tagged["endpoints"][0]["tags"] == ["beta", "prod"]
    assert [(r["label"], r["count"]) for r in tagged["tag_rows"]] == [("beta", 1), ("prod", 1)]
    assert tagged["untagged_count"] == 0

    narrowed = catalog.faceted(categories=["weather"], tags=["untagged"])
    assert narrowed["total"] == 0


def test_tag_filter_narrows_endpoint_search(catalog: Catalog) -> None:
    a = catalog.add("alpha", description="weather forecasts")
    catalog.add("bravo", description="weather radar")
    catalog.tag(a, ["prod"])

    hits = catalog.db.search_mcp_endpoints_fts(catalog.tenant_id, "weather")
    assert sorted(h["endpoint_slug"] for h in hits) == ["alpha", "bravo"]
    hits = catalog.db.search_mcp_endpoints_fts(catalog.tenant_id, "weather", tag="prod")
    assert [h["endpoint_slug"] for h in hits] == ["alpha"]


@pytest.mark.parametrize("bad", ["Prod", "has space", "-x", "a/b"])
def test_check_constraint_rejects_unnormalized_tags(catalog: Catalog, bad: str) -> None:
    ep = catalog.add("a")
    with pytest.raises(psycopg2.errors.CheckViolation):
        catalog.sql(
            "INSERT INTO apiome.mcp_endpoint_tags (endpoint_id, tenant_id, tag) "
            "VALUES (%s::uuid, %s::uuid, %s)",
            (ep, catalog.tenant_id, bad),
        )


@pytest.mark.parametrize("bad", ["Weather", "under_score", "-x"])
def test_check_constraint_rejects_invalid_category_slugs(catalog: Catalog, bad: str) -> None:
    with pytest.raises(psycopg2.errors.CheckViolation):
        catalog.sql(
            "INSERT INTO apiome.mcp_categories (tenant_id, slug, label) VALUES (%s::uuid, %s, 'X')",
            (catalog.tenant_id, bad),
        )
