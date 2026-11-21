"""Silent-loss ledger burn-down — COA-3.1 (#7052).

Pins, on small hand-built models, every fix that emptied ``tests/export_conformance_ledger.py``:

* the shared verdicts of a cross-format export (:mod:`app.conversion_verdicts`) — paradigm change,
  re-key, source-format metadata, document envelope, agents;
* the rule packs that now name those losses (OpenAPI, AsyncAPI, CloudEvents, GraphQL, JTD, CDDL,
  XML-RPC, Protobuf / Connect RPC, ONC RPC, WIT, Avro, Kafka Connect);
* the emitter bugs behind the rest: GraphQL left out every type no root field reaches, ONC RPC left
  out every record of another format and numbered every procedure 1, OpenAPI wrote a required
  request body as an optional one, and Azure API Management wrote the policy's backend into the
  definition's servers.
"""

from __future__ import annotations

import json

import pytest
from graphql import build_schema

from app.canonical_model import (
    AgentDescriptor,
    AgentSkill,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.conversion_verdicts import (
    agent_loss_items,
    envelope_verdicts,
    paradigm_change_verdict,
    rekey_verdicts,
    source_metadata_keys,
    source_metadata_verdict,
)
from app.emitter import load_builtin_emitters
from app.export_service import emit_canonical, resolve_emitter
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity

load_builtin_emitters()

DROP, APPROX, SYNTH, OK = LossinessKind.DROP, LossinessKind.APPROX, LossinessKind.SYNTH, LossinessKind.OK


def _field(owner: str, name: str, ref: str = "string", **kwargs) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref), **kwargs)


def _record(key: str, *fields: CanonicalField, **kwargs) -> Type:
    name = key.rsplit(".", 1)[-1]
    return Type(key=key, name=name, kind=TypeKind.RECORD, fields=list(fields) or [_field(key, "id")], **kwargs)


def _rpc(service: str, name: str, **kwargs) -> Operation:
    return Operation(key=f"{service}.{name}", name=name, kind=OperationKind.REQUEST_RESPONSE, **kwargs)


def _api(
    *types: Type,
    services: list[Service] | None = None,
    paradigm: ApiParadigm = ApiParadigm.DATA_SCHEMA,
    fmt: str = "json-schema",
    identity: ApiIdentity | None = None,
    **kwargs,
) -> CanonicalApi:
    return CanonicalApi(
        paradigm=paradigm, format=fmt, identity=identity or ApiIdentity(name="Orders"),
        services=services or [], types=list(types), **kwargs,
    )


def _agent(key: str, *skills: str) -> AgentDescriptor:
    return AgentDescriptor(
        key=key, name=key, protocol="a2a",
        skills=[AgentSkill(key=f"{key}.{skill}", id=skill, name=skill) for skill in skills],
    )


def _report(api: CanonicalApi, target: str, **options):
    return compute_lossiness_for_emitter(api, resolve_emitter(target), options=options or None)


def _items(report, construct: str, kind: LossinessKind | None = None):
    return [i for i in report.items if i.construct_key == construct and (kind is None or i.kind is kind)]


def _kinds(report, construct: str) -> set:
    return {item.kind for item in _items(report, construct)}


def _text(result) -> str:
    content = result.files[0].content
    return content if isinstance(content, str) else json.dumps(content)


# ---------------------------------------------------------------------------
# app.conversion_verdicts
# ---------------------------------------------------------------------------
def test_a_paradigm_change_is_an_approx_and_the_same_paradigm_is_nothing():
    api = _api(paradigm=ApiParadigm.AGENT)
    verdict = paradigm_change_verdict(api, ApiParadigm.REST, target_label="OpenAPI 3.1")
    assert verdict.kind is APPROX and verdict.severity is LossinessSeverity.WARN
    assert "this agent API" in verdict.message and "reads back as a REST API" in verdict.message
    assert verdict.target_mapping == "agent → rest"
    assert paradigm_change_verdict(api, ApiParadigm.AGENT, target_label="x") is None


