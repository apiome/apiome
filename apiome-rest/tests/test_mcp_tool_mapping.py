"""Tests for the operation→MCP-tool compiler — AGX-1.1 (#4529).

:mod:`app.mcp_tool_mapping` is what every AGX consumer (curation, the invocation proxy,
the golden corpus) and the SDK-4.5 / MFX-32.1 MCP renderers compile through, so these
tests pin the contract they rely on:

* **Petstore** yields one well-formed tool per operation — names from ``operationId``,
  path/query/header parameters merged with the body, and a description that says what a
  successful call returns;
* **the MCP validity pass** leaves only :data:`~app.mcp_tool_mapping.MCP_SCHEMA_KEYWORDS`,
  downgrading what it can and reporting everything it changes;
* **names** are collision-stable: exposure never renames a tool;
* **output** comes from the lowest 2xx response;
* **determinism**: the same spec — in any input order — serializes byte-identically, and
  the whole examples corpus compiles twice to the same bytes with every schema valid.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from jsonschema import Draft202012Validator

import app.mcp_tool_mapping as mapping
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossTracker
from app.import_source import get_import_source, load_builtin_import_sources
from app.mcp_tool_mapping import (
    LOSS_MCP_KEYWORD_DOWNGRADED,
    LOSS_MCP_KEYWORD_DROPPED,
    LOSS_MCP_ROOT_COMBINATOR,
    LOSS_MCP_UNRESOLVED_REF,
    MCP_SCHEMA_KEYWORDS,
    MCP_TOOL_MAPPING_VERSION,
    McpToolMappingError,
    McpToolOutput,
    McpToolset,
    UnknownOperationError,
    compile_mcp_tools,
    mcp_schema_violations,
    sanitize_mcp_schema,
    success_response,
    validate_mcp_tool,
)
from app.openapi_normalizer import OpenApiNormalizer
from app.roundtrip_matrix import import_source_text
from app.tool_projection import (
    LOSS_EVENT_OPERATION,
    LOSS_REQUIRED_WITHOUT_PROPERTY,
    LOSS_RESPONSE_SCHEMA,
    LOSS_SCHEMA_CYCLE,
    TOOL_NAME_PATTERN,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_loader import EXAMPLES_DIR, ValidityClass, load_corpus  # noqa: E402

PETSTORE = EXAMPLES_DIR / "openapi" / "30-openapi-3.0-petstore.yaml"


# ===========================================================================
# Builders
# ===========================================================================


def _import(path: Path, adapter_key: str = "openapi") -> CanonicalApi:
    """Import a corpus file through its registered adapter, as the import pipeline does."""
    load_builtin_import_sources()
    adapter = get_import_source(adapter_key)
    assert adapter is not None
    return import_source_text(adapter, path.read_text(encoding="utf-8"), source_label=path.name)


def _petstore() -> McpToolset:
    return compile_mcp_tools(_import(PETSTORE))


def _by_name(toolset: McpToolset) -> Dict[str, Any]:
    return {tool.name: tool for tool in toolset.tools}


def _response(
    status: Optional[str],
    *,
    key: str = "op",
    payload: Optional[TypeRef] = None,
    schema: Optional[Dict[str, Any]] = None,
    content_types: Optional[List[str]] = None,
    description: Optional[str] = None,
    role: MessageRole = MessageRole.RESPONSE,
) -> Message:
    return Message(
        key=f"{key}#response.{status}",
        role=role,
        status_code=status,
        payload=payload,
        payload_schema=schema,
        content_types=content_types if content_types is not None else ["application/json"],
        description=description,
    )


def _operation(
    key: str,
    *,
    operation_id: Optional[str] = None,
    summary: Optional[str] = None,
    messages: Optional[List[Message]] = None,
    parameters: Optional[List[Parameter]] = None,
    deprecated: bool = False,
    kind: OperationKind = OperationKind.REQUEST_RESPONSE,
) -> Operation:
    method, _, path = key.partition(" ")
    extras: Dict[str, Any] = {}
    if operation_id:
        extras["operationId"] = operation_id
    if summary:
        extras["summary"] = summary
    # Messages are keyed under the operation, as a normalizer keys them.
    keyed = [m.model_copy(update={"key": f"{key}#{m.key.split('#', 1)[1]}"}) for m in messages or []]
    return Operation(
        key=key,
        name=operation_id or key,
        kind=kind,
        description=summary,
        deprecated=deprecated,
        http_method=method,
        http_path=path,
        parameters=parameters or [],
        messages=keyed,
        extras=extras,
    )


def _api(
    operations: List[Operation],
    *,
    types: Optional[List[Type]] = None,
    services: Optional[List[Service]] = None,
) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Widgets"),
        services=services or [Service(key="widgets", name="widgets", operations=operations)],
        types=types or [],
    )


def _widget_type() -> Type:
    return Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="integer", nullable=False))],
    )


def _sanitize(schema: Any, *, arguments: bool = False) -> Dict[str, Any]:
    return sanitize_mcp_schema(schema, losses=LossTracker(), subject="s", arguments=arguments)


def _subjects(losses: Any) -> List[str]:
    return [loss.subject for loss in losses]


# ===========================================================================
# Petstore — the acceptance fixture
# ===========================================================================


def test_petstore_yields_one_tool_per_operation_named_by_operation_id() -> None:
    tools = _by_name(_petstore())
    assert set(tools) == {"listPets", "createPet", "getPetById", "updatePet", "deletePet"}
    assert tools["getPetById"].operation == "GET /pets/{petId}"


def test_petstore_merges_path_query_header_parameters_and_the_body() -> None:
    tools = _by_name(_petstore())
    listing = tools["listPets"].input_schema
    assert set(listing["properties"]) == {"X-Request-ID", "limit", "offset", "tags"}
    assert listing["properties"]["limit"]["minimum"] == 1
    assert "required" not in listing

    create = tools["createPet"].input_schema
    assert {"id", "name", "tag", "age", "X-Request-ID"} <= set(create["properties"])
    assert create["required"] == ["id", "name"]

    update = tools["updatePet"].input_schema
    assert "petId" in update["properties"] and "petId" in update["required"]


def test_petstore_descriptions_say_what_a_successful_call_returns() -> None:
    tools = _by_name(_petstore())
    assert tools["listPets"].description == (
        "List all pets\n\nReturns HTTP 200 application/json (array of Pet): Success"
    )
    assert tools["createPet"].description.endswith("Returns HTTP 201 application/json (Pet): Created")
    assert tools["deletePet"].description.endswith("Returns HTTP 204 with no body: No content")


def test_petstore_output_carries_the_inlined_success_schema() -> None:
    output = _by_name(_petstore())["listPets"].output
    assert output is not None
    assert (output.status, output.media_type, output.shape) == ("200", "application/json", "array of Pet")
    assert output.schema is not None
    assert output.schema["type"] == "array"
    assert output.schema["items"]["required"] == ["id", "name"]


def test_petstore_tools_are_mcp_valid_and_valid_json_schema() -> None:
    for tool in _petstore().tools:
        entry = tool.to_mcp()
        assert validate_mcp_tool(entry) == []
        Draft202012Validator.check_schema(entry["inputSchema"])
        assert set(entry) == {"name", "description", "inputSchema"}


def test_petstore_arguments_validate_against_the_compiled_schema() -> None:
    tools = _by_name(_petstore())
    listing = Draft202012Validator(tools["listPets"].input_schema)
    assert listing.is_valid({"limit": 10, "tags": ["dog"]})
    assert not listing.is_valid({"limit": 0})

    create = Draft202012Validator(tools["createPet"].input_schema)
    assert create.is_valid({"id": 1, "name": "Rex"})
    assert not create.is_valid({"name": "Rex"})


# ===========================================================================
# MCP validity pass
# ===========================================================================


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"oneOf": [{"type": "string"}, {"type": "integer"}]}, {"anyOf": [{"type": "string"}, {"type": "integer"}]}),
        ({"const": "a"}, {"enum": ["a"]}),
        ({"type": "string", "nullable": True}, {"type": ["string", "null"]}),
        ({"type": ["string", "integer"], "nullable": True}, {"type": ["string", "integer", "null"]}),
        ({"type": "string", "example": "x"}, {"type": "string", "examples": ["x"]}),
        ({"minimum": 1, "exclusiveMinimum": True}, {"exclusiveMinimum": 1}),
        ({"maximum": 9, "exclusiveMaximum": True}, {"exclusiveMaximum": 9}),
        (
            {"type": "string", "deprecated": True, "description": "Old"},
            {"type": "string", "description": "Deprecated. Old"},
        ),
        ({"type": "string", "deprecated": True}, {"type": "string", "description": "Deprecated."}),
    ],
)
def test_non_portable_keywords_are_downgraded_to_portable_ones(
    source: Dict[str, Any], expected: Dict[str, Any]
) -> None:
    losses = LossTracker()
    assert sanitize_mcp_schema(source, losses=losses, subject="s") == expected
    assert _subjects(losses.records()) == [LOSS_MCP_KEYWORD_DOWNGRADED]


def test_all_of_is_merged_into_its_parent() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "allOf": [
            {"properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["b"]},
            {"required": ["a"], "allOf": [{"properties": {"c": {"type": "boolean"}}}]},
        ],
    }
    assert _sanitize(schema) == {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}, "c": {"type": "boolean"}},
        "required": ["b", "a"],
    }


@pytest.mark.parametrize(
    "keyword",
    ["readOnly", "writeOnly", "x-internal", "discriminator", "xml", "externalDocs", "not", "if", "then", "else",
     "prefixItems", "patternProperties", "dependentSchemas", "unevaluatedProperties", "$schema", "$id", "$comment"],
)
def test_keywords_outside_the_subset_are_dropped_and_reported(keyword: str) -> None:
    losses = LossTracker()
    result = sanitize_mcp_schema({"type": "string", keyword: {"type": "string"}}, losses=losses, subject="s")
    assert result == {"type": "string"}
    [loss] = losses.records()
    assert loss.subject == LOSS_MCP_KEYWORD_DROPPED
    assert repr(keyword) in loss.detail


def test_an_unresolved_ref_becomes_a_free_form_node_and_is_reported() -> None:
    losses = LossTracker()
    result = sanitize_mcp_schema(
        {"type": "object", "properties": {"p": {"$ref": "#/components/schemas/Ghost", "description": "d"}}},
        losses=losses,
        subject="s",
    )
    assert result["properties"]["p"] == {"description": "d"}
    assert _subjects(losses.records()) == [LOSS_MCP_UNRESOLVED_REF]


def test_an_unresolved_ref_inside_all_of_is_reported_as_a_ref() -> None:
    losses = LossTracker()
    result = sanitize_mcp_schema(
        {"allOf": [{"$ref": "#/components/schemas/Base"}, {"type": "object"}]}, losses=losses, subject="s"
    )
    assert result == {"type": "object"}
    assert LOSS_MCP_UNRESOLVED_REF in _subjects(losses.records())
    assert LOSS_MCP_KEYWORD_DROPPED not in _subjects(losses.records())


def test_the_schemas_own_definitions_are_inlined() -> None:
    schema = {
        "type": "object",
        "properties": {"pet": {"$ref": "#/$defs/Pet"}, "old": {"$ref": "#/definitions/Old"}},
        "$defs": {"Pet": {"type": "object", "properties": {"name": {"type": "string"}}}},
        "definitions": {"Old": {"type": "integer"}},
    }
    assert _sanitize(schema, arguments=True) == {
        "type": "object",
        "properties": {
            "pet": {"type": "object", "properties": {"name": {"type": "string"}}},
            "old": {"type": "integer"},
        },
    }


def test_a_self_referencing_definition_becomes_free_form_at_the_recursion_point() -> None:
    losses = LossTracker()
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}},
    }
    result = sanitize_mcp_schema(schema, losses=losses, subject="s", arguments=True)
    assert result["properties"]["node"] == {"type": "object", "properties": {"next": {}}}
    assert LOSS_SCHEMA_CYCLE in _subjects(losses.records())


def test_a_property_named_like_a_keyword_is_not_mistaken_for_one() -> None:
    schema = {
        "type": "object",
        "properties": {"type": {"type": "string"}, "items": {"type": "string"}, "x-name": {"type": "string"}},
    }
    assert set(_sanitize(schema)["properties"]) == {"type", "items", "x-name"}


def test_boolean_sub_schemas_are_normalized() -> None:
    losses = LossTracker()
    result = sanitize_mcp_schema(
        {"type": "object", "properties": {"any": True, "never": False}, "required": ["any", "never"]},
        losses=losses,
        subject="s",
    )
    assert result == {"type": "object", "properties": {"any": {}}, "required": ["any"]}
    assert LOSS_REQUIRED_WITHOUT_PROPERTY in _subjects(losses.records())


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"type": "file"}, {}),
        ({"type": ["string", "binary"]}, {"type": ["string"]}),
        ({"minLength": -1, "maxLength": 3.0}, {"maxLength": 3}),
        ({"multipleOf": 0}, {}),
        ({"minimum": "1"}, {}),
        ({"title": 7, "description": "ok"}, {"description": "ok"}),
        ({"uniqueItems": "yes"}, {}),
        ({"items": [{"type": "string"}]}, {}),
        ({"enum": "a"}, {}),
    ],
)
def test_invalid_keyword_values_are_dropped(source: Dict[str, Any], expected: Dict[str, Any]) -> None:
    assert _sanitize(source) == expected


def test_argument_root_is_an_object_without_a_root_composition() -> None:
    losses = LossTracker()
    result = sanitize_mcp_schema(
        {"oneOf": [{"type": "object"}, {"type": "object"}]}, losses=losses, subject="s", arguments=True
    )
    assert result == {"type": "object", "properties": {}}
    assert LOSS_MCP_ROOT_COMBINATOR in _subjects(losses.records())


def test_sanitizing_does_not_mutate_its_input_and_is_idempotent() -> None:
    source = {
        "type": "object",
        "properties": {"a": {"type": "string", "nullable": True}},
        "allOf": [{"properties": {"b": {"const": 1}}}],
    }
    snapshot = json.dumps(source, sort_keys=True)
    once = _sanitize(source, arguments=True)
    assert json.dumps(source, sort_keys=True) == snapshot
    assert _sanitize(once, arguments=True) == once


def test_changes_are_aggregated_into_one_loss_per_kind() -> None:
    losses = LossTracker()
    sanitize_mcp_schema(
        {"properties": {"a": {"x-a": 1}, "b": {"x-b": 2}, "c": {"readOnly": True}}}, losses=losses, subject="s"
    )
    assert _subjects(losses.records()) == [LOSS_MCP_KEYWORD_DROPPED]


# ===========================================================================
# Validation
# ===========================================================================


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        ({"name": "bad name", "inputSchema": {"type": "object", "properties": {}}}, "/name"),
        ({"name": "t", "description": "", "inputSchema": {"type": "object", "properties": {}}}, "/description"),
        ({"name": "t", "inputSchema": {"type": "array", "properties": {}}}, "/inputSchema/type"),
        ({"name": "t", "inputSchema": {"type": "object"}}, "/inputSchema/properties"),
        ({"name": "t", "inputSchema": {"type": "object", "properties": {}, "anyOf": [{}]}}, "/inputSchema/anyOf"),
        ({"name": "t", "inputSchema": {"type": "object", "properties": {"p": {"$ref": "#/x"}}}}, "$ref"),
        ({"name": "t", "inputSchema": {"type": "object", "properties": {}, "required": ["p"]}}, "/required"),
        ({"name": "t", "inputSchema": {"type": "object", "properties": {"p": {"type": "file"}}}}, "/type"),
        ({"name": "t", "inputSchema": "nope"}, "/inputSchema"),
    ],
)
def test_validate_mcp_tool_reports_each_contract_breach(entry: Dict[str, Any], fragment: str) -> None:
    problems = validate_mcp_tool(entry)
    assert problems and any(fragment in problem for problem in problems)


def test_schema_violations_point_at_the_offending_keyword() -> None:
    problems = mcp_schema_violations({"properties": {"a/b": {"not": {}}}}, pointer="/inputSchema")
    assert problems == ["/inputSchema/properties/a~1b/not: keyword 'not' is outside the MCP schema subset"]


def test_an_invalid_compiled_tool_is_raised_rather_than_shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mapping, "sanitize_mcp_schema", lambda schema, **_: {**schema, "not": {}})
    with pytest.raises(McpToolMappingError, match="outside the MCP schema subset"):
        compile_mcp_tools(_api([_operation("GET /a", operation_id="a")]))


# ===========================================================================
# Output description
# ===========================================================================


def test_the_lowest_explicit_success_status_wins() -> None:
    operation = _operation(
        "POST /a",
        messages=[_response("201"), _response("200"), _response("2XX"), _response("default")],
    )
    selected = success_response(operation)
    assert selected is not None and selected.status_code == "200"


def test_the_success_range_is_used_when_no_explicit_code_exists() -> None:
    operation = _operation("GET /a", messages=[_response("2XX"), _response("default")])
    selected = success_response(operation)
    assert selected is not None and selected.status_code == "2XX"


def test_errors_and_default_are_never_a_success_response() -> None:
    operation = _operation(
        "GET /a", messages=[_response("404", role=MessageRole.ERROR), _response("default"), _response("302")]
    )
    assert success_response(operation) is None


def test_a_statusless_response_is_the_result_of_a_non_http_operation() -> None:
    operation = _operation("GetPet", messages=[_response(None, payload=TypeRef(name="Widget"), content_types=[])])
    selected = success_response(operation)
    assert selected is not None and selected.status_code is None


@pytest.mark.parametrize(
    ("output", "summary"),
    [
        (McpToolOutput("200", "OK", "application/json", {"type": "array"}, "array of Pet"),
         "Returns HTTP 200 application/json (array of Pet): OK"),
        (McpToolOutput("204", None, None, None, None), "Returns HTTP 204 with no body."),
        (McpToolOutput(None, None, None, {"type": "object"}, "Widget"), "Returns Widget."),
        (McpToolOutput("200", "OK", "text/plain", {"type": "string"}, "string"),
         "Returns HTTP 200 text/plain (string): OK"),
    ],
)
def test_the_output_summary_reads_as_one_sentence(output: McpToolOutput, summary: str) -> None:
    assert output.summary() == summary


def test_a_json_media_type_is_preferred_for_the_output() -> None:
    operation = _operation(
        "GET /a",
        operation_id="a",
        messages=[_response("200", schema={"type": "object"}, content_types=["text/xml", "application/json"])],
    )
    output = compile_mcp_tools(_api([operation])).tools[0].output
    assert output is not None and output.media_type == "application/json"


def test_a_credential_in_the_response_description_is_redacted() -> None:
    operation = _operation(
        "GET /a",
        operation_id="a",
        messages=[_response("200", description="Call https://admin:hunter2@api.example.com first")],
    )
    tool = compile_mcp_tools(_api([operation])).tools[0]
    assert tool.output is not None and "hunter2" not in (tool.output.description or "")
    assert "hunter2" not in (tool.description or "")


def test_a_tool_without_a_success_response_has_no_output_and_keeps_the_response_note() -> None:
    operation = _operation("GET /a", operation_id="a", messages=[_response("302")])
    toolset = compile_mcp_tools(_api([operation]))
    assert toolset.tools[0].output is None
    assert LOSS_RESPONSE_SCHEMA in _subjects(toolset.losses)


def test_the_response_note_is_dropped_when_the_output_is_carried() -> None:
    operation = _operation("GET /a", operation_id="a", messages=[_response("200", schema={"type": "object"})])
    assert LOSS_RESPONSE_SCHEMA not in _subjects(compile_mcp_tools(_api([operation])).losses)


# ===========================================================================
# Refs, names and exposure
# ===========================================================================


def _inline_ref_document() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Refs", "version": "1"},
        "paths": {
            "/owners": {
                "post": {
                    "operationId": "createOwner",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"owner": {"$ref": "#/components/schemas/User"}},
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "made"}},
                }
            }
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}, "friend": {"$ref": "#/components/schemas/User"}},
                }
            }
        },
    }


def test_a_component_ref_inside_an_inline_body_is_resolved() -> None:
    toolset = compile_mcp_tools(OpenApiNormalizer().normalize(_inline_ref_document()))
    owner = toolset.tools[0].input_schema["properties"]["owner"]
    assert owner == {"type": "object", "properties": {"name": {"type": "string"}, "friend": {}}, "required": ["name"]}
    assert LOSS_SCHEMA_CYCLE in _subjects(toolset.losses)
    assert LOSS_MCP_UNRESOLVED_REF not in _subjects(toolset.losses)


def _colliding_api() -> CanonicalApi:
    return _api(
        [
            _operation("GET /a", operation_id="list.items"),
            _operation("GET /b", operation_id="list items"),
            _operation("GET /c", operation_id="list_items"),
        ]
    )


def test_colliding_names_are_disambiguated_deterministically() -> None:
    names = [tool.name for tool in compile_mcp_tools(_colliding_api()).tools]
    assert names == ["list_items", "list_items_2", "list_items_3"]
    assert all(TOOL_NAME_PATTERN.fullmatch(name) for name in names)


def test_exposing_a_subset_never_renames_a_tool() -> None:
    full = {tool.operation: tool.name for tool in compile_mcp_tools(_colliding_api()).tools}
    only_last = compile_mcp_tools(_colliding_api(), exposed=["GET /c"])
    assert [(tool.operation, tool.name) for tool in only_last.tools] == [("GET /c", full["GET /c"])]


def test_an_unknown_exposed_operation_is_rejected() -> None:
    with pytest.raises(UnknownOperationError) as raised:
        compile_mcp_tools(_colliding_api(), exposed=["GET /a", "DELETE /nope"])
    assert raised.value.keys == ("DELETE /nope",)


def test_an_event_operation_cannot_be_exposed() -> None:
    api = _api([_operation("GET /a", operation_id="a"), _operation("pub", kind=OperationKind.PUBLISH)])
    with pytest.raises(UnknownOperationError):
        compile_mcp_tools(api, exposed=["pub"])


def test_exposed_must_be_a_collection_not_a_string() -> None:
    with pytest.raises(TypeError):
        compile_mcp_tools(_colliding_api(), exposed="GET /a")


def test_deprecated_operations_are_hidden_unless_exposed_explicitly() -> None:
    api = _api(
        [
            _operation("GET /a", operation_id="current"),
            _operation("GET /b", operation_id="legacy", summary="Old way", deprecated=True),
        ]
    )
    assert [tool.name for tool in compile_mcp_tools(api).tools] == ["current"]
    [legacy] = compile_mcp_tools(api, exposed=["GET /b"]).tools
    assert legacy.description == "Deprecated. Old way"


def test_losses_about_unexposed_operations_are_not_reported() -> None:
    api = _api(
        [
            _operation("GET /a", operation_id="a"),
            _operation("GET /b", operation_id="b b", messages=[_response("200", schema={"x-b": 1})]),
        ]
    )
    toolset = compile_mcp_tools(api, exposed=["GET /a"])
    assert all(not (loss.pointer or "").startswith("GET /b") for loss in toolset.losses)


def test_a_schema_only_model_compiles_to_an_empty_toolset() -> None:
    toolset = compile_mcp_tools(_api([], types=[_widget_type()]))
    assert toolset.tools == ()
    assert toolset.to_dict() == {"mappingVersion": MCP_TOOL_MAPPING_VERSION, "tools": []}


def test_an_event_only_model_explains_why_it_has_no_tools() -> None:
    toolset = compile_mcp_tools(_api([_operation("pub", kind=OperationKind.PUBLISH)]))
    assert toolset.tools == ()
    assert LOSS_EVENT_OPERATION in _subjects(toolset.losses)


def test_the_mcp_entry_omits_an_absent_description() -> None:
    [tool] = compile_mcp_tools(_api([_operation("GET /a", operation_id="a")])).tools
    assert tool.description is None
    assert tool.to_mcp() == {"name": "a", "inputSchema": {"type": "object", "properties": {}}}
    assert tool.to_dict() == {"name": "a", "inputSchema": {"type": "object", "properties": {}}, "operation": "GET /a"}


# ===========================================================================
# Determinism
# ===========================================================================


def test_the_same_spec_serializes_byte_identically() -> None:
    first, second = _petstore(), _petstore()
    assert first.serialize() == second.serialize()
    assert first.fingerprint() == second.fingerprint()
    assert first.serialize().endswith("}\n")
    assert json.loads(first.serialize())["mappingVersion"] == MCP_TOOL_MAPPING_VERSION


def test_input_order_does_not_change_the_output() -> None:
    api = _import(PETSTORE)
    shuffled = api.model_copy(deep=True)
    rng = random.Random(4529)
    rng.shuffle(shuffled.services)
    rng.shuffle(shuffled.types)
    for service in shuffled.services:
        rng.shuffle(service.operations)
        for operation in service.operations:
            rng.shuffle(operation.parameters)
            rng.shuffle(operation.messages)
    assert compile_mcp_tools(shuffled).serialize() == compile_mcp_tools(api).serialize()


def _corpus_models() -> List[Any]:
    """Every valid corpus entry an adapter can import, as ``(path, model)`` pairs."""
    load_builtin_import_sources()
    models = []
    for entry in load_corpus(validity_class=ValidityClass.VALID):
        adapter = get_import_source(entry.adapter_key) if entry.adapter_key else None
        path = EXAMPLES_DIR / entry.path
        if adapter is None or not path.is_file():
            continue
        try:
            api = import_source_text(adapter, path.read_text(encoding="utf-8"), source_label=path.name)
        except Exception:
            # Import coverage is the corpus suite's job, not this one's.
            continue
        models.append((entry.path, api))
    return models


def test_the_examples_corpus_compiles_deterministically_to_valid_mcp_tools() -> None:
    """The AGX-1.4 prerequisite: repeated compiles are identical and every schema is valid."""
    models = _corpus_models()
    assert len(models) > 300, "the corpus sweep should cover the examples corpus"
    compiled = 0
    for path, api in models:
        first = compile_mcp_tools(api)
        assert compile_mcp_tools(api).serialize() == first.serialize(), path
        for tool in first.tools:
            compiled += 1
            assert validate_mcp_tool(tool.to_mcp()) == [], (path, tool.name)
            Draft202012Validator.check_schema(tool.input_schema)
            if tool.output is not None and tool.output.schema is not None:
                assert mcp_schema_violations(tool.output.schema) == [], (path, tool.name)
                Draft202012Validator.check_schema(tool.output.schema)
    assert compiled > 500


def test_every_emitted_keyword_is_in_the_mcp_subset() -> None:
    """A belt-and-braces walk independent of the validator: no stray keyword anywhere."""

    def keywords(node: Any) -> set:
        found: set = set()
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(key)
                if key == "properties" and isinstance(value, dict):
                    for child in value.values():
                        found |= keywords(child)
                elif key in ("items", "additionalProperties"):
                    found |= keywords(value)
                elif key == "anyOf":
                    for branch in value:
                        found |= keywords(branch)
        return found

    for tool in _petstore().tools:
        assert keywords(tool.input_schema) <= MCP_SCHEMA_KEYWORDS
