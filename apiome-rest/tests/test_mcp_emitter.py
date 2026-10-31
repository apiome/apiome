"""MCP tool-definition emitter — MFX-32.1 (#4295).

Covers :mod:`app.mcp_emitter`, against the issue's acceptance criteria:

* **the tools validate against the MCP tool schema** — every tool of every corpus source's
  descriptor passes the vendored MCP Tool schema of both protocol revisions and the compiler's own
  contract, and the descriptor is the static-manifest shape the MCP importer detects;
* **tool names are unique, deterministic, and flagged SYNTH when synthesized** — names come from
  the shared compiler (AGX-1.1); a name made from the method and path, a sanitized or a
  deduplicated one is ``INFERRED`` in the provenance, an ``mcp-tool-name-synthesized`` loss and a
  ``SYNTH`` verdict in the fidelity report;
* **input schemas round-trip through the MFI MCP importer** — importing the descriptor and
  compiling it again gives the same tools with the same ``inputSchema``.

Plus ``outputSchema`` (object responses on 2025-06-18, on by default), ``per-service`` grouping, the
MCP-source rule (resources and prompts are not tools), deprecated operations and the refusals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, Provenance, coerce_emit_options, load_builtin_emitters
from app.export_routes import build_target_fidelity_entries
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.mcp_emitter import (
    LOSS_NAME_SYNTHESIZED,
    LOSS_NOT_A_TOOL,
    LOSS_OUTPUT_NOT_OBJECT,
    LOSS_OUTPUT_UNSUPPORTED,
    McpEmitOptions,
    McpEmitter,
    mcp_tool_schema_violations,
)
from app.mcp_manifest_parser import is_mcp_manifest
from app.mcp_tool_mapping import compile_mcp_tools, validate_mcp_tool

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _corpus(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _petstore() -> CanonicalApi:
    return _corpus("openapi/30-openapi-3.0-petstore.yaml", "openapi")


def _emit(api: CanonicalApi, **options: Any) -> Any:
    return McpEmitter().emit(api, opts=coerce_emit_options(McpEmitter, options))


def _descriptor(api: CanonicalApi, **options: Any) -> Dict[str, Any]:
    return json.loads(_emit(api, **options).files[0].content)


def _reimport(content: str) -> CanonicalApi:
    source = get_import_source("mcp")
    return source.normalize(source.parse(content))


def _response(op: str, status: str, payload: TypeRef | None = None) -> Message:
    return Message(key=f"{op}#response.{status}", role=MessageRole.RESPONSE, status_code=status,
                   payload=payload, content_types=["application/json"] if payload else [])


def _op(key: str, method: str, path: str, *, operation_id: str | None = None,
        deprecated: bool = False, response: Message | None = None) -> Operation:
    extras = {"operationId": operation_id} if operation_id else {}
    return Operation(key=key, name=operation_id or key, kind=OperationKind.REQUEST_RESPONSE,
                     http_method=method, http_path=path, deprecated=deprecated, extras=extras,
                     messages=[response or _response(key, "204")])


def _api(*ops: Operation, services: List[Service] | None = None) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Shop API"),
                        title="Shop API", version="2.0.0",
                        services=services or [Service(key="shop", name="shop", operations=list(ops))])


# ===========================================================================
# The descriptor and the MCP Tool schema
# ===========================================================================


def test_the_descriptor_is_a_server_manifest_the_importer_detects() -> None:
    result = _emit(_petstore())
    assert [f.path for f in result.files] == ["sample-pet-store-api-openapi-3-0.mcp.json"]
    content = result.files[0].content
    document = json.loads(content)
    assert document["mcpVersion"] == "2025-06-18"
    assert document["server"] == {"name": "sample-pet-store-api-openapi-3-0", "version": "1.0.0",
                                  "title": "Sample Pet Store API (OpenAPI 3.0)"}
    assert document["capabilities"] == {"tools": {}}
    assert is_mcp_manifest(content)


@pytest.mark.parametrize("version", ["2025-06-18", "2025-03-26"])
def test_every_corpus_tool_validates_against_the_mcp_tool_schema(version: str) -> None:
    from corpus_roundtrip import representatives_by_format
    from export_conformance import _import_entry

    checked, failures = 0, []
    for family, entry in sorted(representatives_by_format().items()):
        if entry is None:
            continue
        try:
            api = _import_entry(entry)
            document = _descriptor(api, protocol_version=version)
        except EmitPreconditionError:
            continue
        except Exception as exc:  # noqa: BLE001 - the import matrix owns import failures
            if "not valid" in str(exc):
                failures.append(f"{family}: {exc}")
            continue
        for tool in document["tools"]:
            checked += 1
            problems = mcp_tool_schema_violations(tool, version) + validate_mcp_tool(tool)
            failures += [f"{family} {tool['name']}: {p}" for p in problems]
    assert checked > 50
    assert not failures, "\n".join(failures[:20])


def test_the_schema_check_rejects_an_invalid_tool() -> None:
    assert mcp_tool_schema_violations({"name": "x", "inputSchema": {"type": "array"}}, "2025-06-18")
    assert mcp_tool_schema_violations({"name": "x"}, "2025-06-18")
    # 2025-03-26 has no outputSchema (nor title).
    tool = {"name": "x", "inputSchema": {"type": "object"}, "outputSchema": {"type": "object"}}
    assert mcp_tool_schema_violations(tool, "2025-03-26")
    assert mcp_tool_schema_violations(tool, "2025-06-18") == []


# ===========================================================================
# Names: unique, deterministic, SYNTH when synthesized
# ===========================================================================


def _naming_api() -> CanonicalApi:
    return _api(
        _op("GET /orders", "GET", "/orders", operation_id="listOrders"),
        _op("GET /orders/{id}", "GET", "/orders/{id}"),                       # no operationId
        _op("POST /orders", "POST", "/orders", operation_id="create order!"),  # sanitized
        _op("PUT /orders", "PUT", "/orders", operation_id="listOrders"),       # duplicate
    )


def test_names_are_unique_and_deterministic() -> None:
    first = _emit(_naming_api())
    second = _emit(_naming_api())
    assert first.files[0].content == second.files[0].content
    names = [tool["name"] for tool in json.loads(first.files[0].content)["tools"]]
    assert len(names) == len(set(names)) == 4


def test_a_synthesized_name_is_flagged_synth() -> None:
    api = _naming_api()
    result = _emit(api)
    tools = json.loads(result.files[0].content)["tools"]
    synthesized = {loss.pointer for loss in result.losses if loss.subject == LOSS_NAME_SYNTHESIZED}
    assert synthesized == {"GET /orders/{id}", "POST /orders", "PUT /orders"}
    inferred = [r for r in result.provenance if r.pointer.endswith("/name") and r.provenance is Provenance.INFERRED]
    assert len(inferred) == 3
    assert "listOrders" in [tool["name"] for tool in tools]

    report = compute_lossiness_for_emitter(api, McpEmitter)
    kinds = {item.message.split("'")[1]: item.kind for item in report.items
             if item.target_mapping and item.target_mapping.startswith("operation → tool")}
    assert sorted(kinds.values(), key=str) == [LossinessKind.SYNTH] * 3
    ok = [item for item in report.items if item.kind is LossinessKind.OK and "listOrders" in item.message]
    assert ok


# ===========================================================================
# Input schemas round-trip through the MCP importer
# ===========================================================================


@pytest.mark.parametrize(("path", "fmt"), [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("mcp/02-typical-tickets-server.json", "mcp"),
])
def test_input_schemas_round_trip_through_the_mcp_importer(path: str, fmt: str) -> None:
    api = _corpus(path, fmt)
    result = _emit(api)
    original = {tool["name"]: tool["inputSchema"] for tool in json.loads(result.files[0].content)["tools"]}
    back = _reimport(result.files[0].content)
    again = {tool.name: tool.input_schema for tool in compile_mcp_tools(back).tools}
    assert again == original


def test_a_2025_03_26_descriptor_also_round_trips() -> None:
    result = _emit(_petstore(), protocol_version="2025-03-26")
    back = _reimport(result.files[0].content)
    assert len(list(back.operations())) == len(json.loads(result.files[0].content)["tools"])


# ===========================================================================
# outputSchema
# ===========================================================================


def test_an_object_response_gets_an_output_schema_and_an_array_does_not() -> None:
    result = _emit(_petstore())
    tools = {tool["name"]: tool for tool in json.loads(result.files[0].content)["tools"]}
    assert tools["getPetById"]["outputSchema"]["type"] == "object"
    assert "outputSchema" not in tools["listPets"]  # an array of pets
    assert LOSS_OUTPUT_NOT_OBJECT in {loss.subject for loss in result.losses}


def test_output_schema_can_be_turned_off_and_is_absent_in_2025_03_26() -> None:
    off = _emit(_petstore(), output_schema=False)
    assert all("outputSchema" not in tool for tool in json.loads(off.files[0].content)["tools"])
    assert LOSS_OUTPUT_UNSUPPORTED not in {loss.subject for loss in off.losses}
    older = _emit(_petstore(), protocol_version="2025-03-26")
    document = json.loads(older.files[0].content)
    assert all("outputSchema" not in tool for tool in document["tools"])
    assert "title" not in document["server"]
    assert LOSS_OUTPUT_UNSUPPORTED in {loss.subject for loss in older.losses}


# ===========================================================================
# Grouping, MCP sources, deprecated, refusals, the card
# ===========================================================================


def test_per_service_writes_one_descriptor_per_service_with_the_same_names() -> None:
    api = _api(services=[
        Service(key="orders", name="orders",
                operations=[_op("GET /orders", "GET", "/orders", operation_id="listOrders")]),
        Service(key="users", name="users",
                operations=[_op("GET /users", "GET", "/users", operation_id="listUsers")]),
    ])
    single = [tool["name"] for tool in _descriptor(api)["tools"]]
    grouped = _emit(api, grouping="per-service")
    assert [f.path for f in grouped.files] == ["shop-api-orders.mcp.json", "shop-api-users.mcp.json"]
    names = [tool["name"] for f in grouped.files for tool in json.loads(f.content)["tools"]]
    assert names == single
    assert json.loads(grouped.files[1].content)["server"]["title"] == "Shop API — users"


def test_an_mcp_sources_resources_and_prompts_are_not_tools() -> None:
    api = _corpus("mcp/02-typical-tickets-server.json", "mcp")
    result = _emit(api)
    names = [tool["name"] for tool in json.loads(result.files[0].content)["tools"]]
    assert names == ["close_ticket", "create_ticket", "search_tickets"]
    skipped = [loss for loss in result.losses if loss.subject == LOSS_NOT_A_TOOL]
    assert skipped and all("not a tool" in loss.detail for loss in skipped)
    report = compute_lossiness_for_emitter(api, McpEmitter)
    assert any("resource or prompt is not a tool" in item.message for item in report.items)


def test_deprecated_operations_need_include_deprecated() -> None:
    api = _api(_op("GET /a", "GET", "/a", operation_id="current"),
               _op("GET /b", "GET", "/b", operation_id="legacy", deprecated=True))
    assert [t["name"] for t in _descriptor(api)["tools"]] == ["current"]
    assert [t["name"] for t in _descriptor(api, include_deprecated=True)["tools"]] == ["current", "legacy"]


def test_a_model_with_nothing_callable_is_offered_greyed_out_and_refused() -> None:
    api = _corpus("json-schema/03-multiple-defs.json", "json-schema")
    card = next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == "mcp")
    assert card.descriptor.available is False
    assert "operation an agent can call" in (card.descriptor.unavailable_reason or "")
    with pytest.raises(EmitPreconditionError, match="no callable operation"):
        _emit(api)


@pytest.mark.parametrize("options", [{"protocol_version": "2024-11-05"}, {"grouping": "per-tag"}])
def test_invalid_options_are_rejected(options: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        McpEmitOptions(**options)
    with pytest.raises(Exception):
        coerce_emit_options(McpEmitter, options)


def test_the_card_offers_the_target_for_a_rest_source() -> None:
    card = next(entry for entry in build_target_fidelity_entries(_petstore()) if entry.descriptor.key == "mcp")
    assert card.descriptor.available is True
    assert card.descriptor.paradigm == "agent"
    assert set(card.options_schema["properties"]) == {"protocol_version", "grouping", "output_schema",
                                                       "include_deprecated"}