def test_a_paradigm_label_reads_as_words():
    verdict = paradigm_change_verdict(_api(), ApiParadigm.RPC, target_label="WIT")
    assert "this data schema API" in verdict.message and "reads back as an RPC API" in verdict.message
    event = paradigm_change_verdict(_api(), ApiParadigm.EVENT, target_label="AsyncAPI")
    assert "describes event APIs" in event.message and "as an event API" in event.message
    graph = paradigm_change_verdict(_api(), ApiParadigm.GRAPH, target_label="GraphQL SDL")
    assert "as a GraphQL API" in graph.message


def test_a_rekey_is_a_drop_under_the_old_key_and_a_synth_under_the_new_one():
    drop, (key, synth) = rekey_verdicts(
        "acme.Pet", "Pet", target_label="CDDL", noun="type", reason="rules have no namespaces"
    )
    assert drop.kind is DROP and drop.severity is LossinessSeverity.INFO
    assert "'acme.Pet' is written as 'Pet'" in drop.message
    assert key == "Pet" and synth.kind is SYNTH and synth.target_mapping == "acme.Pet → Pet"
    assert rekey_verdicts("Pet", "Pet", target_label="CDDL", noun="type", reason="x") is None


def test_source_metadata_keys_skip_written_and_empty_values():
    extras = {"operationId": "getPet", "apigee": {"flow": "x"}, "cors": {}, "note": None, "tags": ["a"]}
    assert source_metadata_keys(extras, {"operationId"}) == ["apigee", "tags"]
    assert source_metadata_keys(None) == []


def test_a_source_metadata_verdict_names_the_keys_and_counts_the_rest():
    verdict = source_metadata_verdict(
        ["e", "a", "b", "c", "d", "a"], source_format="apigee", target_label="OpenAPI 3.1", noun="operation"
    )
    assert verdict.kind is DROP and verdict.severity is LossinessSeverity.INFO
    assert "(a, b, c, d and 1 more)" in verdict.message and "apigee metadata of this operation" in verdict.message
    assert source_metadata_verdict([], source_format="x", target_label="y", noun="type") is None


def test_envelope_verdicts_name_what_is_lost_and_what_is_invented():
    api = _api(identity=ApiIdentity(name="Orders", id="urn:x", namespace="acme"), title="Orders", version=None)
    verdicts = envelope_verdicts(
        api, target_label="T", keeps_id=False, keeps_namespace=False, keeps_title=False, default_version="0.0.0"
    )
    assert [v.kind for v in verdicts] == [DROP, SYNTH]
    assert "title 'Orders' and identifier 'urn:x' and namespace 'acme'" in verdicts[0].message
    assert "they are not written" in verdicts[0].message and "'0.0.0' is written" in verdicts[1].message


def test_envelope_verdicts_are_empty_when_the_envelope_survives():
    api = _api(identity=ApiIdentity(name="Orders", id="urn:x"), version="1.0.0")
    assert envelope_verdicts(api, target_label="T", default_version="0.0.0") == []
    lost = envelope_verdicts(api, target_label="T", keeps_version=False)
    assert len(lost) == 1 and "version '1.0.0'; it is not written" in lost[0].message


def test_agent_loss_items_drop_each_agent_and_skill():
    agent = _agent("helper", "search")
    items = agent_loss_items(_api(agents=[agent], paradigm=ApiParadigm.AGENT), target_label="WIT")
    assert [(i.construct_key, i.kind, i.severity) for i in items] == [
        ("helper", DROP, LossinessSeverity.WARN),
        ("helper.search", DROP, LossinessSeverity.INFO),
    ]
    assert agent_loss_items(_api(), target_label="WIT") == []


# ---------------------------------------------------------------------------
# JTD and CDDL: a namespace-qualified type reads back under its bare name
# ---------------------------------------------------------------------------
NAMESPACED = _api(
    _record("X12-850.PO1"), _record("X12-850.Header"),
    fmt="edix12", identity=ApiIdentity(name="X12 850", namespace="X12-850"), title="X12 850",
)


