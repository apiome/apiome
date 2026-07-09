"""API + SQL-clause + projection tests for the faceted catalog search (V2-MCP-35.1 / MCAT-21.1, #4660).

Covers the tenant-scoped ``GET /v1/mcp/{tenant_slug}/facets`` route — facet filters over grade /
transport / category / safety / complexity / protocol / health with live bucket counts — plus the
composable facet WHERE-clause builder (:meth:`Database._mcp_facet_filter_clauses`, where the
multi-facet AND / within-facet OR semantics live) and the wire projections
(:func:`mcp_faceted_search_response_from_bundle`, and the facet fields on the browse endpoint
projection). The SQL itself runs against a live database elsewhere; here
``app.mcp_catalog_routes.db`` is mocked so the suite stays DB-free, asserting the route
normalizes and dispatches the right (token-scoped) arguments and projects what it gets back.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.models import (
    mcp_browse_endpoint_out_from_row,
    mcp_faceted_search_response_from_bundle,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


def _endpoint_row(**overrides):
    """A :meth:`Database.search_mcp_catalog_faceted` endpoint row, overridable per test."""
    row = {
        "id": "ep-1",
        "name": "Acme Weather",
        "slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/sse",
        "transport": "streamable_http",
        "description": "Weather tools",
        "category": "weather",
        "visibility": "private",
        "published": False,
        "enabled": True,
        "last_discovered_at": None,
        "last_discovery_status": "unchanged",
        "quarantined_at": None,
        "current_version_id": "ver-1",
        "score": 87,
        "grade": "B",
        "server_branding": None,
        "protocol_version": "2025-06-18",
        "health": "healthy",
        "has_destructive": True,
        "read_only_only": False,
        "complexity_band": "moderate",
        "tool_count": 3,
        "resource_count": 1,
        "resource_template_count": 0,
        "prompt_count": 0,
    }
    row.update(overrides)
    return row


def _bundle(**overrides):
    """A full :meth:`Database.search_mcp_catalog_faceted` bundle with one match."""
    bundle = {
        "endpoints": [_endpoint_row()],
        "total": 1,
        "grade_rows": [{"label": "B", "count": 1}],
        "transport_rows": [{"label": "streamable_http", "count": 1}],
        "category_rows": [{"label": "weather", "count": 1}],
        "safety_counts": {"has_destructive": 1, "read_only_only": 0},
        "complexity_rows": [{"label": "moderate", "count": 1}],
        "protocol_rows": [{"label": "2025-06-18", "count": 1}],
        "health_rows": [{"label": "healthy", "count": 1}],
    }
    bundle.update(overrides)
    return bundle


_EMPTY_BUNDLE = {
    "endpoints": [],
    "total": 0,
    "grade_rows": [],
    "transport_rows": [],
    "category_rows": [],
    "safety_counts": {"has_destructive": 0, "read_only_only": 0},
    "complexity_rows": [],
    "protocol_rows": [],
    "health_rows": [],
}


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# Facet WHERE-clause builder — the AND/OR semantics
# ===========================================================================


def test_no_filters_yield_no_clauses():
    clauses, params = db._mcp_facet_filter_clauses()
    assert clauses == []
    assert params == []


def test_each_supplied_facet_contributes_exactly_one_clause():
    """Multi-facet AND semantics: one clause per dimension, ANDed in by the caller."""
    clauses, _ = db._mcp_facet_filter_clauses(
        grades=["A"],
        transports=["sse"],
        categories=["weather"],
        safety=["has_destructive"],
        complexity=["simple"],
        protocols=["2025-06-18"],
        health=["healthy"],
        visibility="private",
    )
    assert len(clauses) == 8


def test_within_facet_values_or_via_any():
    clauses, params = db._mcp_facet_filter_clauses(grades=["A", "B"])
    assert clauses == ["(upper(s.grade) = ANY(%s))"]
    assert params == [["A", "B"]]


def test_grade_ungraded_sentinel_ors_an_is_null_predicate():
    clauses, params = db._mcp_facet_filter_clauses(grades=["A", "ungraded"])
    assert clauses == ["(upper(s.grade) = ANY(%s) OR s.grade IS NULL)"]
    assert params == [["A"]]


def test_uncategorized_sentinel_selects_null_or_blank_category():
    clauses, params = db._mcp_facet_filter_clauses(categories=["Weather", "uncategorized"])
    assert clauses == [
        "(lower(e.category) = ANY(%s) OR (e.category IS NULL OR e.category = ''))"
    ]
    # Category matching is case-insensitive: values are lowered to match lower(e.category).
    assert params == [["weather"]]


def test_unknown_protocol_sentinel_selects_null_protocol():
    clauses, params = db._mcp_facet_filter_clauses(protocols=["unknown"])
    assert clauses == ["(cv.protocol_version IS NULL)"]
    assert params == []


def test_safety_values_or_the_posture_expressions():
    clauses, params = db._mcp_facet_filter_clauses(
        safety=["has_destructive", "read_only_only"]
    )
    assert len(clauses) == 1
    assert "destructiveHint" in clauses[0]
    assert "readOnlyHint" in clauses[0]
    assert " OR " in clauses[0]
    assert params == []


def test_health_clause_uses_the_derived_case_expression():
    clauses, params = db._mcp_facet_filter_clauses(health=["failing", "quarantined"])
    assert len(clauses) == 1
    assert "consecutive_failures" in clauses[0]
    assert "quarantined_at" in clauses[0]
    assert params == [["failing", "quarantined"]]


def test_visibility_is_a_single_valued_equality():
    clauses, params = db._mcp_facet_filter_clauses(visibility="public")
    assert clauses == ["e.visibility = %s"]
    assert params == ["public"]


# ===========================================================================
# Wire projections
# ===========================================================================


def test_browse_projection_carries_facet_fields():
    out = mcp_browse_endpoint_out_from_row(_endpoint_row())
    assert out.protocol_version == "2025-06-18"
    assert out.health == "healthy"
    assert out.has_destructive is True
    assert out.read_only_only is False
    assert out.complexity_band == "moderate"
    assert out.version_count == 0


def test_browse_projection_carries_version_count():
    out = mcp_browse_endpoint_out_from_row(_endpoint_row(version_count=4))
    assert out.version_count == 4


def test_browse_projection_facet_fields_default_on_older_rows():
    """A row without the facet columns (older query shape / mocks) still projects totally."""
    row = _endpoint_row(last_discovered_at="2026-07-01T00:00:00+00:00")
    for key in ("protocol_version", "health", "has_destructive", "read_only_only", "complexity_band"):
        row.pop(key)
    out = mcp_browse_endpoint_out_from_row(row)
    assert out.protocol_version is None
    # Health falls back to deriving from the row's own columns (discovered + no failures).
    assert out.health == "healthy"
    assert out.has_destructive is False
    assert out.read_only_only is False
    assert out.complexity_band == "unknown"


def test_bundle_projection_maps_null_buckets_to_sentinels():
    bundle = _bundle(
        grade_rows=[{"label": "A", "count": 2}, {"label": None, "count": 1}],
        category_rows=[{"label": None, "count": 3}],
        protocol_rows=[{"label": None, "count": 3}],
        health_rows=[{"label": "undiscovered", "count": 3}],
    )
    out = mcp_faceted_search_response_from_bundle(bundle, limit=100, offset=0)
    assert [(b.label, b.count) for b in out.facets.grade] == [("A", 2), ("ungraded", 1)]
    assert [(b.label, b.count) for b in out.facets.category] == [("uncategorized", 3)]
    assert [(b.label, b.count) for b in out.facets.protocol_version] == [("unknown", 3)]


def test_bundle_projection_always_lists_both_safety_postures():
    out = mcp_faceted_search_response_from_bundle(
        _bundle(safety_counts={"has_destructive": 0, "read_only_only": 0}), limit=50, offset=0
    )
    assert [(b.label, b.count) for b in out.facets.safety] == [
        ("has_destructive", 0),
        ("read_only_only", 0),
    ]


def test_bundle_projection_totals_and_page_echo():
    out = mcp_faceted_search_response_from_bundle(_bundle(total=42), limit=10, offset=20)
    assert out.total == 42
    assert out.count == 1
    assert out.limit == 10 and out.offset == 20
    assert out.endpoints[0].name == "Acme Weather"


# ===========================================================================
# Route — dispatch, normalization, scoping
# ===========================================================================


def test_facets_route_dispatches_with_token_tenant_and_defaults():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_catalog_faceted.return_value = _bundle()
        res = client.get("/v1/mcp/acme/facets")
    assert res.status_code == 200
    args, kwargs = mdb.search_mcp_catalog_faceted.call_args
    assert args == ("t1",)  # token tenant, never the URL slug
    assert kwargs["grades"] == []
    assert kwargs["safety"] == []
    assert kwargs["visibility"] is None
    assert kwargs["limit"] == 100 and kwargs["offset"] == 0


def test_facets_route_normalizes_and_passes_every_filter():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_catalog_faceted.return_value = _bundle()
        res = client.get(
            "/v1/mcp/acme/facets"
            "?grade=a&grade=B&grade=ungraded"
            "&transport=sse&category=Weather&category=uncategorized"
            "&safety=has_destructive&complexity=SIMPLE"
            "&protocol=2025-06-18&protocol=unknown&health=healthy"
            "&visibility=private&limit=25&offset=5"
        )
    assert res.status_code == 200
    kwargs = mdb.search_mcp_catalog_faceted.call_args.kwargs
    assert kwargs["grades"] == ["A", "B", "ungraded"]
    assert kwargs["transports"] == ["sse"]
    assert kwargs["categories"] == ["Weather", "uncategorized"]
    assert kwargs["safety"] == ["has_destructive"]
    assert kwargs["complexity"] == ["simple"]
    assert kwargs["protocols"] == ["2025-06-18", "unknown"]
    assert kwargs["health"] == ["healthy"]
    assert kwargs["visibility"] == "private"
    assert kwargs["limit"] == 25 and kwargs["offset"] == 5


def test_facets_route_projects_endpoints_and_counts():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_catalog_faceted.return_value = _bundle()
        res = client.get("/v1/mcp/acme/facets")
    body = res.json()
    assert body["success"] is True
    assert body["total"] == 1 and body["count"] == 1
    ep = body["endpoints"][0]
    assert ep["host"] == "mcp.acme.example"
    assert ep["health"] == "healthy"
    assert ep["complexity_band"] == "moderate"
    assert ep["capability_count"] == 4
    assert body["facets"]["grade"] == [{"label": "B", "count": 1}]
    assert body["facets"]["safety"] == [
        {"label": "has_destructive", "count": 1},
        {"label": "read_only_only", "count": 0},
    ]


def test_facets_route_empty_result_is_a_valid_response():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_catalog_faceted.return_value = dict(_EMPTY_BUNDLE)
        res = client.get("/v1/mcp/acme/facets?grade=F&health=quarantined")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0 and body["count"] == 0 and body["endpoints"] == []
    assert body["facets"]["grade"] == []
    # The safety control keeps its full vocabulary even over an empty result.
    assert [b["label"] for b in body["facets"]["safety"]] == [
        "has_destructive",
        "read_only_only",
    ]


@pytest.mark.parametrize(
    "query",
    [
        "grade=E",
        "transport=carrier_pigeon",
        "safety=mostly_safe",
        "complexity=gnarly",
        "health=sideways",
    ],
)
def test_facets_route_rejects_invalid_vocabulary_with_422(query):
    with patch("app.mcp_catalog_routes.db") as mdb:
        res = client.get(f"/v1/mcp/acme/facets?{query}")
        assert not mdb.search_mcp_catalog_faceted.called
    assert res.status_code == 422


def test_facets_route_rejects_invalid_visibility_and_limit():
    res = client.get("/v1/mcp/acme/facets?visibility=everyone")
    assert res.status_code == 422
    res = client.get("/v1/mcp/acme/facets?limit=0")
    assert res.status_code == 422
    res = client.get("/v1/mcp/acme/facets?limit=501")
    assert res.status_code == 422


def test_facets_route_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    res = client.get("/v1/mcp/acme/facets")
    assert res.status_code in (401, 403)
