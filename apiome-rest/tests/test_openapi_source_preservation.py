"""Tests for OpenAPI source preservation through the canonical model (COA-2.1, #7044).

The OpenAPI normalizer keeps each source object it cannot model in ``extras``
(:mod:`app.openapi_source_preservation`) and the OpenAPI emitter writes it back: verbatim
when the entity was not edited, as "model + unmodelled fields + a loss" when it was. These
tests pin both paths, the version gates and the 3.0 → 3.1 schema upgrade, and that the bag
never changes a model's identity (fingerprints, canonical diff).
"""

from __future__ import annotations

import copy
import datetime
import json
from typing import Any, Dict, Optional

import pytest

from app.diff import diff
from app.emitter import EmitResult, LossTracker
from app.fingerprint import canonical_fingerprint as semantic_fingerprint
from app.import_source import canonical_fingerprint
from app.openapi_downgrade import downgrade_remaining_schemas_30
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_import_source import OpenApiImportSource
from app.openapi_source_preservation import (
    OPENAPI_SOURCE_EXTRA,
    entity_digest,
    gate_constructs,
    json_safe,
    preserved_source,
    strip_source_extra,
    upgrade_document_30_to_31,
    upgrade_schema_30_to_31,
)
from app.openapi_validator import validate_openapi_document


def _document(version: str = "3.1.0") -> Dict[str, Any]:
    """A small document holding several constructs the canonical model has no field for."""
    return {
        "openapi": version,
        "info": {
            "title": "Pets",
            "version": "1.0.0",
            "contact": {"name": "API team"},
            "x-audience": "internal",
        },
        "x-owner": "platform",
        "paths": {
            "/pets": {
                "summary": "The collection",
                "post": {
                    "operationId": "createPet",
                    "x-rate-limit": 10,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"},
                                "examples": {"rex": {"value": {"name": "Rex"}}},
                            }
                        },
                    },
                    "callbacks": {
                        "onAdopted": {
                            "{$request.body#/url}": {
                                "post": {"responses": {"204": {"description": "ok"}}}
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "Created.",
                            "links": {"Self": {"operationId": "createPet"}},
                        }
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "required": ["name"],
                    "discriminator": {"propertyName": "kind"},
                    "x-entity": True,
                    "properties": {"name": {"type": "string"}, "kind": {"type": "string"}},
                },
                "Cat": {"allOf": [{"$ref": "#/components/schemas/Pet"}]},
            },
            "links": {"Owner": {"operationId": "createPet"}},
        },
    }


def _normalize(document: Dict[str, Any]):
    """Import ``document`` the way an import does (no ``raw``)."""
    return OpenApiImportSource().normalize(copy.deepcopy(document), include_raw=False)


def _emit(model, version: Optional[str] = None) -> EmitResult:
    """Emit ``model`` at ``version`` (the emitter default when ``None``)."""
    opts = OpenApiEmitOptions(openapi_version=version) if version else None
    return OpenApiEmitter().emit(model, opts=opts)


def _operation(model, key: str):
    """The canonical operation with ``key``."""
    return next(op for service in model.services for op in service.operations if op.key == key)


# ===========================================================================
# Capture
# ===========================================================================


def test_capture_stores_root_operation_and_schema_sources() -> None:
    """The API, each operation and each named type carry their source object."""
    model = _normalize(_document())
    bag = preserved_source(model)
    assert bag is not None and bag["version"] == "3.1.0"
    assert bag["object"]["x-owner"] == "platform"
    assert bag["components"] == {"links": {"Owner": {"operationId": "createPet"}}}
    assert bag["pathItems"] == {"/pets": {"summary": "The collection"}}

    operation = _operation(model, "POST /pets")
    assert "callbacks" in operation.extras[OPENAPI_SOURCE_EXTRA]["object"]
    pet = next(t for t in model.types if t.key == "Pet")
    assert pet.extras[OPENAPI_SOURCE_EXTRA]["object"]["discriminator"] == {"propertyName": "kind"}


def test_capture_digests_match_the_final_model() -> None:
    """Digests are taken over the order-normalized model, so an unedited model matches."""
    model = _normalize(_document())
    operation = _operation(model, "POST /pets")
    assert operation.extras[OPENAPI_SOURCE_EXTRA]["digest"] == entity_digest(operation)


def test_capture_converts_yaml_dates_to_json_text() -> None:
    """An unquoted YAML date becomes its ISO text, so the emitted document stays JSON."""
    document = _document()
    document["info"]["x-released"] = datetime.date(2026, 11, 19)
    model = OpenApiImportSource().normalize(document, include_raw=False)
    emitted = _emit(model).document
    assert emitted["info"]["x-released"] == "2026-11-19"
    json.dumps(emitted)


