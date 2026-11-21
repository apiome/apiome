"""Validators for the export targets that reported "not applicable" — COA-3.4 (#7055).

At the RC7 audit 14 export targets had no emitted-artifact validator, and the report called that
"not applicable", which reads as a pass. Nine gained one in RC7 (wsdl, xsd, raml, smithy,
apiblueprint, thrift, postman, openrpc, flatbuffers) and wadl in MFX-29.3; this ticket adds the
rest — ``connectrpc``, ``cloudevents``, ``xmlrpc``, ``kafka-connect`` — plus the two agent targets
that had none either (``a2a``, ``mcp``). Proven here:

* **the ratchet** — every registered emit target except the internal ``sample-noop`` has a
  validator, so no new target can ship unchecked;
* **valid output passes** — a real emit of each target validates and is ``valid``;
* **broken output is caught** — each spec rule and each re-import failure is a finding with its rule
  as ``keyword``;
* **no validator reads "Not validated"** — :mod:`test_export_validation_gate` pins the copy.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.cloudevents_spec_validation import cloudevents_spec_problems
from app.emitter import EmitResult, EmittedFile, available_emit_formats, get_emitter_instance
from app.export_validation import _OPTION_VALIDATORS, _VALIDATORS, validate_emitted_artifact
from app.xmlrpc_spec_validation import xmlrpc_spec_problems

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: The internal no-op emitter: it writes no importable artifact, so it has nothing to validate.
_NO_ARTIFACT_TARGETS = {"sample-noop"}


def _rpc_api() -> CanonicalApi:
    """An RPC model (one non-HTTP operation, one record type): XML-RPC, MCP and A2A can all emit it."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string", nullable=False))],
    )
    op = Operation(key="listWidgets", name="listWidgets", kind=OperationKind.QUERY)
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="openrpc",
        identity=ApiIdentity(name="widgets", namespace="com.example"),
        services=[Service(key="widgets", name="widgets", operations=[op])],
        types=[widget],
    )


def _one_file(path: str, content: Any) -> EmitResult:
    """A one-file bundle."""
    return EmitResult(files=[EmittedFile(path=path, content=content)])


async def _validate(target: str, emit_result: EmitResult):
    """Run the export gate's validator for ``target``."""
    return await validate_emitted_artifact(target, emit_result, api=_rpc_api())


def _keywords(validation) -> set:
    """The rule keywords of a validation's findings."""
    return {finding.keyword for finding in validation.findings}


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


def test_every_user_facing_emit_target_has_a_validator() -> None:
    """No registered emit target (bar the internal no-op) reports "not applicable" any more."""
    unvalidated = {
        target
        for target in available_emit_formats()
        if target not in _VALIDATORS and target not in _OPTION_VALIDATORS
    }
    assert unvalidated == _NO_ARTIFACT_TARGETS


# ---------------------------------------------------------------------------
# Valid output passes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["cloudevents", "xmlrpc", "kafka-connect", "a2a", "mcp"])
async def test_a_real_emit_validates(target: str) -> None:
    """A real emit of each pure-Python target is validated and valid."""
    api = _rpc_api()
    emit_result = get_emitter_instance(target).emit(api)
    validation = await validate_emitted_artifact(target, emit_result, api=api)

    assert validation.applicable
    assert validation.validated
    assert validation.valid, validation.errors


# ---------------------------------------------------------------------------
# Connect RPC — the same buf compile as protobuf
# ---------------------------------------------------------------------------


async def test_connectrpc_is_skipped_not_passed_when_buf_is_unavailable() -> None:
    """Without ``buf`` the Connect bundle is reported not validated, with the tool named."""
    with patch("app.toolchain_runner.is_tool_available", return_value=False):
        validation = await _validate("connectrpc", _one_file("api.proto", 'syntax = "proto3";\n'))

    assert validation.applicable
    assert not validation.validated
    assert "buf" in (validation.detail or "")


