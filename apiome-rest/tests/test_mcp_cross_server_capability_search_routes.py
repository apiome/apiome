"""API + aggregation tests for cross-server capability search (V2-MCP-35.2 / MCAT-21.2, #4661)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_insight_aggregation import (
    build_capability_item_embedding_text,
    group_cross_server_capability_hits,
    merge_cross_server_capability_hits,
)
from app.models import mcp_cross_server_capability_search_response_from_groups

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


def _capability_row(**overrides):
    row = {
        "kind": "tool",
        "item_id": "item-1",
        "item_name": "geocode",
        "item_title": "Geocode",
        "description": "Convert an address to coordinates",
        "ordinal": 0,
        "endpoint_id": "ep-1",
        "endpoint_name": "Acme Geo",
        "endpoint_slug": "acme-geo",
        "endpoint_url": "https://mcp.acme.example/sse",
        "category": "geo",
        "visibility": "private",
        "current_version_id": "ver-1",
        "last_discovered_at": None,
        "score": 90,
        "grade": "A",
        "relevance": 0.55,
    }
    row.update(overrides)
    return row


def _semantic_row(**overrides):
    semantic = overrides.pop("semantic_similarity", 0.72)
    row = _capability_row(relevance=None, **overrides)
    row["semantic_similarity"] = semantic
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# Pure aggregation
# ===========================================================================


def test_build_capability_item_embedding_text_includes_title_and_description():
    text = build_capability_item_embedding_text(
        "geocode", "lat/lon lookup", title="Geocode address"
    )
    assert "geocode" in text.lower()
    assert "lat/lon" in text


def test_merge_cross_server_capability_hits_dedupes_and_marks_both():
    merged = merge_cross_server_capability_hits(
        [_capability_row()],
        [_semantic_row(item_id="item-1", semantic_similarity=0.8)],
    )
    assert len(merged) == 1
    assert merged[0]["match_source"] == "both"
    assert merged[0]["relevance"] == pytest.approx(0.8)


def test_merge_semantic_only_hit():
    merged = merge_cross_server_capability_hits(
        [],
        [_semantic_row(item_id="item-2", endpoint_id="ep-2", semantic_similarity=0.61)],
    )
    assert len(merged) == 1
    assert merged[0]["match_source"] == "semantic"
    assert merged[0]["relevance"] == pytest.approx(0.61)


def test_group_cross_server_capability_hits_orders_by_relevance_then_grade():
    merged = merge_cross_server_capability_hits(
        [
            _capability_row(endpoint_id="ep-low", endpoint_name="Zed", grade="C", relevance=0.4),
            _capability_row(
                endpoint_id="ep-high",
                endpoint_name="Acme",
                item_id="item-2",
                item_name="reverse_geocode",
                grade="B",
                relevance=0.9,
            ),
        ],
        [],
    )
    groups, total = group_cross_server_capability_hits(merged, limit=10, offset=0)
    assert total == 2
    assert [g["endpoint_id"] for g in groups] == ["ep-high", "ep-low"]
    assert len(groups[0]["capabilities"]) == 1


def test_group_cross_server_capability_hits_paginates_server_groups():
    merged = merge_cross_server_capability_hits(
        [
            _capability_row(endpoint_id="ep-1", endpoint_name="A", relevance=0.9),
            _capability_row(endpoint_id="ep-2", endpoint_name="B", relevance=0.5),
        ],
        [],
    )
    groups, total = group_cross_server_capability_hits(merged, limit=1, offset=1)
    assert total == 2
    assert len(groups) == 1
    assert groups[0]["endpoint_id"] == "ep-2"


def test_cross_server_response_projection_redacts_url():
    resp = mcp_cross_server_capability_search_response_from_groups(
        query="geo",
        scope=None,
        semantic_enabled=True,
        limit=10,
        offset=0,
        total=1,
        groups=[
            {
                "endpoint_id": "ep-1",
                "endpoint_name": "Acme",
                "endpoint_slug": "acme",
                "endpoint_url": "https://user:secret@mcp.acme.example/sse",
                "category": "geo",
                "visibility": "private",
                "score": 90,
                "grade": "A",
                "max_relevance": 0.8,
                "capabilities": [_capability_row(match_source="both", relevance=0.8)],
            }
        ],
    )
    assert resp.groups[0].host == "mcp.acme.example"
    assert "secret" not in resp.groups[0].endpoint_url
    assert resp.groups[0].capabilities[0].match_source == "both"


# ===========================================================================
# Route — dispatch & scoping
# ===========================================================================


def test_cross_server_search_merges_keyword_and_semantic():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.settings"
    ) as msettings, patch("app.mcp_catalog_routes.get_embedding", return_value=[0.1, 0.2]):
        msettings.mcp_similarity_embeddings_enabled = True
        mdb.search_mcp_capability_items.return_value = [_capability_row()]
        mdb.search_mcp_capability_items_semantic.return_value = [
            _semantic_row(item_id="item-9", endpoint_id="ep-9")
        ]
        r = client.get("/v1/mcp/acme/capabilities/search", params={"q": "geocode"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["semantic_enabled"] is True
    assert body["total"] == 2
    mdb.search_mcp_capability_items_semantic.assert_called_once()


def test_cross_server_search_skips_semantic_when_disabled():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.settings"
    ) as msettings, patch("app.mcp_catalog_routes.get_embedding") as mget:
        msettings.mcp_similarity_embeddings_enabled = False
        mdb.search_mcp_capability_items.return_value = [_capability_row()]
        r = client.get("/v1/mcp/acme/capabilities/search", params={"q": "geocode"})
    assert r.status_code == 200
    assert r.json()["semantic_enabled"] is False
    mget.assert_not_called()
    mdb.search_mcp_capability_items_semantic.assert_not_called()


def test_cross_server_search_scoped_to_token_tenant():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get("/v1/mcp/other/capabilities/search", params={"q": "geo"})
    args, _ = mdb.search_mcp_capability_items.call_args
    assert args[0] == "t1"


def test_cross_server_search_whitespace_query_returns_empty_without_db():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.get("/v1/mcp/acme/capabilities/search", params={"q": "   "})
    assert r.status_code == 200
    body = r.json()
    assert body["groups"] == []
    assert body["total"] == 0
    mdb.search_mcp_capability_items.assert_not_called()


def test_cross_server_search_no_match_returns_empty_groups():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        r = client.get("/v1/mcp/acme/capabilities/search", params={"q": "nonexistent"})
    assert r.status_code == 200
    body = r.json()
    assert body["groups"] == []
    assert body["total"] == 0


def test_cross_server_search_rejects_endpoint_scope():
    r = client.get(
        "/v1/mcp/acme/capabilities/search", params={"q": "weather", "scope": "endpoint"}
    )
    assert r.status_code == 422


def test_cross_server_search_passes_visibility_filter():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get(
            "/v1/mcp/acme/capabilities/search",
            params={"q": "geo", "visibility": "public"},
        )
    _, kwargs = mdb.search_mcp_capability_items.call_args
    assert kwargs["visibility"] == "public"


def test_cross_server_search_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get("/v1/mcp/acme/capabilities/search", params={"q": "x"})
    assert r.status_code == 401
