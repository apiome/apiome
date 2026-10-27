"""REST hypermedia conventions — MFI-19.6 (#3984).

Acceptance: an OpenAPI artifact declaring JSON:API / HAL is tagged and conformance-linted; a JTD
schema imports via the JSON Schema path; the catalog facet filters by convention; fixtures cover
each convention (``fixtures/rest_conventions``: a conforming and a nonconforming document each).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_categories import (
    UNCATEGORIZED,
    CatalogFacetFilters,
    catalog_convention_label,
    catalog_facet_counts,
    filter_catalog_items,
    item_conventions,
)
from app.import_source import get_import_source, load_builtin_import_sources
from app.import_source_pipeline import rest_conventions_metadata
from app.lint_engine import get_paradigm_rule_pack, lint_canonical_model
from app.main import app
from app.rest_conventions import (
    CONVENTIONS,
    convention_details,
    convention_of_media_type,
    detect_conventions,
    iter_bodies,
)
from app.rest_conventions_lint import RULE_IDS, RestConventionsRulePack

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rest_conventions"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

load_builtin_import_sources()


def _openapi(name: str) -> CanonicalApi:
    source = get_import_source("openapi")
    return source.normalize(source.parse((_FIXTURES / name).read_text(encoding="utf-8"), source_label=name))


def _rules(api: CanonicalApi) -> Set[str]:
    return {f.rule for f in lint_canonical_model(api).findings if f.rule.startswith("rest-conventions.")}


# ===========================================================================
# Detection and details
# ===========================================================================


@pytest.mark.parametrize(
    "media_type, convention",
    [
        ("application/vnd.api+json", "jsonapi"),
        ("application/vnd.api+json; ext=\"https://jsonapi.org/ext/atomic\"", "jsonapi"),
        ("application/HAL+JSON", "hal"),
        ("application/hal+xml", "hal"),
        ("application/prs.hal-forms+json", "hal-forms"),
        ("application/ld+json", "json-ld"),
        ('application/ld+json; profile="http://www.w3.org/ns/hydra/core#"', "hydra"),
        ("application/json", None),
        ("", None),
    ],
)
def test_media_types(media_type: str, convention):
    assert convention_of_media_type(media_type) == convention


@pytest.mark.parametrize(
    "name, conventions",
    [
        ("jsonapi.yaml", ["jsonapi"]),
        ("hal.yaml", ["hal", "hal-forms"]),
        ("hydra.yaml", ["json-ld", "hydra"]),
    ],
)
def test_an_artifact_is_tagged_with_what_it_declares(name: str, conventions: List[str]):
    assert detect_conventions(_openapi(name)) == conventions


def test_an_artifact_that_declares_none_is_not_tagged():
    source = get_import_source("openapi")
    path = _EXAMPLES / "openapi" / "01-numeric-constraints.yaml"
    api = source.normalize(source.parse(path.read_text(), source_label=path.name))
    assert detect_conventions(api) == []
    assert rest_conventions_metadata(api) == {}


def test_the_resource_and_link_conventions_are_normalized():
    assert convention_details(_openapi("jsonapi.yaml")) == {
        "jsonapi": {"operations": ["GET /articles", "POST /articles"], "resourceTypes": ["articles"]}
    }
    assert convention_details(_openapi("hal.yaml")) == {
        "hal": {"operations": ["GET /orders"], "linkRelations": ["item", "next", "self"], "embedded": ["orders"]},
        "hal-forms": {"operations": ["GET /orders/{id}"], "linkRelations": ["self"], "templates": ["default"]},
    }
    details = convention_details(_openapi("hydra.yaml"))
    assert details["hydra"] == {"operations": ["GET /people"], "types": ["hydra:Collection"]}
    assert details["json-ld"]["types"] == ["Person", "hydra:Collection"]


def test_swagger_2_bodies_are_read():
    source = get_import_source("openapi")
    document = {
        "swagger": "2.0",
        "info": {"title": "S", "version": "1"},
        "produces": ["application/hal+json"],
        "paths": {
            "/orders": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "schema": {
                                "type": "object",
                                "properties": {"_links": {"type": "object", "properties": {}}},
                            },
                        }
                    }
                }
            }
        },
    }
    api = source.normalize(source.parse(json.dumps(document), source_label="s.json"))
    assert detect_conventions(api) == ["hal"]
    assert "rest-conventions.hal-self-link" in _rules(api)


def _canonical_only() -> CanonicalApi:
    """A REST model with no retained document (a RAML or Postman import looks like this)."""
    order = Type(
        key="Order",
        name="Order",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Order.total", name="total", type=TypeRef(name="number"))],
    )
    message = Message(
        key="GET /orders#response.200",
        role=MessageRole.RESPONSE,
        payload=TypeRef(name="Order"),
        content_types=["application/hal+json"],
        status_code="200",
    )
    op = Operation(key="GET /orders", name="getOrders", kind=OperationKind.REQUEST_RESPONSE, messages=[message])
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="raml-1.0",
        identity=ApiIdentity(name="Orders"),
        services=[Service(key="orders", name="orders", operations=[op])],
        types=[order],
    )


def test_without_a_document_the_canonical_messages_are_read():
    api = _canonical_only()
    (body,) = list(iter_bodies(api))
    assert (body.convention, body.status, body.role) == ("hal", "200", "response")
    assert body.schema == {"type": "object", "properties": {"total": {}}}
    assert detect_conventions(api) == ["hal"]
    assert _rules(api) == {"rest-conventions.hal-self-link"}


# ===========================================================================
# Conformance lint
# ===========================================================================


def test_the_pack_runs_for_the_rest_paradigm():
    assert get_paradigm_rule_pack(ApiParadigm.REST) is RestConventionsRulePack
    assert len(RULE_IDS) == 9


@pytest.mark.parametrize("name", ["jsonapi.yaml", "hal.yaml", "hydra.yaml"])
def test_conforming_documents_are_clean(name: str):
    assert _rules(_openapi(name)) == set()


@pytest.mark.parametrize(
    "name, rules",
    [
        (
            "jsonapi-nonconforming.yaml",
            {"jsonapi-data-and-errors", "jsonapi-resource-object", "jsonapi-error-document", "jsonapi-top-level"},
        ),
        ("hal-nonconforming.yaml", {"hal-self-link", "hal-link-object", "hal-forms-template"}),
        ("hydra-nonconforming.yaml", {"hydra-collection-member", "jsonld-context"}),
    ],
)
def test_nonconforming_documents_are_flagged(name: str, rules: Set[str]):
    assert _rules(_openapi(name)) == {f"rest-conventions.{rule}" for rule in rules}


def test_every_rule_is_covered_by_a_fixture():
    fired: Set[str] = set()
    for name in ("jsonapi-nonconforming.yaml", "hal-nonconforming.yaml", "hydra-nonconforming.yaml"):
        fired |= _rules(_openapi(name))
    assert fired == set(RULE_IDS)


def test_findings_point_at_the_body():
    report = lint_canonical_model(_openapi("hal-nonconforming.yaml"))
    (finding,) = [f for f in report.findings if f.rule.endswith("link-object")]
    assert finding.path == "GET /orders#response.200 (application/hal+json) _links.next"
    assert finding.severity == "warning"


def test_a_schema_that_declares_no_properties_is_not_judged():
    source = get_import_source("openapi")
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Opaque", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "responses": {
                        "200": {"description": "ok", "content": {"application/vnd.api+json": {"schema": {}}}}
                    }
                }
            }
        },
    }
    api = source.normalize(source.parse(json.dumps(document), source_label="o.json"))
    assert detect_conventions(api) == ["jsonapi"]
    assert _rules(api) == set()


# ===========================================================================
# Recorded on the revision; the catalog facet
# ===========================================================================


def test_the_revision_records_the_conventions():
    assert rest_conventions_metadata(_openapi("hal.yaml")) == {
        "restConventions": ["hal", "hal-forms"],
        "restConventionDetails": convention_details(_openapi("hal.yaml")),
    }


def _item(item_id: str, conventions: List[str] | None) -> Dict[str, Any]:
    metadata = {"restConventions": conventions} if conventions is not None else {}
    return {
        "id": item_id,
        "protocol": "rest",
        "source_format": "openapi-3.1",
        "metadata": {},
        "format_metadata": metadata,
    }


_ITEMS = [_item("articles", ["jsonapi"]), _item("orders", ["hal", "hal-forms"]), _item("plain", None)]


def test_an_items_conventions_are_read_in_order():
    assert item_conventions(_item("x", ["hydra", "jsonapi", "bogus"])) == ["jsonapi", "hydra"]
    assert item_conventions({"format_metadata": None}) == []
    assert catalog_convention_label("hal-forms") == "HAL-FORMS"
    assert catalog_convention_label(UNCATEGORIZED) == "No convention"


@pytest.mark.parametrize(
    "selected, expected",
    [
        (["jsonapi"], ["articles"]),
        (["JSON:API"], ["articles"]),
        (["hal_forms"], ["orders"]),
        (["jsonapi", "hal"], ["articles", "orders"]),
        ([UNCATEGORIZED], ["plain"]),
        (["nonsense"], []),
    ],
)
def test_the_facet_filters_by_convention(selected: List[str], expected: List[str]):
    filters = CatalogFacetFilters.from_query(conventions=selected)
    assert [item["id"] for item in filter_catalog_items(_ITEMS, {}, filters)] == expected


def test_the_facet_counts_conventions():
    counts = catalog_facet_counts(_ITEMS, {}, CatalogFacetFilters.from_query())
    by_value = {bucket["value"]: (bucket["label"], bucket["count"]) for bucket in counts["conventions"]}
    assert by_value == {
        "jsonapi": ("JSON:API", 1),
        "hal": ("HAL", 1),
        "hal-forms": ("HAL-FORMS", 1),
        UNCATEGORIZED: ("No convention", 1),
    }


client = TestClient(app)


def test_the_catalog_routes_take_the_convention_facet():
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t", "user_id": "u", "auth_method": "jwt"}
    try:
        with patch("app.catalog_routes.db") as db:
            db.get_catalog_items_for_tenant.return_value = [
                {**item, "tenant_id": "t", "creator_id": "u", "name": item["id"], "slug": item["id"], "enabled": True,
                 "publishable": False, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
                 "deleted_at": None, "versions_count": 1, "tool_versions": {}}
                for item in _ITEMS
            ]
            db.get_artifact_tags_for_projects.return_value = {}
            listed = client.get("/v1/catalog/t", params={"convention": "hal"})
            facets = client.get("/v1/catalog/t/facets", params={"convention": "jsonapi"})
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert listed.status_code == 200
    assert [(item["id"], item["conventions"]) for item in listed.json()] == [("orders", ["hal", "hal-forms"])]
    body = facets.json()
    assert (body["total"], body["matched"]) == (3, 1)
    assert {b["value"] for b in body["facets"]["conventions"] if b["selected"]} == {"jsonapi"}


def test_the_convention_vocabulary():
    assert CONVENTIONS == ("jsonapi", "hal", "hal-forms", "json-ld", "hydra")


# ===========================================================================
# JTD through the JSON Schema path
# ===========================================================================


def test_a_jtd_schema_imports_like_its_json_schema():
    """A JTD schema lands as the same data-schema record its JSON Schema equivalent does: the same
    fields, required and optional alike."""
    jtd_source, json_source = get_import_source("jtd"), get_import_source("json-schema")
    jtd_text = (_EXAMPLES / "jtd" / "01-user.jtd.json").read_text()
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "User",
        "type": "object",
        "required": ["id", "email", "status", "createdAt"],
        "properties": {
            "id": {"type": "string"},
            "email": {"type": "string"},
            "status": {"enum": ["active", "suspended", "deleted"]},
            "createdAt": {"type": "string", "format": "date-time"},
            "displayName": {"type": "string"},
            "roles": {"type": "array", "items": {"type": "string"}},
            "address": {"type": "object", "properties": {"street": {"type": "string"}}},
        },
    }
    from_jtd = jtd_source.normalize(jtd_source.parse(jtd_text, source_label="user.jtd.json"))
    from_schema = json_source.normalize(json_source.parse(json.dumps(schema), source_label="user.schema.json"))

    def shape(api: CanonicalApi) -> Dict[str, bool]:
        user = api.type_by_key("User")
        return {f.name: f.type.nullable for f in user.fields}

    assert from_jtd.paradigm is from_schema.paradigm is ApiParadigm.DATA_SCHEMA
    assert shape(from_jtd) == shape(from_schema)
