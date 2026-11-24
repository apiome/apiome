"""DBP-1.22 (#7205) on a real database: budgets, plans' results and parity with the old tools.

Skipped unless ``APIOME_MCP_TEST_DATABASE_URL`` names a **migrated, disposable** PostgreSQL
database with the ``vector`` extension (the workflow's service database is not migrated, so CI
skips these; the SQL they cover is also pinned by ``apiome-db``'s plan check and schema tests)::

    createdb apiome_t7205
    node ../apiome-db/dist/cli.js migrate --database-url postgresql://localhost/apiome_t7205
    APIOME_MCP_TEST_DATABASE_URL=postgresql://localhost/apiome_t7205 uv run pytest tests/test_spec_tools_db.py

What they prove, against the acceptance criteria:

* the set-based loader returns exactly the rows of the per-operation loader it replaces, and the
  six spec tools run the same statements for a 10-operation and a 1,000-operation spec;
* a second call for an unchanged revision runs one statement (the resolve), and a write to the
  revision's rows rebuilds the document;
* ``spec.list``, ``spec.list_my_specs``-style authenticated lists, ``project.list``,
  ``spec.list_tags`` and ``spec.search`` return, page for page, what the pre-DBP-1.22 tools
  (``tests/legacy_*``) return for the same catalog and caller;
* ``spec.search_semantic`` returns the exact query's top results, from the HNSW index.

Each run seeds rows under a fresh label and deletes them afterwards.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import psycopg
import pytest

import legacy_project_list_tool
import legacy_spec_list_tags_tool
import legacy_spec_list_tool
import legacy_spec_openapi_loaders
import legacy_spec_search_tool
import legacy_spec_semantic_search_tool
from apiome_mcp import project_list_tool, spec_list_tags_tool, spec_list_tool, spec_search_tool
from apiome_mcp import spec_semantic_search_tool as semantic
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.settings import Settings
from apiome_mcp.spec_describe_component_tool import build_spec_describe_component_response
from apiome_mcp.spec_describe_operation_tool import build_spec_describe_operation_response
from apiome_mcp.spec_document_cache import DOCUMENT_CACHE
from apiome_mcp.spec_export_yaml_tool import build_spec_export_yaml_response
from apiome_mcp.spec_get_openapi_tool import build_spec_get_openapi_response
from apiome_mcp.spec_list_components_tool import build_spec_list_components_response
from apiome_mcp.spec_list_operations_tool import build_spec_list_operations_response
from apiome_mcp.spec_openapi_loaders import fetch_openapi_generation_inputs_async
from spec_db_fixture import cluster_vector, seed_catalog, seed_spec

DATABASE_URL = os.environ.get("APIOME_MCP_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set APIOME_MCP_TEST_DATABASE_URL to a migrated database")


# ==================================================================================================
# A pool that counts statements
# ==================================================================================================
class _CountingCursor:
    def __init__(self, cursor: Any, pool: CountingPool) -> None:
        self._cursor, self._pool = cursor, pool

    async def execute(self, sql: Any, params: Any = None) -> Any:
        self._pool.statements.append(str(sql))
        return await self._cursor.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _CountingConnection:
    def __init__(self, conn: Any, pool: CountingPool) -> None:
        self._conn, self._pool = conn, pool

    @asynccontextmanager
    async def cursor(self, *args: Any, **kwargs: Any) -> Any:
        async with self._conn.cursor(*args, **kwargs) as cur:
            yield _CountingCursor(cur, self._pool)

    async def execute(self, sql: Any, params: Any = None) -> Any:
        self._pool.statements.append(str(sql))
        return await self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class CountingPool:
    """Opens one autocommit connection per checkout (as the product pool does) and records SQL."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.statements: list[str] = []

    @asynccontextmanager
    async def connection(self) -> Any:
        from pgvector.psycopg import register_vector_async

        async with await psycopg.AsyncConnection.connect(self._url, autocommit=True) as conn:
            await register_vector_async(conn)
            yield _CountingConnection(conn, self)