def test_json_safe_handles_nested_dates_and_keys() -> None:
    """Dates anywhere (and non-string keys) are made JSON-compatible."""
    assert json_safe({1: [datetime.date(2020, 1, 2)]}) == {"1": ["2020-01-02"]}


# ===========================================================================
# Verbatim restore
# ===========================================================================


@pytest.mark.parametrize("version,target", [("3.0.3", "3.0"), ("3.1.0", "3.1"), ("3.2.0", "3.2")])
def test_an_unedited_document_round_trips_at_its_own_version(version: str, target: str) -> None:
    """Every source object comes back unchanged (only ``openapi`` is the emitter's)."""
    source = _document(version)
    emitted = _emit(_normalize(source), target).document
    expected = {key: value for key, value in source.items() if key != "openapi"}
    assert {key: value for key, value in emitted.items() if key != "openapi"} == expected


def test_a_restored_document_is_meta_schema_valid() -> None:
    """The restored 3.1 output validates against the bundled meta-schema."""
    assert validate_openapi_document(_emit(_normalize(_document())).document) == []


def test_reimporting_the_export_gives_the_same_model() -> None:
    """import → emit → re-import is lossless at the entity level."""
    model = _normalize(_document())
    emitted = _emit(model).document
    source = OpenApiImportSource()
    reimported = source.normalize(source.parse(json.dumps(emitted)), include_raw=False)
    assert diff(model, reimported).is_empty()


def test_restored_objects_have_source_provenance() -> None:
    """Restored operations and schemas are recorded as coming from the source."""
    provenance = {record.pointer: record for record in _emit(_normalize(_document())).provenance}
    assert provenance["/paths/~1pets/post"].detail.startswith("preserved OpenAPI source")
    assert "/components/schemas/Pet" in provenance


def test_unreferenced_synthesized_types_are_not_written() -> None:
    """An inline enum lifted into a named type does not become a new component."""
    document = _document()
    document["paths"]["/pets"]["post"]["parameters"] = [
        {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["asc", "desc"]}}
    ]
    model = _normalize(document)
    emitted = _emit(model).document
    assert set(emitted["components"]["schemas"]) == {"Pet", "Cat"}


def test_a_model_without_preserved_source_is_emitted_as_before() -> None:
    """Without the document-level bag (a model from another paradigm) nothing is restored."""
    model = _normalize(_document())
    model.extras.pop(OPENAPI_SOURCE_EXTRA)
    result = _emit(model)
    assert "x-owner" not in result.document
    assert "callbacks" not in result.document["paths"]["/pets"]["post"]
    assert not [loss for loss in result.losses if loss.subject.startswith("openapi-edited")]


# ===========================================================================
# Edited entities
# ===========================================================================


def test_an_edited_operation_keeps_its_unmodelled_fields_and_records_a_loss() -> None:
    """The model's values win; callbacks and extensions come back; the edit is reported."""
    model = _normalize(_document())
    _operation(model, "POST /pets").description = "Adopt a pet."
    result = _emit(model)
    operation = result.document["paths"]["/pets"]["post"]
    assert operation["description"] == "Adopt a pet."
    assert operation["callbacks"] == _document()["paths"]["/pets"]["post"]["callbacks"]
    assert operation["x-rate-limit"] == 10
    assert ("openapi-edited-operation", "#/paths/~1pets/post") in {
        (loss.subject, loss.pointer) for loss in result.losses
    }


def test_an_edited_schema_keeps_its_unmodelled_keywords_and_records_a_loss() -> None:
    """A changed type keeps ``discriminator`` and its extensions, with a loss."""
    model = _normalize(_document())
    next(t for t in model.types if t.key == "Pet").description = "A pet."
    result = _emit(model)
    pet = result.document["components"]["schemas"]["Pet"]
    assert pet["description"] == "A pet."
    assert pet["discriminator"] == {"propertyName": "kind"}
    assert pet["x-entity"] is True
    assert "openapi-edited-schema" in {loss.subject for loss in result.losses}


def test_an_edited_root_keeps_the_new_title_and_the_source_metadata() -> None:
    """A changed title is emitted; the contact and extensions are still written."""
    model = _normalize(_document())
    model.title = "Pet store"
    result = _emit(model)
    assert result.document["info"]["title"] == "Pet store"
    assert result.document["info"]["contact"] == {"name": "API team"}
    assert result.document["x-owner"] == "platform"
    assert "openapi-edited-document" in {loss.subject for loss in result.losses}


