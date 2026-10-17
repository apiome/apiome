"""Catalog categorization (MFI-6.3, #3755).

Pins three layers:

* the pure rules (:mod:`app.catalog_categories`) — tag and domain normalization, how an item's
  paradigm/format/domain are read, and the facet semantics (AND across facets, OR within one,
  ``uncategorized`` buckets, unknown values narrow to nothing, counts ignore the facet's own
  selection);
* the routes — the list's repeatable facet filters and categorization fields, ``/facets``,
  and ``PUT …/categories`` (404 / permission / 422 / normalized write);
* the data layer — the categories write's statement sequence and its "no live catalog item"
  guard, and the V277 migration's shape (static SQL guardrails).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_categories import (
    MAX_TAGS_PER_ITEM,
    UNCATEGORIZED,
    CatalogCategoryError,
    CatalogFacetFilters,
    catalog_domain_label,
    catalog_facet_counts,
    filter_catalog_items,
    item_domain,
    item_format,
    item_paradigm,
    normalize_domain,
    normalize_tag,
    normalize_tags,
)
from app.database import Database
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V277__artifact_tags_3755.sql"
)


def _item(item_id: str, *, protocol=None, source_format=None, metadata=None) -> Dict[str, Any]:
    """A catalog row in the shape ``get_catalog_items_for_tenant`` returns."""
    return {
        "id": item_id,
        "tenant_id": "test-tenant-id",
        "creator_id": "user-1",
        "name": item_id,
        "description": None,
        "slug": item_id,
        "enabled": True,
        "metadata": metadata or {},
        "publishable": False,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "deleted_at": None,
        "creator_name": "Test User",
        "creator_email": "test@example.com",
        "quality_score": None,
        "quality_grade": None,
        "versions_count": 1,
        "source_format": source_format,
        "protocol": protocol,
        "format_metadata": {},
        "tool_versions": {},
    }


ORDERS = _item("orders", protocol="rpc", source_format="protobuf", metadata={"domainCategory": "ecommerce"})
BILLING = _item("billing", protocol="rpc", source_format="protobuf", metadata={"domainCategory": "finance"})
EVENTS = _item("events", protocol="event", source_format="asyncapi-3", metadata={"domainCategory": "none"})
LEGACY = _item("legacy", metadata={"domain": "Logistics", "domainCategory": "iot"})
ITEMS = [ORDERS, BILLING, EVENTS, LEGACY]
TAGS = {"orders": ["checkout", "public"], "billing": ["public"]}


def _ids(rows) -> List[str]:
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_tags_are_trimmed_lowercased_and_collapsed() -> None:
    assert normalize_tag("  Payments   Core ") == "payments core"
    assert normalize_tags(["Public", "public", " PUBLIC ", "beta"]) == ["public", "beta"]
    assert normalize_tags(None) == []


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "x" * 65, "bad\x07bell", UNCATEGORIZED, "Uncategorized", 42],
    ids=["empty", "blank", "too-long", "control-char", "reserved", "reserved-case", "not-text"],
)
def test_invalid_tags_are_refused(raw) -> None:
    with pytest.raises(CatalogCategoryError):
        normalize_tag(raw)


def test_a_tag_list_is_capped() -> None:
    normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_ITEM)])
    with pytest.raises(CatalogCategoryError):
        normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_ITEM + 1)])


def test_domains_come_from_the_project_allow_list() -> None:
    assert normalize_domain("Finance") == "finance"
    assert normalize_domain(None) is None
    assert normalize_domain("") is None
    assert normalize_domain("none") is None
    with pytest.raises(CatalogCategoryError, match="Unknown domain"):
        normalize_domain("astrology")


def test_an_items_categories_are_read_like_the_browse_directory_reads_them() -> None:
    assert item_paradigm({"protocol": "grpc"}) == "rpc"
    assert item_paradigm({"protocol": None}) is None
    assert item_format({"source_format": "AsyncAPI-3"}) == "asyncapi-3"
    assert item_domain(ORDERS) == "ecommerce"
    assert item_domain(EVENTS) is None  # "none" means unset
    assert item_domain(LEGACY) == "logistics"  # a free-text domain wins
    assert item_domain({"metadata": None}) is None
    assert catalog_domain_label("ecommerce") == "E-commerce"
    assert catalog_domain_label(UNCATEGORIZED) == "No domain"


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------


def _filters(**kwargs) -> CatalogFacetFilters:
    return CatalogFacetFilters.from_query(**kwargs)


def test_no_selection_keeps_everything() -> None:
    assert _ids(filter_catalog_items(ITEMS, TAGS, _filters())) == _ids(ITEMS)


def test_values_within_a_facet_or_and_facets_and() -> None:
    by_domain = filter_catalog_items(ITEMS, TAGS, _filters(domains=["finance", "ECOMMERCE"]))
    assert _ids(by_domain) == ["orders", "billing"]
    both = filter_catalog_items(
        ITEMS, TAGS, _filters(domains=["finance", "ecommerce"], tags=["checkout"])
    )
    assert _ids(both) == ["orders"]


def test_protocol_and_format_accept_the_common_spellings() -> None:
    assert _ids(filter_catalog_items(ITEMS, TAGS, _filters(protocols=["gRPC"]))) == ["orders", "billing"]
    assert _ids(filter_catalog_items(ITEMS, TAGS, _filters(formats=["AsyncAPI-3"]))) == ["events"]


def test_uncategorized_selects_items_without_a_value() -> None:
    assert _ids(filter_catalog_items(ITEMS, TAGS, _filters(tags=[UNCATEGORIZED]))) == ["events", "legacy"]
    assert _ids(filter_catalog_items(ITEMS, TAGS, _filters(domains=["uncategorized"]))) == ["events"]
    assert _ids(filter_catalog_items(ITEMS, TAGS, _filters(protocols=[UNCATEGORIZED]))) == ["legacy"]


def test_an_unknown_value_narrows_to_nothing() -> None:
    assert filter_catalog_items(ITEMS, TAGS, _filters(tags=["no-such-tag"])) == []
    assert filter_catalog_items(ITEMS, TAGS, _filters(protocols=["carrier-pigeon"])) == []


def _bucket(buckets, value) -> Dict[str, Any]:
    return next(bucket for bucket in buckets if bucket["value"] == value)


def test_counts_ignore_their_own_facet_but_honor_the_others() -> None:
    facets = catalog_facet_counts(ITEMS, TAGS, _filters(domains=["finance"]))
    # The domain facet still counts every domain, so another can be added to the selection.
    assert _bucket(facets["domains"], "ecommerce")["count"] == 1
    assert _bucket(facets["domains"], "finance") == {
        "value": "finance",
        "label": "Finance",
        "count": 1,
        "selected": True,
    }
    # The tag facet counts only what the finance selection leaves.
    assert [(b["value"], b["count"]) for b in facets["tags"]] == [("public", 1)]
    # Paradigm counts are taken under the finance selection: only billing (rpc) remains.
    assert [(b["value"], b["count"]) for b in facets["protocols"]] == [("rpc", 1)]


def test_a_selected_value_stays_listed_at_zero_and_uncategorized_sorts_last() -> None:
    facets = catalog_facet_counts(ITEMS, TAGS, _filters(tags=["gone"]))
    assert _bucket(facets["tags"], "gone") == {"value": "gone", "label": "gone", "count": 0, "selected": True}
    unfiltered = catalog_facet_counts(ITEMS, TAGS, _filters())
    assert [b["value"] for b in unfiltered["tags"]] == ["public", "checkout", UNCATEGORIZED]
    assert _bucket(unfiltered["tags"], UNCATEGORIZED)["label"] == "No tags"
    assert _bucket(unfiltered["protocols"], UNCATEGORIZED)["label"] == "Unknown paradigm"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _mock_reads(mock_db) -> None:
    mock_db.get_catalog_items_for_tenant.return_value = ITEMS
    mock_db.get_artifact_tags_for_projects.return_value = TAGS


def test_list_carries_each_items_categorization(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db:
        _mock_reads(mock_db)
        response = client.get("/v1/catalog/test-tenant")
    assert response.status_code == 200
    body = {row["id"]: row for row in response.json()}
    assert body["orders"]["paradigm"] == "rpc"
    assert body["orders"]["domain"] == "ecommerce"
    assert body["orders"]["tags"] == ["checkout", "public"]
    assert body["events"]["domain"] is None and body["events"]["tags"] == []
    mock_db.get_artifact_tags_for_projects.assert_called_once_with(
        "test-tenant-id", ["orders", "billing", "events", "legacy"]
    )


def test_list_filters_by_repeatable_facets(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db:
        _mock_reads(mock_db)
        response = client.get(
            "/v1/catalog/test-tenant",
            params=[("domain", "finance"), ("domain", "ecommerce"), ("tag", "checkout")],
        )
    assert [row["id"] for row in response.json()] == ["orders"]

    with patch("app.catalog_routes.db") as mock_db:
        _mock_reads(mock_db)
        response = client.get("/v1/catalog/test-tenant", params={"protocol": "event", "format": "asyncapi-3"})
    assert [row["id"] for row in response.json()] == ["events"]


def test_facets_route_is_not_mistaken_for_an_item(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db:
        _mock_reads(mock_db)
        response = client.get("/v1/catalog/test-tenant/facets", params={"tag": "public"})
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["matched"]) == (4, 2)
    assert set(body["facets"]) == {"protocols", "formats", "domains", "tags"}
    assert _bucket(body["facets"]["tags"], "public")["selected"] is True
    mock_db.get_catalog_item_by_id.assert_not_called()


def test_facets_require_auth() -> None:
    assert client.get("/v1/catalog/test-tenant/facets").status_code == 401


def test_categories_404_for_an_unknown_item(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db:
        mock_db.get_catalog_item_by_id.return_value = None
        response = client.put("/v1/catalog/test-tenant/nope/categories", json={"tags": ["a"]})
    assert response.status_code == 404
    mock_db.set_catalog_item_categories.assert_not_called()


def test_categories_require_projects_edit(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db, patch(
        "app.catalog_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="forbidden"),
    ) as mock_perm:
        mock_db.get_catalog_item_by_id.return_value = ORDERS
        response = client.put("/v1/catalog/test-tenant/orders/categories", json={"tags": ["a"]})
    assert response.status_code == 403
    _, _, resource, action = mock_perm.call_args.args
    assert (resource.value if hasattr(resource, "value") else resource) == "projects"
    assert action == "edit"
    mock_db.set_catalog_item_categories.assert_not_called()


@pytest.mark.parametrize(
    "body,fragment",
    [({"domain": "astrology"}, "Unknown domain"), ({"tags": ["uncategorized"]}, "reserved")],
    ids=["unknown-domain", "reserved-tag"],
)
def test_categories_refuse_invalid_values(authed, body, fragment) -> None:
    with patch("app.catalog_routes.db") as mock_db, patch("app.catalog_routes.enforce_permission"):
        mock_db.get_catalog_item_by_id.return_value = ORDERS
        response = client.put("/v1/catalog/test-tenant/orders/categories", json=body)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    mock_db.set_catalog_item_categories.assert_not_called()


def test_categories_write_the_normalized_domain_and_tags(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db, patch("app.catalog_routes.enforce_permission"):
        mock_db.get_catalog_item_by_id.return_value = ORDERS
        mock_db.set_catalog_item_categories.return_value = True
        response = client.put(
            "/v1/catalog/test-tenant/orders/categories",
            json={"domain": "Finance", "tags": [" Public ", "beta", "public"]},
        )
    assert response.status_code == 200
    assert response.json() == {"paradigm": "rpc", "domain": "finance", "tags": ["beta", "public"]}
    mock_db.set_catalog_item_categories.assert_called_once_with(
        tenant_id="test-tenant-id",
        project_id="orders",
        domain="finance",
        tags=["public", "beta"],
        user_id="test-user-id",
    )


def test_categories_404_when_the_write_matched_nothing(authed) -> None:
    with patch("app.catalog_routes.db") as mock_db, patch("app.catalog_routes.enforce_permission"):
        mock_db.get_catalog_item_by_id.return_value = ORDERS
        mock_db.set_catalog_item_categories.return_value = False
        response = client.put("/v1/catalog/test-tenant/orders/categories", json={"domain": None})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


class _Cursor:
    """Records each statement; the UPDATE's rowcount is set by the test."""

    def __init__(self, update_rowcount: int) -> None:
        self.update_rowcount = update_rowcount
        self.statements: List[tuple] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple) -> None:
        self.statements.append((" ".join(sql.split()), params))
        self.rowcount = self.update_rowcount if sql.strip().startswith("UPDATE") else 1