# ==================================================================================================
# Seed data
# ==================================================================================================
@pytest.fixture(scope="module")
def seeded() -> Iterator[dict[str, Any]]:
    """Two specs (10 and 1,000 operations) and a catalog, committed; deleted after the module."""
    assert DATABASE_URL
    label = "t" + uuid.uuid4().hex[:10]
    with psycopg.connect(DATABASE_URL) as conn:
        data: dict[str, Any] = {
            "label": label,
            "small": seed_spec(conn, label=f"{label}-s", operations=10),
            "large": seed_spec(conn, label=f"{label}-l", operations=1000),
            "catalog": seed_catalog(conn, label=f"{label}-c"),
        }
        conn.commit()
    try:
        yield data
    finally:
        with psycopg.connect(DATABASE_URL) as conn:
            like = f"t-{label}-%"
            mine = "SELECT p.id FROM apiome.projects p JOIN apiome.tenants t ON t.id = p.tenant_id WHERE t.slug LIKE %s"
            # Paths first (operations, bodies and responses cascade, and their content rows must
            # go before the classes they reference), then classes (their properties cascade;
            # revisions and project properties do not cascade to them), then the rest.
            revisions = f"SELECT v.id FROM apiome.versions v WHERE v.project_id IN ({mine})"
            conn.execute(f"DELETE FROM apiome.version_path WHERE version_id IN ({revisions})", (like,))
            conn.execute(f"DELETE FROM apiome.classes WHERE version_id IN ({revisions})", (like,))
            conn.execute(f"DELETE FROM apiome.versions WHERE project_id IN ({mine})", (like,))
            conn.execute(f"DELETE FROM apiome.properties WHERE project_id IN ({mine})", (like,))
            conn.execute(f"DELETE FROM apiome.projects WHERE id IN ({mine})", (like,))
            conn.execute("DELETE FROM apiome.tenants WHERE slug LIKE %s", (like,))
            conn.execute("DELETE FROM apiome.users WHERE email LIKE %s", (f"{label}-%@apiome.local",))
            conn.commit()


@pytest.fixture
def pool() -> CountingPool:
    assert DATABASE_URL
    return CountingPool(DATABASE_URL)


@pytest.fixture(autouse=True)
def _large_payloads_and_no_audit() -> Iterator[None]:
    """Lift the payload cap (the 1,000-operation spec is large) and keep audits off the database."""
    with (
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
        patch("apiome_mcp.spec_export_yaml_tool.get_settings") as ys,
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit"),
        patch("apiome_mcp.spec_list_tool.schedule_mcp_private_access_audit_batch"),
        patch("legacy_spec_list_tool.schedule_mcp_private_access_audit_batch"),
    ):
        gs.return_value.openapi_max_json_bytes = ys.return_value.openapi_max_json_bytes = 1_000_000_000
        yield


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


# ==================================================================================================
# The loader and the spec tools
# ==================================================================================================
@pytest.mark.parametrize("size", ["small", "large"])
def test_set_based_loader_returns_the_rows_of_the_per_operation_loader(
    seeded: dict[str, Any], pool: CountingPool, size: str
) -> None:
    async def run() -> tuple[Any, Any, int, int]:
        async with pool.connection() as conn:
            new = await fetch_openapi_generation_inputs_async(conn, seeded[size])
            new_count = len(pool.statements)
            old = await legacy_spec_openapi_loaders.fetch_openapi_generation_inputs_async(conn, seeded[size])
            return new, old, new_count, len(pool.statements) - new_count

    new, old, new_count, old_count = asyncio.run(run())
    assert _canonical(new) == _canonical(old)
    assert new_count == 10
    operations = 10 if size == "small" else 1000
    # What it replaces: one statement per path and four per operation, plus five fixed ones.
    assert old_count == 5 + operations // 2 + 4 * operations


SPEC_TOOLS: dict[str, tuple[Callable[[Any, str], Any], int]] = {
    "spec.get_openapi": (lambda p, sid: build_spec_get_openapi_response(p, spec_id=sid), 12),
    "spec.export_yaml": (lambda p, sid: build_spec_export_yaml_response(p, spec_id=sid), 12),
    "spec.describe_operation": (
        lambda p, sid: build_spec_describe_operation_response(
            p, spec_id=sid, path="/resources00000/{id}", method="post"
        ),
        12,
    ),
    "spec.describe_component": (
        lambda p, sid: build_spec_describe_component_response(p, spec_id=sid, kind="schemas", name="Model00000"),
        12,
    ),
    "spec.list_operations": (lambda p, sid: build_spec_list_operations_response(p, spec_id=sid), 4),
    "spec.list_components": (lambda p, sid: build_spec_list_components_response(p, spec_id=sid), 5),
}