# ===========================================================================
# Version gates and dialect conversion
# ===========================================================================


def _document_32() -> Dict[str, Any]:
    """A 3.2 document with 3.2-only constructs."""
    return {
        "openapi": "3.2.0",
        "$self": "https://example.com/openapi.yaml",
        "info": {"title": "S", "version": "1"},
        "servers": [{"url": "https://api.example.com", "name": "prod"}],
        "paths": {
            "/s": {
                "get": {
                    "parameters": [
                        {"name": "q", "in": "querystring", "content": {"application/json": {}}}
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "summary": "OK",
                            "content": {"application/jsonl": {"itemSchema": {"type": "string"}}},
                        }
                    },
                }
            }
        },
        "webhooks": {"w": {"post": {"responses": {"200": {"description": "ok"}}}}},
    }


def test_32_only_constructs_are_dropped_with_a_loss_at_31() -> None:
    """``$self``, server ``name``, ``querystring``, response ``summary``, ``itemSchema``."""
    result = _emit(_normalize(_document_32()), "3.1")
    document = result.document
    assert "$self" not in document
    assert "name" not in document["servers"][0]
    operation = document["paths"]["/s"]["get"]
    assert "parameters" not in operation or operation["parameters"] == []
    response = operation["responses"]["200"]
    assert "summary" not in response
    assert "itemSchema" not in response["content"]["application/jsonl"]
    assert "webhooks" in document  # a 3.1 construct
    gated = {loss.pointer for loss in result.losses if loss.subject == "openapi-3.2-only"}
    assert {
        "#/$self",
        "#/servers/0/name",
        "#/paths/~1s/get/parameters/0",
        "#/paths/~1s/get/responses/200/summary",
        "#/paths/~1s/get/responses/200/content/application~1jsonl/itemSchema",
    } <= gated
    assert validate_openapi_document(document) == []


def test_31_only_constructs_are_dropped_with_a_loss_at_30() -> None:
    """``webhooks`` and ``jsonSchemaDialect`` have no 3.0 form."""
    document = _document()
    document["webhooks"] = {"w": {"post": {"responses": {"200": {"description": "ok"}}}}}
    document["jsonSchemaDialect"] = "https://spec.openapis.org/oas/3.1/dialect/base"
    result = _emit(_normalize(document), "3.0")
    assert "webhooks" not in result.document and "jsonSchemaDialect" not in result.document
    assert {"#/webhooks", "#/jsonSchemaDialect"} <= {
        loss.pointer for loss in result.losses if loss.subject == "openapi-3.1-only"
    }


def test_a_30_source_is_upgraded_at_31() -> None:
    """``nullable`` and boolean exclusive bounds take their 2020-12 forms; nothing is lost."""
    document = _document("3.0.3")
    document["components"]["schemas"]["Pet"]["properties"]["nick"] = {
        "type": "string",
        "nullable": True,
    }
    document["components"]["schemas"]["Pet"]["properties"]["age"] = {
        "type": "integer",
        "minimum": 0,
        "exclusiveMinimum": True,
    }
    result = _emit(_normalize(document), "3.1")
    properties = result.document["components"]["schemas"]["Pet"]["properties"]
    assert properties["nick"] == {"type": ["string", "null"]}
    assert properties["age"] == {"type": "integer", "exclusiveMinimum": 0}
    assert validate_openapi_document(result.document) == []


def test_a_30_source_at_30_keeps_its_30_schemas() -> None:
    """A 3.0 source emitted as 3.0 is restored after the downgrade, untouched."""
    document = _document("3.0.3")
    document["components"]["schemas"]["Pet"]["properties"]["nick"] = {
        "type": "string",
        "nullable": True,
    }
    emitted = _emit(_normalize(document), "3.0").document
    assert emitted["components"]["schemas"]["Pet"] == document["components"]["schemas"]["Pet"]


def test_a_31_source_at_30_downgrades_the_restored_schemas() -> None:
    """Restored 3.1 schemas are rewritten into 3.0, including those in other sections."""
    document = _document()
    document["components"]["schemas"]["Pet"]["properties"]["nick"] = {"type": ["string", "null"]}
    document["components"]["parameters"] = {
        "Limit": {"name": "limit", "in": "query", "schema": {"type": ["integer", "null"]}}
    }
    emitted = _emit(_normalize(document), "3.0").document
    assert emitted["components"]["schemas"]["Pet"]["properties"]["nick"] == {
        "type": "string",
        "nullable": True,
    }
    assert emitted["components"]["parameters"]["Limit"]["schema"] == {
        "type": "integer",
        "nullable": True,
    }