def test_jtd_reports_the_rekey_the_namespace_and_the_root_copy():
    report = _report(NAMESPACED, "jtd")
    assert _kinds(report, "X12-850.PO1") == {DROP}
    assert _kinds(report, "PO1") == {SYNTH} and _kinds(report, "Header") == {SYNTH}
    assert "namespace 'X12-850'" in _items(report, "", DROP)[0].message
    assert "also written as the root" in _items(report, "X12 850", SYNTH)[0].message


def test_jtd_writes_an_imported_document_back_and_reports_no_rekey():
    api = NAMESPACED.model_copy(update={"raw": {"source": {"properties": {"id": {"type": "string"}}}}})
    report = _report(api, "jtd")
    assert not _items(report, "", DROP) and _kinds(report, "X12-850.PO1") == {OK}
    assert not _items(report, "PO1")


def test_jtd_keeps_a_type_whose_key_is_its_name():
    report = _report(_api(_record("Pet"), title="Pet"), "jtd")
    assert _kinds(report, "Pet") == {OK} and not _items(report, "")


def test_cddl_reports_the_rekey_and_the_envelope_a_grammar_cannot_hold():
    report = _report(NAMESPACED, "cddl")
    assert _kinds(report, "X12-850.Header") == {DROP} and _kinds(report, "Header") == {SYNTH}
    root = _items(report, "", DROP)[0].message
    assert "title 'X12 850'" in root and "namespace 'X12-850'" in root


def test_cddl_keeps_the_title_a_reader_derives_from_the_first_rule():
    api = _api(_record("Pet"), fmt="cddl", identity=ApiIdentity(name="Pet"), title="Pet")
    report = _report(api, "cddl")
    assert not _items(report, "") and _kinds(report, "Pet") == {OK}


# ---------------------------------------------------------------------------
# OpenAPI: a document rebuilt from another format's model
# ---------------------------------------------------------------------------
def _rpc_api(**kwargs) -> CanonicalApi:
    call = _rpc("Wallet", "getBalance", extras={"jsonrpc": {"paramStructure": "by-name"}})
    return _api(
        _record("Balance", extras={"rpc_kind": "result"}),
        services=[Service(key="Wallet", name="Wallet", operations=[call])],
        paradigm=ApiParadigm.RPC, fmt="openrpc", **kwargs,
    )


def test_openapi_reports_what_a_rebuilt_document_changes():
    report = _report(_rpc_api(), "openapi")
    root = _items(report, "")
    assert {i.kind for i in root} == {APPROX, SYNTH}
    assert any("this RPC API" in i.message for i in root) and any("'0.0.0' is written" in i.message for i in root)

    operation = _items(report, "Wallet.getBalance")
    assert OK not in {i.kind for i in operation}
    assert any("is written as 'POST /Wallet/getBalance'" in i.message for i in operation)
    assert any("no operationId" in i.message for i in operation)
    assert any("an empty default response is written" in i.message for i in operation)
    assert any("openrpc metadata of this operation (jsonrpc)" in i.message for i in operation)
    assert _kinds(report, "POST /Wallet/getBalance") == {SYNTH}

    assert _kinds(report, "Wallet") == {DROP} and _kinds(report, "default") == {SYNTH}
    assert "openrpc metadata of this type (rpc_kind)" in _items(report, "Balance", DROP)[0].message


