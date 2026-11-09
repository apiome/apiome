"""Unit tests for the MCP catalog categorization model & manual tags (V2-MCP-23.3 / MCAT-9.3, #3693).

Covers the pure vocabulary and normalizers (:mod:`app.mcp_categorization`), the tag facet in
:mod:`app.mcp_facets`, the SQL clause builders that turn categories and tags into browse / search
filters, the wire projections (tags on browse rows, tag buckets), and every route: the category
lookup CRUD and endpoint tag CRUD (:mod:`app.mcp_categorization_routes`), plus the category / tag
facets on ``/browse``, ``/facets`` and ``/search`` and the lenient category resolution on endpoint
create / patch. ``db`` is mocked, so the suite stays DB-free; ``test_mcp_categorization_db.py``
runs the SQL for real.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.mcp_categorization import (
    BUILTIN_CATEGORIES,
    MAX_TAGS_PER_ENDPOINT,
    CategorizationValidationError,
    normalize_category_label,
    normalize_category_slug,
    normalize_tag,
    normalize_tags,
    resolve_category,
    slugify_category,
)
from app.mcp_facets import canonical_tag, normalize_catalog_facet_filters
from app.models import (
    mcp_browse_endpoint_out_from_row,
    mcp_category_out_from_row,
    mcp_faceted_search_response_from_bundle,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_EP = "11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V365__mcp_categories_and_tags_3693.sql"
)


def _category(slug="weather", label="Weather", *, builtin=False, endpoint_count=0, **extra):
    """A :meth:`Database.get_mcp_category` row."""
    row = {
        "id": "cat-1",
        "tenant_id": None if builtin else "t1",
        "slug": slug,
        "label": label,
        "description": None,
        "sort_order": 500,
        "builtin": builtin,
        "endpoint_count": endpoint_count,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(extra)
    return row


_LOOKUP = [
    _category("developer-tools", "Developer tools", builtin=True),
    _category("data-analytics", "Data & analytics", builtin=True),
    _category("weather", "Weather"),
]


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# Pure vocabulary & normalizers
# ===========================================================================


def test_builtin_categories_mirror_the_migration_seed():
    sql = _MIGRATION.read_text()
    for slug, label in BUILTIN_CATEGORIES:
        assert f"(NULL, '{slug}', '{label}'," in sql
    assert sql.count("(NULL, '") == len(BUILTIN_CATEGORIES)


def test_builtin_category_slugs_are_valid_and_unique():
    slugs = [slug for slug, _ in BUILTIN_CATEGORIES]
    assert len(set(slugs)) == len(slugs)
    for slug in slugs:
        assert normalize_category_slug(slug) == slug


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Prod", "prod"),
        ("  Team Payments ", "team-payments"),
        ("tier:gold", "tier:gold"),
        ("v1.2_beta", "v1.2_beta"),
    ],
)
def test_normalize_tag_canonicalizes(raw, expected):
    assert normalize_tag(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "   ", None, "-leading", "has/slash", "emoji🙂", "x" * 65, "untagged", "UNTAGGED"]
)
def test_normalize_tag_rejects_invalid(raw):
    with pytest.raises(CategorizationValidationError):
        normalize_tag(raw)


def test_canonical_tag_folds_without_validating():
    assert canonical_tag(" Has/Slash  Here ") == "has/slash-here"
    assert canonical_tag(None) == ""


def test_normalize_tags_dedupes_in_first_seen_order():
    assert normalize_tags(["b", "A", "a", " b "]) == ["b", "a"]
    assert normalize_tags(None) == []


def test_normalize_tags_enforces_the_limit():
    normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_ENDPOINT)])
    with pytest.raises(CategorizationValidationError, match="at most"):
        normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_ENDPOINT + 1)])


@pytest.mark.parametrize(
    "label, slug",
    [
        ("Data & Analytics", "data-analytics"),
        ("  Weather  ", "weather"),
        ("A/B Testing!", "a-b-testing"),
        ("&&&", ""),
    ],
)
def test_slugify_category(label, slug):
    assert slugify_category(label) == slug


def test_slugify_category_truncates_without_trailing_hyphen():
    slug = slugify_category("a" * 63 + " b")
    assert len(slug) <= 64
    assert not slug.endswith("-")


@pytest.mark.parametrize("raw", ["", "Has Space", "-x", "under_score", "x" * 65, "uncategorized"])
def test_normalize_category_slug_rejects_invalid(raw):
    with pytest.raises(CategorizationValidationError):
        normalize_category_slug(raw)


def test_normalize_category_slug_lowercases():
    assert normalize_category_slug(" Weather ") == "weather"


def test_normalize_category_label_bounds():
    assert normalize_category_label("  Weather ") == "Weather"
    with pytest.raises(CategorizationValidationError):
        normalize_category_label("  ")
    with pytest.raises(CategorizationValidationError):
        normalize_category_label("x" * 129)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("developer-tools", "developer-tools"),
        ("DEVELOPER-TOOLS", "developer-tools"),
        ("data & analytics", "data-analytics"),
        ("  Weather ", "weather"),
        ("Something New", "Something New"),
        ("  ", None),
        (None, None),
    ],
)
def test_resolve_category_is_lenient(value, expected):
    assert resolve_category(value, _LOOKUP) == expected


def test_resolve_category_prefers_slug_over_label():
    lookup = [_category("ops", "Weather"), _category("weather", "Forecasts")]
    assert resolve_category("weather", lookup) == "weather"


# ===========================================================================
# Tag facet normalization & SQL clauses
# ===========================================================================


def test_facet_filters_fold_tags_and_keep_the_untagged_sentinel():
    filters = normalize_catalog_facet_filters(tag=["Prod", " prod ", "Team Payments", "UNTAGGED"])
    assert filters.tags == ["prod", "team-payments", "untagged"]


def test_tag_facet_clause_matches_any_listed_tag():
    clauses, params = db._mcp_facet_filter_clauses(tags=["prod", "beta"])
    assert len(clauses) == 1
    assert "EXISTS (SELECT 1 FROM apiome.mcp_endpoint_tags et" in clauses[0]
    assert "et.tag = ANY(%s)" in clauses[0]
    assert params == [["prod", "beta"]]


def test_untagged_sentinel_ors_a_not_exists_predicate():
    clauses, params = db._mcp_facet_filter_clauses(tags=["prod", "untagged"])
    assert " OR NOT EXISTS (SELECT 1 FROM apiome.mcp_endpoint_tags et" in clauses[0]
    assert params == [["prod"]]
    only, only_params = db._mcp_facet_filter_clauses(tags=["untagged"])
    assert only[0].startswith("(NOT EXISTS")
    assert only_params == []


def test_tag_facet_is_its_own_and_clause():
    clauses, _ = db._mcp_facet_filter_clauses(categories=["weather"], tags=["prod"])
    assert len(clauses) == 2


def test_search_filter_clause_adds_a_tag_exists():
    clauses, params = db._mcp_search_filter_clauses(
        host=None, category="weather", grade=None, visibility=None, tag="prod"
    )
    assert any("et.tag = %s" in c for c in clauses)
    assert params == ["prod", "weather"]


def test_search_filter_clause_without_tag_is_unchanged():
    clauses, params = db._mcp_search_filter_clauses(
        host=None, category=None, grade=None, visibility=None
    )
    assert clauses == [] and params == []


# ===========================================================================
# Projections
# ===========================================================================


def _browse_row(**overrides):
    row = {
        "id": "ep-1",
        "name": "Acme Weather",
        "slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/sse",
        "transport": "streamable_http",
        "category": "weather",
        "visibility": "private",
        "published": False,
        "enabled": True,
        "tags": ["beta", "prod"],
    }
    row.update(overrides)
    return row


def test_browse_projection_carries_tags():
    assert mcp_browse_endpoint_out_from_row(_browse_row()).tags == ["beta", "prod"]


def test_browse_projection_tags_default_to_empty():
    row = _browse_row()
    del row["tags"]
    assert mcp_browse_endpoint_out_from_row(row).tags == []
    assert mcp_browse_endpoint_out_from_row(_browse_row(tags=None)).tags == []


def test_bundle_projection_lists_tag_buckets_then_untagged():
    resp = mcp_faceted_search_response_from_bundle(
        {
            "endpoints": [],
            "tag_rows": [{"label": "prod", "count": 3}, {"label": "beta", "count": 1}],
            "untagged_count": 2,
        },
        limit=10,
        offset=0,
    )
    assert [(b.label, b.count) for b in resp.facets.tag] == [
        ("prod", 3),
        ("beta", 1),
        ("untagged", 2),
    ]


def test_bundle_projection_omits_an_empty_untagged_bucket():
    resp = mcp_faceted_search_response_from_bundle(
        {"endpoints": [], "tag_rows": [], "untagged_count": 0}, limit=10, offset=0
    )
    assert resp.facets.tag == []


def test_category_projection():
    out = mcp_category_out_from_row(_category(builtin=True, endpoint_count=4))
    assert out.builtin is True
    assert out.endpoint_count == 4
    assert out.created_at == _NOW.isoformat()


# ===========================================================================
# Category routes
# ===========================================================================


def test_list_categories_scoped_to_token_tenant():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = _LOOKUP
        res = client.get("/v1/mcp/other-slug/categories")
    assert res.status_code == 200
    mdb.list_mcp_categories.assert_called_once_with("t1")
    body = res.json()
    assert [c["slug"] for c in body["categories"]] == [
        "developer-tools",
        "data-analytics",
        "weather",
    ]
    assert body["categories"][0]["builtin"] is True


def test_create_category_derives_slug_from_label():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = _LOOKUP
        mdb.create_mcp_category.return_value = _category("internal-apis", "Internal APIs")
        res = client.post(
            "/v1/mcp/acme/categories",
            json={"label": " Internal APIs ", "description": "  ", "sortOrder": 5},
        )
    assert res.status_code == 201
    args, kwargs = mdb.create_mcp_category.call_args
    assert args == ("t1", "user-1")
    assert kwargs == {
        "slug": "internal-apis",
        "label": "Internal APIs",
        "description": None,
        "sort_order": 5,
    }
    assert res.json()["category"]["slug"] == "internal-apis"


def test_create_category_honours_an_explicit_slug():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = []
        mdb.create_mcp_category.return_value = _category("int", "Internal")
        res = client.post("/v1/mcp/acme/categories", json={"label": "Internal", "slug": "INT"})
    assert res.status_code == 201
    assert mdb.create_mcp_category.call_args.kwargs["slug"] == "int"


@pytest.mark.parametrize(
    "body",
    [
        {"label": "Weather"},  # slug taken
        {"label": "DEVELOPER TOOLS", "slug": "devtools"},  # label taken (built-in)
        {"label": "Anything", "slug": "developer-tools"},  # shadows a built-in slug
    ],
)
def test_create_category_conflicts_409(body):
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = _LOOKUP
        res = client.post("/v1/mcp/acme/categories", json=body)
    assert res.status_code == 409
    mdb.create_mcp_category.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [{"label": "&&&"}, {"label": "Fine", "slug": "bad slug"}, {"label": "Fine", "slug": "uncategorized"}],
)
def test_create_category_invalid_422(body):
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = []
        res = client.post("/v1/mcp/acme/categories", json=body)
    assert res.status_code == 422


def test_create_category_race_maps_unique_violation_to_409():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = []
        mdb.create_mcp_category.side_effect = pg_errors.UniqueViolation()
        res = client.post("/v1/mcp/acme/categories", json={"label": "New"})
    assert res.status_code == 409


def test_get_category_404_and_ok():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = None
        assert client.get("/v1/mcp/acme/categories/nope").status_code == 404
        mdb.get_mcp_category.return_value = _category("security", "Security", builtin=True)
        res = client.get("/v1/mcp/acme/categories/Security")
    assert res.status_code == 200
    mdb.get_mcp_category.assert_called_with("t1", "security")


def test_patch_category_applies_present_fields():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = _category()
        mdb.list_mcp_categories.return_value = _LOOKUP
        mdb.update_mcp_category.return_value = _category(label="Forecasts")
        res = client.patch(
            "/v1/mcp/acme/categories/weather",
            json={"label": " Forecasts ", "description": None, "sort_order": 7},
        )
    assert res.status_code == 200
    assert mdb.update_mcp_category.call_args.args == (
        "t1",
        "weather",
        {"label": "Forecasts", "description": None, "sort_order": 7},
    )


def test_patch_category_keeping_its_own_label_is_not_a_conflict():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = _category()
        mdb.list_mcp_categories.return_value = _LOOKUP
        mdb.update_mcp_category.return_value = _category()
        res = client.patch("/v1/mcp/acme/categories/weather", json={"label": "WEATHER"})
    assert res.status_code == 200


def test_patch_category_label_conflict_409():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = _category()
        mdb.list_mcp_categories.return_value = _LOOKUP
        res = client.patch("/v1/mcp/acme/categories/weather", json={"label": "Developer Tools"})
    assert res.status_code == 409
    mdb.update_mcp_category.assert_not_called()


def test_patch_category_empty_body_is_a_noop():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = _category()
        res = client.patch("/v1/mcp/acme/categories/weather", json={})
    assert res.status_code == 200
    mdb.update_mcp_category.assert_not_called()


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_builtin_categories_are_read_only_403(method):
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = _category("security", "Security", builtin=True)
        kwargs = {"json": {"label": "X"}} if method == "patch" else {}
        res = getattr(client, method)("/v1/mcp/acme/categories/security", **kwargs)
    assert res.status_code == 403
    mdb.update_mcp_category.assert_not_called()
    mdb.delete_mcp_category.assert_not_called()


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_unknown_category_404(method):
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = None
        kwargs = {"json": {"label": "X"}} if method == "patch" else {}
        res = getattr(client, method)("/v1/mcp/acme/categories/nope", **kwargs)
    assert res.status_code == 404


def test_delete_category_ok():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_category.return_value = _category()
        mdb.delete_mcp_category.return_value = True
        res = client.delete("/v1/mcp/acme/categories/weather")
    assert res.status_code == 200
    mdb.delete_mcp_category.assert_called_once_with("t1", "weather")


def test_category_routes_require_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    assert client.get("/v1/mcp/acme/categories").status_code == 401


# ===========================================================================
# Tag routes
# ===========================================================================


def test_tag_vocabulary():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.list_mcp_tag_vocabulary.return_value = [
            {"tag": "prod", "endpoint_count": 3},
            {"tag": "beta", "endpoint_count": 1},
        ]
        res = client.get("/v1/mcp/acme/tags")
    assert res.status_code == 200
    mdb.list_mcp_tag_vocabulary.assert_called_once_with("t1")
    assert res.json()["tags"] == [
        {"tag": "prod", "endpoint_count": 3},
        {"tag": "beta", "endpoint_count": 1},
    ]


def test_endpoint_tags_require_a_tenant_endpoint_404():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        assert client.get(f"/v1/mcp/acme/endpoints/{_EP}/tags").status_code == 404
        assert (
            client.put(f"/v1/mcp/acme/endpoints/{_EP}/tags", json={"tags": ["a"]}).status_code
            == 404
        )
    mdb.get_mcp_endpoint.assert_called_with("t1", _EP)
    mdb.replace_mcp_endpoint_tags.assert_not_called()


def test_list_endpoint_tags():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        mdb.list_mcp_endpoint_tags.return_value = ["beta", "prod"]
        res = client.get(f"/v1/mcp/acme/endpoints/{_EP}/tags")
    assert res.status_code == 200
    assert res.json() == {"success": True, "endpoint_id": _EP, "tags": ["beta", "prod"]}


def test_replace_endpoint_tags_normalizes():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        mdb.replace_mcp_endpoint_tags.return_value = ["prod", "team-payments"]
        res = client.put(
            f"/v1/mcp/acme/endpoints/{_EP}/tags", json={"tags": ["Prod", "team payments", "prod"]}
        )
    assert res.status_code == 200
    mdb.replace_mcp_endpoint_tags.assert_called_once_with(
        "t1", _EP, ["prod", "team-payments"], "user-1"
    )
    assert res.json()["tags"] == ["prod", "team-payments"]


def test_replace_endpoint_tags_empty_list_clears():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        mdb.replace_mcp_endpoint_tags.return_value = []
        res = client.put(f"/v1/mcp/acme/endpoints/{_EP}/tags", json={"tags": []})
    assert res.status_code == 200
    assert mdb.replace_mcp_endpoint_tags.call_args.args[2] == []


@pytest.mark.parametrize("tags", [["bad/tag"], ["untagged"], [f"t{i}" for i in range(33)]])
def test_replace_endpoint_tags_invalid_422(tags):
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        res = client.put(f"/v1/mcp/acme/endpoints/{_EP}/tags", json={"tags": tags})
    assert res.status_code == 422
    mdb.replace_mcp_endpoint_tags.assert_not_called()


def test_add_endpoint_tags_unions_with_existing():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        mdb.list_mcp_endpoint_tags.return_value = ["beta"]
        mdb.replace_mcp_endpoint_tags.return_value = ["beta", "prod"]
        res = client.post(f"/v1/mcp/acme/endpoints/{_EP}/tags", json={"tags": ["Prod", "beta"]})
    assert res.status_code == 200
    assert mdb.replace_mcp_endpoint_tags.call_args.args[2] == ["beta", "prod"]


def test_add_endpoint_tags_over_the_limit_422():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        mdb.list_mcp_endpoint_tags.return_value = [f"t{i}" for i in range(MAX_TAGS_PER_ENDPOINT)]
        res = client.post(f"/v1/mcp/acme/endpoints/{_EP}/tags", json={"tags": ["one-more"]})
    assert res.status_code == 422
    mdb.replace_mcp_endpoint_tags.assert_not_called()


def test_remove_endpoint_tag_canonicalizes_and_404s_when_absent():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _EP}
        mdb.remove_mcp_endpoint_tag.return_value = True
        mdb.list_mcp_endpoint_tags.return_value = ["beta"]
        res = client.delete(f"/v1/mcp/acme/endpoints/{_EP}/tags/PROD")
        assert res.status_code == 200
        assert res.json()["tags"] == ["beta"]
        mdb.remove_mcp_endpoint_tag.assert_called_once_with(_EP, "prod")
        mdb.remove_mcp_endpoint_tag.return_value = False
        assert client.delete(f"/v1/mcp/acme/endpoints/{_EP}/tags/nope").status_code == 404


# ===========================================================================
# Facets on browse / facets / search, and category resolution on endpoint writes
# ===========================================================================


def test_browse_passes_category_and_tag_facets():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.browse_mcp_endpoints.return_value = [_browse_row()]
        res = client.get(
            "/v1/mcp/acme/browse?category=Weather&category=uncategorized&tag=Prod&tag=untagged"
        )
    assert res.status_code == 200
    mdb.browse_mcp_endpoints.assert_called_once_with(
        "t1", team=None, categories=["Weather", "uncategorized"], tags=["prod", "untagged"]
    )
    endpoint = res.json()["groups"][0]["endpoints"][0]
    assert endpoint["tags"] == ["beta", "prod"]


def test_facets_route_passes_tags_and_projects_tag_buckets():
    bundle = {
        "endpoints": [_browse_row()],
        "total": 1,
        "tag_rows": [{"label": "prod", "count": 1}],
        "untagged_count": 0,
    }
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_catalog_faceted.return_value = bundle
        res = client.get("/v1/mcp/acme/facets?tag=PROD&tag=untagged")
    assert res.status_code == 200
    assert mdb.search_mcp_catalog_faceted.call_args.kwargs["tags"] == ["prod", "untagged"]
    body = res.json()
    assert body["facets"]["tag"] == [{"label": "prod", "count": 1}]
    assert body["endpoints"][0]["tags"] == ["beta", "prod"]


@pytest.mark.parametrize("scope", [None, "endpoint"])
def test_search_passes_canonical_tag(scope):
    url = "/v1/mcp/acme/search?q=weather&tag=%20Team%20Payments%20"
    if scope:
        url += f"&scope={scope}"
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        mdb.search_mcp_endpoints_fts.return_value = []
        res = client.get(url)
    assert res.status_code == 200
    called = mdb.search_mcp_endpoints_fts if scope else mdb.search_mcp_capability_items
    assert called.call_args.kwargs["tag"] == "team-payments"


def test_search_without_tag_passes_none():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get("/v1/mcp/acme/search?q=weather&tag=%20")
    assert mdb.search_mcp_capability_items.call_args.kwargs["tag"] is None


def test_create_endpoint_resolves_category_against_the_lookup():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = _LOOKUP
        mdb.insert_mcp_endpoint.return_value = {
            "id": "ep-1",
            "tenant_id": "t1",
            "name": "Acme",
            "slug": "acme",
            "endpoint_url": "https://mcp.acme.example/mcp",
            "transport": "streamable_http",
            "category": "data-analytics",
            "visibility": "private",
            "published": False,
            "enabled": True,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        res = client.post(
            "/v1/mcp/acme/endpoints",
            json={
                "name": "Acme",
                "endpoint_url": "https://mcp.acme.example/mcp",
                "category": "Data & Analytics",
            },
        )
    assert res.status_code == 201
    mdb.list_mcp_categories.assert_called_once_with("t1")
    assert mdb.insert_mcp_endpoint.call_args.kwargs["category"] == "data-analytics"


@pytest.mark.parametrize(
    "category, stored",
    [("developer-tools", "developer-tools"), ("Brand New", "Brand New"), ("  ", None)],
)
def test_patch_endpoint_resolves_category_leniently(category, stored):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_categories.return_value = _LOOKUP
        mdb.update_mcp_endpoint.return_value = None
        client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"category": category})
    assert mdb.update_mcp_endpoint.call_args.args[2] == {"category": stored}
