"""Statement shapes of the MCP catalog reads after DBP-1.17 (#7200), without a database.

``tests/test_mcp_version_facts_db.py`` proves on a real database that these statements return the
same values as before and stay within their budgets. The tests here run everywhere: they count the
statements each read issues and pin the parts of the SQL the performance depends on, so a later
edit cannot quietly bring back an item join, a per-dimension query or an unindexable predicate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

from app import database as database_module
from app.database import Database, _mcp_kind_count_sql, _mcp_version_fact_sql

TENANT = "11111111-1111-1111-1111-111111111111"
ENDPOINT = "22222222-2222-2222-2222-222222222222"
MIGRATION = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts" / "V425__mcp_version_derived_facts_7200.sql"


def _statements(call: Callable[[Database], Any], rows: Any = None) -> List[Tuple[str, Tuple[Any, ...]]]:
    """Run ``call`` against a ``Database`` whose ``execute_query`` is recorded.

    Args:
        call: Invokes the read on the database it is given.
        rows: What each statement returns: a list (every statement), or a callable taking the
            statement's index and SQL.

    Returns:
        ``(sql with whitespace collapsed, params)`` per statement, in order.
    """
    seen: List[Tuple[str, Tuple[Any, ...]]] = []

    def record(self, query, params=None, *args, **kwargs):
        sql = " ".join(str(query).split())
        seen.append((sql, tuple(params or ())))
        if callable(rows):
            return rows(len(seen) - 1, sql)
        return list(rows or [])

    with patch.object(Database, "execute_query", record):
        call(Database.__new__(Database))
    for sql, params in seen:
        assert sql.count("%s") == len(params), "placeholders and parameters must line up"
    return seen


# ───────────────────────────── the fact expressions ─────────────────────────────


def test_a_fact_reads_its_column_and_recomputes_only_for_an_underived_snapshot():
    sql = _mcp_version_fact_sql("has_destructive", "apiome.mcp_version_has_destructive(cv.id)", absent="false")
    assert sql == (
        "(CASE WHEN cv.tool_count IS NOT NULL THEN cv.has_destructive "
        "WHEN cv.id IS NULL THEN false ELSE apiome.mcp_version_has_destructive(cv.id) END)"
    )
    # Without `absent` (the snapshot row always exists) there is no third branch.
    assert _mcp_version_fact_sql("change_count", "f(v.id)", version="v") == (
        "(CASE WHEN v.tool_count IS NOT NULL THEN v.change_count ELSE f(v.id) END)"
    )


def test_kind_counts_keep_the_bigint_type_count_gave_them():
    sql = _mcp_kind_count_sql("resource_template", version="v")
    assert sql.endswith("::bigint")
    assert "v.resource_template_count" in sql
    assert "apiome.mcp_version_kind_count(v.id, 'resource_template')" in sql
    assert set(Database._MCP_KIND_COUNT_EXPRS) == {"tool", "resource", "resource_template", "prompt"}


def test_no_fact_expression_reads_capability_items_inline():
    """The recomputation lives in SQL functions: an inline sub-select prices every row at its cost."""
    for sql in (
        Database._MCP_HAS_DESTRUCTIVE_EXPR,
        Database._MCP_READ_ONLY_ONLY_EXPR,
        Database._MCP_MAX_TOOL_PROPS_EXPR,
        *Database._MCP_KIND_COUNT_EXPRS.values(),
    ):
        assert "mcp_capability_items" not in sql and "SELECT" not in sql
        assert "cv.tool_count IS NOT NULL" in sql and "WHEN cv.id IS NULL" in sql


def test_every_recomputation_function_the_readers_call_is_defined_by_the_migration():
    migration = MIGRATION.read_text()
    called = set()
    for sql in (
        Database._MCP_HAS_DESTRUCTIVE_EXPR,
        Database._MCP_READ_ONLY_ONLY_EXPR,
        Database._MCP_MAX_TOOL_PROPS_EXPR,
        Database._MCP_INSIGHT_RANKED_SQL,
        *Database._MCP_KIND_COUNT_EXPRS.values(),
    ):
        called.update(re.findall(r"apiome\.(mcp_version_\w+)\(", sql))
    assert called == {
        "mcp_version_has_destructive",
        "mcp_version_read_only_only",
        "mcp_version_max_tool_props",
        "mcp_version_kind_count",
        "mcp_version_change_count",
    }
    for name in called:
        assert f"CREATE OR REPLACE FUNCTION apiome.{name}(" in migration
    # They only read, so they must not forbid a parallel plan for the statements that name them.
    assert migration.count("PARALLEL SAFE") >= len(called)


# ───────────────────────────── browse ─────────────────────────────


def test_browse_is_one_statement_that_joins_no_capability_item_and_groups_nothing():
    statements = _statements(lambda db: db.browse_mcp_endpoints(TENANT, limit=101))
    assert len(statements) == 1
    sql, params = statements[0]
    assert "JOIN apiome.mcp_capability_items" not in sql
    assert "GROUP BY" not in sql
    assert "cv.tool_count" in sql and "cv.max_tool_props" in sql
    for column in ("tool_count", "resource_count", "resource_template_count", "prompt_count"):
        assert f"AS {column}" in sql
    assert params[0] == TENANT and params[-1] == 101


# ───────────────────────────── faceted search ─────────────────────────────


def test_faceted_search_is_two_statements_whatever_the_filters():
    plain = _statements(lambda db: db.search_mcp_catalog_faceted(TENANT))
    filtered = _statements(
        lambda db: db.search_mcp_catalog_faceted(
            TENANT,
            grades=["A", "ungraded"],
            transports=["sse"],
            categories=["weather", "uncategorized"],
            safety=["has_destructive", "read_only_only"],
            complexity=["complex"],
            protocols=["2025-06-18", "unknown"],
            health=["failing"],
            visibility="public",
            tags=["beta", "untagged"],
            limit=25,
            cursor=["Server 10", ENDPOINT],
        )
    )
    assert len(plain) == len(filtered) == 2
    page_sql, page_params = filtered[0]
    counts_sql, counts_params = filtered[1]
    assert page_sql.endswith("ORDER BY e.name ASC, e.id ASC LIMIT %s OFFSET %s")
    # The counts describe the whole match: same filter parameters, no cursor, no limit.
    assert counts_params == page_params[: len(counts_params)]
    assert "Server 10" not in counts_params and 25 not in counts_params


def test_the_facet_counts_statement_reads_the_filtered_set_once():
    _, (sql, _params) = _statements(lambda db: db.search_mcp_catalog_faceted(TENANT, safety=["has_destructive"]))
    assert sql.startswith("WITH f AS MATERIALIZED (")
    assert sql.count("FROM apiome.mcp_endpoints e") == 1, "the filter runs once, not once per dimension"
    assert (
        "GROUP BY GROUPING SETS ((f.grade), (f.transport), (f.category), (f.complexity), (f.protocol), (f.health), ())"
        in sql
    )
    assert "JOIN f ON f.id = bt.endpoint_id GROUP BY bt.tag" in sql
    assert sql.endswith("ORDER BY dimension ASC, count DESC, label ASC NULLS LAST")


def test_each_grouping_mask_names_the_dimension_whose_bit_is_clear():
    """GROUPING(a, …, f) sets a bit per column *not* grouped by; the CASE must decode it right."""
    _, (sql, _params) = _statements(lambda db: db.search_mcp_catalog_faceted(TENANT))
    dimensions = [d for d, _key, _expr in Database._MCP_FACET_DIMENSIONS]
    assert dimensions == ["grade", "transport", "category", "complexity", "protocol", "health"]
    full = (1 << len(dimensions)) - 1
    for position, dimension in enumerate(dimensions):
        mask = full & ~(1 << (len(dimensions) - 1 - position))
        assert f"WHEN {mask} THEN '{dimension}'" in sql
        assert f"WHEN {mask} THEN f.{dimension}::text" in sql
    assert f"WHEN c.grouped = {full} THEN c.has_destructive" in sql


def _count_rows() -> List[Dict[str, Any]]:
    def row(dimension, label, count, **extra):
        return {
            "dimension": dimension,
            "label": label,
            "count": count,
            "has_destructive": None,
            "read_only_only": None,
            "untagged": None,
            **extra,
        }

    return [
        row("category", "weather", 3),
        row("category", None, 2),
        row("complexity", "simple", 4),
        row("complexity", "unknown", 1),
        row("grade", "A", 2),
        row("grade", None, 3),
        row("health", "healthy", 5),
        row("protocol", "2025-06-18", 5),
        row("tag", "beta", 2),
        row("total", None, 5, has_destructive=1, read_only_only=2, untagged=3),
        row("transport", "sse", 5),
    ]


def test_the_count_rows_fold_into_the_bundle_the_wire_model_reads():
    bundle = Database.__new__(Database)._mcp_facet_counts_from_rows(_count_rows())
    assert bundle["total"] == 5
    assert bundle["category_rows"] == [{"label": "weather", "count": 3}, {"label": None, "count": 2}]
    assert bundle["grade_rows"] == [{"label": "A", "count": 2}, {"label": None, "count": 3}]
    assert bundle["complexity_rows"] == [{"label": "simple", "count": 4}, {"label": "unknown", "count": 1}]
    assert bundle["tag_rows"] == [{"label": "beta", "count": 2}]
    assert bundle["safety_counts"] == {"has_destructive": 1, "read_only_only": 2, "untagged": 3}
    assert bundle["untagged_count"] == 3
    assert set(bundle) == {
        "total",
        "grade_rows",
        "transport_rows",
        "category_rows",
        "complexity_rows",
        "protocol_rows",
        "health_rows",
        "tag_rows",
        "safety_counts",
        "untagged_count",
    }


def test_an_empty_match_folds_to_zeros_and_empty_lists():
    empty_total = {
        "dimension": "total",
        "label": None,
        "count": 0,
        "has_destructive": 0,
        "read_only_only": 0,
        "untagged": 0,
    }
    for rows in ([empty_total], []):
        bundle = Database.__new__(Database)._mcp_facet_counts_from_rows(rows)
        assert bundle["total"] == 0
        assert all(bundle[key] == [] for key in bundle if key.endswith("_rows"))
        assert bundle["safety_counts"] == {"has_destructive": 0, "read_only_only": 0, "untagged": 0}
        assert bundle["untagged_count"] == 0


def test_the_faceted_search_bundle_carries_the_page_and_the_counts():
    def rows(index, _sql):
        return [{"id": ENDPOINT, "name": "Server"}] if index == 0 else _count_rows()

    captured: Dict[str, Any] = {}
    _statements(lambda db: captured.update(db.search_mcp_catalog_faceted(TENANT)), rows)
    assert captured["endpoints"] == [{"id": ENDPOINT, "name": "Server"}]
    assert captured["total"] == 5 and captured["untagged_count"] == 3


# ───────────────────────────── insight ─────────────────────────────


def _insight_rows(index: int, _sql: str) -> List[Dict[str, Any]]:
    if index == 1:
        return [
            {"kind": "change_leader", "endpoint_id": ENDPOINT, "name": "Busy", "item_type": None, "n": 12},
            {"kind": "top_capability", "endpoint_id": None, "name": "search", "item_type": "tool", "n": 4},
        ]
    summary = {
        "endpoint_count": 3,
        "published_count": 1,
        "public_count": 1,
        "private_count": 2,
        "discovered_count": 2,
        "tool_count": 10,
        "resource_count": 2,
        "resource_template_count": 0,
        "prompt_count": 1,
        "avg_score": 71.5,
        "scored_count": 2,
    }
    blank = {key: None for key in summary}

    def row(dimension, label, count, **extra):
        return {"dimension": dimension, "label": label, "count": count, "tool_counts": None, **blank, **extra}

    return [
        row("category", "weather", 2),
        row("category", None, 1),
        row("discovery", "changed", 2),
        row("discovery", None, 1),
        row("grade", "A", 1),
        row("grade", "C", 1),
        row("protocol", "2025-06-18", 2),
        row("total", None, 3, tool_counts=[6, 4, 0], **summary),
        row("transport", "sse", 3),
    ]


def test_the_insight_is_two_statements_and_folds_to_the_same_shape():
    captured: Dict[str, Any] = {}
    statements = _statements(lambda db: captured.update(db.get_mcp_catalog_insight(TENANT)), _insight_rows)
    assert len(statements) == 2
    scope_sql, scope_params = statements[0]
    ranked_sql, ranked_params = statements[1]
    assert scope_params == (TENANT,) and ranked_params == (TENANT, TENANT)
    assert scope_sql.startswith("WITH scope AS MATERIALIZED (")
    assert scope_sql.count("FROM apiome.mcp_endpoints e") == 1
    assert "mcp_capability_items" not in scope_sql, "per-kind totals come from the stored facts"
    assert "SUM((CASE WHEN v.tool_count IS NOT NULL THEN v.change_count" in ranked_sql

    assert captured["endpoint_count"] == 3 and captured["tool_count"] == 10 and captured["avg_score"] == 71.5
    assert captured["grade_distribution"] == {"A": 1, "C": 1}
    assert captured["category_rows"] == [{"label": "weather", "count": 2}, {"label": None, "count": 1}]
    assert captured["discovery_rows"] == [{"label": "changed", "count": 2}, {"label": None, "count": 1}]
    assert captured["protocol_rows"] == [{"label": "2025-06-18", "count": 2}]
    assert captured["transport_rows"] == [{"label": "sse", "count": 3}]
    assert captured["tool_count_rows"] == [{"tool_count": 6}, {"tool_count": 4}, {"tool_count": 0}]
    assert captured["change_leader_rows"] == [{"endpoint_id": ENDPOINT, "name": "Busy", "change_count": 12}]
    assert captured["top_capability_rows"] == [{"item_type": "tool", "item_name": "search", "endpoint_count": 4}]


def test_the_insight_grouping_masks_match_their_dimensions():
    sql = " ".join(Database._MCP_INSIGHT_SCOPE_SQL.split())
    assert "GROUPING(f.grade, f.category, f.transport, f.protocol, f.discovery)" in sql
    # Five columns: the grouped one has its bit clear (grade is the most significant).
    for mask, dimension in ((15, "grade"), (23, "category"), (27, "transport"), (29, "protocol"), (30, "discovery")):
        assert f"WHEN {mask} THEN '{dimension}'" in sql
        assert f"WHEN {mask} THEN f.{dimension}::text" in sql
    # Ungraded endpoints are no grade bucket; undiscovered endpoints report no protocol.
    assert "WHEN 15 THEN COUNT(*) FILTER (WHERE f.grade IS NOT NULL)" in sql
    assert "WHEN 29 THEN COUNT(*) FILTER (WHERE f.has_snapshot)" in sql
    assert "WHERE c.dimension = 'total' OR c.count > 0" in sql


# ───────────────────────────── evolution ─────────────────────────────


def test_the_evolution_series_is_one_statement_with_one_pass_over_the_changes():
    for limit, expected_params in ((None, (ENDPOINT,)), (50, (ENDPOINT, ENDPOINT, 50))):
        statements = _statements(lambda db, limit=limit: db.get_mcp_evolution_series(ENDPOINT, limit=limit))
        assert len(statements) == 1
        sql, params = statements[0]
        assert params == expected_params
        assert sql.count("FROM apiome.mcp_version_changes c") == 1
        assert "FROM apiome.mcp_capability_items" not in sql
        for column in ("v.tool_count", "v.resource_count", "v.resource_template_count", "v.prompt_count"):
            assert column in sql
        assert "ORDER BY v.version_seq ASC" in sql


# ───────────────────────────── similar servers ─────────────────────────────


def test_similar_servers_rank_and_limit_in_the_database():
    def rows(index, _sql):
        if index == 0:
            return [
                {
                    "target_capability_count": 3,
                    "endpoint_id": ENDPOINT,
                    "name": "Peer",
                    "slug": "peer",
                    "category": None,
                    "shared_count": 2,
                    "candidate_capability_count": 4,
                    "shared_capabilities": ["a", "b"],
                }
            ]
        return [{"endpoint_id": ENDPOINT, "name": "Peer", "slug": "peer", "category": None, "similarity": 0.9}]

    captured: Dict[str, Any] = {}
    statements = _statements(lambda db: captured.update(db.get_mcp_similar_servers(TENANT, ENDPOINT, limit=5)), rows)
    assert len(statements) == 2
    overlap_sql, overlap_params = statements[0]
    embedding_sql, embedding_params = statements[1]
    assert overlap_params == (ENDPOINT, TENANT, TENANT, ENDPOINT, 5)
    assert embedding_params == (ENDPOINT, TENANT, TENANT, ENDPOINT, 5)
    # Jaccard in SQL: exact ratio, then shared names, then name in code-point order (as Python sorts).
    assert "sc.shared_count::numeric / ((SELECT COUNT(*) FROM target)" in overlap_sql
    assert 'lower(e.name) COLLATE "C" ASC LIMIT %s' in overlap_sql
    assert "HAVING COUNT(t.name) > 0" in overlap_sql
    # Nearest neighbours by distance, with a limit — no vector leaves the database.
    assert embedding_sql.endswith("ORDER BY v.mcp_capability_embedding <=> t.embedding ASC LIMIT %s")
    assert "::text" not in embedding_sql
    for sql in (overlap_sql, embedding_sql):
        assert "e.tenant_id = %s::uuid AND e.deleted_at IS NULL" in sql

    assert captured["target_capability_count"] == 3
    assert captured["overlap_rows"] == [
        {
            "endpoint_id": ENDPOINT,
            "name": "Peer",
            "slug": "peer",
            "category": None,
            "shared_count": 2,
            "candidate_capability_count": 4,
            "shared_capabilities": ["a", "b"],
        }
    ]
    assert captured["embedding_rows"][0]["similarity"] == 0.9


def test_similar_servers_skip_the_embedding_statement_when_the_flag_is_off():
    no_peer = [{"target_capability_count": 2, "endpoint_id": None, "name": None}]
    captured: Dict[str, Any] = {}
    statements = _statements(
        lambda db: captured.update(db.get_mcp_similar_servers(TENANT, ENDPOINT, with_embeddings=False)), no_peer
    )
    assert len(statements) == 1
    # The target's count comes back even when no peer shares a name.
    assert captured == {"target_capability_count": 2, "overlap_rows": [], "embedding_rows": []}


def test_a_failing_embedding_read_degrades_to_overlap_only():
    def rows(index, _sql):
        if index == 1:
            raise RuntimeError('type "vector" does not exist')
        return [{"target_capability_count": 1, "endpoint_id": None}]

    captured: Dict[str, Any] = {}
    _statements(lambda db: captured.update(db.get_mcp_similar_servers(TENANT, ENDPOINT)), rows)
    assert captured["embedding_rows"] == [] and captured["target_capability_count"] == 1


# ───────────────────────────── duplicate hints ─────────────────────────────


def test_duplicate_hints_ask_only_for_endpoints_that_share_a_key():
    statements = _statements(lambda db: db.list_published_mcp_duplicate_hints(TENANT))
    assert len(statements) == 1
    sql, params = statements[0]
    assert params == (TENANT, TENANT, TENANT)
    assert sql.startswith("WITH local AS MATERIALIZED (")
    assert "v.surface_fingerprint = ANY(ARRAY( SELECT DISTINCT l.surface_fingerprint FROM local l" in sql
    assert "= ANY(ARRAY(SELECT DISTINCT l.dedup_key FROM local l))" in sql
    assert sql.count("e.published = true AND e.deleted_at IS NULL") == 2
    assert sql.count("e.tenant_id <> %s::uuid") == 2
    assert "ORDER BY t.slug ASC, e.name ASC, e.id ASC LIMIT" in sql


def test_the_dedup_key_is_the_expression_the_migration_indexes():
    """The planner uses an expression index only for the very same expression."""
    index = re.search(
        r"CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_published_dedup_key\s+"
        r"ON apiome\.mcp_endpoints \(\s*\((.*?)\)\s*\)\s*WHERE",
        MIGRATION.read_text(),
        re.S,
    )
    assert index is not None
    assert Database._MCP_ENDPOINT_DEDUP_KEY_EXPR.replace("e.endpoint_url", "endpoint_url") == index.group(1).strip()
    assert "CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_versions_surface_fingerprint" in MIGRATION.read_text()


def test_two_urls_that_normalize_alike_share_a_dedup_key():
    """The key is coarser than the normalization, so prefiltering on it can never lose a match."""
    from app.mcp_duplicate_detection import normalize_mcp_endpoint_url_for_dedup

    def key(url: str) -> str:
        # The SQL expression, evaluated in Python: lower(host) or the trimmed URL.
        host = re.search(r"://(?:[^@/]*@)?([^:/?#]+)", url)
        return host.group(1).lower() if host else url.strip(" \t\n\r")

    pairs = [
        ("https://Example.com/mcp/", "https://user:secret@example.com:443/mcp"),
        ("http://HOST.example.com:80/a?x=1", "http://host.example.com/a?x=1"),
        ("  npx  some-server ", "npx  some-server"),
        ("https://[::1]:443/mcp", "https://[::1]/mcp/"),
    ]
    for left, right in pairs:
        assert normalize_mcp_endpoint_url_for_dedup(left) == normalize_mcp_endpoint_url_for_dedup(right), (left, right)
        assert key(left) == key(right), (left, right)


# ───────────────────────────── semantic capability search ─────────────────────────────


def test_semantic_search_takes_the_nearest_first_and_applies_the_floor_outside(monkeypatch):
    executed: List[Tuple[str, Tuple[Any, ...]]] = []

    class Cursor:
        description = [("item_id",), ("semantic_similarity",), ("semantic_distance",)]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            executed.append((" ".join(sql.split()), params))

        def fetchall(self):
            return [("i1", 0.9, 0.1)]

    class Connection:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

    db = Database.__new__(Database)
    monkeypatch.setattr(Database, "connect", lambda self: Connection())
    monkeypatch.setattr(Database, "vector_ready", lambda self, conn: None)
    rows = db.search_mcp_capability_items_semantic(TENANT, [0.1, 0.2], limit=7, min_similarity=0.35, grade="A")

    sql, params = executed[0]
    inner = sql[sql.index("FROM (") : sql.index(") nearest")].strip()
    # No expression on the distance in the inner WHERE: the nearest `limit` are taken by ordering.
    assert "<=>" not in inner[inner.index("WHERE") : inner.index("ORDER BY")]
    assert inner.endswith(
        "ORDER BY ci.embedding <=> %s ASC, s.score DESC NULLS LAST, e.name ASC, ci.ordinal ASC LIMIT %s"
    )
    assert "WHERE nearest.semantic_similarity >= %s ORDER BY nearest.semantic_distance ASC" in sql
    assert params[-2:] == (7, 0.35)
    assert sql.count("%s") == len(params)
    # The ordering key is not part of the row the route receives.
    assert rows == [{"item_id": "i1", "semantic_similarity": 0.9}]


def test_the_module_no_longer_loads_every_embedding_as_text():
    source = Path(database_module.__file__).read_text()
    assert "def get_mcp_similar_candidates" not in source
    assert "mcp_capability_embedding::text" not in source