@pytest.mark.parametrize("tool", sorted(SPEC_TOOLS))
def test_spec_tool_statement_budget_at_10_and_1000_operations(seeded: dict[str, Any], tool: str) -> None:
    call, budget = SPEC_TOOLS[tool]
    counts = {}
    for size in ("small", "large"):
        DOCUMENT_CACHE.clear()
        pool = CountingPool(DATABASE_URL or "")
        asyncio.run(call(pool, str(seeded[size])))
        counts[size] = len(pool.statements)
        pool.statements.clear()
        asyncio.run(call(pool, str(seeded[size])))
        assert len(pool.statements) == 1, "an unchanged revision is served from the document cache"
    assert counts["small"] == counts["large"] == budget


def test_narrow_tools_agree_with_the_full_document(seeded: dict[str, Any], pool: CountingPool) -> None:
    sid = str(seeded["large"])
    operations = asyncio.run(build_spec_list_operations_response(pool, spec_id=sid))
    components = asyncio.run(build_spec_list_components_response(pool, spec_id=sid))
    DOCUMENT_CACHE.clear()
    document = asyncio.run(build_spec_get_openapi_response(pool, spec_id=sid))
    # With the document cached, both tools derive from it: same answers as their narrow loads.
    assert asyncio.run(build_spec_list_operations_response(pool, spec_id=sid)) == operations
    assert asyncio.run(build_spec_list_components_response(pool, spec_id=sid)) == components
    assert len(operations) == 1000
    assert {o["operation_id"] for o in operations} == {f"op{n}" for n in range(1000)}
    assert components["schemas"] == sorted(document["components"]["schemas"])
    assert components["securitySchemes"] == ["ApiKeyHeader", "ApiKeyQuery"]


def test_document_matches_one_generated_from_the_per_operation_loader(
    seeded: dict[str, Any], pool: CountingPool
) -> None:
    from app.openapi_generator import generate_openapi_spec

    sid = seeded["small"]
    document = asyncio.run(build_spec_get_openapi_response(pool, spec_id=str(sid)))

    async def legacy() -> Any:
        async with pool.connection() as conn:
            return await legacy_spec_openapi_loaders.fetch_openapi_generation_inputs_async(conn, sid)

    classes, properties, paths, security, servers = asyncio.run(legacy())
    label = seeded["label"]
    expected = generate_openapi_spec(
        f"t-{label}-s",
        f"p-{label}-s",
        "1.0.0",
        classes,
        properties,
        project_description="Seeded spec",
        version_db_id=str(sid),
        revision_metadata=None,
        paths_data=paths,
        security_scheme_rows=security,
        server_rows=servers,
        component_pin_rows=[],
    )
    assert _canonical(document) == _canonical(expected)


def test_a_write_to_the_revision_rebuilds_its_document(seeded: dict[str, Any], pool: CountingPool) -> None:
    sid = seeded["small"]
    before = asyncio.run(build_spec_get_openapi_response(pool, spec_id=str(sid)))
    with psycopg.connect(DATABASE_URL or "") as conn:
        conn.execute(
            "UPDATE apiome.path_operation_description SET summary = 'Renamed operation' WHERE operation_id = 'op0'"
            " AND path_operation_id IN (SELECT po.id FROM apiome.path_operation po JOIN apiome.version_path vp"
            " ON vp.id = po.version_path_id WHERE vp.version_id = %s)",
            (sid,),
        )
        conn.commit()
    after = asyncio.run(build_spec_get_openapi_response(pool, spec_id=str(sid)))
    assert before["paths"]["/resources00000/{id}"]["get"]["summary"] == "Operation 0"
    assert after["paths"]["/resources00000/{id}"]["get"]["summary"] == "Renamed operation"