async def test_connectrpc_that_does_not_compile_is_caught() -> None:
    """With ``buf`` present and the compile failing, the Connect export fails validation."""
    from app.proto_descriptor import ProtoCompileError

    async def _fail_compile(*args, **kwargs):
        raise ProtoCompileError("buf build failed", diagnostics="api.proto:1:1: syntax error")

    with patch("app.toolchain_runner.is_tool_available", return_value=True), patch(
        "app.proto_descriptor.compile_proto_descriptor_set", _fail_compile
    ):
        validation = await _validate("connectrpc", _one_file("api.proto", "not proto"))

    assert validation.failed
    assert any("syntax error" in error for error in validation.errors)


# ---------------------------------------------------------------------------
# CloudEvents — the 1.0 core and JSON-format rules
# ---------------------------------------------------------------------------

_EVENT: Dict[str, Any] = {"specversion": "1.0", "id": "1", "source": "/widgets", "type": "com.example.widget"}


def _rules(content: Any) -> set:
    """The rule ids :func:`cloudevents_spec_problems` reports for ``content``."""
    return {problem["rule"] for problem in cloudevents_spec_problems(content, file="e.json")}


def test_a_minimal_event_meets_the_spec() -> None:
    """The four required attributes are all an event needs."""
    assert cloudevents_spec_problems(dict(_EVENT)) == []


def test_a_full_event_meets_the_spec() -> None:
    """Every optional attribute with its spec type, plus legal extensions, passes."""
    event = {
        **_EVENT,
        "subject": "w-1",
        "time": "2026-11-20T10:00:00.123Z",
        "datacontenttype": "application/json",
        "dataschema": "https://example.com/widget.json",
        "data": {"id": "w-1"},
        "traceparent": "00-abc",
        "partitionkey": 7,
        "sampled": True,
        "unset": None,
    }
    assert cloudevents_spec_problems(json.dumps(event)) == []


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"specversion": "2.0"}, "cloudevents.specversion"),
        ({"id": ""}, "cloudevents.required"),
        ({"source": 3}, "cloudevents.required"),
        ({"subject": ""}, "cloudevents.attribute-type"),
        ({"time": "yesterday"}, "cloudevents.attribute-type"),
        ({"time": "2026-13-40T99:00:00Z"}, "cloudevents.attribute-type"),
        ({"data_base64": 12}, "cloudevents.attribute-type"),
        ({"data": {}, "data_base64": "e30="}, "cloudevents.data-exclusive"),
        ({"Bad-Name": "x"}, "cloudevents.attribute-name"),
        ({"nested": {"a": 1}}, "cloudevents.extension-value"),
        ({"ratio": 0.5}, "cloudevents.extension-value"),
    ],
)
def test_each_spec_rule_is_enforced(change: Dict[str, Any], rule: str) -> None:
    """Breaking one rule reports exactly that rule."""
    assert rule in _rules({**_EVENT, **change})


def test_a_missing_required_attribute_is_reported() -> None:
    """Dropping ``id`` (the parser tolerates it) is a spec violation."""
    event = dict(_EVENT)
    del event["id"]
    problems = cloudevents_spec_problems(event, file="e.json")
    assert [(p["rule"], p["path"], p["file"]) for p in problems] == [("cloudevents.required", "/id", "e.json")]


def test_a_batch_is_checked_event_by_event() -> None:
    """Each batch entry is checked, its pointer carrying the index; a non-object entry is a finding."""
    problems = cloudevents_spec_problems([dict(_EVENT), {**_EVENT, "type": ""}, "nope"])
    assert [(p["rule"], p["path"]) for p in problems] == [
        ("cloudevents.required", "/1/type"),
        ("cloudevents.document", "/2"),
    ]


@pytest.mark.parametrize("content", ["not json", "[]", "42"])
def test_a_file_that_is_not_an_event_document_is_reported(content: str) -> None:
    """Non-JSON, an empty batch and a scalar are all document-level violations."""
    assert _rules(content) == {"cloudevents.document"}


def test_version_0_3_round_trips() -> None:
    """An event imported at 0.3 (with its ``datacontentencoding``) is written back as read."""
    assert cloudevents_spec_problems({**_EVENT, "specversion": "0.3", "datacontentencoding": "base64"}) == []


async def test_the_gate_rejects_an_invalid_cloudevents_export() -> None:
    """Through the export gate, a spec violation fails the export with its rule as ``keyword``."""
    validation = await _validate("cloudevents", _one_file("e.json", json.dumps({**_EVENT, "specversion": "9"})))

    assert validation.failed
    assert "cloudevents.specversion" in _keywords(validation)


