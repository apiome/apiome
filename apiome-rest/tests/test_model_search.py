"""Cross-protocol search over the normalized model (MFI-6.2, #3754).

Pins four layers:

* the pure rules (:mod:`app.model_search`) — filter normalization, facet semantics (OR within a
  facet, AND across facets, counts ignore the facet's own selection, selected values always
  listed), display order, and the statement's shape (V135 index expressions verbatim, inline
  tsquery for index use, tenant scoping, latest-revision scope, the classic-store de-duplication);
* the route — validation, filters, paging, facet buckets, the cap flag;
* the backfill (:mod:`app.canonical_model_reindex`) — indexed / skipped / failed accounting;
* the import pipeline — every import persists its canonical model, best-effort except for the
  formats that always required it, and Arazzo is not written twice.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model_reindex import reindex_catalog_canonical_models
from app.conversion_job import ConversionError
from app.main import app
from app.model_search import (
    SEARCH_HIT_CAP,
    UNGRADED,
    ModelSearchFilters,
    build_model_search_sql,
    facet_counts,
    filter_hits,
    normalize_grade_filter,
    normalize_kind_filter,
    ordered_buckets,
)

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}

V135 = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V135__canonical_api_model_persistence_3739.sql"
)


def _row(element_id: str, *, kind="operation", paradigm="rpc", fmt="protobuf", grade="A",
         name=None, store="canonical") -> Dict[str, Any]:
    """A row in the shape ``search_normalized_model`` returns."""
    return {
        "kind": kind,
        "element_id": element_id,
        "name": name or element_id,
        "element_key": f"key.{element_id}",
        "detail": "request_response" if kind == "operation" else "record",
        "method": None,
        "path": None,
        "parent": "OrderService",
        "snippet": "Creates an order",
        "paradigm": paradigm,
        "format": fmt,
        "store": store,
        "rank": 0.5,
        "project_id": f"p-{element_id}",
        "project_slug": f"proj-{element_id}",
        "project_name": "Orders",
        "publishable": store == "openapi",
        "version_record_id": f"v-{element_id}",
        "version_label": "1.0.0",
        "quality_grade": grade,
    }


#: A cross-format result set: gRPC operation + type, AsyncAPI operation + message, OpenAPI op.
_ROWS = [
    _row("grpc-op", paradigm="rpc", fmt="protobuf", grade="A"),
    _row("grpc-type", kind="type", paradigm="rpc", fmt="protobuf", grade="A"),
    _row("async-op", paradigm="event", fmt="asyncapi-3", grade=None),
    _row("async-msg", kind="message", paradigm="event", fmt="asyncapi-3", grade=None),
    _row("oas-op", paradigm="rest", fmt="openapi", grade="C", store="openapi"),
]


# --- pure rules ---------------------------------------------------------------------------------


def test_kind_and_grade_normalization() -> None:
    assert normalize_kind_filter(" Operations ") == "operation"
    assert normalize_kind_filter("schema") == "type"
    assert normalize_kind_filter("messages") == "message"
    assert normalize_kind_filter("bogus") == "bogus"
    assert normalize_kind_filter("  ") is None
    assert normalize_grade_filter("b") == "B"
    assert normalize_grade_filter("None") == UNGRADED
    assert normalize_grade_filter("") is None


def test_filters_normalize_dedupe_and_accept_protocol_aliases() -> None:
    filters = ModelSearchFilters.from_query(
        kinds=["operation", "Operations", ""],
        protocols=["grpc", "RPC", "graphql"],
        formats=[" Protobuf "],
        grades=["a", "A", "ungraded"],
    )
    assert filters.kinds == ("operation",)
    assert filters.protocols == ("rpc", "graph")
    assert filters.formats == ("protobuf",)
    assert filters.grades == ("A", UNGRADED)


def test_no_filters_keep_every_hit() -> None:
    assert filter_hits(_ROWS, ModelSearchFilters()) == _ROWS


def test_values_or_within_a_facet_and_facets_and_together() -> None:
    either = ModelSearchFilters.from_query(protocols=["rpc", "rest"])
    assert [h["element_id"] for h in filter_hits(_ROWS, either)] == ["grpc-op", "grpc-type", "oas-op"]

    both = ModelSearchFilters.from_query(protocols=["rpc", "rest"], kinds=["operation"])
    assert [h["element_id"] for h in filter_hits(_ROWS, both)] == ["grpc-op", "oas-op"]

    graded = ModelSearchFilters.from_query(kinds=["operation"], grades=["ungraded"])
    assert [h["element_id"] for h in filter_hits(_ROWS, graded)] == ["async-op"]


def test_unknown_value_narrows_to_nothing() -> None:
    assert filter_hits(_ROWS, ModelSearchFilters.from_query(formats=["cobol"])) == []


def test_facet_counts_ignore_their_own_selection() -> None:
    filters = ModelSearchFilters.from_query(protocols=["rpc"], kinds=["operation"])
    counts = facet_counts(_ROWS, filters)
    # Protocol is counted over the operations (kind applied, protocol not): every paradigm shows.
    assert counts["protocol"] == {"rpc": 1, "event": 1, "rest": 1}
    # Kind is counted over the rpc rows (protocol applied, kind not).
    assert counts["kind"] == {"operation": 1, "type": 1}
    # Format and grade see both selections.
    assert counts["format"] == {"protobuf": 1}
    assert counts["grade"] == {"A": 1}


def test_selected_value_is_listed_even_at_zero() -> None:
    counts = facet_counts(_ROWS, ModelSearchFilters.from_query(formats=["cobol"]))
    assert counts["format"]["cobol"] == 0
    assert counts["format"]["protobuf"] == 2


def test_ungraded_bucket_counts_revisions_without_a_grade() -> None:
    counts = facet_counts(_ROWS, ModelSearchFilters())
    assert counts["grade"] == {"A": 2, UNGRADED: 2, "C": 1}


def test_ordered_buckets_fixed_vocabularies_then_count() -> None:
    assert ordered_buckets("kind", {"message": 1, "type": 5, "operation": 2}) == [
        ("operation", 2), ("type", 5), ("message", 1)
    ]
    assert ordered_buckets("grade", {UNGRADED: 9, "C": 1, "A": 2}) == [
        ("A", 2), ("C", 1), (UNGRADED, 9)
    ]
    assert ordered_buckets("format", {"protobuf": 2, "graphql": 2, "avro": 5}) == [
        ("avro", 5), ("graphql", 2), ("protobuf", 2)
    ]


# --- the statement ------------------------------------------------------------------------------


def _squash(text: str) -> str:
    """Collapse whitespace and drop table aliases (``o.name`` → ``name``) for comparison."""
    return re.sub(r"\b[a-z]\.", "", re.sub(r"\s+", " ", text)).strip()


@pytest.mark.parametrize(
    "index, alias",
    [("idx_api_operations_fts", "o"), ("idx_api_types_fts", "t"), ("idx_api_messages_fts", "m")],
)
def test_match_expressions_equal_the_v135_index_definitions(index: str, alias: str) -> None:
    """A drifted expression silently loses its GIN index; pin it to the migration text."""
    migration = V135.read_text()
    match = re.search(
        rf"CREATE INDEX IF NOT EXISTS {index}\s+ON \w+ USING gin \((to_tsvector\(.*?\))\);",
        migration,
        re.S,
    )
    assert match, f"{index} not found in V135"
    indexed = _squash(match.group(1))
    sql, _ = build_model_search_sql(tenant_id="t", query="x")
    predicates = re.findall(
        rf"AND (to_tsvector\('english', coalesce\({alias}\.name[^@]*?)\s*@@ websearch_to_tsquery",
        sql,
    )
    assert predicates, f"no predicate for alias {alias}"
    assert all(_squash(p) == indexed for p in predicates)


def test_statement_is_parameterized_and_tenant_scoped() -> None:
    sql, params = build_model_search_sql(tenant_id="tenant-1", query="createOrder'; drop", cap=50)
    assert params == {"query": "createOrder'; drop", "tenant_id": "tenant-1", "cap": 50}
    assert "createOrder" not in sql
    assert "p.tenant_id = %(tenant_id)s AND p.deleted_at IS NULL" in sql
    for alias in ("o", "t", "m", "a"):
        assert f"{alias}.tenant_id = %(tenant_id)s" in sql
    assert "LIMIT %(cap)s" in sql


def test_match_predicates_inline_the_tsquery_for_index_use() -> None:
    sql, _ = build_model_search_sql(tenant_id="t", query="x")
    assert sql.count("@@ websearch_to_tsquery('english', %(query)s)") == 5
    assert "@@ q.tsq" not in sql


def test_latest_revision_by_default_every_revision_on_request() -> None:
    latest, _ = build_model_search_sql(tenant_id="t", query="x")
    every, _ = build_model_search_sql(tenant_id="t", query="x", all_versions=True)
    assert "ORDER BY v.created_at DESC NULLS LAST, v.id DESC LIMIT 1" in latest
    assert "LIMIT 1" not in every


def test_classic_openapi_rows_only_for_revisions_without_a_canonical_artifact() -> None:
    sql, _ = build_model_search_sql(tenant_id="t", query="x")
    assert sql.count("WHERE NOT EXISTS (SELECT 1 FROM art WHERE art.version_id = s.version_pk)") == 2
    assert "JOIN apiome.path_operation po" in sql
    assert "JOIN apiome.classes c" in sql


def test_only_live_rows_are_searched() -> None:
    sql, _ = build_model_search_sql(tenant_id="t", query="x")
    for clause in ("a.deleted_at IS NULL", "o.deleted_at IS NULL", "t.deleted_at IS NULL",
                   "m.deleted_at IS NULL", "svc.deleted_at IS NULL", "c.deleted_at IS NULL",
                   "v.deleted_at IS NULL"):
        assert clause in sql


# --- the route ----------------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_route_returns_cross_format_hits_with_facets(authed) -> None:
    with patch("app.model_search_routes.db") as mock_db:
        mock_db.search_normalized_model.return_value = _ROWS
        response = client.get("/v1/search/test-tenant/model", params={"q": " createOrder "})
    assert response.status_code == 200
    body = response.json()
    mock_db.search_normalized_model.assert_called_once_with(
        tenant_id="test-tenant-id", query="createOrder", all_versions=False
    )
    assert body["query"] == "createOrder"
    assert body["total"] == body["matched"] == 5
    assert body["truncated"] is False
    assert {h["format"] for h in body["hits"]} == {"protobuf", "asyncapi-3", "openapi"}
    first = body["hits"][0]
    assert first["kind"] == "operation" and first["key"] == "key.grpc-op"
    assert first["format_label"]
    assert [b["value"] for b in body["facets"]["kinds"]] == ["operation", "type", "message"]
    assert body["facets"]["kinds"][0]["label"] == "Operations"
    grades = {b["value"]: b for b in body["facets"]["grades"]}
    assert grades[UNGRADED]["label"] == "Ungraded" and grades[UNGRADED]["count"] == 2


def test_route_filters_compose_and_mark_selected_buckets(authed) -> None:
    with patch("app.model_search_routes.db") as mock_db:
        mock_db.search_normalized_model.return_value = _ROWS
        response = client.get(
            "/v1/search/test-tenant/model",
            params=[("q", "order"), ("protocol", "grpc"), ("protocol", "rest"), ("kind", "operation"),
                    ("all_versions", "true")],
        )
    body = response.json()
    assert [h["element_id"] for h in body["hits"]] == ["grpc-op", "oas-op"]
    assert body["matched"] == 2 and body["total"] == 5
    selected = {b["value"] for b in body["facets"]["protocols"] if b["selected"]}
    assert selected == {"rpc", "rest"}
    assert mock_db.search_normalized_model.call_args.kwargs["all_versions"] is True


def test_route_pages_the_kept_hits(authed) -> None:
    with patch("app.model_search_routes.db") as mock_db:
        mock_db.search_normalized_model.return_value = _ROWS
        response = client.get("/v1/search/test-tenant/model", params={"q": "o", "limit": 2, "offset": 3})
    body = response.json()
    assert [h["element_id"] for h in body["hits"]] == ["async-msg", "oas-op"]
    assert body["offset"] == 3 and body["limit"] == 2


def test_route_flags_a_capped_result(authed) -> None:
    rows = [_row(f"r{i}") for i in range(SEARCH_HIT_CAP)]
    with patch("app.model_search_routes.db") as mock_db:
        mock_db.search_normalized_model.return_value = rows
        response = client.get("/v1/search/test-tenant/model", params={"q": "r"})
    assert response.json()["truncated"] is True


@pytest.mark.parametrize("q", ["   ", "x" * 201])
def test_route_rejects_blank_or_oversized_queries(authed, q: str) -> None:
    with patch("app.model_search_routes.db") as mock_db:
        response = client.get("/v1/search/test-tenant/model", params={"q": q})
    assert response.status_code == 422
    mock_db.search_normalized_model.assert_not_called()


def test_route_requires_q_and_bounds_paging(authed) -> None:
    assert client.get("/v1/search/test-tenant/model").status_code == 422
    assert client.get("/v1/search/test-tenant/model", params={"q": "x", "limit": 101}).status_code == 422
    assert client.get("/v1/search/test-tenant/model", params={"q": "x", "offset": -1}).status_code == 422


def test_route_requires_authentication() -> None:
    response = client.get("/v1/search/test-tenant/model", params={"q": "x"})
    assert response.status_code in (401, 403)


# --- the backfill -------------------------------------------------------------------------------


def _reindex_db(candidates: List[Dict[str, Any]]) -> MagicMock:
    db = MagicMock()
    db.list_catalog_versions_needing_canonical_reindex.return_value = candidates
    db.get_catalog_item_by_id.side_effect = lambda project_id, tenant_id: (
        None if project_id == "gone" else {"id": project_id}
    )
    return db


def _candidate(project_id: str) -> Dict[str, Any]:
    return {"tenant_id": "t1", "project_id": project_id, "version_id": f"v-{project_id}", "creator_id": "u1"}


def test_reindex_rebuilds_and_persists_each_candidate() -> None:
    db = _reindex_db([_candidate("grpc"), _candidate("graphql")])
    api = object()
    with patch("app.canonical_model_reindex.build_conversion_source") as build:
        build.return_value = MagicMock(api=api)
        summary = reindex_catalog_canonical_models(db, limit=10)
    db.list_catalog_versions_needing_canonical_reindex.assert_called_once_with(limit=10)
    build.assert_any_call({"id": "grpc"}, source_version_id="v-grpc")
    db.persist_canonical_api.assert_any_call(
        tenant_id="t1", creator_id="u1", version_id="v-grpc", model=api
    )
    assert summary["processed"] == 2 and summary["indexed"] == 2 and summary["failed"] == 0


def test_reindex_skips_items_without_a_source_and_records_failures() -> None:
    db = _reindex_db([_candidate("nosource"), _candidate("broken"), _candidate("gone"), _candidate("ok")])
    db.persist_canonical_api.side_effect = lambda **kw: None

    def build(item, source_version_id):
        if item["id"] == "nosource":
            raise ConversionError("no captured source", status_code=422)
        if item["id"] == "broken":
            raise RuntimeError("adapter bug")
        return MagicMock(api=object())

    with patch("app.canonical_model_reindex.build_conversion_source", side_effect=build):
        summary = reindex_catalog_canonical_models(db)
    assert summary["processed"] == 4
    assert summary["indexed"] == 1
    assert summary["skipped"] == 1 and summary["skips"][0]["projectId"] == "nosource"
    assert summary["failed"] == 2
    assert {f["projectId"] for f in summary["failures"]} == {"broken", "gone"}


def test_reindex_counts_a_failed_write_as_a_failure() -> None:
    db = _reindex_db([_candidate("grpc")])
    db.persist_canonical_api.side_effect = RuntimeError("constraint")
    with patch("app.canonical_model_reindex.build_conversion_source") as build:
        build.return_value = MagicMock(api=object())
        summary = reindex_catalog_canonical_models(db)
    assert summary["indexed"] == 0 and summary["failed"] == 1
    assert summary["failures"][0]["reason"] == "constraint"


def test_reindex_candidates_are_latest_catalog_revisions_without_an_artifact() -> None:
    from app.database import Database

    database = Database.__new__(Database)
    with patch.object(Database, "execute_query", return_value=[]) as execute:
        database.list_catalog_versions_needing_canonical_reindex(limit=5)
    sql, params = execute.call_args.args
    assert "p.publishable = false" in sql
    assert "ORDER BY v.created_at DESC NULLS LAST, v.id DESC" in sql
    assert "a.version_id = lv.id AND a.deleted_at IS NULL" in sql
    assert sql.rstrip().endswith("LIMIT %s") and params == (5,)


# --- the import pipeline ------------------------------------------------------------------------


def _persist(model: Any, *, creator_id: str = "u1", fail: bool = False) -> MagicMock:
    """Run the pipeline's canonical-persistence step for ``model`` against a mock db."""
    from app import import_source_pipeline as pipeline

    db = MagicMock()
    if fail:
        db.persist_canonical_api.side_effect = RuntimeError("boom")
    pipeline._persist_canonical_model(
        db,
        tenant_id="t1",
        creator_id=creator_id,
        version_record_id="v1",
        model=model,
        required=False,
    )
    return db


