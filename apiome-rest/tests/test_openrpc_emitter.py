"""OpenRPC emitter — MFX-33.1 (#4301).

Covers, in order:

* the document: ``openrpc`` version, ``info`` (a synthesized version is reported), servers and variables;
* RPC methods: params (an OpenRPC source's list, else one ``params`` descriptor), ``paramStructure``,
  ``result``, ``errors``, tags, ``deprecated``; one-way operations as notifications (no ``result``);
  method names unique across services;
* REST sources reframed: parameters and body as by-name params, the success response as the result
  (``null`` without a body), statuses as error codes, ``x-http``, all reported;
* schemas: components through the canonical JSON-Schema mapping, ``$ref``\\ s naming written components,
  canonical scalars resolved, repeated fields reported;
* what is not carried and reported, by the writer and by :class:`OpenRpcFidelityRulePack`;
* the OpenRPC reader additions the round trip relies on (notifications, errors, tags, ``deprecated``);
* emitted-output validation against the vendored OpenRPC meta-schema;
* acceptance: every OpenRPC corpus file round-trips unchanged; corpus exports from other formats are
  valid OpenRPC.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import (
    AgentDescriptor,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, LossKind
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.openrpc_emitter import OpenRpcEmitter, meta_schema_errors, validate_openrpc_document
from app.openrpc_import_source import OpenRpcImportSource
from app.openrpc_normalizer import OpenRpcNormalizer
from app.openrpc_parser import parse_openrpc
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _field(owner: str, name: str, ref: str = "string", **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref, nullable=kw.pop("nullable", True)),
                          **kw)


def _record(name: str, *fields: CanonicalField, key: str = None) -> Type:
    return Type(key=key or name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*, types=(), operations=(), services=None, paradigm=ApiParadigm.RPC, **kw) -> CanonicalApi:
    if services is None:
        services = [Service(key="Wallet", name="Wallet", operations=list(operations))] if operations else []
    defaults = dict(paradigm=paradigm, format="protobuf", identity=ApiIdentity(name="Wallet"), title="Wallet",
                    version="1.0.0", types=list(types), services=services)
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _op(key: str, **kw) -> Operation:
    return Operation(key=key, name=kw.pop("name", key.split(".")[-1]),
                     kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE), **kw)


def _msg(key: str, role: MessageRole, payload: str = None, **kw) -> Message:
    return Message(key=key, role=role, payload=TypeRef(name=payload) if payload else None, **kw)


def _emit(api: CanonicalApi) -> EmitResult:
    return OpenRpcEmitter().emit(api)


def _doc(api: CanonicalApi) -> Dict[str, Any]:
    return json.loads(_emit(api).files[0].content)


def _method(api: CanonicalApi, name: str) -> Dict[str, Any]:
    return next(m for m in _doc(api)["methods"] if m["name"] == name)


def _subjects(result: EmitResult) -> List[tuple]:
    return sorted((loss.subject, loss.pointer) for loss in result.losses)


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _rest_api() -> CanonicalApi:
    pet = _record("Pet", _field("Pet", "id", "i64", nullable=False), _field("Pet", "name"))
    error = _record("Error", _field("Error", "message"))
    get = _op("GET /pets/{id}", name="getPet", http_method="GET", http_path="/pets/{id}", parameters=[
        Parameter(key="GET /pets/{id}#path.id", name="id", location=ParameterLocation.PATH, type=TypeRef(name="i64"),
                  required=True),
        Parameter(key="GET /pets/{id}#query.fields", name="fields", location=ParameterLocation.QUERY,
                  type=TypeRef(name="string"), description="Sparse fields.", constraints=Constraints(min_length=1.0)),
        Parameter(key="GET /pets/{id}#header.X-Trace", name="X-Trace", location=ParameterLocation.HEADER,
                  type=TypeRef(name="string"), deprecated=True),
    ], messages=[
        _msg("GET /pets/{id}#200", MessageRole.RESPONSE, "Pet", status_code="200", description="The pet."),
        _msg("GET /pets/{id}#404", MessageRole.ERROR, "Error", status_code="404"),
        _msg("GET /pets/{id}#default", MessageRole.ERROR, "Error", status_code="default"),
    ])
    delete = _op("DELETE /pets/{id}", name="deletePet", http_method="DELETE", http_path="/pets/{id}", parameters=[
        Parameter(key="DELETE /pets/{id}#path.id", name="id", location=ParameterLocation.PATH,
                  type=TypeRef(name="i64"), required=True)],
        messages=[_msg("DELETE /pets/{id}#204", MessageRole.RESPONSE, status_code="204")])
    create = _op("POST /pets", name="createPet", http_method="POST", http_path="/pets", messages=[
        _msg("POST /pets#request", MessageRole.REQUEST, "Pet", required=True),
        _msg("POST /pets#201", MessageRole.RESPONSE, "Pet", status_code="201"),
        _msg("POST /pets#202", MessageRole.RESPONSE, "Pet", status_code="202"),
    ])
    return _api(types=[pet, error], operations=[get, delete, create], paradigm=ApiParadigm.REST, format="openapi-3.1")


# ===========================================================================
# The document
# ===========================================================================


def test_the_document_envelope() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], description="Wallets.",
               servers=[Server(url="https://{region}.rpc.example.com", name="regional", description="Regional.",
                               variables=[ServerVariable(name="region", enum=["eu", "us"], description="Region.")])])
    doc = _doc(api)
    assert doc["openrpc"] == "1.3.2"
    assert doc["info"] == {"title": "Wallet", "version": "1.0.0", "description": "Wallets."}
    assert doc["servers"] == [{"url": "https://{region}.rpc.example.com", "name": "regional",
                               "description": "Regional.",
                               "variables": {"region": {"default": "eu", "enum": ["eu", "us"],
                                                        "description": "Region."}}}]
    assert doc["methods"] == []


def test_a_missing_version_is_synthesized_and_reported() -> None:
    result = _emit(_api(types=[_record("Pet", _field("Pet", "id"))], version=None))
    assert json.loads(result.files[0].content)["info"]["version"] == "0.0.0"
    assert ("version-synthesized", None) in _subjects(result)


def test_an_openrpc_source_keeps_its_version_and_nothing_to_write_is_refused() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], format="openrpc", extras={"openrpc_version": "1.2.6"})
    assert _doc(api)["openrpc"] == "1.2.6"
    with pytest.raises(EmitPreconditionError):
        _emit(_api())


# ===========================================================================
# RPC methods
# ===========================================================================


def test_rpc_methods_params_result_errors_tags_and_deprecation() -> None:
    op = _op("Wallet.Transfer", name="Transfer", description="Move funds.", tags=["funds"], deprecated=True,
             messages=[_msg("Wallet.Transfer#request", MessageRole.REQUEST, "TransferRequest", required=True),
                       _msg("Wallet.Transfer#response", MessageRole.RESPONSE, "Receipt", name="receipt"),
                       _msg("Wallet.Transfer#error.-32001", MessageRole.ERROR, status_code="-32001",
                            description="Insufficient funds.")])
    api = _api(types=[_record("TransferRequest", _field("TransferRequest", "amount", "i64")),
                      _record("Receipt", _field("Receipt", "id"))], operations=[op])
    assert _method(api, "Transfer") == {
        "name": "Transfer",
        "description": "Move funds.",
        "tags": [{"name": "funds"}],
        "params": [{"name": "params", "schema": {"$ref": "#/components/schemas/TransferRequest"}, "required": True}],
        "result": {"name": "receipt", "schema": {"$ref": "#/components/schemas/Receipt"}},
        "errors": [{"code": -32001, "message": "Insufficient funds."}],
        "deprecated": True,
    }


def test_one_way_operations_are_notifications() -> None:
    api = _api(operations=[_op("Wallet.Ping", name="Ping", kind=OperationKind.ONE_WAY)])
    method = _method(api, "Ping")
    assert method == {"name": "Ping", "params": []}
    report = {item.construct_key: item for item in compute_lossiness_for_emitter(api, OpenRpcEmitter()).items}
    assert report["Wallet.Ping"].target_mapping == "notification Ping"


def test_method_names_are_unique_across_services() -> None:
    services = [Service(key="A", name="A", operations=[_op("A.Get", name="Get")]),
                Service(key="B", name="B", operations=[_op("B.Get", name="Get")])]
    result = _emit(_api(services=services))
    assert [m["name"] for m in json.loads(result.files[0].content)["methods"]] == ["Get", "B.Get"]
    assert ("renamed-method", "B.Get") in _subjects(result)


def test_events_streams_and_extra_responses_are_reported() -> None:
    ops = [_op("Wallet.onTx", name="onTx", kind=OperationKind.SUBSCRIBE),
           _op("Wallet.Watch", name="Watch", streaming=StreamingMode.SERVER),
           _op("Wallet.Sub", name="Sub", kind=OperationKind.SUBSCRIPTION),
           _op("Wallet.Fire", name="Fire", kind=OperationKind.ONE_WAY,
               messages=[_msg("Wallet.Fire#response", MessageRole.RESPONSE, "string")])]
    result = _emit(_api(operations=ops))
    assert [m["name"] for m in json.loads(result.files[0].content)["methods"]] == ["onTx", "Watch", "Sub", "Fire"]
    assert {("event-as-notification", "Wallet.onTx"), ("streaming-dropped", "Wallet.Watch"),
            ("streaming-dropped", "Wallet.Sub"), ("response-dropped", "Wallet.Fire")} <= set(_subjects(result))


# ===========================================================================
# REST sources are reframed
# ===========================================================================


def test_rest_operations_are_reframed_as_by_name_methods() -> None:
    result = _emit(_rest_api())
    methods = {m["name"]: m for m in json.loads(result.files[0].content)["methods"]}
    get = methods["getPet"]
    assert get["paramStructure"] == "by-name"
    assert get["params"] == [
        {"name": "id", "schema": {"type": "integer", "format": "int64"}, "required": True,
         "description": "(path parameter)"},
        {"name": "fields", "schema": {"type": "string", "minLength": 1},
         "description": "Sparse fields. (query parameter)"},
        {"name": "X-Trace", "schema": {"type": "string"}, "description": "(header parameter)", "deprecated": True},
    ]
    assert get["result"] == {"name": "result", "schema": {"$ref": "#/components/schemas/Pet"},
                             "description": "The pet."}
    assert get["errors"] == [{"code": 404, "message": "Not Found"}]
    assert get["x-http"] == {"method": "GET", "path": "/pets/{id}"}
    assert methods["deletePet"]["result"] == {"name": "result", "schema": {"type": "null"}}
    assert methods["createPet"]["params"] == [
        {"name": "body", "schema": {"$ref": "#/components/schemas/Pet"}, "required": True}]
    found = set(_subjects(result))
    assert {("http-binding-dropped", "GET /pets/{id}"), ("error-dropped", "GET /pets/{id}"),
            ("error-payload-dropped", "GET /pets/{id}"), ("response-dropped", "POST /pets")} <= found


def test_the_rest_reframing_is_in_the_fidelity_report() -> None:
    report = compute_lossiness_for_emitter(_rest_api(), OpenRpcEmitter())
    root = {item.target_mapping: item for item in report.items if item.construct_key == ""}
    assert root["rest → JSON-RPC"].kind is LossinessKind.APPROX
    get = {item.target_mapping: item for item in report.items if item.construct_key == "GET /pets/{id}"}
    assert get["http-binding-dropped"].kind is LossinessKind.DROP and "x-http" in get["http-binding-dropped"].message
    assert get["error-dropped"].kind is LossinessKind.DROP


# ===========================================================================
# Schemas
# ===========================================================================


def test_components_refs_and_scalars() -> None:
    pet = _record("Pet", _field("Pet", "id", "i64", nullable=False), _field("Pet", "born", "timestamp"),
                  _field("Pet", "owner", "example.Owner"), _field("Pet", "odd", "Snowflake"),
                  key="example.Pet")
    owner = _record("Owner", _field("Owner", "name"), key="example.Owner")
    weird = _record("my type/1", _field("my type/1", "x"))
    result = _emit(_api(types=[pet, owner, weird]))
    schemas = json.loads(result.files[0].content)["components"]["schemas"]
    assert set(schemas) == {"Pet", "Owner", "my_type_1"}
    props = schemas["Pet"]["properties"]
    assert props["id"] == {"type": "integer", "format": "int64"}
    assert props["born"] == {"type": "string", "format": "date-time"}
    assert props["owner"] == {"$ref": "#/components/schemas/Owner"}
    assert props["odd"] == {}
    found = set(_subjects(result))
    assert ("unknown-type", "example.Pet") in found and ("renamed-component", "my type/1") in found


def test_repeated_fields_keep_one_entry_and_are_reported() -> None:
    doubled = _record("Batch", _field("Batch", "item", nullable=False), _field("Batch", "item", nullable=False))
    result = _emit(_api(types=[doubled]))
    schema = json.loads(result.files[0].content)["components"]["schemas"]["Batch"]
    assert schema["required"] == ["item"]
    assert ("duplicate-field-dropped", "Batch") in _subjects(result)


def test_every_writer_loss_is_predicted_and_agents_are_dropped() -> None:
    api = _rest_api().model_copy(update={"agents": [AgentDescriptor(key="a", name="a", protocol="a2a")]})
    report = compute_lossiness_for_emitter(api, OpenRpcEmitter())
    predicted = {(item.target_mapping, item.kind) for item in report.items}
    for loss in _emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else LossinessKind.APPROX
        assert (loss.subject, kind) in predicted, loss
    assert ("agents → dropped", LossinessKind.DROP) in predicted


# ===========================================================================
# The OpenRPC reader additions
# ===========================================================================

_READER_SAMPLE = json.dumps({
    "openrpc": "1.3.2",
    "info": {"title": "T", "version": "1"},
    "methods": [
        {"name": "emit", "params": [], "tags": [{"name": "ingest"}, {"$ref": "#/components/tags/admin"}],
         "deprecated": True},
        {"name": "get", "params": [], "result": {"name": "r", "schema": {"type": "string"}},
         "errors": [{"code": 404, "message": "Missing", "data": {"hint": "x"}},
                    {"$ref": "#/components/errors/Busy"}, {"message": "no code"}]},
    ],
    "components": {"errors": {"Busy": {"code": -32001, "message": "Busy"}}},
})


def test_the_reader_reads_notifications_errors_tags_and_deprecation() -> None:
    doc = parse_openrpc(_READER_SAMPLE)
    emit, get = doc.methods
    assert (emit.notification, emit.tags, emit.deprecated) == (True, ("ingest", "admin"), True)
    assert get.notification is False
    assert [(e.code, e.message, e.data) for e in get.errors] == [
        (404, "Missing", {"hint": "x"}), (-32001, "Busy", None)]
    api = OpenRpcNormalizer().normalize(doc)
    ops = {op.name: op for op in api.operations()}
    assert ops["emit"].kind is OperationKind.ONE_WAY and ops["emit"].tags == ["ingest", "admin"]
    errors = [m for m in ops["get"].messages if m.role is MessageRole.ERROR]
    assert [(m.status_code, m.description, m.extras) for m in errors] == [
        ("-32001", "Busy", {}), ("404", "Missing", {"openrpc_error_data": {"hint": "x"}})]


def test_errors_with_data_round_trip() -> None:
    api = OpenRpcNormalizer().normalize(parse_openrpc(_READER_SAMPLE))
    result = _emit(api)
    method = next(m for m in json.loads(result.files[0].content)["methods"] if m["name"] == "get")
    assert sorted(method["errors"], key=lambda e: e["code"]) == [
        {"code": -32001, "message": "Busy"}, {"code": 404, "message": "Missing", "data": {"hint": "x"}}]
    assert canonical_diff(api, reimport_emitted(OpenRpcImportSource(), result, multi_file=False)).entries == []


# ===========================================================================
# Validation
# ===========================================================================


def test_the_meta_schema_rejects_a_broken_document() -> None:
    errors = meta_schema_errors({"openrpc": "9.9", "info": {"title": "x"}, "methods": [{"name": "m"}]})
    assert errors[0] == "info: 'version' is a required property"
    assert errors[1] == "methods/0: {'name': 'm'} is not valid under any of the given schemas"
    assert errors[2].startswith("openrpc: '9.9' is not one of")
    with pytest.raises(ValueError, match="meta-schema"):
        validate_openrpc_document(json.dumps({"openrpc": "1.3.2", "info": {"title": "x"}, "methods": []}))


async def test_emitted_output_validation_passes_and_rejects() -> None:
    api = _rest_api()
    verdict = await validate_emitted_artifact("openrpc", _emit(api), api=api)
    assert (verdict.applicable, verdict.validated, verdict.valid) == (True, True, True)
    result = _emit(api)
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": '{"openrpc": 1}'})]})
    verdict = await validate_emitted_artifact("openrpc", broken, api=api)
    assert verdict.failed and "meta-schema" in verdict.findings[0].message


# ===========================================================================
# Acceptance: OpenRPC round trips; other formats export to valid OpenRPC
# ===========================================================================

_OPENRPC_CORPUS = sorted((_EXAMPLES / "openrpc").glob("*.json"))


@pytest.mark.parametrize("path", _OPENRPC_CORPUS, ids=lambda p: p.name)
def test_openrpc_corpus_round_trips(path: Path) -> None:
    api = _corpus_api(path, "openrpc")
    result = _emit(api)
    validate_openrpc_document(result.files[0].content)
    assert result.losses == []
    assert canonical_diff(api, reimport_emitted(OpenRpcImportSource(), result, multi_file=False)).entries == []


_OTHER_CORPUS = [
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("thrift/01-user-service.thrift", "thrift"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("avro/01-user-record.avsc", "avro"),
    ("json-schema/02-product-types.json", "json-schema"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    ("smithy/01-weather-service.smithy", "smithy"),
    ("typespec/05-grammar-corners.tsp", "typespec"),
]


@pytest.mark.parametrize(("path", "fmt"), _OTHER_CORPUS, ids=lambda v: str(v))
def test_corpus_exports_are_valid_openrpc(path: str, fmt: str) -> None:
    validate_openrpc_document(_emit(_corpus_api(_EXAMPLES / path, fmt)).files[0].content)