def test_openapi_keeps_a_service_that_is_its_operations_first_tag():
    operation = Operation(
        key="GET /pets", name="listPets", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
        http_path="/pets", tags=["pets"], extras={"operationId": "listPets"},
        messages=[Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200")],
    )
    api = _api(
        services=[Service(key="pets", name="pets", description="Pet operations", operations=[operation])],
        paradigm=ApiParadigm.REST, fmt="raml", version="1.0.0",
    )
    report = _report(api, "openapi")
    assert _kinds(report, "GET /pets") == {OK}
    assert _kinds(report, "pets") == {APPROX} and not _items(report, "default")
    assert "rebuilt as an OpenAPI 3.1 document" in _items(report, "", APPROX)[0].message


def test_openapi_says_nothing_of_a_model_written_back_from_its_openapi_source():
    api = _rpc_api(extras={"openapiSource": {"object": {"openapi": "3.1.0"}, "version": "3.1.0"}}).model_copy(
        update={"format": "openapi-3.1", "paradigm": ApiParadigm.REST}
    )
    report = _report(api, "openapi")
    assert not _items(report, "") and _kinds(report, "Wallet.getBalance") == {OK}
    assert not _items(report, "Wallet") and _kinds(report, "Balance") == {OK}


def test_openapi_says_gateway_metadata_reads_back_only_as_vendor_extensions():
    operation = Operation(
        key="GET /orders", name="listOrders", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
        http_path="/orders", extras={"aws_apigateway": {"integration": {"type": "aws_proxy"}}, "openapiSource": {}},
    )
    api = _api(
        services=[Service(key="default", name="default", operations=[operation])],
        paradigm=ApiParadigm.REST, fmt="aws-apigateway", version="1",
        extras={"openapiSource": {"object": {"openapi": "3.0.1"}, "version": "3.0.1"}, "aws_apigateway": {"x": 1}},
    )
    report = _report(api, "openapi")
    item = _items(report, "GET /orders")
    assert [i.kind for i in item] == [APPROX] and "(aws_apigateway)" in item[0].message
    assert "reads neither back" in item[0].message
    assert [i.kind for i in _items(report, "")] == [APPROX]


def test_openapi_drops_agents_and_skills_of_a_rebuilt_document():
    agent = _agent("helper", "search")
    api = _api(
        services=[Service(key="helper", name="helper", operations=[_rpc("helper", "search")])],
        agents=[agent], paradigm=ApiParadigm.AGENT, fmt="a2a",
    )
    report = _report(api, "openapi")
    assert DROP in _kinds(report, "helper") and any(
        i.target_mapping == "skill → dropped" for i in _items(report, "helper.search")
    )


def test_openapi_writes_a_required_request_body_as_required():
    def post(required: bool) -> CanonicalApi:
        body = Message(
            key="POST /orders#request", role=MessageRole.REQUEST, payload=TypeRef(name="Order"), required=required
        )
        operation = Operation(
            key="POST /orders", name="createOrder", kind=OperationKind.REQUEST_RESPONSE, http_method="POST",
            http_path="/orders", messages=[body],
        )
        return _api(
            _record("Order"), services=[Service(key="default", name="default", operations=[operation])],
            paradigm=ApiParadigm.REST, fmt="raml",
        )

    document = emit_canonical(post(True), "openapi").files[0].content
    assert document["paths"]["/orders"]["post"]["requestBody"]["required"] is True
    optional = emit_canonical(post(False), "openapi").files[0].content
    assert "required" not in optional["paths"]["/orders"]["post"]["requestBody"]


# ---------------------------------------------------------------------------
# GraphQL: every type is written; a reframed source says what changed
# ---------------------------------------------------------------------------
def test_graphql_writes_the_types_of_a_source_with_no_operations():
    sdl = _text(emit_canonical(_api(_record("User"), _record("UserAddress")), "graphql"))
    schema = build_schema(sdl)
    assert schema.get_type("User") is not None and schema.get_type("UserAddress") is not None
    assert "_: Boolean" in sdl  # the placeholder Query a schema still needs


def test_graphql_writes_a_type_no_root_field_reaches():
    query = Operation(
        key="Query.pet", name="pet", kind=OperationKind.QUERY,
        messages=[Message(key="Query.pet#response", role=MessageRole.RESPONSE, payload=TypeRef(name="Pet"))],
    )
    api = _api(
        _record("Pet"), _record("Unused"),
        services=[Service(key="Query", name="Query", operations=[query])],
        paradigm=ApiParadigm.GRAPH, fmt="graphql",
    )
    schema = build_schema(_text(emit_canonical(api, "graphql")))
    assert schema.get_type("Unused") is not None


def test_graphql_reports_a_reframed_data_schema():
    api = _api(
        _record("acme.Pet"), identity=ApiIdentity(name="Pets", id="urn:pets", namespace="acme"),
        title="Pets", version="2.0.0",
    )
    report = _report(api, "graphql")
    root = _items(report, "")
    assert any("this data schema API" in i.message for i in root)
    assert any("title 'Pets'" in i.message and "version '2.0.0'" in i.message for i in root)
    assert _kinds(report, "acme.Pet") == {DROP} and _kinds(report, "Pet") == {SYNTH}
    assert _kinds(report, "Query") == {SYNTH} and "placeholder" in _items(report, "Query._")[0].message


def test_graphql_reports_the_root_field_an_rpc_operation_becomes():
    api = _api(
        services=[Service(key="Wallet", name="Wallet", operations=[_rpc("Wallet", "transfer")])],
        paradigm=ApiParadigm.RPC, fmt="openrpc",
    )
    report = _report(api, "graphql")
    assert "is written as 'Mutation.transfer'" in _items(report, "Wallet.transfer", DROP)[0].message
    assert _kinds(report, "Mutation.transfer") == {SYNTH} and _kinds(report, "Mutation") == {SYNTH}
    assert _kinds(report, "Wallet") == {DROP}


def test_graphql_says_nothing_new_of_a_graphql_schema():
    query = Operation(key="Query.pet", name="pet", kind=OperationKind.QUERY)
    api = _api(
        _record("Pet"), services=[Service(key="Query", name="Query", operations=[query])],
        paradigm=ApiParadigm.GRAPH, fmt="graphql", identity=ApiIdentity(name="GraphQL Schema"),
    )
    report = _report(api, "graphql")
    assert report.is_lossless


# ---------------------------------------------------------------------------
# AsyncAPI and CloudEvents
# ---------------------------------------------------------------------------
def test_asyncapi_reports_a_components_only_document():
    report = _report(_api(_record("Order"), identity=ApiIdentity(name="Orders", id="urn:o")), "asyncapi")
    root = _items(report, "")
    assert any("this data schema API" in i.message for i in root)
    assert any("holds only its 1 type(s), under components.schemas" in i.message for i in root)
    assert any("identifier 'urn:o'" in i.message for i in root) and any(i.kind is SYNTH for i in root)


def test_asyncapi_reports_a_2x_document_written_as_3x():
    channel = Channel(key="user/signedup", address="user/signedup")
    subscribe = Operation(
        key="onSignUp", name="onSignUp", kind=OperationKind.SUBSCRIBE, channel_ref="user/signedup"
    )
    api = _api(
        services=[Service(key="default", name="default", operations=[subscribe])], channels=[channel],
        paradigm=ApiParadigm.EVENT, fmt="asyncapi-2", version="1.0.0",
    )
    report = _report(api, "asyncapi")
    assert "written as AsyncAPI 3.1" in _items(report, "", APPROX)[0].message
    assert _kinds(report, "onSignUp") == {APPROX} and _kinds(report, "user/signedup") == {SYNTH}
    native = _report(api.model_copy(update={"format": "asyncapi-3"}), "asyncapi")
    assert native.is_lossless


def test_cloudevents_drops_every_type_and_says_the_event_is_a_placeholder():
    report = _report(_api(_record("Order", _field("Order", "id")), title="Orders"), "cloudevents")
    assert _kinds(report, "Order") == {DROP} and not _items(report, "Order.id")
    root = _items(report, "")
    assert any(i.severity is LossinessSeverity.CRITICAL and "placeholder event" in i.message for i in root)
    assert any("title 'Orders'" in i.message for i in root)


def test_cloudevents_keeps_its_own_documents_verdicts():
    api = _api(_record("Order"), paradigm=ApiParadigm.EVENT, fmt="cloudevents")
    report = _report(api, "cloudevents")
    assert _kinds(report, "Order") == {OK} and not _items(report, "")


# ---------------------------------------------------------------------------
# XML-RPC: one methodCall per document
# ---------------------------------------------------------------------------
def _two_calls() -> CanonicalApi:
    calls = [_rpc("acme.Bank", "deposit"), _rpc("acme.Bank", "open")]
    service = Service(key="acme.Bank", name="Bank", operations=calls)
    return _api(
        _record("acme.Account"), services=[service], paradigm=ApiParadigm.RPC, fmt="corbaidl",
        identity=ApiIdentity(name="Banking", namespace="acme"),
    )


def test_xmlrpc_writes_one_call_and_drops_the_rest():
    report = _report(_two_calls(), "xmlrpc")
    assert "is written as 'deposit.deposit'" in _items(report, "acme.Bank.deposit", DROP)[0].message
    assert "one methodCall" in _items(report, "acme.Bank.open", DROP)[0].message
    assert _kinds(report, "acme.Account") == {DROP} and _kinds(report, "acme.Bank") == {DROP}
    assert _kinds(report, "deposit.deposit") == {SYNTH} and _kinds(report, "deposit") == {SYNTH}
    assert "namespace 'acme'" in _items(report, "", DROP)[0].message


def test_xmlrpc_says_nothing_of_its_own_document():
    call = Operation(key="add.add", name="add", kind=OperationKind.REQUEST_RESPONSE)
    api = _api(
        services=[Service(key="add", name="add", operations=[call])], paradigm=ApiParadigm.RPC, fmt="xmlrpc",
        identity=ApiIdentity(name="add"),
    )
    assert _report(api, "xmlrpc").is_lossless


# ---------------------------------------------------------------------------
# Protobuf / Connect RPC: identifiers, agents, paradigm
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target", ["protobuf", "connectrpc"])
def test_proto_reports_a_service_and_method_renamed_to_identifiers(target):
    agent = _agent("Travel Concierge")
    service = Service(
        key="Travel Concierge", name="Travel Concierge",
        operations=[Operation(key="Travel Concierge.find", name="Find flights", kind=OperationKind.REQUEST_RESPONSE)],
    )
    api = _api(services=[service], agents=[agent], paradigm=ApiParadigm.AGENT, fmt="a2a", title="Concierge")
    report = _report(api, target)
    assert DROP in _kinds(report, "Travel Concierge") and _kinds(report, "Travel_Concierge") == {SYNTH}
    assert _kinds(report, "Travel_Concierge.Find_flights") == {SYNTH}
    assert OK not in _kinds(report, "Travel Concierge.find")
    root = _items(report, "")
    assert any("this agent API" in i.message for i in root) and any("title 'Concierge'" in i.message for i in root)
    assert any(i.target_mapping == "agent → dropped" for i in report.items)


def test_proto_keeps_a_service_named_in_protobuf_terms():
    service = Service(key="acme.v1.Bank", name="Bank", operations=[_rpc("acme.v1.Bank", "Deposit")])
    api = _api(services=[service], paradigm=ApiParadigm.RPC, fmt="proto3")
    report = _report(api, "protobuf")
    assert not _items(report, "") and not _items(report, "acme.v1.Bank", DROP)
    assert not any(i.kind is DROP for i in _items(report, "acme.v1.Bank.Deposit"))


# ---------------------------------------------------------------------------
# ONC RPC: records are written, procedures are numbered, names are identifiers
# ---------------------------------------------------------------------------
def test_oncrpc_writes_a_record_of_another_format_and_numbers_procedures():
    request = Message(key="Bank API.open#request", role=MessageRole.REQUEST, payload=TypeRef(name="Account"))
    service = Service(
        key="Bank API", name="Bank API",
        operations=[
            Operation(key="Bank API.open", name="open", kind=OperationKind.REQUEST_RESPONSE, messages=[request]),
            Operation(key="Bank API.close", name="close account", kind=OperationKind.REQUEST_RESPONSE),
        ],
    )
    api = _api(_record("Account", _field("Account", "holder name")), services=[service], paradigm=ApiParadigm.RPC)
    text = _text(emit_canonical(api, "oncrpc"))
    assert "struct Account {" in text and "string holder_name;" in text
    assert "program Bank_API {" in text
    assert "void open(Account) = 1;" in text and "void close_account(void) = 2;" in text


def test_oncrpc_keeps_a_procedure_number_the_source_assigned():
    service = Service(
        key="P", name="P",
        operations=[
            _rpc("P", "a"),
            _rpc("P", "b", extras={"oncrpc_procedure_number": 1}),
        ],
    )
    text = _text(emit_canonical(_api(services=[service], paradigm=ApiParadigm.RPC), "oncrpc"))
    assert "void a(void) = 2;" in text and "void b(void) = 1;" in text


def test_oncrpc_reports_the_keys_a_reader_files_under_the_first_program():
    service = Service(key="acme.Bank", name="Bank", operations=[_rpc("acme.Bank", "open")])
    api = _api(
        _record("acme.Account"), Type(key="acme.Tags", name="Tags", kind=TypeKind.MAP),
        services=[service], paradigm=ApiParadigm.REST, fmt="wsdl", title="Banking",
    )
    report = _report(api, "oncrpc")
    assert _kinds(report, "acme.Account") == {DROP} and _kinds(report, "Bank.Account") == {SYNTH}
    assert _kinds(report, "Bank.Bank") == {SYNTH} and _kinds(report, "Bank.Bank.open") == {SYNTH}
    assert "map type 'acme.Tags' is not written" in _items(report, "acme.Tags", DROP)[0].message
    root = _items(report, "")
    assert any("this REST API" in i.message for i in root) and any("title 'Banking'" in i.message for i in root)


def test_oncrpc_files_a_program_less_document_under_the_default_namespace():
    report = _report(_api(_record("game.Monster"), fmt="flatbuffers"), "oncrpc")
    assert _kinds(report, "OncRpc.Monster") == {SYNTH}


# ---------------------------------------------------------------------------
# WIT, Avro, Kafka Connect
# ---------------------------------------------------------------------------
def test_wit_states_the_writers_document_losses_at_the_root():
    report = _report(_api(_record("UserAddress"), title="Users"), "wit")
    root = {i.target_mapping: i.kind for i in _items(report, "")}
    assert root["renamed-identifier"] is APPROX
    assert root["synthesized-package-name"] is SYNTH and root["synthesized-interface"] is SYNTH
    assert root["data_schema → rpc"] is APPROX


def test_wit_reports_nothing_for_a_source_it_refuses():
    assert not _items(_report(_api(paradigm=ApiParadigm.RPC, fmt="wit"), "wit"), "")


@pytest.mark.parametrize("target", ["avro", "kafka-connect"])
def test_a_named_schema_target_reports_the_qualified_name_and_the_envelope(target):
    api = _api(
        _record("orders"), fmt="odcs", version="2.3.0",
        identity=ApiIdentity(name="orders", id="0f6d", namespace="commerce"),
    )
    report = _report(api, target)
    assert DROP in _kinds(report, "orders") and _kinds(report, "commerce.orders") == {SYNTH}
    root = _items(report, "", DROP)[0].message
    assert "identifier '0f6d'" in root and "version '2.3.0'" in root


@pytest.mark.parametrize(("target", "fmt"), [("avro", "avro"), ("kafka-connect", "kafka-connect")])
def test_a_named_schema_target_says_nothing_of_its_own_envelope(target, fmt):
    api = _api(
        _record("commerce.orders", namespace="commerce"), fmt=fmt, version="1",
        identity=ApiIdentity(name="orders", id="0f6d", namespace="commerce"),
    )
    report = _report(api, target)
    assert not _items(report, "") and not _items(report, "commerce.orders", DROP)


# ---------------------------------------------------------------------------
# Azure API Management: the policy's backend is not a definition server
# ---------------------------------------------------------------------------
def test_azure_apim_keeps_the_backend_server_out_of_the_definition():
    operation = Operation(
        key="GET /orders", name="listOrders", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
        http_path="/orders",
        extras={"backend": {"uri": "https://orders.internal.example.com", "derivedFrom": "policy"}},
    )
    api = _api(
        services=[Service(key="default", name="default", operations=[operation])],
        paradigm=ApiParadigm.REST, fmt="azure-apim", version="1",
        servers=[
            Server(url="https://example.azure-api.net/orders"),
            Server(url="https://orders.internal.example.com", name="backend"),
        ],
    )
    result = emit_canonical(api, "azure-apim")
    definition = json.loads(next(f.content for f in result.files if f.path == "openapi.json"))
    assert [server["url"] for server in definition["servers"]] == ["https://example.azure-api.net/orders"]
    policy = next(f.content for f in result.files if f.path == "policy.xml")
    assert "https://orders.internal.example.com" in policy