def test_swagger_2_output_reports_the_source_constructs_it_cannot_carry() -> None:
    """Swagger 2.0 is built from the model only, and says so."""
    result = _emit(_normalize(_document()), "2.0")
    assert "openapi-swagger-2-source-constructs" in {loss.subject for loss in result.losses}


def test_gate_constructs_removes_nested_32_only_keys() -> None:
    """``discriminator.defaultMapping`` and the device-authorization flow are 3.2-only."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "components": {
            "schemas": {"A": {"discriminator": {"propertyName": "k", "defaultMapping": "#/x"}}},
            "securitySchemes": {
                "o": {"type": "oauth2", "flows": {"deviceAuthorization": {"tokenUrl": "t"}}}
            },
        },
    }
    losses = LossTracker()
    gate_constructs(document, "3.1", losses)
    assert document["components"]["schemas"]["A"]["discriminator"] == {"propertyName": "k"}
    assert document["components"]["securitySchemes"]["o"]["flows"] == {}
    assert len(losses.records()) == 2


def test_gate_constructs_leaves_a_32_document_alone() -> None:
    """At 3.2 nothing is gated."""
    document = _document_32()
    before = copy.deepcopy(document)
    losses = LossTracker()
    gate_constructs(document, "3.2", losses)
    assert document == before and losses.records() == []


@pytest.mark.parametrize(
    "schema,expected",
    [
        ({"type": "string", "nullable": True}, {"type": ["string", "null"]}),
        ({"type": "string", "nullable": False}, {"type": "string"}),
        (
            {"type": "string", "enum": ["a"], "nullable": True},
            {"type": ["string", "null"], "enum": ["a", None]},
        ),
        (
            {"$ref": "#/components/schemas/A", "nullable": True},
            {"anyOf": [{"$ref": "#/components/schemas/A"}, {"type": "null"}]},
        ),
        ({"maximum": 5, "exclusiveMaximum": True}, {"exclusiveMaximum": 5}),
        ({"minimum": 5, "exclusiveMinimum": False}, {"minimum": 5}),
        (
            {"type": ["string", "null"], "exclusiveMinimum": 1},
            {"type": ["string", "null"], "exclusiveMinimum": 1},
        ),
    ],
)
def test_upgrade_schema_30_to_31(schema: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Each 3.0 form becomes its 2020-12 form; a 2020-12 schema is left as it is."""
    upgrade_schema_30_to_31(schema)
    assert schema == expected


def test_upgrade_document_walks_every_schema() -> None:
    """Nested and non-component schemas are upgraded too."""
    document = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "parameters": [
                        {"name": "p", "in": "query", "schema": {"type": "string", "nullable": True}}
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {
            "schemas": {"A": {"properties": {"b": {"items": {"type": "integer", "nullable": True}}}}}
        },
    }
    upgrade_document_30_to_31(document)
    assert document["paths"]["/a"]["get"]["parameters"][0]["schema"]["type"] == ["string", "null"]
    assert document["components"]["schemas"]["A"]["properties"]["b"]["items"]["type"] == [
        "integer",
        "null",
    ]


def test_downgrade_remaining_schemas_records_dropped_ref_siblings() -> None:
    """3.0 ignores keywords beside ``$ref``; dropping them is a recorded loss."""
    document = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "components": {
            "headers": {
                "H": {"schema": {"$ref": "#/components/schemas/A", "description": "An A."}}
            }
        },
    }
    losses = LossTracker()
    downgrade_remaining_schemas_30(document, losses)
    assert document["components"]["headers"]["H"]["schema"] == {"$ref": "#/components/schemas/A"}
    assert [loss.subject for loss in losses.records()] == ["openapi-30-ref-siblings"]


# ===========================================================================
# Identity: the bag never changes fingerprints or diffs
# ===========================================================================


def test_fingerprints_ignore_the_preserved_source() -> None:
    """Both fingerprints are the same with and without the bag."""
    model = _normalize(_document())
    stripped = model.model_validate(strip_source_extra(model.model_dump()))
    assert canonical_fingerprint(model) == canonical_fingerprint(stripped)
    assert semantic_fingerprint(model) == semantic_fingerprint(stripped)


def test_the_canonical_diff_ignores_the_preserved_source() -> None:
    """Two imports that differ only in unmodelled source detail diff as identical."""
    other = _document()
    other["paths"]["/pets"]["post"]["x-rate-limit"] = 99
    assert diff(_normalize(_document()), _normalize(other)).is_empty()
