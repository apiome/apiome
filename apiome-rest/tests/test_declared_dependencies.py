"""Declared dependencies without a database — CDG-3.2 (#5967).

* The ``x-apiome-depends-on`` grammar, through the **real** import adapters' ``model.raw`` for
  AsyncAPI, JSON Schema, Avro and GraphQL, and as a plain OpenAPI dict.
* Backstage ``catalog-info`` parsing: entity references, the three relation lists, multi-document
  files, malformed YAML.
* The three producers' hooks: the in-process import, the worker-backed (OpenAPI) completion and the
  repository scan — each best-effort.
* The ``…/dependencies`` routes: permissions per kind, validation, status codes.
* The migration's shape.

Behaviour against real rows is in ``test_declared_dependencies_db.py``.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import declared_dependency_store as store
from app import graph_routes as routes
from app import import_source_pipeline, spec_import_engine
from app.auth import validate_authentication
from app.declared_dependencies import (
    MAX_DECLARED,
    DependencyValidationError,
    backstage_entities,
    backstage_name,
    is_backstage_path,
    parse_reference,
    references_from_document,
)
from app.import_source import get_import_source
from app.main import app
from app.repository_file_scan import apply_backstage

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_USER = "33333333-3333-4333-8333-333333333333"


def _slugs(document: Any) -> List[tuple]:
    return [(ref.slug, ref.pointer) for ref in references_from_document(document)]


# ---------------------------------------------------------------------------------------------
# the grammar
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,slug,pointer",
    [
        ("payments", "payments", None),
        ("Payments#/components/schemas/Card", "payments", "/components/schemas/Card"),
        ("customers#components", "customers", "/components"),
        ("  ledger  ", "ledger", None),
    ],
)
def test_parse_reference(text, slug, pointer) -> None:
    ref = parse_reference(text)
    assert (ref.slug, ref.pointer, ref.edge_kind) == (slug, pointer, "depends_on")
    assert ref.reference == text.strip()


def test_an_empty_reference_is_nothing() -> None:
    assert parse_reference("   ") is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (["payments", "ledger#/paths"], [("payments", None), ("ledger", "/paths")]),
        ("payments, ledger", [("payments", None), ("ledger", None)]),
        ("payments", [("payments", None)]),
        (["payments", "payments", 7, None, {"x": 1}], [("payments", None), ("7", None)]),
        ({"payments": True}, []),
    ],
)
def test_an_openapi_root_declares_a_list_a_string_or_a_comma_list(value, expected) -> None:
    assert _slugs({"openapi": "3.1.0", "x-apiome-depends-on": value}) == expected


def test_no_extension_declares_nothing() -> None:
    assert _slugs({"openapi": "3.1.0"}) == [] and _slugs(None) == [] and _slugs("not a doc") == []


def test_declarations_are_capped() -> None:
    many = [f"api-{i}" for i in range(MAX_DECLARED + 50)]
    assert len(references_from_document({"x-apiome-depends-on": many})) == MAX_DECLARED


def _raw(key: str, text: str) -> Any:
    adapter = get_import_source(key)
    return adapter.normalize(adapter.parse(text)).raw


def test_asyncapi_through_its_adapter() -> None:
    raw = _raw("asyncapi", json.dumps({
        "asyncapi": "2.6.0", "info": {"title": "Orders", "version": "1"}, "channels": {},
        "x-apiome-depends-on": ["payments#/channels/card"],
    }))
    assert _slugs(raw) == [("payments", "/channels/card")]


def test_json_schema_through_its_adapter() -> None:
    raw = _raw("json-schema", json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Order", "type": "object",
        "x-apiome-depends-on": "customers",
    }))
    assert _slugs(raw) == [("customers", None)]


def test_avro_through_its_adapter() -> None:
    raw = _raw("avro", json.dumps({
        "type": "record", "name": "Order", "fields": [{"name": "id", "type": "string"}],
        "x-apiome-depends-on": ["payments"],
    }))
    assert _slugs(raw) == [("payments", None)]


@pytest.mark.parametrize(
    "sdl",
    [
        '"""\nx-apiome-depends-on: payments, customers#/types/Customer\n"""\nschema { query: Query }\n'
        "type Query { a: String }",
        '"""\nThe orders graph.\n\nx-apiome-depends-on: payments, customers#/types/Customer\n"""\n'
        "schema { query: Query }\ntype Query { a: String }",
    ],
)
def test_graphql_declares_in_a_description_line(sdl) -> None:
    assert _slugs(_raw("graphql", sdl)) == [("payments", None), ("customers", "/types/Customer")]


