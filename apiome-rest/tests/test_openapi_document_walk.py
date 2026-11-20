"""Tests for the structure-aware OpenAPI document walk (COA-2.1, #7044)."""

from __future__ import annotations

from app.openapi_document_walk import (
    escape_pointer_token,
    is_missing,
    join_pointer,
    node_pointers,
    resolve_pointer,
    walk_document,
)

_DOCUMENT = {
    "openapi": "3.2.0",
    "info": {"title": "T", "version": "1", "license": {"name": "MIT"}},
    "servers": [{"url": "https://a", "variables": {"v": {"default": "x"}}}],
    "tags": [{"name": "t", "externalDocs": {"url": "https://d"}}],
    "paths": {
        "/a/{id}": {
            "parameters": [{"name": "id", "in": "path", "schema": {"type": "string"}}],
            "get": {
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "callbacks": {
                    "cb": {"{$url}": {"post": {"responses": {"200": {"description": "ok"}}}}}
                },
                "responses": {
                    "200": {
                        "description": "ok",
                        "headers": {"H": {"schema": {"type": "integer"}}},
                        "links": {"L": {"operationId": "x"}},
                        "content": {
                            "text/event-stream": {
                                "itemSchema": {"properties": {"data": {"type": "string"}}},
                                "itemEncoding": {"contentType": "text/plain"},
                            }
                        },
                    }
                },
            },
            "additionalOperations": {"COPY": {"responses": {}}},
        }
    },
    "webhooks": {"w": {"post": {"responses": {}}}},
    "components": {
        "schemas": {
            "A": {
                "allOf": [{"$ref": "#/components/schemas/B"}],
                "properties": {"callbacks": {"type": "string"}},
                "items": [{"type": "string"}],
            }
        },
        "securitySchemes": {"o": {"type": "oauth2", "flows": {"implicit": {"scopes": {}}}}},
    },
}


def _kinds() -> dict:
    return {node.pointer: node.kind for node in walk_document(_DOCUMENT)}


def test_every_object_kind_is_reached_with_its_pointer() -> None:
    """The walk reaches each OpenAPI object kind at its RFC 6901 pointer."""
    kinds = _kinds()
    assert kinds[""] == "root"
    assert kinds["/info/license"] == "license"
    assert kinds["/servers/0/variables/v"] == "server_variable"
    assert kinds["/tags/0/externalDocs"] == "external_docs"
    assert kinds["/paths/~1a~1{id}"] == "path_item"
    assert kinds["/paths/~1a~1{id}/parameters/0/schema"] == "schema"
    assert kinds["/paths/~1a~1{id}/get"] == "operation"
    assert kinds["/paths/~1a~1{id}/get/requestBody"] == "request_body"
    assert kinds["/paths/~1a~1{id}/get/callbacks/cb"] == "callback"
    assert kinds["/paths/~1a~1{id}/get/callbacks/cb/{$url}/post"] == "operation"
    assert kinds["/paths/~1a~1{id}/get/responses/200/headers/H"] == "header"
    assert kinds["/paths/~1a~1{id}/get/responses/200/links/L"] == "link"
    media = "/paths/~1a~1{id}/get/responses/200/content/text~1event-stream"
    assert kinds[media] == "media_type"
    assert kinds[media + "/itemSchema/properties/data"] == "schema"
    assert kinds[media + "/itemEncoding"] == "encoding"
    assert kinds["/paths/~1a~1{id}/additionalOperations/COPY"] == "operation"
    assert kinds["/webhooks/w/post"] == "operation"
    assert kinds["/components/schemas/A/allOf/0"] == "schema"
    assert kinds["/components/schemas/A/items/0"] == "schema"
    assert kinds["/components/securitySchemes/o/flows/implicit"] == "oauth_flow"


def test_a_property_named_like_a_construct_is_a_schema() -> None:
    """``properties.callbacks`` is a schema, not a Callback Object."""
    assert _kinds()["/components/schemas/A/properties/callbacks"] == "schema"


def test_parents_come_before_children() -> None:
    """An object is yielded before every object nested inside it."""
    order = {pointer: index for index, pointer in enumerate(node_pointers(_DOCUMENT))}
    for pointer, index in order.items():
        ancestors = [other for other in order if other and pointer.startswith(other + "/")]
        assert all(order[ancestor] < index for ancestor in ancestors), pointer


def test_pointer_helpers_round_trip() -> None:
    """Escaping, joining and resolving agree."""
    assert escape_pointer_token("a/b~c") == "a~1b~0c"
    pointer = join_pointer("", "paths", "/a/{id}", "get")
    assert pointer == "/paths/~1a~1{id}/get"
    assert "callbacks" in resolve_pointer(_DOCUMENT, pointer)
    assert resolve_pointer(_DOCUMENT, "/servers/0/url") == "https://a"
    assert is_missing(resolve_pointer(_DOCUMENT, "/servers/5"))
    assert is_missing(resolve_pointer(_DOCUMENT, "/nope"))
    assert resolve_pointer(_DOCUMENT, "") is _DOCUMENT


def test_non_documents_yield_nothing() -> None:
    """A non-mapping input is not walked."""
    assert list(walk_document([])) == []  # type: ignore[arg-type]