# ==================================================================================================
# Listing parity with the pre-DBP-1.22 tools
# ==================================================================================================
def _pages(build: Callable[..., Any], pool: Any, *, limit: int, **kwargs: Any) -> list[dict[str, Any]]:
    """Every page of a paginated tool, each as returned (items, has_more, next_cursor)."""

    async def run() -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = await build(pool, limit=limit, cursor=cursor, **kwargs)
            pages.append(page)
            cursor = page["next_cursor"]
            if not page["has_more"]:
                return pages
            assert len(pages) < 10_000

    return asyncio.run(run())


def _callers(catalog: dict[str, Any]) -> dict[str, McpAuthContext | None]:
    tenant_a, tenant_b = catalog["tenants"]

    def key(tenant: Any, scope: Scope) -> McpAuthContext:
        return McpAuthContext(key_id=str(uuid.uuid4()), tenant_id=str(tenant), label="k", scope=scope)

    return {
        "anonymous": None,
        "key of tenant A": key(tenant_a, Scope()),
        "key of tenant B": key(tenant_b, Scope()),
        "key scoped to tenant B": key(tenant_a, Scope(tenants=[str(tenant_b)])),
        "key scoped to its own tenant": key(tenant_a, Scope(tenants=[str(tenant_a)])),
        "key scoped to three projects": key(
            tenant_a,
            Scope(projects=[str(p) for p in (*catalog["projects"][tenant_a][:2], catalog["projects"][tenant_b][0])]),
        ),
        "key whose scope has no valid id": key(tenant_a, Scope(projects=["not-a-uuid"])),
    }


def _filters(catalog: dict[str, Any]) -> dict[str, dict[str, str]]:
    tenant_a, tenant_b = catalog["tenants"]
    return {
        "no filter": {},
        "tenant A": {"tenant_id": str(tenant_a)},
        "tenant B": {"tenant_id": str(tenant_b)},
        "one project": {"project_id": str(catalog["projects"][tenant_a][0])},
        "a disabled project": {"project_id": str(catalog["projects"][tenant_a][2])},
        "tenant and project": {"tenant_id": str(tenant_b), "project_id": str(catalog["projects"][tenant_b][1])},
    }


CALLERS = [
    "anonymous",
    "key of tenant A",
    "key of tenant B",
    "key scoped to tenant B",
    "key scoped to its own tenant",
    "key scoped to three projects",
    "key whose scope has no valid id",
]
FILTERS = ["no filter", "tenant A", "tenant B", "one project", "a disabled project", "tenant and project"]


@pytest.mark.parametrize("filter_name", FILTERS)
@pytest.mark.parametrize("caller", CALLERS)
def test_spec_list_matches_the_view_based_tool(
    seeded: dict[str, Any], pool: CountingPool, caller: str, filter_name: str
) -> None:
    auth = _callers(seeded["catalog"])[caller]
    filters = _filters(seeded["catalog"])[filter_name]
    new = _pages(spec_list_tool.build_spec_list_response, pool, limit=7, auth_ctx=auth, **filters)
    old = _pages(legacy_spec_list_tool.build_spec_list_response, pool, limit=7, auth_ctx=auth, **filters)
    assert new == old


def test_spec_list_fixture_exercises_every_rule(seeded: dict[str, Any], pool: CountingPool) -> None:
    """The parity above is only worth something if the catalog lists some rows and hides others."""
    catalog = seeded["catalog"]
    tenant_a, tenant_b = catalog["tenants"]

    def items(caller: str, **filters: str) -> list[dict[str, Any]]:
        auth = _callers(catalog)[caller]
        pages = _pages(spec_list_tool.build_spec_list_response, pool, limit=100, auth_ctx=auth, **filters)
        return [i for page in pages for i in page["items"]]

    ours = {str(p) for ps in catalog["projects"].values() for p in ps}
    anonymous = [i for i in items("anonymous") if i["project_id"] in ours]
    # 24 projects, 8 of them disabled or deleted; two public published enabled revisions each.
    assert len(anonymous) == 16 * 2
    assert {i["version"] for i in anonymous} == {"1.0.0", "1.1.0"}
    own = [i for i in items("key of tenant A") if i["project_id"] in ours]
    assert len(own) == 16 * 2 + 8 * 2  # plus tenant A's private revisions
    assert {i["version"] for i in own if i["tenant_id"] == str(tenant_b)} == {"1.0.0", "1.1.0"}
    assert {i["version"] for i in own if i["tenant_id"] == str(tenant_a)} == {"1.0.0", "1.1.0", "2.0.0", "2.1.0"}
    tagged = next(i for i in anonymous if i["version"] == "1.0.0")
    assert tagged["tags"] == sorted(tagged["tags"]) and "stable" in tagged["tags"]
    assert items("key whose scope has no valid id") == []
    # Timestamps repeat, so the id tiebreak is exercised.
    stamps = [i["updated_at"] for i in anonymous]
    assert len(set(stamps)) < len(stamps)