def _run_write(update_rowcount: int, **kwargs):
    database = Database.__new__(Database)
    cursor = _Cursor(update_rowcount)
    outcome: Dict[str, Any] = {}

    def fake_tx(work):
        outcome["result"] = work(cursor)
        return outcome["result"]

    database._guarded_tx = fake_tx  # type: ignore[method-assign]
    written = database.set_catalog_item_categories(
        tenant_id="t-1", project_id="p-1", user_id="u-1", **kwargs
    )
    return written, cursor.statements, outcome["result"]


def test_categories_write_replaces_domain_and_tags_in_one_transaction() -> None:
    written, statements, _ = _run_write(1, domain="finance", tags=["beta", "public"])
    assert written is True
    update, delete, *inserts = statements
    assert update[0].startswith("UPDATE apiome.projects")
    assert "- 'domain'" in update[0] and "publishable = false" in update[0]
    assert update[1] == ("finance", "p-1", "t-1")
    assert delete[0].startswith("DELETE FROM apiome.artifact_tags")
    assert [params for _, params in inserts] == [
        ("t-1", "p-1", "beta", "u-1"),
        ("t-1", "p-1", "public", "u-1"),
    ]


def test_clearing_the_domain_writes_none() -> None:
    _, statements, _ = _run_write(1, domain=None, tags=[])
    assert statements[0][1][0] == "none"
    assert len(statements) == 2  # update + delete, no inserts


def test_no_live_catalog_item_writes_nothing() -> None:
    written, statements, result = _run_write(0, domain="finance", tags=["x"])
    # The guard returns None, which rolls the transaction back.
    assert written is False and result is None
    assert len(statements) == 1


def test_tags_read_is_skipped_for_no_items() -> None:
    database = Database.__new__(Database)
    assert database.get_artifact_tags_for_projects("t-1", []) == {}


def test_migration_v277_shape() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS apiome.artifact_tags" in sql
    assert "REFERENCES apiome.projects(id) ON DELETE CASCADE" in sql
    assert "REFERENCES apiome.mcp_endpoints(id) ON DELETE CASCADE" in sql
    assert "num_nonnulls(project_id, mcp_endpoint_id) = 1" in sql
    assert "uq_artifact_tags_project_tag" in sql and "lower(tag)" in sql
    assert "length(tag) BETWEEN 1 AND 64" in sql