async def test_the_gate_rejects_a_cloudevents_file_that_does_not_import() -> None:
    """A file the CloudEvents reader refuses is a re-import finding."""
    validation = await _validate("cloudevents", _one_file("e.json", json.dumps({"hello": "world"})))

    assert validation.failed
    assert "cloudevents.reimport" in _keywords(validation)


# ---------------------------------------------------------------------------
# XML-RPC — structure plus the stdlib unmarshaller
# ---------------------------------------------------------------------------

_CALL = (
    '<?xml version="1.0"?>\n<methodCall><methodName>{name}</methodName>'
    "<params><param><value>{value}</value></param></params></methodCall>"
)


def _xml_rules(content: str) -> set:
    """The rule ids :func:`xmlrpc_spec_problems` reports for ``content``."""
    return {problem["rule"] for problem in xmlrpc_spec_problems(content, file="m.xml")}


def test_a_well_formed_call_meets_the_spec() -> None:
    """Every value type the emitter writes reads back through ``xmlrpc.client``."""
    value = (
        "<struct><member><name>id</name><value><string>w</string></value></member>"
        "<member><name>n</name><value><int>3</int></value></member>"
        "<member><name>ok</name><value><boolean>1</boolean></value></member>"
        "<member><name>r</name><value><double>0.5</double></value></member>"
        "<member><name>z</name><value><nil/></value></member>"
        "<member><name>a</name><value><array><data><value><i4>1</i4></value></data></array></value></member>"
        "</struct>"
    )
    assert xmlrpc_spec_problems(_CALL.format(name="system.listMethods", value=value)) == []


def test_a_fault_response_meets_the_spec() -> None:
    """A ``<fault>`` response is a legal message (the stdlib raises it by design)."""
    fault = (
        "<methodResponse><fault><value><struct>"
        "<member><name>faultCode</name><value><int>4</int></value></member>"
        "<member><name>faultString</name><value><string>Too many</string></value></member>"
        "</struct></value></fault></methodResponse>"
    )
    assert xmlrpc_spec_problems(fault) == []


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        (_CALL.format(name="list widgets", value="<string/>"), "xmlrpc.method-name"),
        (_CALL.format(name="list-widgets", value="<string/>"), "xmlrpc.method-name"),
        ("<methodCall><params/></methodCall>", "xmlrpc.method-name"),
        (_CALL.format(name="a", value="<int>abc</int>"), "xmlrpc.value"),
        (_CALL.format(name="a", value="<bogus>1</bogus>"), "xmlrpc.value"),
        ("<methodRequest/>", "xmlrpc.document"),
        ("<methodCall>", "xmlrpc.document"),
    ],
)
def test_each_xmlrpc_rule_is_enforced(content: str, rule: str) -> None:
    """Breaking one rule reports that rule."""
    assert rule in _xml_rules(content)


def test_a_dtd_is_refused_before_the_stdlib_sees_it() -> None:
    """Entity expansion never reaches ``xmlrpc.client``: the secure parser refuses the document."""
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
        "<methodCall><methodName>&b;</methodName></methodCall>"
    )
    assert _xml_rules(bomb) == {"xmlrpc.document"}


async def test_the_gate_rejects_an_invalid_xmlrpc_export() -> None:
    """Through the export gate, an illegal method name fails the export."""
    validation = await _validate("xmlrpc", _one_file("m.xml", _CALL.format(name="bad name", value="<int>1</int>")))

    assert validation.failed
    assert "xmlrpc.method-name" in _keywords(validation)


@pytest.mark.parametrize(
    ("name", "written"),
    [
        ("system.listMethods", "system.listMethods"),
        ("Build itinerary", "Build_itinerary"),
        ("https://returns.example/.well-known/agent-card.json", "https://returns.example/.well_known/agent_card.json"),
        ("list-widgets  now", "list_widgets_now"),
        ("  ", "method"),
    ],
)
def test_an_operation_name_becomes_a_legal_method_name(name: str, written: str) -> None:
    """Each run of illegal characters becomes one ``_``; a legal name is unchanged."""
    from app.xmlrpc_emitter import xmlrpc_method_name

    assert xmlrpc_method_name(name) == written


