"""Unit tests for the Pact v4 generator — PFX-2.6 (#6930).

The contracts are built the way the picker builds them (:func:`app.consumer_surface.
resolve_selection` against the same document), so every pointer is one the registry would store.
What is asserted:

* sample values come from the specification's examples, in the documented order;
* only declared fields are written, one interaction per response status;
* every invented value and every omission is a finding with a stable reason — nothing is dropped;
* the output is a valid pact that re-imports onto the same surface (CTG-4.1) and compares green
  against the same specification (PFX-2.2);
* the output is deterministic.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

from app.consumer_contract import (
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractRecord,
    ConsumerContractSurface,
    SelectedField,
    SelectedOperation,
    SurfaceSelection,
    UnresolvedInteraction,
)
from app.consumer_pact_export import (
    EXPORT_REASONS,
    OUTCOME_OMITTED,
    OUTCOME_PLACEHOLDER,
    build_consumer_pact,
)
from app.consumer_surface import SpecIndex, resolve_selection
from app.pact_contract_import import import_pact
from app.pact_oas_compare import compare_pact_to_oas
from app.pact_publication import pact_content_sha, prepare_pact, validate_pact_document

_DOCUMENT: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}, "example": 10},
                    {"name": "X-Trace", "in": "header", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PetList"}}},
                    }
                },
            },
            "post": {
                "operationId": "createPet",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/NewPet"},
                            "example": {"name": "Rex", "tag": "dog"},
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
                    }
                },
            },
        },
        "/pets/{petId}": {
            "parameters": [
                {"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}, "example": "p-42"}
            ],
            "get": {
                "operationId": "showPet",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"},
                                "examples": {"fido": {"value": {"id": "p-42", "name": "Fido", "born": "2020-01-02"}}},
                            }
                        },
                    },
                    "404": {
                        "description": "missing",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                    },
                    "default": {
                        "description": "error",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                    },
                },
            },
        },
        "/health": {
            "get": {
                "operationId": "health",
                "responses": {
                    "2XX": {
                        "description": "ok",
                        "content": {"text/plain": {"schema": {"type": "string", "example": "ok"}}},
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "string", "example": "p-1"},
                    "name": {"type": "string", "example": "Bella"},
                    "born": {"type": "string", "format": "date"},
                    "status": {"type": "string", "enum": ["available", "sold"]},
                },
            },
            "NewPet": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "tag": {"type": "string"}},
            },
            "PetList": {
                "type": "object",
                "properties": {
                    "total": {"type": "integer", "default": 1},
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}},
                },
            },
            "Error": {
                "type": "object",
                "properties": {"code": {"type": "integer"}, "message": {"type": "string"}},
            },
        }
    },
}


def _index(document: Dict[str, Any] = _DOCUMENT) -> SpecIndex:
    """Index the test document."""
    return SpecIndex(copy.deepcopy(document))


def _contract(selection: SurfaceSelection, index: SpecIndex, **overrides: Any) -> ConsumerContractRecord:
    """Resolve a picker selection the way ``PUT …/contract`` does and wrap it as a stored revision."""
    surface, unresolved = resolve_selection(selection, index)
    payload: Dict[str, Any] = {
        "id": "44444444-4444-4444-8444-444444444444",
        "consumer_id": "33333333-3333-4333-8333-333333333333",
        "revision": 3,
        "source": "manual",
        "version_id": "22222222-2222-4222-8222-222222222222",
        "version_label": "1.0.0",
        "surface": surface,
        "unresolved": unresolved,
        "unresolved_count": len(unresolved),
    }
    payload.update(overrides)
    return ConsumerContractRecord(**payload)


def _op(method: str, path: str, *fields: SelectedField) -> SelectedOperation:
    """One picked operation."""
    return SelectedOperation(method=method, path=path, fields=list(fields))


def _response(path: str, status: str | None = None) -> SelectedField:
    """A picked response field."""
    return SelectedField(location="response", path=path, status=status)


def _export(selection: SurfaceSelection, index: SpecIndex | None = None):
    """Generate the pact of a selection."""
    idx = index or _index()
    return build_consumer_pact(
        _contract(selection, idx), idx, consumer_name="web-app", provider_name="pets-api", consumer_slug="web-app"
    )


def _reasons(findings: List[Any], outcome: str) -> List[str]:
    """The reason codes of one outcome."""
    return [f.reason for f in findings if f.outcome == outcome]


# ===========================================================================
# Document shape
# ===========================================================================


def test_the_document_is_a_valid_pact_v4_with_names_and_provenance() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("name"))]))
    document = export.document
    assert validate_pact_document(document) == 1
    assert document["consumer"] == {"name": "web-app"}
    assert document["provider"] == {"name": "pets-api"}
    assert document["metadata"]["pactSpecification"] == {"version": "4.0"}
    assert document["metadata"]["apiome"] == {
        "generatedFrom": "consumer-contract",
        "contractRevision": 3,
        "versionRecordId": "22222222-2222-4222-8222-222222222222",
        "versionLabel": "1.0.0",
        "consumer": "web-app",
    }
    interaction = document["interactions"][0]
    assert interaction["type"] == "Synchronous/HTTP"
    assert interaction["description"] == "showPet returns 200"
    assert interaction["pending"] is False
    # prepare_pact is the publish path's own validation.
    stored = prepare_pact(
        json.dumps(document).encode(), consumer_name="web-app", provider_name="pets-api", max_bytes=1 << 20
    )
    assert stored.specification_version == "4.0"


def test_the_path_carries_the_server_base_path_and_the_path_parameter_example() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}")]))
    request = export.document["interactions"][0]["request"]
    assert request == {"method": "GET", "path": "/v1/pets/p-42"}


def test_an_operation_without_fields_expects_its_default_status_and_no_body() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}")]))
    assert export.document["interactions"][0]["response"] == {"status": 200}
    assert export.findings == []


# ===========================================================================
# Sample values
# ===========================================================================


def test_a_whole_body_media_example_wins_over_property_examples() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("name"), _response("born"))]))
    body = export.document["interactions"][0]["response"]["body"]
    assert body == {
        "contentType": "application/json",
        "encoded": False,
        "content": {"born": "2020-01-02", "name": "Fido"},
    }
    assert export.findings == []


def test_only_declared_fields_are_written() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("id"))]))
    assert export.document["interactions"][0]["response"]["body"]["content"] == {"id": "p-42"}


def test_property_examples_default_and_enum_fill_a_body_without_a_media_example() -> None:
    export = _export(
        SurfaceSelection(
            operations=[
                _op("get", "/pets", _response("total"), _response("items.id"), _response("items.status")),
            ]
        )
    )
    content = export.document["interactions"][0]["response"]["body"]["content"]
    assert content == {"items": [{"id": "p-1", "status": "available"}], "total": 1}
    assert export.findings == []


def test_a_field_without_any_example_gets_a_typed_placeholder_and_a_finding() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("code", "404"))]))
    content = export.document["interactions"][0]["response"]["body"]["content"]
    assert content == {"code": 0}
    (finding,) = export.findings
    assert finding.outcome == OUTCOME_PLACEHOLDER
    assert finding.reason == "no-example"
    assert (finding.method, finding.path, finding.status, finding.location, finding.field) == (
        "GET",
        "/pets/{petId}",
        "404",
        "response",
        "code",
    )


def test_a_format_shaped_placeholder_is_written_for_a_date() -> None:
    document = copy.deepcopy(_DOCUMENT)
    del document["paths"]["/pets/{petId}"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("born"))]), _index(document))
    assert export.document["interactions"][0]["response"]["body"]["content"] == {"born": "2026-01-01"}
    assert _reasons(export.findings, OUTCOME_PLACEHOLDER) == ["no-example"]


def test_a_request_body_uses_the_media_example_and_sets_content_type() -> None:
    export = _export(
        SurfaceSelection(
            operations=[
                _op("post", "/pets", SelectedField(location="request", path="name"), _response("id")),
            ]
        )
    )
    request = export.document["interactions"][0]["request"]
    assert request["body"] == {"contentType": "application/json", "encoded": False, "content": {"name": "Rex"}}
    assert request["headers"] == {"Content-Type": ["application/json"]}
    response = export.document["interactions"][0]["response"]
    assert response["status"] == 201
    assert response["body"]["content"] == {"id": "p-1"}
    # Requests carry no matcher: they are what the consumer sends.
    assert "matchingRules" not in request


def test_declared_parameters_use_their_examples_and_missing_ones_are_reported() -> None:
    export = _export(
        SurfaceSelection(
            operations=[
                _op(
                    "get",
                    "/pets",
                    SelectedField(location="parameter", path="limit"),
                    SelectedField(location="parameter", path="X-Trace"),
                )
            ]
        )
    )
    request = export.document["interactions"][0]["request"]
    assert request["query"] == {"limit": ["10"]}
    assert request["headers"] == {"X-Trace": ["string"]}
    (finding,) = export.findings
    assert (finding.outcome, finding.reason, finding.field) == (OUTCOME_PLACEHOLDER, "no-example", "X-Trace")


def test_response_bodies_are_matched_by_type() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("name"))]))
    response = export.document["interactions"][0]["response"]
    assert response["matchingRules"] == {"body": {"$": {"combine": "AND", "matchers": [{"match": "type"}]}}}
    assert response["headers"] == {"Content-Type": ["application/json"]}


# ===========================================================================
# Statuses
# ===========================================================================


def test_one_interaction_per_declared_status() -> None:
    export = _export(
        SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("name"), _response("message", "404"))])
    )
    statuses = [i["response"]["status"] for i in export.document["interactions"]]
    assert statuses == [200, 404]
    descriptions = [i["description"] for i in export.document["interactions"]]
    assert descriptions == ["showPet returns 200", "showPet returns 404"]


def test_a_default_response_is_omitted_with_a_reason() -> None:
    export = _export(
        SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("name"), _response("code", "default"))])
    )
    assert [i["response"]["status"] for i in export.document["interactions"]] == [200]
    assert _reasons(export.findings, OUTCOME_OMITTED) == ["status-default"]


def test_an_operation_with_only_a_default_response_is_omitted_entirely() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("code", "default"))]))
    assert export.interaction_count == 0
    assert _reasons(export.findings, OUTCOME_OMITTED) == ["status-default", "no-response-declared"]


def test_operations_map_each_declared_operation_to_its_interactions_and_findings() -> None:
    """PFX-8.18 (#7315): the Export page's checklist reads which interactions each operation wrote."""
    export = _export(
        SurfaceSelection(
            operations=[
                _op("get", "/pets/{petId}", _response("name"), _response("code", "404")),
                _op("get", "/pets", _response("total")),
            ]
        )
    )
    by_key = {(op.method, op.path): op for op in export.operations}
    assert len(export.operations) == 2
    shown = by_key[("GET", "/pets/{petId}")]
    assert len(shown.interactions) == 2
    assert shown.placeholder_count == 1
    listed = by_key[("GET", "/pets")]
    assert len(listed.interactions) == 1
    assert listed.placeholder_count == 0
    every = sorted(index for op in export.operations for index in op.interactions)
    assert every == list(range(export.interaction_count))
    assert sum(len(op.interactions) for op in export.operations) == export.interaction_count
    for op in export.operations:
        for index in op.interactions:
            assert export.document["interactions"][index]["request"]["method"] == op.method


def test_an_operation_left_out_has_no_interaction_and_its_omission_counted() -> None:
    export = _export(SurfaceSelection(operations=[_op("get", "/pets/{petId}", _response("code", "default"))]))
    (operation,) = export.operations
    assert operation.interactions == []
    assert operation.omitted_count == 2
    assert operation.operation_id == "showPet"


def test_a_status_range_becomes_its_first_code_and_a_non_json_body_is_omitted() -> None:
    index = _index()
    contract = _contract(SurfaceSelection(operations=[_op("get", "/health")]), index)
    # The picker cannot name a text body's data path, so declare the root field directly.
    contract.surface.operations[0].fields.append(
        ConsumerContractField(
            pointer="/paths/~1health/get/responses/2XX/content/text~1plain/schema",
            schema_pointer="/paths/~1health/get/responses/2XX/content/text~1plain/schema",
            location="response",
            status="2XX",
            media_type="text/plain",
            path="",
        )
    )
    export = build_consumer_pact(contract, index, consumer_name="web-app", provider_name="pets-api")
    assert export.document["interactions"][0]["response"] == {"status": 200}
    assert _reasons(export.findings, OUTCOME_PLACEHOLDER) == ["status-range"]
    assert _reasons(export.findings, OUTCOME_OMITTED) == ["media-type-not-json"]


# ===========================================================================
# Nothing dropped
# ===========================================================================


def test_unresolved_items_of_the_stored_contract_are_carried_over() -> None:
    index = _index()
    contract = _contract(SurfaceSelection(operations=[_op("get", "/pets/{petId}")]), index)
    contract.unresolved.append(
        UnresolvedInteraction(reason="operation-not-found", message="no GET /owners", method="get", path="/owners")
    )
    export = build_consumer_pact(contract, index, consumer_name="web-app", provider_name="pets-api")
    (finding,) = export.findings
    assert (finding.outcome, finding.reason, finding.method, finding.path) == (
        OUTCOME_OMITTED,
        "contract-unresolved",
        "GET",
        "/owners",
    )
    assert "operation-not-found" in finding.message


def test_an_operation_or_field_the_specification_no_longer_declares_is_omitted() -> None:
    index = _index()
    stale = ConsumerContractRecord(
        id="x",
        consumer_id="y",
        revision=1,
        version_id="v",
        surface=ConsumerContractSurface(
            operations=[
                ConsumerContractOperation(method="delete", path="/pets", pointer="/paths/~1pets/delete"),
                ConsumerContractOperation(
                    method="get",
                    path="/pets/{petId}",
                    pointer="/paths/~1pets~1{petId}/get",
                    fields=[
                        ConsumerContractField(
                            pointer="p",
                            schema_pointer="p",
                            location="response",
                            status="200",
                            media_type="application/json",
                            path="nickname",
                        ),
                        ConsumerContractField(
                            pointer="q",
                            schema_pointer="q",
                            location="parameter",
                            path="expand",
                        ),
                    ],
                ),
            ]
        ),
    )
    export = build_consumer_pact(stale, index, consumer_name="web-app", provider_name="pets-api")
    assert export.interaction_count == 1
    assert sorted(_reasons(export.findings, OUTCOME_OMITTED)) == [
        "field-not-found",
        "operation-not-found",
        "parameter-not-declared",
    ]


def test_every_finding_reason_is_a_documented_code() -> None:
    export = _export(
        SurfaceSelection(
            operations=[
                _op("get", "/pets/{petId}", _response("code", "404"), _response("code", "default")),
                _op("get", "/pets", SelectedField(location="parameter", path="X-Trace")),
            ]
        )
    )
    assert export.findings
    assert all(f.reason in EXPORT_REASONS for f in export.findings)


def test_a_self_referencing_array_terminates() -> None:
    document = copy.deepcopy(_DOCUMENT)
    document["components"]["schemas"]["Nest"] = {"type": "array", "items": {"$ref": "#/components/schemas/Nest"}}
    document["paths"]["/nest"] = {
        "get": {
            "responses": {
                "200": {
                    "description": "ok",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Nest"}}},
                }
            }
        }
    }
    index = _index(document)
    contract = _contract(SurfaceSelection(operations=[_op("get", "/nest")]), index)
    contract.surface.operations[0].fields.append(
        ConsumerContractField(
            pointer="r",
            schema_pointer="/components/schemas/Nest",
            location="response",
            status="200",
            media_type="application/json",
            path="",
        )
    )
    # The root is declared directly; the walk must stop at the depth guard, not recurse forever.
    export = build_consumer_pact(contract, index, consumer_name="a", provider_name="b")
    assert export.interaction_count == 1


# ===========================================================================
# Round trips
# ===========================================================================


_ROUND_TRIP = SurfaceSelection(
    operations=[
        _op(
            "get", "/pets", SelectedField(location="parameter", path="limit"), _response("total"), _response("items.id")
        ),
        _op("post", "/pets", SelectedField(location="request", path="name"), _response("id")),
        _op("get", "/pets/{petId}", _response("name"), _response("message", "404")),
    ]
)


def test_the_pact_reimports_onto_the_same_declared_surface() -> None:
    index = _index()
    contract = _contract(_ROUND_TRIP, index)
    export = build_consumer_pact(contract, index, consumer_name="web-app", provider_name="pets-api")
    reimported = import_pact(export.document, index)
    assert reimported.unresolved == []

    def pointers(surface: ConsumerContractSurface) -> List[tuple]:
        return sorted((op.method, op.path, sorted(f.pointer for f in op.fields)) for op in surface.operations)

    original = pointers(contract.surface)
    again = pointers(reimported.surface)
    # Import adds the intermediate object paths a body implies (items for items.id); every
    # declared pointer comes back.
    for (method, path, declared), (method2, path2, found) in zip(original, again):
        assert (method, path) == (method2, path2)
        assert set(declared) <= set(found)


def test_the_pact_compares_green_against_the_same_specification() -> None:
    index = _index()
    export = build_consumer_pact(
        _contract(_ROUND_TRIP, index), index, consumer_name="web-app", provider_name="pets-api"
    )
    result = compare_pact_to_oas(export.document, copy.deepcopy(_DOCUMENT))
    assert result.success, result.failures
    assert result.verdict == "pass", [(n.kind, n.message) for n in result.fidelity]


def test_the_same_revision_always_produces_the_same_pact() -> None:
    first = _export(_ROUND_TRIP)
    second = _export(_ROUND_TRIP)
    assert first.document == second.document
    assert pact_content_sha(first.document) == pact_content_sha(second.document)