@pytest.mark.parametrize("filter_name", FILTERS)
@pytest.mark.parametrize("caller", CALLERS)
def test_project_list_matches_the_view_based_tool(
    seeded: dict[str, Any], pool: CountingPool, caller: str, filter_name: str
) -> None:
    auth = _callers(seeded["catalog"])[caller]
    filters = _filters(seeded["catalog"])[filter_name]
    new = _pages(project_list_tool.build_project_list_response, pool, limit=5, auth_ctx=auth, **filters)
    old = _pages(legacy_project_list_tool.build_project_list_response, pool, limit=5, auth_ctx=auth, **filters)
    assert new == old


def test_project_list_shows_a_keys_own_private_activity(seeded: dict[str, Any], pool: CountingPool) -> None:
    catalog = seeded["catalog"]
    tenant_a = catalog["tenants"][0]
    ours = {str(p) for p in catalog["projects"][tenant_a]}

    def stamps(caller: str) -> dict[str, str]:
        auth = _callers(catalog)[caller]
        pages = _pages(project_list_tool.build_project_list_response, pool, limit=100, auth_ctx=auth)
        return {i["project_id"]: i["updated_at"] for p in pages for i in p["items"] if i["project_id"] in ours}

    anonymous, own = stamps("anonymous"), stamps("key of tenant A")
    assert set(anonymous) == set(own) and len(own) == 8
    assert all(own[p] >= anonymous[p] for p in own)
    assert any(own[p] > anonymous[p] for p in own), "a private revision is the newest in some project"


@pytest.mark.parametrize("limit", [1, 2, 50])
def test_spec_list_tags_matches_the_view_based_tool(seeded: dict[str, Any], pool: CountingPool, limit: int) -> None:
    spec_list_tags_tool.TAG_HISTOGRAM_CACHE.clear()
    new = _pages(spec_list_tags_tool.build_spec_list_tags_response, pool, limit=limit)
    cached_statements = len(pool.statements)
    old = _pages(legacy_spec_list_tags_tool.build_spec_list_tags_response, pool, limit=limit)
    assert new == old
    assert cached_statements == 1, "every page after the count is served from memory"
    tags = {i["tag"]: i["count"] for page in new for i in page["items"]}
    assert tags["stable"] >= 16 and "beta" not in tags  # beta tags only private revisions


def test_spec_list_tags_database_cursor_path_matches(seeded: dict[str, Any], pool: CountingPool) -> None:
    """With the cache off, every page after the first is answered by the cursor statement."""
    off = spec_list_tags_tool.TagHistogramCache(ttl_seconds=lambda: 0.0)
    old = _pages(legacy_spec_list_tags_tool.build_spec_list_tags_response, pool, limit=2)
    with patch("apiome_mcp.spec_list_tags_tool.TAG_HISTOGRAM_CACHE", off):
        new = _pages(spec_list_tags_tool.build_spec_list_tags_response, pool, limit=2)

        # A cursor the fresh histogram does not hold (a count that no longer exists).
        stale = spec_list_tags_tool.encode_spec_list_tags_cursor(10**6, "zzz")
        after = asyncio.run(spec_list_tags_tool.build_spec_list_tags_response(pool, limit=2, cursor=stale))
    assert new == old
    legacy_after = asyncio.run(legacy_spec_list_tags_tool.build_spec_list_tags_response(pool, limit=2, cursor=stale))
    assert after == legacy_after