async def test_an_agent_skill_name_exports_as_a_valid_xmlrpc_call() -> None:
    """A skill named ``Build itinerary`` (an agent source) is written as a legal ``methodName``."""
    api = _rpc_api()
    api.services[0].operations[0] = Operation(key="Build itinerary", name="Build itinerary", kind=OperationKind.QUERY)
    emit_result = get_emitter_instance("xmlrpc").emit(api)
    validation = await validate_emitted_artifact("xmlrpc", emit_result, api=api)

    assert "<methodName>Build_itinerary</methodName>" in emit_result.files[0].content
    assert validation.valid, validation.errors


# ---------------------------------------------------------------------------
# Kafka Connect — the reader is the authority
# ---------------------------------------------------------------------------


async def test_the_gate_rejects_a_connect_schema_the_reader_refuses() -> None:
    """A Connect schema that does not read back fails the export."""
    broken = {"type": "struct", "fields": "not-a-list"}
    validation = await _validate("kafka-connect", _one_file("Widget.json", broken))

    assert validation.failed
    assert _keywords(validation) == {"kafka-connect.reimport"}


async def test_a_connect_schema_with_its_connector_config_validates_together() -> None:
    """The schemas and ``connector.json`` are imported as one pipeline, as Connect composes them."""
    schema = {"type": "struct", "name": "Widget", "fields": [{"field": "id", "type": "string"}]}
    connector = {"name": "widgets", "config": {"connector.class": "io.example.Sink"}}
    emit_result = EmitResult(
        files=[
            EmittedFile(path="connector.json", content=connector),
            EmittedFile(path="Widget.json", content=schema),
        ]
    )
    validation = await _validate("kafka-connect", emit_result)

    assert validation.valid, validation.errors


# ---------------------------------------------------------------------------
# A2A and MCP — the vendored schemas
# ---------------------------------------------------------------------------


async def test_the_gate_rejects_an_agent_card_that_breaks_the_schema() -> None:
    """A card missing the schema's required members fails with ``a2a.schema`` findings."""
    validation = await _validate("a2a", _one_file("agent-card.json", json.dumps({"name": "x"})))

    assert validation.failed
    assert "a2a.schema" in _keywords(validation)


async def test_the_gate_rejects_an_mcp_descriptor_with_an_unknown_version() -> None:
    """An ``mcpVersion`` outside the vendored revisions is a descriptor finding."""
    descriptor = {"mcpVersion": "1999-01-01", "server": {"name": "x"}, "tools": []}
    validation = await _validate("mcp", _one_file("x.mcp.json", json.dumps(descriptor)))

    assert validation.failed
    assert "mcp.descriptor" in _keywords(validation)


async def test_the_gate_rejects_an_mcp_tool_that_breaks_the_schema() -> None:
    """A tool without its ``inputSchema`` breaks the MCP Tool schema, located by its index."""
    api = _rpc_api()
    emitted = get_emitter_instance("mcp").emit(api).files[0]
    descriptor = json.loads(emitted.content)
    del descriptor["tools"][0]["inputSchema"]
    validation = await validate_emitted_artifact("mcp", _one_file(emitted.path, json.dumps(descriptor)), api=api)

    assert validation.failed
    schema_findings = [f for f in validation.findings if f.keyword == "mcp.tool-schema"]
    assert schema_findings and schema_findings[0].path.startswith("/tools/0")


@pytest.mark.parametrize("target", ["a2a", "mcp"])
async def test_a_file_that_is_not_json_is_caught(target: str) -> None:
    """A non-JSON card or descriptor fails on its syntax."""
    validation = await _validate(target, _one_file("x.json", "{nope"))

    assert validation.failed
    assert "json.syntax" in _keywords(validation)


@pytest.mark.parametrize("target", ["cloudevents", "xmlrpc", "kafka-connect", "a2a", "mcp"])
async def test_an_empty_bundle_is_rejected(target: str) -> None:
    """A bundle with no file has nothing that could be valid."""
    validation = await _validate(target, EmitResult(files=[]))

    assert validation.failed
