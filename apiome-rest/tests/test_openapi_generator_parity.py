"""The generator differences the COA-5.13 (#7089) parity audit found, each fixed and pinned.

The UI used to build revision documents with its own TypeScript generator. Before it was removed,
both generators rendered the OpenAPI corpus and the differences were classified
(``docs/coa-5-13-generator-parity.md``). Five were defects of this generator, which is now the
only one:

* a property's ``description`` column was ignored;
* an operation's ``operationId`` was dropped (the row names it ``operation_id``);
* only ``apiKey`` security schemes were written;
* an object property with required children lost its own ``required`` flag;
* ``type: object`` was forced on a schema composed with ``allOf`` / ``anyOf`` / ``oneOf``.

Also here: ``include_private``, which the members' document uses to keep ``x-private`` operations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.openapi_generator import (
    _security_schemes_from_rows,
    build_class_openapi_schema,
    generate_openapi_spec,
)
from app.paths_generator import build_operation_for_openapi


def _prop(
    pid: str, name: str, data: Dict[str, Any], *, parent: Optional[str] = None, description: Optional[str] = None
) -> Dict[str, Any]:
    """A ``class_properties`` row."""
    return {"id": pid, "name": name, "data": data, "parent_id": parent, "description": description}


def _schema(properties: List[Dict[str, Any]], schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return build_class_openapi_schema({"id": "c1", "name": "Order", "schema": schema or {"type": "object"}}, properties)


# ───────────────────────────── property descriptions ─────────────────────────────


def test_the_description_column_is_written() -> None:
    built = _schema([_prop("p1", "amount", {"type": "integer"}, description="Amount in minor units.")])
    assert built["properties"]["amount"] == {"type": "integer", "description": "Amount in minor units."}


def test_the_description_column_wins_over_the_stored_json() -> None:
    built = _schema([_prop("p1", "amount", {"type": "integer", "description": "old"}, description="new")])
    assert built["properties"]["amount"]["description"] == "new"


def test_a_description_in_the_json_is_kept_when_the_column_is_empty() -> None:
    built = _schema([_prop("p1", "amount", {"type": "integer", "description": "from json"}, description="")])
    assert built["properties"]["amount"]["description"] == "from json"


@pytest.mark.parametrize(
    "data", [{"type": "string", "title": "Code"}, {"type": "string", "title": "Code", "description": None}]
)
def test_the_title_stands_in_for_a_missing_description(data: Dict[str, Any]) -> None:
    assert _schema([_prop("p1", "code", data)])["properties"]["code"]["description"] == "Code"


def test_a_property_without_any_description_has_none() -> None:
    assert _schema([_prop("p1", "code", {"type": "string", "description": None})])["properties"]["code"] == {
        "type": "string"
    }


def test_a_nested_property_takes_its_description_column_too() -> None:
    built = _schema(
        [
            _prop("p1", "profile", {"type": "object"}),
            _prop("p2", "avatar", {"type": "string"}, parent="p1", description="Use avatarUrl instead"),
        ]
    )
    assert built["properties"]["profile"]["properties"]["avatar"]["description"] == "Use avatarUrl instead"


# ───────────────────────────── required ─────────────────────────────


def test_an_object_property_with_required_children_stays_required_on_its_class() -> None:
    built = _schema(
        [
            _prop("p1", "customer", {"type": "object", "required": True}),
            _prop("p2", "id", {"type": "string", "required": True}, parent="p1"),
            _prop("p3", "note", {"type": "string", "required": False}),
        ]
    )
    assert built["required"] == ["customer"]
    assert built["properties"]["customer"]["required"] == ["id"]
    assert "required" not in built["properties"]["note"]


def test_a_nested_object_with_required_children_stays_required_on_its_parent() -> None:
    built = _schema(
        [
            _prop("p1", "shipping", {"type": "object"}),
            _prop("p2", "address", {"type": "object", "required": True}, parent="p1"),
            _prop("p3", "city", {"type": "string", "required": True}, parent="p2"),
        ]
    )
    shipping = built["properties"]["shipping"]
    assert shipping["required"] == ["address"]
    assert shipping["properties"]["address"]["required"] == ["city"]
    assert "required" not in built


def test_array_items_collect_their_required_children() -> None:
    built = _schema(
        [
            _prop("p1", "lines", {"type": "array", "required": True}),
            _prop("p2", "sku", {"type": "string", "required": True}, parent="p1"),
            _prop("p3", "qty", {"type": "integer"}, parent="p1"),
        ]
    )
    assert built["required"] == ["lines"]
    assert built["properties"]["lines"]["items"] == {
        "type": "object",
        "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}},
        "required": ["sku"],
    }


# ───────────────────────────── composed schemas ─────────────────────────────


@pytest.mark.parametrize("keyword", ["allOf", "anyOf", "oneOf"])
def test_a_composed_schema_is_not_made_an_object(keyword: str) -> None:
    built = _schema([], {keyword: [{"type": "string"}, {"type": "integer"}]})
    assert "type" not in built
    assert built[keyword] == [{"type": "string"}, {"type": "integer"}]
    assert built["title"] == "Order"


def test_a_composed_schema_keeps_a_type_it_declares_and_its_own_properties() -> None:
    built = _schema(
        [_prop("p1", "extra", {"type": "string", "required": True})],
        {"type": "object", "allOf": [{"$ref": "#/components/schemas/Base"}]},
    )
    assert built["type"] == "object"
    assert built["properties"] == {"extra": {"type": "string"}}
    assert built["required"] == ["extra"]


def test_a_plain_schema_is_still_an_object() -> None:
    assert _schema([], {})["type"] == "object"


# ───────────────────────────── operationId ─────────────────────────────


@pytest.mark.parametrize("key", ["operation_id", "operationId"])
def test_the_operation_id_is_written_from_either_spelling(key: str) -> None:
    built = build_operation_for_openapi({"operation": "get", "description": {key: "listPets"}, "responses": []})
    assert built["operationId"] == "listPets"


def test_an_operation_without_an_id_has_none() -> None:
    built = build_operation_for_openapi({"operation": "get", "description": {"summary": "List"}, "responses": []})
    assert "operationId" not in built


# ───────────────────────────── security schemes ─────────────────────────────


def _scheme(name: str, scheme_type: str, **fields: Any) -> Dict[str, Any]:
    return {"scheme_name": name, "scheme_type": scheme_type, **fields}


def test_every_stored_scheme_type_is_written() -> None:
    flows = {"clientCredentials": {"tokenUrl": "https://id.example/token", "scopes": {}}}
    built = _security_schemes_from_rows(
        [
            _scheme("key", "apiKey", param_name="X-Key", in_location="query", description="A key."),
            _scheme("bearer", "http", http_scheme="bearer", data={"bearerFormat": "JWT"}, description="A token."),
            _scheme("basic", "http", http_scheme="basic"),
            _scheme("oauth", "oauth2", data={"flows": flows}),
            _scheme("oidc", "openIdConnect", data='{"openIdConnectUrl": " https://id.example/.well-known "}'),
            _scheme("mtls", "mutualTLS", description="Client certificate."),
            _scheme("hmac", "custom", data={"type": "http", "scheme": "hmac", "x-algorithm": "sha256", "skip": None}),
        ]
    )
    assert built == {
        "key": {"type": "apiKey", "name": "X-Key", "in": "query", "description": "A key."},
        "bearer": {"type": "http", "scheme": "bearer", "description": "A token.", "bearerFormat": "JWT"},
        "basic": {"type": "http", "scheme": "basic"},
        "oauth": {"type": "oauth2", "flows": flows},
        "oidc": {"type": "openIdConnect", "openIdConnectUrl": "https://id.example/.well-known"},
        "mtls": {"type": "mutualTLS", "description": "Client certificate."},
        "hmac": {"type": "http", "scheme": "hmac", "x-algorithm": "sha256"},
    }


def test_an_api_key_scheme_defaults_its_name_and_location() -> None:
    assert _security_schemes_from_rows([_scheme("apiKey", "apiKey")]) == {
        "apiKey": {"type": "apiKey", "name": "apiKey", "in": "header"}
    }


def test_a_custom_scheme_defaults_to_api_key_and_takes_the_json_description() -> None:
    built = _security_schemes_from_rows([_scheme("x", "custom", data={"description": "From JSON", "name": "X"})])
    assert built == {"x": {"type": "apiKey", "description": "From JSON", "name": "X"}}


@pytest.mark.parametrize(
    "row",
    [
        _scheme("a", "http"),
        _scheme("b", "oauth2", data={"flows": {}}),
        _scheme("c", "openIdConnect", data={"openIdConnectUrl": "  "}),
        _scheme("d", "unknown"),
    ],
)
def test_a_scheme_that_would_not_be_valid_is_left_out(row: Dict[str, Any]) -> None:
    assert _security_schemes_from_rows([row]) == {}


# ───────────────────────────── private operations ─────────────────────────────


def _paths() -> List[Dict[str, Any]]:
    def operation(method: str, private: bool) -> Dict[str, Any]:
        return {
            "operation": method,
            "description": {"summary": method, "x_private": private},
            "parameters": [],
            "requestBody": None,
            "responses": [],
        }

    return [{"id": "p", "pathname": "/pets", "operations": [operation("get", False), operation("post", True)]}]


def _generate(**options: Any) -> Dict[str, Any]:
    return generate_openapi_spec(
        "acme", "pets", "1.0.0", [], {}, paths_data=_paths(), security_scheme_rows=[], server_rows=[],
        component_pin_rows=[], **options,
    )


def test_the_public_document_leaves_private_operations_out() -> None:
    assert sorted(_generate()["paths"]["/pets"]) == ["get"]


def test_include_private_keeps_them_and_marks_them() -> None:
    document = _generate(include_private=True, openapi_version="3.2.0")
    assert sorted(document["paths"]["/pets"]) == ["get", "post"]
    assert document["paths"]["/pets"]["post"]["x-private"] is True
    assert "x-private" not in document["paths"]["/pets"]["get"]
    assert document["openapi"] == "3.2.0"
