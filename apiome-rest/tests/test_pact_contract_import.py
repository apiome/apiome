"""Importing a Pact file into a consumer contract — CTG-4.1 (#4479).

The acceptance criterion is specific: *a Pact file imports into a stored contract whose
interactions resolve to the project's operations/fields, with unresolvable interactions
reported, not silently dropped*. Both halves are asserted here — what resolves, and that
everything which does not comes back with a stable reason.

The Pact ecosystem writes the same information four ways (v1 through v4, plus the Ruby and JVM
matcher wrappers), and a consumer's declared surface must not depend on which one their test
framework emitted. Each shape gets a test.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from app.consumer_contract import ConsumerValidationError
from app.consumer_surface import SpecIndex
from app.pact_contract_import import (
    MAX_PACT_BYTES,
    import_pact,
    pact_consumer_name,
    pact_specification_version,
    parse_pact_document,
)


def _document() -> Dict[str, Any]:
    """A specification the pact interactions below resolve against."""
    return {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com/v1"}],
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                        {"name": "sort", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PetList"}
                                }
                            },
                        }
                    },
                },
                "post": {
                    "operationId": "createPet",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                },
            },
            "/pets/{petId}": {
                "get": {
                    "operationId": "getPet",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "tag": {"type": "string"},
                    },
                },
                "PetList": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Pet"},
                        },
                        "total": {"type": "integer"},
                    },
                },
            }
        },
    }


def _index() -> SpecIndex:
    """The index the imports resolve against."""
    return SpecIndex(_document())


def _pact(**overrides: Any) -> Dict[str, Any]:
    """A v3 pact with two resolvable interactions."""
    document: Dict[str, Any] = {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Pets"},
        "interactions": [
            {
                "description": "a request for a pet",
                "request": {"method": "GET", "path": "/v1/pets/42"},
                "response": {"status": 200, "body": {"id": "42", "name": "Rex"}},
            },
            {
                "description": "a request for the pet list",
                "request": {
                    "method": "GET",
                    "path": "/v1/pets",
                    "query": {"limit": ["10"]},
                },
                "response": {
                    "status": 200,
                    "body": {"items": [{"id": "1", "name": "Rex"}], "total": 1},
                },
            },
        ],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }
    document.update(overrides)
    return document


# ===========================================================================
# Parsing and provenance
# ===========================================================================


def test_a_pact_document_parses_with_a_content_digest() -> None:
    document, digest = parse_pact_document(json.dumps(_pact()))
    assert document["consumer"]["name"] == "Billing Service"
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_the_same_document_produces_the_same_digest() -> None:
    text = json.dumps(_pact())
    assert parse_pact_document(text)[1] == parse_pact_document(text)[1]


def test_text_that_is_not_json_is_refused_with_a_stable_code() -> None:
    with pytest.raises(ConsumerValidationError) as caught:
        parse_pact_document("not json at all")
    assert caught.value.code == "consumer-pact-malformed"


def test_a_json_document_without_interactions_is_refused() -> None:
    with pytest.raises(ConsumerValidationError) as caught:
        parse_pact_document(json.dumps({"consumer": {"name": "x"}}))
    assert caught.value.code == "consumer-pact-malformed"


def test_an_oversized_document_is_refused_by_name() -> None:
    with pytest.raises(ConsumerValidationError) as caught:
        parse_pact_document("x" * (MAX_PACT_BYTES + 1))
    assert caught.value.code == "consumer-pact-too-large"


def test_both_spellings_of_the_specification_version_are_read() -> None:
    assert pact_specification_version(_pact()) == "3.0.0"
    assert (
        pact_specification_version(
            {"metadata": {"pact-specification": {"version": "2.0.0"}}}
        )
        == "2.0.0"
    )
    assert pact_specification_version({"metadata": {}}) is None


def test_the_consumer_name_is_read_from_the_document() -> None:
    assert pact_consumer_name(_pact()) == "Billing Service"
    assert pact_consumer_name({}) is None


# ===========================================================================
# What resolves
# ===========================================================================


def test_interactions_resolve_to_the_projects_operations() -> None:
    result = import_pact(_pact(), _index())
    assert [(op.method, op.path) for op in result.surface.operations] == [
        ("get", "/pets"),
        ("get", "/pets/{petId}"),
    ]
    assert result.resolved_count == 2
    assert result.interaction_count == 2


def test_a_response_body_key_becomes_a_declared_field() -> None:
    result = import_pact(_pact(), _index())
    pet = next(op for op in result.surface.operations if op.path == "/pets/{petId}")
    assert {field.path for field in pet.fields} == {"id", "name"}
    assert {field.status for field in pet.fields} == {"200"}
    assert {field.schema_pointer for field in pet.fields} == {
        "/components/schemas/Pet/properties/id",
        "/components/schemas/Pet/properties/name",
    }


def test_a_nested_array_body_yields_the_container_and_its_members() -> None:
    result = import_pact(_pact(), _index())
    listing = next(op for op in result.surface.operations if op.path == "/pets")
    paths = {field.path for field in listing.fields if field.location == "response"}
    assert paths == {"items", "items.id", "items.name", "total"}


def test_a_query_parameter_is_declared_as_parameter_usage() -> None:
    result = import_pact(_pact(), _index())
    listing = next(op for op in result.surface.operations if op.path == "/pets")
    assert {field.path for field in listing.fields if field.location == "parameter"} == {"limit"}


def test_a_v2_query_string_is_read_the_same_as_a_v3_query_object() -> None:
    pact = _pact()
    pact["interactions"][1]["request"]["query"] = "limit=10&sort=name"
    result = import_pact(pact, _index())
    listing = next(op for op in result.surface.operations if op.path == "/pets")
    assert {field.path for field in listing.fields if field.location == "parameter"} == {
        "limit",
        "sort",
    }


def test_a_request_body_key_is_declared_as_request_usage() -> None:
    pact = _pact(
        interactions=[
            {
                "description": "create a pet",
                "request": {
                    "method": "POST",
                    "path": "/v1/pets",
                    "body": {"name": "Rex", "tag": "dog"},
                },
                "response": {"status": 201, "body": {"id": "1"}},
            }
        ]
    )
    result = import_pact(pact, _index())
    create = next(op for op in result.surface.operations if op.method == "post")
    request_fields = {field.path for field in create.fields if field.location == "request"}
    response_fields = {field.path for field in create.fields if field.location == "response"}
    assert request_fields == {"name", "tag"}
    assert response_fields == {"id"}


def test_two_interactions_on_one_operation_merge_into_one_declaration() -> None:
    pact = _pact()
    pact["interactions"].append(
        {
            "description": "another pet",
            "request": {"method": "GET", "path": "/v1/pets/99"},
            "response": {"status": 200, "body": {"id": "99", "tag": "cat"}},
        }
    )
    result = import_pact(pact, _index())
    assert len([op for op in result.surface.operations if op.path == "/pets/{petId}"]) == 1
    pet = next(op for op in result.surface.operations if op.path == "/pets/{petId}")
    assert {field.path for field in pet.fields} == {"id", "name", "tag"}


def test_a_ruby_matcher_wrapper_is_unwrapped_to_its_value() -> None:
    pact = _pact(
        interactions=[
            {
                "description": "a matched pet",
                "request": {"method": "GET", "path": "/v1/pets/42"},
                "response": {
                    "status": 200,
                    "body": {
                        "json_class": "Pact::SomethingLike",
                        "contents": {"id": "42", "name": "Rex"},
                    },
                },
            }
        ]
    )
    result = import_pact(pact, _index())
    pet = result.surface.operations[0]
    assert {field.path for field in pet.fields} == {"id", "name"}


def test_a_v4_plugin_matcher_wrapper_is_unwrapped_to_its_value() -> None:
    pact = _pact(
        interactions=[
            {
                "type": "Synchronous/HTTP",
                "description": "a matched pet",
                "request": {"method": "GET", "path": "/v1/pets/42"},
                "response": {
                    "status": 200,
                    "body": {"pact:matcher:type": "type", "value": {"id": "42"}},
                },
            }
        ]
    )
    result = import_pact(pact, _index())
    assert {field.path for field in result.surface.operations[0].fields} == {"id"}


def test_the_import_metadata_records_the_pacts_own_provenance() -> None:
    result = import_pact(_pact(), _index())
    assert result.metadata["consumer"] == "Billing Service"
    assert result.metadata["provider"] == "Pets"
    assert result.metadata["pactSpecification"] == "3.0.0"
    assert result.metadata["interactionCount"] == 2
    assert result.metadata["resolvedInteractionCount"] == 2


# ===========================================================================
# What does not resolve is reported, never dropped
# ===========================================================================


def test_an_interaction_for_a_retired_endpoint_is_reported() -> None:
    pact = _pact()
    pact["interactions"].append(
        {
            "description": "a retired call",
            "request": {"method": "GET", "path": "/v1/orders"},
            "response": {"status": 200},
        }
    )
    result = import_pact(pact, _index())
    reasons = [entry.reason for entry in result.unresolved]
    assert "operation-not-found" in reasons
    reported = next(e for e in result.unresolved if e.reason == "operation-not-found")
    assert reported.path == "/v1/orders"
    assert reported.description == "a retired call"


def test_a_known_path_with_an_unknown_method_gets_its_own_reason() -> None:
    pact = _pact(
        interactions=[
            {
                "description": "delete a pet",
                "request": {"method": "DELETE", "path": "/v1/pets/42"},
                "response": {"status": 204},
            }
        ]
    )
    result = import_pact(pact, _index())
    assert [entry.reason for entry in result.unresolved] == ["method-not-declared"]


def test_a_field_the_specification_no_longer_declares_is_reported() -> None:
    pact = _pact(
        interactions=[
            {
                "description": "a pet with an old field",
                "request": {"method": "GET", "path": "/v1/pets/42"},
                "response": {"status": 200, "body": {"id": "42", "nickname": "Rexy"}},
            }
        ]
    )
    result = import_pact(pact, _index())
    assert [entry.reason for entry in result.unresolved] == ["field-not-found"]
    assert result.unresolved[0].field_path == "nickname"
    # The operation itself survives: "you call this, but that field is gone" is the useful answer.
    assert [op.path for op in result.surface.operations] == ["/pets/{petId}"]


def test_a_status_the_specification_does_not_declare_is_reported() -> None:
    pact = _pact(
        interactions=[
            {
                "description": "a teapot",
                "request": {"method": "GET", "path": "/v1/pets/42"},
                "response": {"status": 418, "body": {"id": "42"}},
            }
        ]
    )
    result = import_pact(pact, _index())
    assert [entry.reason for entry in result.unresolved] == ["status-not-declared"]


def test_a_v4_message_interaction_is_reported_as_not_http() -> None:
    pact = _pact(
        interactions=[
            {
                "type": "Asynchronous/Messages",
                "description": "a pet created event",
                "contents": {"id": "1"},
            }
        ],
        metadata={"pactSpecification": {"version": "4.0"}},
    )
    result = import_pact(pact, _index())
    assert [entry.reason for entry in result.unresolved] == ["interaction-not-http"]
    assert result.surface.operations == []


def test_an_interaction_without_a_method_or_path_is_reported_as_malformed() -> None:
    pact = _pact(interactions=[{"description": "nonsense", "request": {}, "response": {}}])
    result = import_pact(pact, _index())
    assert [entry.reason for entry in result.unresolved] == ["interaction-malformed"]


def test_a_pact_that_resolves_nothing_stores_a_visibly_empty_surface() -> None:
    pact = _pact(
        interactions=[
            {
                "description": "one",
                "request": {"method": "GET", "path": "/gone"},
                "response": {"status": 200},
            },
            {
                "description": "two",
                "request": {"method": "GET", "path": "/also-gone"},
                "response": {"status": 200},
            },
        ]
    )
    result = import_pact(pact, _index())
    assert result.surface.operations == []
    assert len(result.unresolved) == 2
    assert result.resolved_count == 0
    assert result.metadata["resolvedInteractionCount"] == 0


def test_an_import_against_an_empty_specification_reports_every_interaction() -> None:
    result = import_pact(_pact(), SpecIndex({}))
    assert result.surface.operations == []
    assert len(result.unresolved) == 2
    assert {entry.reason for entry in result.unresolved} == {"operation-not-found"}
