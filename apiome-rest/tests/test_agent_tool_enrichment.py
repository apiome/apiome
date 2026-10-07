"""Description enrichment analysis — AGX-1.3 (#4531).

The pure half of the enrichment pass, tested without a database or a model:

* the agent-hostile flags and their machine-readable reason codes (the AGX-4.4 contract);
* which descriptions count as thin enough to propose a replacement for;
* that the prompt carries only the spec's own documentation and names exactly the reply keys;
* that a model reply is parsed defensively (unrequested keys, junk, credentials, over-long text);
* that applying accepted text changes descriptions only, never tool names or schemas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.agent_tool_enrichment import (
    MAX_PARAM_DESCRIPTION_CHARS,
    MAX_TOOL_DESCRIPTION_CHARS,
    REASON_CODES,
    REASON_MISSING_DESCRIPTION,
    REASON_MISSING_EXAMPLES,
    REASON_MISSING_PARAM_DESCRIPTION,
    REASON_THIN_DESCRIPTION,
    REASON_THIN_PARAM_DESCRIPTION,
    REASON_UNDOCUMENTED_ERRORS,
    TARGET_PARAMETER,
    TARGET_TOOL,
    agent_hostile_flags,
    apply_description_overrides,
    build_enrichment_prompt,
    enrichment_targets,
    flag_operation,
    operation_has_examples,
    parse_enrichment_reply,
    served_description_overrides,
    tool_description_text,
)
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
)
from app.import_source import get_import_source, load_builtin_import_sources
from app.mcp_agent_readiness import MIN_TOOL_DESCRIPTION_CHARS
from app.mcp_tool_mapping import compile_mcp_tools
from app.openapi_normalizer import OpenApiNormalizer
from app.roundtrip_matrix import import_source_text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_loader import EXAMPLES_DIR, ValidityClass, load_corpus  # noqa: E402

_LONG = "Lists every pet in the store, newest first, paginated by cursor."


def _doc(paths: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {"openapi": "3.0.3", "info": {"title": "Pets", "version": "1.0.0"}, "paths": paths, **extra}


#: One agent-hostile operation, one agent-friendly one.
SPEC: Dict[str, Any] = _doc(
    {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    {"name": "q", "in": "query", "description": "Text", "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "ok"}},
            },
        },
        "/pets/{id}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get one pet",
                "description": "Returns a single pet by its id, including owner and vaccination status.",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "description": "The pet's UUID, as returned by listPets.",
                        "schema": {"type": "string", "format": "uuid"},
                        "example": "3f6c1f0a-0000-4000-8000-000000000001",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "The pet",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"},
                            }
                        },
                    },
                    "404": {"description": "No pet with that id"},
                },
            },
        },
    },
    components={
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
            }
        }
    },
)


def _api(spec: Dict[str, Any] = SPEC) -> CanonicalApi:
    return OpenApiNormalizer().normalize(spec)


def _op(api: CanonicalApi, key: str) -> Operation:
    return next(op for service in api.services for op in service.operations if op.key == key)


# ============================================================================
# Flags
# ============================================================================
def test_an_undocumented_operation_is_flagged_with_every_reason():
    api = _api()
    reasons = flag_operation(api, _op(api, "GET /pets"))
    assert [(r.code, r.parameter) for r in reasons] == [
        (REASON_MISSING_DESCRIPTION, None),
        (REASON_MISSING_EXAMPLES, None),
        (REASON_UNDOCUMENTED_ERRORS, None),
        (REASON_MISSING_PARAM_DESCRIPTION, "query.limit"),
        (REASON_THIN_PARAM_DESCRIPTION, "query.q"),
    ]
    assert all(reason.message for reason in reasons)


def test_a_documented_operation_is_not_flagged():
    api = _api()
    assert flag_operation(api, _op(api, "GET /pets/{id}")) == ()


def test_flags_list_only_hostile_operations_in_key_order():
    api = _api()
    operations = [op for service in api.services for op in service.operations]
    flags = agent_hostile_flags(api, reversed(operations))
    assert [flag.operation_key for flag in flags] == ["GET /pets"]
    assert flags[0].codes == (
        REASON_MISSING_DESCRIPTION,
        REASON_MISSING_EXAMPLES,
        REASON_UNDOCUMENTED_ERRORS,
        REASON_MISSING_PARAM_DESCRIPTION,
        REASON_THIN_PARAM_DESCRIPTION,
    )


def test_reasons_serialize_with_a_parameter_only_when_set():
    api = _api()
    reasons = [r.to_dict() for r in flag_operation(api, _op(api, "GET /pets"))]
    assert reasons[0].keys() == {"code", "message"}
    assert reasons[-1]["parameter"] == "query.q"
    assert {r["code"] for r in reasons} <= set(REASON_CODES)


def test_a_short_summary_is_thin_not_missing():
    api = _api(_doc({"/x": {"get": {"summary": "List x", "responses": {"default": {"description": "e"}}}}}))
    codes = [r.code for r in flag_operation(api, _op(api, "GET /x"))]
    assert REASON_THIN_DESCRIPTION in codes and REASON_MISSING_DESCRIPTION not in codes
    # A `default` response counts as documenting errors.
    assert REASON_UNDOCUMENTED_ERRORS not in codes


def test_the_summary_and_description_are_measured_together():
    api = _api(_doc({"/x": {"get": {"summary": "List x", "description": _LONG, "responses": {}}}}))
    assert tool_description_text(_op(api, "GET /x")) == f"List x\n\n{_LONG}"


def test_examples_are_found_in_payload_schemas_and_media_types():
    inline = _doc(
        {
            "/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object", "properties": {"a": {"type": "string", "example": "z"}}}
                            }
                        }
                    },
                    "responses": {},
                }
            }
        }
    )
    api = _api(inline)
    assert operation_has_examples(api, _op(api, "POST /x"))
    # Without the retained source, the inline payload schema alone still carries it.
    api.raw = None
    assert operation_has_examples(api, _op(api, "POST /x"))


def test_an_empty_example_does_not_count():
    api = _api(_doc({"/x": {"get": {"parameters": [{"name": "a", "in": "query", "example": ""}], "responses": {}}}}))
    assert not operation_has_examples(api, _op(api, "GET /x"))


def test_a_non_http_operation_is_never_flagged_for_error_docs():
    op = Operation(key="Query.user", name="user", kind=OperationKind.QUERY)
    api = CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="g"),
        services=[Service(key="Query", name="Query", operations=[op])],
    )
    codes = [r.code for r in flag_operation(api, op)]
    assert codes == [REASON_MISSING_DESCRIPTION, REASON_MISSING_EXAMPLES]


# ============================================================================
# Targets
# ============================================================================
def test_targets_are_the_thin_tool_and_thin_parameters():
    api = _api()
    targets = enrichment_targets(_op(api, "GET /pets"))
    assert [(t.kind, t.target_key, t.parameter, t.original) for t in targets] == [
        (TARGET_TOOL, "GET /pets", None, None),
        (TARGET_PARAMETER, "GET /pets#query.limit", "query.limit", None),
        (TARGET_PARAMETER, "GET /pets#query.q", "query.q", "Text"),
    ]
    assert enrichment_targets(_op(api, "GET /pets/{id}")) == []


def test_the_thin_threshold_is_the_readiness_packs():
    text = "x" * MIN_TOOL_DESCRIPTION_CHARS
    api = _api(_doc({"/x": {"get": {"description": text, "responses": {}}}}))
    assert enrichment_targets(_op(api, "GET /x")) == []
    api = _api(_doc({"/x": {"get": {"description": text[:-1], "responses": {}}}}))
    assert [t.kind for t in enrichment_targets(_op(api, "GET /x"))] == [TARGET_TOOL]


# ============================================================================
# Prompt
# ============================================================================
def test_the_prompt_carries_the_spec_context_and_the_reply_keys():
    api = _api()
    op = _op(api, "GET /pets/{id}")
    # Ask about a documented operation to see every section rendered.
    targets = enrichment_targets(_op(api, "GET /pets"))
    prompt = build_enrichment_prompt(api, op, targets)
    assert "API: Pets" in prompt
    assert "Operation: GET /pets/{id}" in prompt
    assert "Operation id: getPet" in prompt
    assert "- path.id (string, required): The pet's UUID" in prompt
    assert "- 200: Pet (fields: id, name) — The pet" in prompt
    assert "- 404: no payload — No pet with that id" in prompt
    assert 'Examples: ["3f6c1f0a-0000-4000-8000-000000000001"]' in prompt
    assert prompt.endswith('omitting any key you cannot describe from the excerpt.')
    assert '"tool", "query.limit", "query.q"' in prompt


def test_the_prompt_is_deterministic():
    api = _api()
    op = _op(api, "GET /pets")
    targets = enrichment_targets(op)
    assert build_enrichment_prompt(api, op, targets) == build_enrichment_prompt(_api(), op, targets)


# ============================================================================
# Reply parsing
# ============================================================================
def _targets() -> List[Any]:
    api = _api()
    return enrichment_targets(_op(api, "GET /pets"))


def test_a_well_formed_reply_yields_one_proposal_per_target():
    reply = (
        '{"tool": "  Lists pets\\n in the store. ", "parameters": '
        '{"query.limit": "Maximum number of pets to return.", "query.q": "Free-text search over pet names."}}'
    )
    assert parse_enrichment_reply(reply, _targets()) == {
        "GET /pets": "Lists pets in the store.",
        "GET /pets#query.limit": "Maximum number of pets to return.",
        "GET /pets#query.q": "Free-text search over pet names.",
    }


def test_a_fenced_reply_with_prose_is_still_read():
    reply = 'Sure!\n```json\n{"tool": "Lists pets."}\n```'
    assert parse_enrichment_reply(reply, _targets()) == {"GET /pets": "Lists pets."}


def test_junk_and_unusable_values_yield_nothing():
    targets = _targets()
    assert parse_enrichment_reply(None, targets) == {}
    assert parse_enrichment_reply("not json", targets) == {}
    assert parse_enrichment_reply("[1, 2]", targets) == {}
    reply = '{"tool": 42, "parameters": {"query.limit": "  ", "query.q": "Text", "query.other": "x"}}'
    # A number, a blank, an unchanged text and an unrequested key are all dropped.
    assert parse_enrichment_reply(reply, targets) == {}


def test_proposals_are_capped_and_credential_scrubbed():
    long_tool = "Lists pets. " * (MAX_TOOL_DESCRIPTION_CHARS // 10)
    long_param = "Page size. " * (MAX_PARAM_DESCRIPTION_CHARS // 10)
    reply = json.dumps(
        {
            "tool": long_tool,
            "parameters": {
                "query.limit": long_param,
                "query.q": "Search, e.g. https://admin:hunter2@example.com",
            },
        }
    )
    proposals = parse_enrichment_reply(reply, _targets())
    assert len(proposals["GET /pets"]) == MAX_TOOL_DESCRIPTION_CHARS
    assert len(proposals["GET /pets#query.limit"]) == MAX_PARAM_DESCRIPTION_CHARS
    assert "hunter2" not in proposals["GET /pets#query.q"]


# ============================================================================
# Applying accepted text
# ============================================================================
def test_overrides_change_descriptions_only():
    api = _api()
    overrides = {
        "GET /pets": "Lists every pet in the store.",
        "GET /pets#query.limit": "Maximum number of pets to return.",
        "GET /nope": "ignored",
    }
    patched = apply_description_overrides(api, overrides)
    assert _op(api, "GET /pets").description is None, "the input model must not be modified"

    before = {tool.name: tool for tool in compile_mcp_tools(api).tools}
    after = {tool.name: tool for tool in compile_mcp_tools(patched).tools}
    assert before.keys() == after.keys()
    tool = after["listPets"]
    assert tool.description.startswith("Lists every pet in the store.")
    assert tool.input_schema["properties"]["limit"]["description"] == "Maximum number of pets to return."
    assert after["getPet"].to_mcp() == before["getPet"].to_mcp()


def test_a_summary_still_leads_the_compiled_description():
    api = _api(_doc({"/x": {"get": {"operationId": "x", "summary": "List x", "responses": {}}}}))
    patched = apply_description_overrides(api, {"GET /x": _LONG})
    [tool] = compile_mcp_tools(patched).tools
    assert tool.description.startswith(f"List x\n\n{_LONG}")


def test_no_overrides_returns_the_same_model():
    api = _api()
    assert apply_description_overrides(api, {}) is api


# ============================================================================
# Every paradigm
# ============================================================================
def test_the_corpus_flags_and_prompts_without_error():
    """Flags, targets and prompts work for every importable corpus entry, whatever its format."""
    load_builtin_import_sources()
    swept = flagged = 0
    for entry in load_corpus(validity_class=ValidityClass.VALID):
        adapter = get_import_source(entry.adapter_key) if entry.adapter_key else None
        path = EXAMPLES_DIR / entry.path
        if adapter is None or not path.is_file():
            continue
        try:
            api = import_source_text(adapter, path.read_text(encoding="utf-8"), source_label=path.name)
        except Exception:
            continue  # import coverage is the corpus suite's job
        operations = [op for service in api.services for op in service.operations]
        for flag in agent_hostile_flags(api, operations):
            flagged += 1
            assert flag.reasons and set(flag.codes) <= set(REASON_CODES), (entry.path, flag)
        for op in operations:
            targets = enrichment_targets(op)
            if targets:
                assert build_enrichment_prompt(api, op, targets)
        swept += 1
    assert swept > 300 and flagged > 0


def test_served_description_overrides_keeps_accepted_text_of_exposed_operations():
    rows = [
        {"target_key": "GET /pets", "operation_key": "GET /pets", "accepted_description": "List pets."},
        {"target_key": "GET /pets#query.limit", "operation_key": "GET /pets", "accepted_description": "Cap."},
        {"target_key": "POST /pets", "operation_key": "POST /pets", "accepted_description": "Create."},
        {"target_key": "GET /pets/{id}", "operation_key": "GET /pets/{id}", "accepted_description": None},
    ]
    assert served_description_overrides(rows, ["GET /pets", "GET /pets/{id}"]) == {
        "GET /pets": "List pets.",
        "GET /pets#query.limit": "Cap.",
    }
    assert served_description_overrides(rows, []) == {}