@pytest.mark.parametrize("q", ["catalog", "payments", "revision 1.1.0", "stable", "beta", "nothing-matches-this"])
def test_spec_search_matches_the_view_based_tool(seeded: dict[str, Any], pool: CountingPool, q: str) -> None:
    new = _pages(spec_search_tool.build_spec_search_response, pool, limit=5, q=q)
    old = _pages(legacy_spec_search_tool.build_spec_search_response, pool, limit=5, q=q)
    assert new == old
    if q == "catalog":
        assert sum(len(p["items"]) for p in new) >= 32
    if q == "beta":
        # "beta" tags only private revisions, which have no public search document.
        label = seeded["label"]
        assert not [i for p in new for i in p["items"] if label in i["title"]]


# ==================================================================================================
# Semantic search
# ==================================================================================================
def _semantic(module: Any, pool: Any, vector: list[float], *, limit: int) -> list[dict[str, Any]]:
    settings = Settings.model_construct(openai_embedding_dimensions=len(vector))
    with (
        patch.object(module, "_fetch_query_embedding", AsyncMock(return_value=vector)),
        patch.object(module, "ensure_vector_registered", AsyncMock()),
    ):
        return _pages(module.build_spec_semantic_search_response, pool, limit=limit, settings=settings, q="payments")


@pytest.mark.parametrize("cluster", [0, 1, 2, 3])
def test_semantic_search_returns_the_exact_querys_top_results(
    seeded: dict[str, Any], pool: CountingPool, cluster: int
) -> None:
    """Acceptance: the HNSW-backed search returns what the exact (sequential) query returns."""
    vector = cluster_vector(cluster, 0)
    new = _semantic(semantic, pool, vector, limit=3)
    exact = _semantic(legacy_spec_semantic_search_tool, pool, vector, limit=3)
    new_items = [i for p in new for i in p["items"]]
    exact_items = [i for p in exact for i in p["items"]]
    assert len(exact_items) >= 16, "the fixture embeds one public revision per listed project"
    assert len(new_items) == min(len(exact_items), semantic.SEMANTIC_SEARCH_DEPTH)
    assert new_items == exact_items[: len(new_items)]
    assert [p["items"] for p in new] == [p["items"] for p in exact][: len(new)]
    # The nearest results are the query's own cluster.
    label = seeded["label"]
    ours = [i for i in new_items if label in i["title"]]
    assert ours[0]["rank_score"] > ours[-1]["rank_score"]


def test_semantic_search_statement_can_be_served_by_the_hnsw_index(seeded: dict[str, Any]) -> None:
    """The statement's shape and predicate fit ``idx_versions_mcp_public_listed_embedding_hnsw``.

    A test database is small enough that reading and sorting every row is cheapest, so sequential
    scans, bitmap scans and sorts are disabled here: what is checked is that the index *can*
    answer the statement (bare distance order, the index's predicate implied). That the planner
    picks it at catalog size was measured on the scale database with embeddings seeded (the plan
    is in the pull request of #7205; the scale seed has no embeddings to check it nightly).
    """
    from pgvector.psycopg import Vector, register_vector

    sql = semantic.build_semantic_search_query(has_cursor=False)
    with psycopg.connect(DATABASE_URL or "") as conn:
        register_vector(conn)
        conn.execute("SET LOCAL enable_seqscan = off")
        conn.execute("SET LOCAL enable_bitmapscan = off")
        conn.execute("SET LOCAL enable_sort = off")
        plan = conn.execute(
            "EXPLAIN (FORMAT JSON) " + sql,
            {"qv": Vector(cluster_vector(0, 0)), "depth": semantic.SEMANTIC_SEARCH_DEPTH, "lim": 51},
        ).fetchone()
    assert plan is not None
    assert "idx_versions_mcp_public_listed_embedding_hnsw" in json.dumps(plan[0])


def test_semantic_search_stops_at_the_paging_depth(seeded: dict[str, Any], pool: CountingPool) -> None:
    vector = cluster_vector(0, 0)
    with patch.object(semantic, "SEMANTIC_SEARCH_DEPTH", 5):
        pages = _semantic(semantic, pool, vector, limit=2)
    assert [len(p["items"]) for p in pages] == [2, 2, 1]
    assert pages[-1]["has_more"] is False and pages[-1]["next_cursor"] is None
    exact = _semantic(legacy_spec_semantic_search_tool, pool, vector, limit=5)
    assert [i for p in pages for i in p["items"]] == exact[0]["items"]
