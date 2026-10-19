"""The catalog entity-kind registry and the unified entity list — CDG-5.1 (#5979).

* **Registry**: six kinds in display order; it agrees with the owner registry (table and live
  predicate) and the graph's node kinds; a kind added to it appears in the summary's kinds and in
  the graph labeller with no other change.
* **Envelope**: every kind comes back in one shape with a ``kind`` discriminator, its owner, the UI
  page that renders it and its graph node.
* **Paging**: pages across kinds in name order with a stable cursor — no duplicates or gaps,
  whatever the page size; a malformed cursor is a 400.
* **Statement count**: one statement per kind in scope, whatever the rows (no N+1); the summary is a
  fixed number of statements.
* **Filters and permissions**: ``team`` skips kinds without owners; kinds the caller may not view
  are left out; an unknown ``kind`` is a 422; ``/entities`` is not read as a catalog item id.
* **Callouts**: unowned, stale (cadence × 2) and shadow.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import catalog_entities, catalog_entity_store, graph_nodes
from app.auth import validate_authentication
from app.catalog_entities import REGISTRY, EntityKind, EntityKindError, entity_href, kind, parse_kinds
from app.catalog_graph import NODE_KINDS
from app.entity_owners import KINDS as OWNER_KINDS
from app.main import app
from app.permissions import Resource

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "33333333-3333-4333-8333-333333333333"
_WHEN = datetime(2026, 10, 1, tzinfo=timezone.utc)
_OWNER = {"team": {"id": "t-1", "slug": "payments", "name": "Payments"}, "status": "confirmed", "source": "manual"}


def _id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


# ---------------------------------------------------------------------------------------------
# A fake database: one in-memory table per kind, honouring the store's keyset predicates
# ---------------------------------------------------------------------------------------------


def _kind_of(sql: str) -> EntityKind:
    """The registry kind a per-kind SELECT reads (by its table and live predicate)."""
    for entry in REGISTRY:
        if f"FROM {entry.table} e" in sql and entry.live_where in sql:
            if entry.key == "api" and "NOT e.publishable" in sql:
                continue
            return entry
    raise AssertionError(f"unexpected SQL: {sql[:120]}")


class FakeDb:
    """Records every statement; serves list, count and callout reads from ``rows``."""

    def __init__(self, rows: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        self.rows = rows or {}
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute_query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        sql = " ".join(sql.split())
        self.statements.append((sql, tuple(params)))
        if sql.startswith("SELECT %s AS kind"):
            keys = [p for p in params if isinstance(p, str) and p in catalog_entities.kind_keys() + ("gadget",)]
            return [{"kind": key, "n": len(self.rows.get(key, []))} for key in keys]
        if sql.startswith("SELECT count(*) AS n"):
            # One row per UNION ALL part, each counting 1.
            return [{"n": 1} for _ in range(sql.count("SELECT count(*) AS n"))]
        entry = _kind_of(sql)
        data = sorted(self.rows.get(entry.key, []), key=lambda r: (r["name"].lower(), r["id"]))
        limit = int(params[-1])
        if "e.id::text COLLATE \"C\") > (%s, %s)" in sql:
            name, entity_id = params[-3], params[-2]
            data = [r for r in data if (r["name"].lower(), r["id"]) > (name, entity_id)]
        elif re.search(r'COLLATE "C" >= %s', sql):
            data = [r for r in data if r["name"].lower() >= params[-2]]
        elif re.search(r'COLLATE "C" > %s', sql):
            data = [r for r in data if r["name"].lower() > params[-2]]
        return [
            {
                "id": r["id"],
                "slug": r.get("slug"),
                "name": r["name"],
                "description": r.get("description"),
                "updated_at": _WHEN,
                "sort_name": r["name"].lower(),
                "entity_owner": r.get("owner"),
            }
            for r in data[:limit]
        ]


def _catalog() -> Dict[str, List[Dict[str, Any]]]:
    """Two of every kind, with names that interleave across kinds (and one tie)."""
    names = {
        "api": ["Orders API", "Billing API"],
        "spec": ["Orders events", "Avro ledger"],
        "mcp_server": ["Docs MCP", "Orders MCP"],
        "consumer": ["Checkout web", "Orders API"],
        "connector": ["Kong prod", "Apigee"],
        "agent": ["Support bot", "Orders agent"],
        "model": ["Claude", "Llama self-hosted"],
        "gateway_config": ["Kong · prod", "Kong · staging"],
        "team": ["Payments", "Catalog team"],
    }
    rows: Dict[str, List[Dict[str, Any]]] = {}
    n = 0
    for key, labels in names.items():
        rows[key] = []
        for label in labels:
            n += 1
            rows[key].append({
                "id": _id(n),
                "name": label,
                "slug": None if key == "connector" else label.lower().replace(" ", "-"),
                "owner": _OWNER if key != "team" and n % 2 else None,
            })
    return rows


# ---------------------------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------------------------


def test_the_registry_lists_its_kinds_in_order() -> None:
    assert catalog_entities.kind_keys() == (
        "api", "spec", "mcp_server", "consumer", "connector", "agent", "model", "gateway_config", "team",
    )


def test_api_and_spec_are_distinct_projects_rows() -> None:
    assert kind("api").live_where == "e.publishable AND e.deleted_at IS NULL"
    assert kind("spec").live_where == "NOT e.publishable AND e.deleted_at IS NULL"


def test_the_registry_agrees_with_the_owner_registry_and_the_graph() -> None:
    for entry in REGISTRY:
        if entry.owner_kind:
            spec = OWNER_KINDS[entry.owner_kind]
            assert spec.table == entry.table
            assert spec.where == entry.live_where
        if entry.graph_kind:
            assert entry.graph_kind in NODE_KINDS
    assert kind("team").owner_kind is None and kind("team").graph_kind is None


def test_unknown_kinds_are_refused() -> None:
    with pytest.raises(EntityKindError):
        kind("galaxy")
    with pytest.raises(EntityKindError):
        parse_kinds(["api", "galaxy"])


def test_parse_kinds_dedupes_and_keeps_registry_order() -> None:
    assert [e.key for e in parse_kinds(["team,api", "api"])] == ["api", "team"]
    assert parse_kinds(None) == REGISTRY
    assert parse_kinds(["", " "]) == REGISTRY


def test_entity_href_fills_and_escapes() -> None:
    assert entity_href(kind("spec"), "a b", None) == "/ade/dashboard/catalog/a%20b"
    assert entity_href(kind("team"), "id-1", "payments") == "/ade/dashboard/teams/payments"
    assert entity_href(kind("api"), "p-1", "x") == "/ade/dashboard/versions?projectId=p-1"


def test_the_graph_labeller_reads_the_registry() -> None:
    sql = graph_nodes.label_sql()
    for entry in REGISTRY:
        if entry.graph_kind:
            table_kind = "project" if entry.graph_kind == "catalog_item" else entry.graph_kind
            assert f"FROM {entry.table} e" in sql[table_kind]
    assert "repository" in sql and "mcp_source" in sql


_GADGET = EntityKind(
    key="gadget",
    label="Gadget",
    plural_label="Gadgets",
    table="apiome.gadgets",
    live_where="e.deleted_at IS NULL",
    slug_sql="e.slug",
    description_sql="NULL::text",
    owner_kind=None,
    graph_kind="identity_group",
    resource=Resource.PROJECTS,
    detail_route="/ade/dashboard/gadgets/{id}",
    list_route=None,
)


@pytest.fixture
def with_gadget(monkeypatch):
    """Add a kind to the registry — nothing else changes."""
    monkeypatch.setattr(catalog_entities, "REGISTRY", (*REGISTRY, _GADGET))
    monkeypatch.setattr(catalog_entity_store, "REGISTRY", (*REGISTRY, _GADGET))
    yield


def test_a_new_kind_appears_in_the_summary_and_the_graph_without_other_changes(with_gadget, authed) -> None:
    db = FakeDb({"gadget": [{"id": _id(99), "name": "Widget"}]})
    with patch("app.catalog_entity_routes.db", db), patch(
        "app.catalog_entity_routes.has_permission", return_value=True
    ), patch("app.catalog_entity_routes.shadow_api_store") as shadow:
        shadow.load_report_connectors.return_value = []
        shadow.load_report_items.return_value = []
        shadow.load_catalog_entries.return_value = []
        body = authed.get(f"/v1/catalog/{_TENANT}/entities/summary").json()
    gadget = next(k for k in body["kinds"] if k["kind"] == "gadget")
    assert gadget == {
        "kind": "gadget", "label": "Gadget", "pluralLabel": "Gadgets", "count": 1,
        "ownerSupport": False, "graphKind": "identity_group", "listHref": None,
    }
    assert "FROM apiome.gadgets e" in graph_nodes.label_sql()["identity_group"]


# ---------------------------------------------------------------------------------------------
# Paging, envelope and statement count (store)
# ---------------------------------------------------------------------------------------------


def _page_through(db: FakeDb, limit: int) -> List[Tuple[str, str]]:
    seen: List[Tuple[str, str]] = []
    cursor = None
    for _ in range(50):
        page = catalog_entity_store.list_entities(db, _TENANT, REGISTRY, cursor=cursor, limit=limit)
        seen += [(row["kind"].key, row["id"]) for row in page.rows]
        cursor = page.next_cursor
        if cursor is None:
            break
    return seen


@pytest.mark.parametrize("limit", [1, 2, 3, 5, 12, 50])
def test_paging_visits_every_entity_once_in_name_order(limit: int) -> None:
    db = FakeDb(_catalog())
    seen = _page_through(db, limit)
    total = 2 * len(REGISTRY)  # two of every kind
    assert len(seen) == total and len(set(seen)) == total
    one_page = catalog_entity_store.list_entities(FakeDb(_catalog()), _TENANT, REGISTRY, limit=50).rows
    assert seen == [(row["kind"].key, row["id"]) for row in one_page]
    names = [row["name"].lower() for row in one_page]
    assert names == sorted(names)


def test_a_name_tie_breaks_by_kind_order() -> None:
    rows = catalog_entity_store.list_entities(FakeDb(_catalog()), _TENANT, REGISTRY, limit=50).rows
    tie = [row["kind"].key for row in rows if row["name"] == "Orders API"]
    assert tie == ["api", "consumer"]


@pytest.mark.parametrize("limit", [1, 5, 50])
def test_one_statement_per_kind_whatever_the_rows(limit: int) -> None:
    for rows in ({}, _catalog()):
        db = FakeDb(rows)
        catalog_entity_store.list_entities(db, _TENANT, REGISTRY, limit=limit)
        assert len(db.statements) == len(REGISTRY)
        assert all(params[-1] == limit + 1 for _sql, params in db.statements)


def test_a_team_filter_skips_kinds_without_owners_and_filters_in_sql() -> None:
    db = FakeDb(_catalog())
    catalog_entity_store.list_entities(db, _TENANT, REGISTRY, team="Payments", limit=10)
    assert len(db.statements) == len(REGISTRY) - 1
    assert not any("apiome.teams e" in sql for sql, _ in db.statements)
    for sql, params in db.statements:
        assert "own.entity_owner->'team'->>'slug' = %s" in sql and "payments" in params


def test_text_search_matches_name_slug_and_description() -> None:
    db = FakeDb()
    catalog_entity_store.list_entities(db, _TENANT, (kind("spec"),), q="orders", limit=10)
    sql, params = db.statements[0]
    assert "e.name ILIKE %s" in sql and params.count("%orders%") == 3


def test_projects_rows_join_both_owner_kinds() -> None:
    db = FakeDb()
    catalog_entity_store.list_entities(db, _TENANT, (kind("spec"),), limit=10)
    assert "eo.entity_kind IN ('project', 'catalog_item')" in db.statements[0][0]


@pytest.mark.parametrize("cursor", ["%%%", "bm90LWpzb24", "eyJuIjoxfQ", "eyJuIjoiYSIsImsiOiJnYWxheHkiLCJpIjoiMSJ9"])
def test_a_malformed_cursor_is_refused(cursor: str) -> None:
    with pytest.raises(catalog_entity_store.CursorError):
        catalog_entity_store.list_entities(FakeDb(), _TENANT, REGISTRY, cursor=cursor)


def test_a_cursor_round_trips() -> None:
    cursor = catalog_entity_store.encode_cursor("orders api", kind("consumer"), _id(8))
    assert catalog_entity_store.decode_cursor(cursor) == ("orders api", 3, _id(8))


def test_counts_are_one_statement() -> None:
    db = FakeDb(_catalog())
    counts = catalog_entity_store.kind_counts(db, _TENANT, REGISTRY)
    assert len(db.statements) == 1 and counts == {key: 2 for key in catalog_entities.kind_keys()}
    db = FakeDb(_catalog())
    counts = catalog_entity_store.kind_counts(db, _TENANT, REGISTRY, team="payments")
    assert counts["team"] == 0 and "FROM apiome.teams e" not in db.statements[0][0]


def test_unowned_counts_confirmed_live_teams_only() -> None:
    db = FakeDb()
    total = catalog_entity_store.unowned_count(db, _TENANT, REGISTRY)
    sql, params = db.statements[0]
    owner_kinds = sum(1 for entry in REGISTRY if entry.owner_kind)
    assert len(db.statements) == 1 and total == owner_kinds  # one each from the fake
    assert "eo.status = 'confirmed'" in sql and "t.deleted_at IS NULL" in sql
    assert "apiome.teams e" not in sql


def test_stale_is_twice_the_cadence_and_one_statement() -> None:
    db = FakeDb()
    total = catalog_entity_store.stale_count(
        db, _TENANT, connectors=True, mcp_servers=True,
        connector_default_seconds=300, connector_floor_seconds=60, mcp_default_seconds=3600,
    )
    sql, params = db.statements[0]
    assert len(db.statements) == 1 and total == 2
    assert sql.count("2 * ") == 2 and "c.status <> 'paused'" in sql and "m.enabled" in sql
    assert params == (_TENANT, 300, 60, _TENANT, 3600)
    assert catalog_entity_store.stale_count(
        FakeDb(), _TENANT, connectors=False, mcp_servers=False,
        connector_default_seconds=300, connector_floor_seconds=60, mcp_default_seconds=3600,
    ) == 0


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def _get(client: TestClient, path: str, db: FakeDb, allowed=lambda resource: True):
    with patch("app.catalog_entity_routes.db", db), patch(
        "app.catalog_entity_routes.has_permission", side_effect=lambda _db, _auth, resource, _action: allowed(resource)
    ):
        return client.get(path)


def test_the_list_returns_one_envelope_for_every_kind(authed) -> None:
    response = _get(authed, f"/v1/catalog/{_TENANT}/entities?limit=50", FakeDb(_catalog()))
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"] == {"nextCursor": None}
    assert {item["kind"] for item in body["items"]} == set(catalog_entities.kind_keys())
    for item in body["items"]:
        assert set(item) == {"kind", "id", "slug", "name", "description", "owner", "updatedAt", "href", "graphNode"}
    by_kind = {item["kind"]: item for item in body["items"]}
    assert by_kind["connector"]["slug"] is None
    assert by_kind["team"]["graphNode"] is None and by_kind["team"]["owner"] is None
    assert by_kind["spec"]["graphNode"]["kind"] == "catalog_item"
    assert by_kind["spec"]["href"].startswith("/ade/dashboard/catalog/")
    owned = [item for item in body["items"] if item["owner"]]
    assert owned and owned[0]["owner"]["team"]["slug"] == "payments"


def test_the_list_pages_with_the_cursor(authed) -> None:
    first = _get(authed, f"/v1/catalog/{_TENANT}/entities?limit=5", FakeDb(_catalog())).json()
    cursor = first["pagination"]["nextCursor"]
    assert len(first["items"]) == 5 and cursor
    second = _get(authed, f"/v1/catalog/{_TENANT}/entities?limit=5&cursor={cursor}", FakeDb(_catalog())).json()
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


def test_the_kind_filter_and_its_refusal(authed) -> None:
    body = _get(authed, f"/v1/catalog/{_TENANT}/entities?kind=spec&kind=team", FakeDb(_catalog())).json()
    assert {item["kind"] for item in body["items"]} == {"spec", "team"}
    response = _get(authed, f"/v1/catalog/{_TENANT}/entities?kind=galaxy", FakeDb())
    assert response.status_code == 422 and response.json()["detail"]["code"] == "kind-invalid"


def test_kinds_the_caller_cannot_view_are_left_out(authed) -> None:
    db = FakeDb(_catalog())
    body = _get(authed, f"/v1/catalog/{_TENANT}/entities", db, allowed=lambda r: r == Resource.PROJECTS).json()
    assert {item["kind"] for item in body["items"]} == {"api", "spec", "mcp_server"}
    assert len(db.statements) == 3


def test_a_malformed_cursor_is_a_400(authed) -> None:
    response = _get(authed, f"/v1/catalog/{_TENANT}/entities?cursor=nonsense", FakeDb())
    assert response.status_code == 400 and response.json()["detail"]["code"] == "cursor-invalid"


def test_entities_is_not_read_as_a_catalog_item(authed) -> None:
    with patch("app.catalog_routes.db") as catalog_db:
        response = _get(authed, f"/v1/catalog/{_TENANT}/entities", FakeDb())
    assert response.status_code == 200
    catalog_db.get_catalog_item.assert_not_called()


def test_the_summary_counts_kinds_and_computes_the_callouts(authed) -> None:
    db = FakeDb(_catalog())
    with patch("app.catalog_entity_routes.shadow_api_store") as shadow, patch(
        "app.catalog_entity_routes.build_shadow_report", return_value={"summary": {"shadow": 4}}
    ) as report:
        shadow.load_report_connectors.return_value = [{"id": "c-1"}]
        shadow.load_report_items.return_value = []
        shadow.load_catalog_entries.return_value = []
        body = _get(authed, f"/v1/catalog/{_TENANT}/entities/summary", db).json()
    assert [k["kind"] for k in body["kinds"]] == list(catalog_entities.kind_keys())
    assert all(k["count"] == 2 for k in body["kinds"])
    owner_kinds = sum(1 for entry in REGISTRY if entry.owner_kind)
    assert body["callouts"] == {"unowned": owner_kinds, "stale": 2, "shadow": 4}
    report.assert_called_once()
    shadow.load_report_items.assert_called_once_with(db, ["c-1"])
    assert len(db.statements) == 3  # counts, unowned, stale


def test_the_summary_hides_callouts_the_caller_cannot_see(authed) -> None:
    db = FakeDb(_catalog())
    with patch("app.catalog_entity_routes.shadow_api_store") as shadow:
        body = _get(authed, f"/v1/catalog/{_TENANT}/entities/summary", db, allowed=lambda r: r == Resource.TEAMS).json()
    assert [k["kind"] for k in body["kinds"]] == ["team"]
    assert body["callouts"] == {"unowned": None, "stale": None, "shadow": None}
    shadow.load_report_connectors.assert_not_called()