def test_avro_idl_and_unparseable_avro_declare_nothing() -> None:
    assert _slugs({"avro": "protocol Orders { record A { string id; } }"}) == []


# ---------------------------------------------------------------------------------------------
# Backstage
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [("catalog-info.yaml", True), ("svc/Catalog-Info.YML", True), ("catalog-info.json", False),
     ("docs/my-catalog-info.yaml", False)],
)
def test_backstage_paths(path, expected) -> None:
    assert is_backstage_path(path) is expected


@pytest.mark.parametrize(
    "ref,name",
    [("api:default/Payments", "payments"), ("api:payments", "payments"), ("default/payments", "payments"),
     ("payments", "payments"), ("component:", None), ("", None)],
)
def test_backstage_entity_references(ref, name) -> None:
    assert backstage_name(ref) == name


def test_a_catalog_info_file_yields_each_entitys_relations() -> None:
    text = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata: {name: orders-service}
spec:
  providesApis: [api:orders]
  consumesApis: [api:default/payments, api:payments, api:customers]
  dependsOn: [resource:orders-db]
---
kind: Group
metadata: {name: team-a}
---
kind: API
metadata: {name: orders}
spec: {type: openapi}
"""
    first, second = backstage_entities(text)
    assert (first.name, first.provides) == ("orders-service", ("orders",))
    assert [(r.edge_kind, r.slug, r.reference) for r in first.references] == [
        ("consumes", "payments", "api:default/payments"),
        ("consumes", "customers", "api:customers"),
        ("depends_on", "orders-db", "resource:orders-db"),
    ]
    assert (second.name, second.references) == ("orders", ())


def test_malformed_backstage_yaml_yields_nothing() -> None:
    assert backstage_entities("kind: [unclosed") == [] and backstage_entities("") == []


# ---------------------------------------------------------------------------------------------
# the producers' hooks
# ---------------------------------------------------------------------------------------------


def test_the_in_process_import_records_spec_declarations() -> None:
    calls: List[tuple] = []
    with patch("app.declared_dependency_store.record_spec_dependencies", side_effect=lambda *a: calls.append(a)):
        import_source_pipeline._record_spec_dependencies("t-1", "p-1", False, {"x-apiome-depends-on": "a"})
        import_source_pipeline._record_spec_dependencies("t-1", "p-1", True, {})
    assert calls == [
        ("t-1", "catalog_item", "p-1", {"x-apiome-depends-on": "a"}),
        ("t-1", "project", "p-1", {}),
    ]


def test_a_recording_failure_never_raises(monkeypatch) -> None:
    def _down(work):
        raise RuntimeError("database down")

    monkeypatch.setattr(store.db, "_guarded_tx", _down)
    assert store.record_spec_dependencies(_TENANT, "project", _PROJECT, {"x-apiome-depends-on": "a"}) is None
    assert store.record_backstage_dependencies(_TENANT, "r", "main", {}) is None


@pytest.mark.parametrize("encoding", ["yaml", "json"])
def test_a_worker_import_records_its_documents_declarations(monkeypatch, encoding) -> None:
    from app.database import db

    document = {"openapi": "3.1.0", "x-apiome-depends-on": ["payments"]}
    text = json.dumps(document) if encoding == "json" else "openapi: 3.1.0\nx-apiome-depends-on: [payments]\n"
    payload = {"document_base64": base64.b64encode(text.encode()).decode()}
    monkeypatch.setattr(db, "get_project_by_id", lambda pid, tid: {"id": pid, "publishable": False})
    calls: List[tuple] = []
    with patch("app.declared_dependency_store.record_spec_dependencies", side_effect=lambda *a: calls.append(a)):
        spec_import_engine._record_worker_declared_dependencies(_TENANT, _PROJECT, payload)
    assert calls == [(_TENANT, "catalog_item", _PROJECT, document)]


@pytest.mark.parametrize(
    "payload",
    [{}, {"document_base64": base64.b64encode(b"- just\n- a list\n").decode()},
     {"document_base64": base64.b64encode(b"key: [unclosed").decode()}],
)
def test_an_unreadable_worker_document_records_nothing(monkeypatch, payload) -> None:
    from app.database import db

    monkeypatch.setattr(db, "get_project_by_id", lambda pid, tid: {"id": pid, "publishable": True})
    with patch("app.declared_dependency_store.record_spec_dependencies") as record:
        spec_import_engine._record_worker_declared_dependencies(_TENANT, _PROJECT, payload)
    record.assert_not_called()


class _ScanDb:
    def __init__(self, paths: List[str]) -> None:
        self.paths = paths
        self.queries: List[str] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        self.queries.append(sql)
        return [{"path": path} for path in self.paths]


def test_the_scan_hands_every_catalog_info_file_to_the_recorder() -> None:
    fetched: List[str] = []
    recorded: List[tuple] = []

    def _fetch(owner, repo, path, ref, token, max_bytes):
        fetched.append(path)
        return f"text of {path}", False

    db = _ScanDb(["catalog-info.yaml", "svc/catalog-info.yml"])
    apply_backstage(
        db, _TENANT, "r", "main", "acme", "orders", None, fetch_text=_fetch,
        record=lambda *a: recorded.append(a) or {"entities": 1}, catalog=lambda *a, **k: None,
    )
    assert fetched == ["catalog-info.yaml", "svc/catalog-info.yml"]
    assert recorded == [(_TENANT, "r", "main", {
        "catalog-info.yaml": "text of catalog-info.yaml", "svc/catalog-info.yml": "text of svc/catalog-info.yml",
    })]
    assert "catalog-info" in db.queries[0]


def test_without_catalog_info_files_the_recorder_still_runs_to_clear_old_ones() -> None:
    recorded: List[tuple] = []
    apply_backstage(_ScanDb([]), _TENANT, "r", "main", "acme", "orders", None, record=lambda *a: recorded.append(a),
                    catalog=lambda *a, **k: None)
    assert recorded == [(_TENANT, "r", "main", {})]


def test_a_github_failure_never_fails_the_scan() -> None:
    def _broken(*a, **k):
        raise RuntimeError("GitHub 502")

    assert apply_backstage(
        _ScanDb(["catalog-info.yaml"]), _TENANT, "r", "main", "acme", "orders", None, fetch_text=_broken,
        record=lambda *a: pytest.fail("should not record"), catalog=lambda *a, **k: pytest.fail("should not stage"),
    ) is None


# ---------------------------------------------------------------------------------------------
# the routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return True

    monkeypatch.setattr(routes.db, "user_has_permission", _has)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield TestClient(app), asked
    app.dependency_overrides.clear()


def _result(**extra: Any) -> Dict[str, Any]:
    edge = {
        "id": "e1", "from_kind": "project", "from_id": _PROJECT, "to_kind": "project", "to_id": _USER,
        "edge_kind": "depends_on", "pointer": None, "provenance": "declared", "source_ref": "manual",
        "evidence": {"reference": "payments"}, "first_seen_at": None, "last_seen_at": None,
        "stale_since": None, "stale": False,
    }
    unresolved = {"source_ref": "spec", "reference": "ledger", "pointer": None, "edge_kind": "depends_on",
                  "reason": "not-found", "note": None, "created_at": None}
    return {"kind": "project", "entity_id": _PROJECT, "declared": [edge], "unresolved": [unresolved],
            "truncated": False, **extra}


_URL = f"/v1/graph/acme/entities/project/{_PROJECT}/dependencies"


def test_get_reads_with_the_kinds_view_permission(client, monkeypatch) -> None:
    http, asked = client
    monkeypatch.setattr(routes, "read_dependencies", lambda tenant, kind, entity: _result())
    body = http.get(_URL).json()
    assert body["declared"][0]["evidence"]["reference"] == "payments"
    assert body["unresolved"][0]["reason"] == "not-found"
    http.get(f"/v1/graph/acme/entities/consumer/{_PROJECT}/dependencies")
    http.get(f"/v1/graph/acme/entities/connector/{_PROJECT}/dependencies")
    assert asked == ["projects:view", "consumer_contracts:view", "imports:view"]


def test_put_sends_the_list_with_the_kinds_edit_permission(client, monkeypatch) -> None:
    http, asked = client
    seen: Dict[str, Any] = {}

    def _put(tenant, kind, entity, items, *, actor):
        seen.update(tenant=tenant, kind=kind, entity=entity, items=items, actor=actor)
        return _result()

    monkeypatch.setattr(routes, "put_dependencies", _put)
    body = {"dependencies": [{"to": {"slug": "payments"}, "pointer": "/paths", "note": "checkout"}]}
    response = http.put("/v1/graph/acme/entities/project/orders/dependencies", json=body)
    assert response.status_code == 200
    assert seen["entity"] == "orders" and seen["tenant"] == _TENANT
    assert seen["items"] == [{"to": {"kind": None, "id": None, "slug": "payments"}, "pointer": "/paths",
                              "note": "checkout"}]
    assert seen["actor"].user_id == _USER
    assert asked == ["projects:edit"]


def test_the_routes_refuse_bad_input(client, monkeypatch) -> None:
    http, _ = client
    assert http.get(f"/v1/graph/acme/entities/galaxy/{_PROJECT}/dependencies").status_code == 400
    too_many = {"dependencies": [{"to": {"slug": f"a{i}"}} for i in range(MAX_DECLARED + 1)]}
    assert http.put(_URL, json=too_many).status_code == 422
    assert http.put(_URL, json={"dependencies": [{"to": {"slug": "a"}, "extra": 1}]}).status_code == 422

    def _missing(*a, **k):
        raise DependencyValidationError("graph-entity-not-found", "no project 'orders' in this tenant")

    monkeypatch.setattr(routes, "read_dependencies", _missing)
    response = http.get(_URL)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "graph-entity-not-found"

    def _invalid(*a, **k):
        raise DependencyValidationError("graph-invalid", "each dependency names its target by exactly one")

    monkeypatch.setattr(routes, "put_dependencies", _invalid)
    assert http.put(_URL, json={"dependencies": []}).status_code == 400


def test_put_needs_edit(client, monkeypatch) -> None:
    http, _ = client
    monkeypatch.setattr(routes.db, "user_has_permission", lambda t, u, resource, action: action == "view")
    assert http.put(_URL, json={"dependencies": []}).status_code == 403


@pytest.mark.parametrize(
    "item,message",
    [
        ({"to": {}}, "exactly one"),
        ({"to": {"slug": "a", "id": _PROJECT, "kind": "project"}}, "exactly one"),
        ({"to": {"id": _PROJECT}}, "needs a kind"),
        ({"to": {"slug": "a", "kind": "consumer"}}, "by slug"),
        ({"to": {"slug": "a"}, "pointer": "paths"}, "JSON pointer"),
        ({"to": {"slug": "a"}, "note": "x" * 501}, "500"),
    ],
)
def test_malformed_put_entries_are_graph_invalid(item, message) -> None:
    with pytest.raises(DependencyValidationError, match=message) as raised:
        store._manual_reference(item)
    assert raised.value.code == "graph-invalid"


def test_a_well_formed_put_entry() -> None:
    ref = store._manual_reference({"to": {"kind": "consumer", "id": _USER}, "pointer": "/x", "note": "why"})
    assert (ref.kind, ref.entity_id, ref.slug, ref.pointer, ref.note) == ("consumer", _USER, None, "/x", "why")
    assert ref.reference == f"consumer:{_USER}#/x"


# ---------------------------------------------------------------------------------------------
# the migration
# ---------------------------------------------------------------------------------------------


def test_migration(repo_root) -> None:
    text = (repo_root / "apiome-db/scripts/V289__catalog_unresolved_dependencies_cdg_3_2.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS catalog_unresolved_dependencies" in text
    assert "UNIQUE NULLS NOT DISTINCT" in text
    assert "(tenant_id, from_kind, from_id, source_ref, reference, pointer, edge_kind)" in text
    assert "CHECK (reason IN ('not-found', 'self'))" in text
    assert "REFERENCES tenants(id) ON DELETE CASCADE" in text
