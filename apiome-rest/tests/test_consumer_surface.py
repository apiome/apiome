"""Resolving a declared surface against a specification — CTG-4.1 (#4479).

:mod:`app.consumer_surface` is the piece the whole registry rests on: if the pointers it
produces are not the pointers :mod:`app.change_taxonomy_enum` emits, then CTG-4.2's
per-consumer intersection compares two different vocabularies and quietly answers "nothing
breaks". So the first thing asserted here is that agreement, against the real classifier rather
than against a copy of its rules.

The rest covers what an ingestion path actually hits: a concrete URL that has to become a path
template, a base path that has to come off, a ``$ref`` whose node lives somewhere else, a
recursive schema that must terminate, and a field that is simply not there — which must be
reported rather than dropped.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from app.change_taxonomy import classify_openapi_changes
from app.consumer_contract import (
    ConsumerValidationError,
    SelectedField,
    SelectedOperation,
    SurfaceSelection,
    contract_pointers,
    count_fields,
    slugify_consumer_name,
    validate_slug,
)
from app.consumer_surface import (
    MAX_FIELDS_PER_OPERATION,
    SpecIndex,
    operation_pointer,
    resolve_selection,
)


def _document() -> Dict[str, Any]:
    """A small specification with the shapes that matter: a template path, a server base path,
    a ``$ref``, an array of ``$ref``, and a parameter."""
    return {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com/v1"}],
        "paths": {
            "/pets": {
                "parameters": [
                    {"name": "traceId", "in": "header", "schema": {"type": "string"}}
                ],
                "get": {
                    "operationId": "listPets",
                    "summary": "List pets",
                    "tags": ["pets"],
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}}
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
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
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
            "/pets/mine": {
                "get": {"operationId": "myPets", "responses": {"200": {"description": "ok"}}}
            },
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "required": ["id"],
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
    """The index under test."""
    return SpecIndex(_document())


# ===========================================================================
# The pointer vocabulary is the classifier's, not a private one
# ===========================================================================


def test_an_operation_pointer_is_spelled_the_way_the_classifier_spells_it() -> None:
    base = _document()
    head = copy.deepcopy(base)
    del head["paths"]["/pets/{petId}"]

    emitted = {
        change.pointer
        for change in classify_openapi_changes(base, head).changes
        if change.change_kind == "path_removed"
    }
    assert "/paths/~1pets~1{petId}" in emitted
    assert operation_pointer("/pets/{petId}", "get").startswith("/paths/~1pets~1{petId}")


def test_a_removed_field_lands_on_a_pointer_the_contract_stored() -> None:
    """The CTG-4.2 intersection in miniature: remove a field, and the pointer the classifier
    reports must be one the declared surface already holds."""
    base = _document()
    index = SpecIndex(base)
    surface, unresolved = resolve_selection(
        SurfaceSelection(
            operations=[
                SelectedOperation(
                    method="get",
                    path="/pets/{petId}",
                    fields=[SelectedField(location="response", path="name")],
                )
            ]
        ),
        index,
    )
    assert unresolved == []
    declared = set(contract_pointers(surface))

    head = copy.deepcopy(base)
    del head["components"]["schemas"]["Pet"]["properties"]["name"]
    changed = {change.pointer for change in classify_openapi_changes(base, head).changes}

    # The classifier reports the removal under the component schema; the contract stored exactly
    # that pointer as the field's ``schema_pointer``.
    assert "/components/schemas/Pet/properties/name" in changed
    assert "/components/schemas/Pet/properties/name" in declared


def test_a_declared_parameter_uses_the_classifiers_parameter_identity() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["paths"]["/pets"]["get"]["parameters"][0]["required"] = True

    changed = {change.pointer for change in classify_openapi_changes(base, head).changes}
    surface, _ = resolve_selection(
        SurfaceSelection(
            operations=[
                SelectedOperation(
                    method="get",
                    path="/pets",
                    fields=[SelectedField(location="parameter", path="limit")],
                )
            ]
        ),
        _index(),
    )
    declared = set(contract_pointers(surface))
    # ``required`` flips are reported one level below the parameter pointer the contract holds,
    # which is why the store's intersection matches prefixes in both directions.
    assert any(pointer.startswith("/paths/~1pets/get/parameters/query:limit") for pointer in changed)
    assert "/paths/~1pets/get/parameters/query:limit" in declared


# ===========================================================================
# Matching a concrete path onto a template
# ===========================================================================


def test_a_concrete_path_resolves_to_its_template() -> None:
    entry = _index().match_operation("GET", "/pets/42")
    assert entry is not None
    assert entry.path == "/pets/{petId}"


def test_a_server_base_path_is_taken_off_before_matching() -> None:
    entry = _index().match_operation("get", "/v1/pets/42")
    assert entry is not None
    assert entry.path == "/pets/{petId}"


def test_a_literal_segment_beats_a_template_when_both_match() -> None:
    entry = _index().match_operation("get", "/pets/mine")
    assert entry is not None
    assert entry.path == "/pets/mine"


def test_a_query_string_does_not_prevent_a_match() -> None:
    entry = _index().match_operation("get", "/pets?limit=10")
    assert entry is not None
    assert entry.path == "/pets"


def test_an_undeclared_path_matches_nothing() -> None:
    index = _index()
    assert index.match_operation("get", "/orders") is None
    assert index.matches_any_method("/orders") is False


def test_a_declared_path_with_an_undeclared_method_is_distinguishable() -> None:
    index = _index()
    assert index.match_operation("delete", "/pets/42") is None
    assert index.matches_any_method("/pets/42") is True


# ===========================================================================
# Field resolution
# ===========================================================================


def test_a_field_reached_through_a_ref_carries_both_pointers() -> None:
    index = _index()
    entry = index.get_operation("get", "/pets/{petId}")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="response", path="name")
    assert reason is None
    assert field is not None
    assert field.pointer == (
        "/paths/~1pets~1{petId}/get/responses/200/content/application~1json/schema/properties/name"
    )
    assert field.schema_pointer == "/components/schemas/Pet/properties/name"


def test_an_array_level_is_transparent_in_the_data_path() -> None:
    index = _index()
    entry = index.get_operation("get", "/pets")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="response", path="items.id")
    assert reason is None
    assert field is not None
    assert field.schema_pointer == "/components/schemas/Pet/properties/id"


def test_a_request_body_field_resolves_under_request_body() -> None:
    index = _index()
    entry = index.get_operation("post", "/pets")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="request", path="name")
    assert reason is None
    assert field is not None
    assert field.pointer.startswith("/paths/~1pets/post/requestBody/content/")
    assert field.status is None


def test_the_default_response_status_is_the_lowest_two_hundred() -> None:
    index = _index()
    entry = index.get_operation("post", "/pets")
    assert entry is not None
    assert index.default_status(entry) == "201"


def test_a_field_that_is_not_there_is_reported_not_invented() -> None:
    index = _index()
    entry = index.get_operation("get", "/pets/{petId}")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="response", path="nickname")
    assert field is None
    assert reason == "field-not-found"


def test_an_undeclared_status_is_its_own_reason() -> None:
    index = _index()
    entry = index.get_operation("get", "/pets/{petId}")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="response", path="id", status="418")
    assert field is None
    assert reason == "status-not-declared"


def test_an_undeclared_parameter_is_its_own_reason() -> None:
    index = _index()
    entry = index.get_operation("get", "/pets")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="parameter", path="offset")
    assert field is None
    assert reason == "parameter-not-declared"


def test_a_path_item_parameter_is_visible_on_every_operation_of_the_path() -> None:
    index = _index()
    entry = index.get_operation("get", "/pets")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="parameter", path="traceId")
    assert reason is None
    assert field is not None
    assert field.pointer.endswith("/parameters/header:traceId")


def test_a_map_typed_body_resolves_an_unknown_key_onto_additional_properties() -> None:
    document = _document()
    document["paths"]["/pets"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"type": "object", "additionalProperties": {"type": "string"}}
    index = SpecIndex(document)
    entry = index.get_operation("get", "/pets")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="response", path="whatever")
    assert reason is None
    assert field is not None
    assert field.pointer.endswith("/schema/additionalProperties")


def test_a_composition_branch_is_searched_for_the_field() -> None:
    document = _document()
    document["components"]["schemas"]["Pet"] = {
        "allOf": [
            {"type": "object", "properties": {"id": {"type": "string"}}},
            {"type": "object", "properties": {"name": {"type": "string"}}},
        ]
    }
    index = SpecIndex(document)
    entry = index.get_operation("get", "/pets/{petId}")
    assert entry is not None
    field, reason = index.resolve_field(entry, location="response", path="name")
    assert reason is None
    assert field is not None
    assert field.schema_pointer == "/components/schemas/Pet/allOf/1/properties/name"


# ===========================================================================
# Enumeration (the picker's catalogue)
# ===========================================================================


def test_the_catalogue_lists_every_operation_in_a_stable_order() -> None:
    surface = _index().available_surface()
    assert [(op.method, op.path) for op in surface.operations] == [
        ("get", "/pets"),
        ("post", "/pets"),
        ("get", "/pets/mine"),
        ("get", "/pets/{petId}"),
    ]


def test_the_catalogue_lists_parameters_before_bodies() -> None:
    surface = _index().available_surface()
    listing = next(op for op in surface.operations if op.path == "/pets" and op.method == "get")
    locations = [field.location for field in listing.fields]
    assert locations[: locations.count("parameter")] == ["parameter"] * locations.count("parameter")
    assert {field.path for field in listing.fields if field.location == "parameter"} == {
        "limit",
        "traceId",
    }


def test_the_catalogue_marks_a_required_property() -> None:
    surface = _index().available_surface()
    listing = next(
        op for op in surface.operations if op.path == "/pets/{petId}" and op.method == "get"
    )
    required = {field.path for field in listing.fields if field.required}
    assert "id" in required
    assert "name" not in required


def test_a_recursive_schema_terminates_instead_of_exhausting_the_stack() -> None:
    document = _document()
    document["components"]["schemas"]["Pet"]["properties"]["parent"] = {
        "$ref": "#/components/schemas/Pet"
    }
    surface = SpecIndex(document).available_surface()
    listing = next(
        op for op in surface.operations if op.path == "/pets/{petId}" and op.method == "get"
    )
    assert any(field.path == "parent" for field in listing.fields)
    assert len(listing.fields) <= MAX_FIELDS_PER_OPERATION


def test_a_very_wide_operation_is_truncated_and_says_so() -> None:
    document = _document()
    document["components"]["schemas"]["Pet"]["properties"] = {
        f"field{index:04d}": {"type": "string"} for index in range(MAX_FIELDS_PER_OPERATION + 50)
    }
    surface = SpecIndex(document).available_surface()
    listing = next(
        op for op in surface.operations if op.path == "/pets/{petId}" and op.method == "get"
    )
    assert listing.truncated is True
    assert surface.truncated is True
    assert len(listing.fields) <= MAX_FIELDS_PER_OPERATION


def test_a_non_json_body_contributes_no_fields() -> None:
    document = _document()
    document["paths"]["/pets/{petId}"]["get"]["responses"]["200"]["content"] = {
        "application/xml": {"schema": {"$ref": "#/components/schemas/Pet"}}
    }
    surface = SpecIndex(document).available_surface()
    listing = next(
        op for op in surface.operations if op.path == "/pets/{petId}" and op.method == "get"
    )
    assert [field.location for field in listing.fields] == ["parameter"]


def test_an_empty_document_indexes_as_an_empty_catalogue() -> None:
    assert SpecIndex({}).available_surface().operations == ()
    assert SpecIndex(None).available_surface().operations == ()  # type: ignore[arg-type]


# ===========================================================================
# resolve_selection
# ===========================================================================


def test_a_selection_resolves_into_a_surface_with_counts() -> None:
    surface, unresolved = resolve_selection(
        SurfaceSelection(
            operations=[
                SelectedOperation(
                    method="GET",
                    path="/pets",
                    fields=[
                        SelectedField(location="response", path="items.name"),
                        SelectedField(location="parameter", path="limit"),
                    ],
                ),
                SelectedOperation(method="get", path="/pets/{petId}"),
            ]
        ),
        _index(),
    )
    assert unresolved == []
    assert len(surface.operations) == 2
    assert count_fields(surface) == 2
    assert [op.path for op in surface.operations] == ["/pets", "/pets/{petId}"]


def test_an_unresolvable_operation_is_reported_and_omitted() -> None:
    surface, unresolved = resolve_selection(
        SurfaceSelection(operations=[SelectedOperation(method="get", path="/orders")]),
        _index(),
    )
    assert surface.operations == []
    assert [entry.reason for entry in unresolved] == ["operation-not-found"]


def test_an_unresolvable_field_keeps_its_operation() -> None:
    surface, unresolved = resolve_selection(
        SurfaceSelection(
            operations=[
                SelectedOperation(
                    method="get",
                    path="/pets/{petId}",
                    fields=[
                        SelectedField(location="response", path="name"),
                        SelectedField(location="response", path="nickname"),
                    ],
                )
            ]
        ),
        _index(),
    )
    assert len(surface.operations) == 1
    assert [field.path for field in surface.operations[0].fields] == ["name"]
    assert [entry.reason for entry in unresolved] == ["field-not-found"]


def test_contract_pointers_include_both_pointers_of_every_field() -> None:
    surface, _ = resolve_selection(
        SurfaceSelection(
            operations=[
                SelectedOperation(
                    method="get",
                    path="/pets/{petId}",
                    fields=[SelectedField(location="response", path="name")],
                )
            ]
        ),
        _index(),
    )
    pointers = contract_pointers(surface)
    assert "/paths/~1pets~1{petId}/get" in pointers
    assert "/components/schemas/Pet/properties/name" in pointers
    assert pointers == sorted(set(pointers))


# ===========================================================================
# Handles
# ===========================================================================


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Billing Service", "billing-service"),
        ("  ACME/Payments  ", "acme-payments"),
        ("v2 API!!", "v2-api"),
        ("...", ""),
    ],
)
def test_a_handle_is_derived_from_a_display_name(name: str, expected: str) -> None:
    assert slugify_consumer_name(name) == expected


@pytest.mark.parametrize("slug", ["billing-service", "a", "svc2"])
def test_a_well_formed_handle_is_accepted(slug: str) -> None:
    assert validate_slug(slug) == slug


@pytest.mark.parametrize("slug", ["", "-lead", "trail-", "Has Space", "a/b", "UPPER" * 40])
def test_a_malformed_handle_is_refused_with_a_stable_code(slug: str) -> None:
    with pytest.raises(ConsumerValidationError) as caught:
        validate_slug(slug)
    assert caught.value.code == "consumer-invalid-slug"