def test_canonical_persistence_is_best_effort_when_not_required() -> None:
    model = MagicMock(format="protobuf")
    db = _persist(model, fail=True)
    db.persist_canonical_api.assert_called_once_with(
        tenant_id="t1", creator_id="u1", version_id="v1", model=model
    )


def test_canonical_persistence_raises_when_required() -> None:
    from app import import_source_pipeline as pipeline

    db = MagicMock()
    db.persist_canonical_api.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        pipeline._persist_canonical_model(
            db, tenant_id="t1", creator_id="u1", version_record_id="v1",
            model=MagicMock(format="asyncapi-3"), required=True,
        )


def test_pipeline_persists_every_format_once_and_leaves_arazzo_to_its_helper() -> None:
    """The persist step is unconditional except for Arazzo (whose helper writes the artifact)."""
    source = Path(__file__).resolve().parents[1].joinpath(
        "src", "app", "import_source_pipeline.py"
    ).read_text()
    body = source[source.index("def persist_adapter_import("):source.index("def _record_spec_owner_suggestions(")]
    assert "if creator_id and model.format not in ARAZZO_WORKFLOW_FORMATS:" in body
    assert body.count("_persist_canonical_model(") == 1
    assert "db.persist_canonical_api(" not in body
    assert "required=is_asyncapi or bool(model.agents)" in body
