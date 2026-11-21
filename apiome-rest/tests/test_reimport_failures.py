"""Re-import failures — COA-3.3 (#7054).

RC7 §0.1 listed eight export targets whose output often did not import back: WADL, ASN.1, AsyncAPI,
Postman, ONC RPC, Protobuf, Connect RPC and CORBA IDL. Each one now either writes a file its own
importer reads, or refuses the source up front with a reason. This module pins every fix on small
hand-built models:

* **AsyncAPI** wrote another format's metadata (a Postman ``sample_count``, a gateway's
  ``backends``) as AsyncAPI fields, ``$ref``\\s to scalar names that have no component (``bool``,
  ``int32``), component keys AsyncAPI does not allow (a WSDL ``http://…`` namespace), and a
  ``required`` / ``enum`` list with repeated items; the parser wrapper overflowed its stack on a
  recursive schema.
* **Protobuf / Connect RPC** wrote source names (``CUSTOMER-RECORD``, ``FIX.4.4``) as packages,
  references to names the file does not declare (``.decimal``, an alias, a scalar rpc payload),
  field number ``0``, repeated field names, a service named like a message, and enum values that
  share a number without ``allow_alias``.
* **ONC RPC** wrote canonical scalar names (``integer age;``), and its importer did not recognise
  a file of structs only.
* **ASN.1 and WADL** wrote an empty module for a source with nothing they can hold; they refuse it.
* **Postman and CORBA IDL** already re-import every file they write: Postman refuses a source with
  no HTTP operation, and those cells are deliberate refusals now.
"""

from __future__ import annotations

import json
from typing import Any, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import EmitPreconditionError, SchemaEmitter, load_builtin_emitters
from app.export_service import emit_canonical, resolve_emitter
from app.field_identity_store import FieldNumberAllocator
from app.import_source import get_import_source, load_builtin_import_sources
from app.oncrpc_parser import is_oncrpc, is_xdr_types_only
from app.roundtrip_matrix import reimport_emitted
from app.toolchain_runner import is_tool_available

load_builtin_emitters()
load_builtin_import_sources()


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------
def _field(owner: str, name: str, ref: str = "string", **kwargs: Any) -> CanonicalField:
    """A record field ``<owner>.<name>`` of type ``ref``."""
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref), **kwargs)


def _record(key: str, *fields: CanonicalField, name: str | None = None) -> Type:
    """A record type; its name defaults to the last key segment."""
    return Type(
        key=key,
        name=name or key.rsplit(".", 1)[-1],
        kind=TypeKind.RECORD,
        fields=list(fields) or [_field(key, "id")],
    )


def _rpc(service: str, name: str, *, request: str | None = None, response: str | None = None) -> Operation:
    """A request/response operation whose messages carry the named payloads."""
    messages: List[Message] = []
    if request:
        messages.append(Message(key=f"{service}.{name}#req", role=MessageRole.REQUEST, payload=TypeRef(name=request)))
    if response:
        messages.append(Message(key=f"{service}.{name}#res", role=MessageRole.RESPONSE, payload=TypeRef(name=response)))
    return Operation(key=f"{service}.{name}", name=name, kind=OperationKind.REQUEST_RESPONSE, messages=messages)


def _api(*types: Type, services: List[Service] | None = None, fmt: str = "json-schema", **kwargs: Any) -> CanonicalApi:
    """A canonical model of ``types`` and ``services`` imported as ``fmt``."""
    return CanonicalApi(
        paradigm=kwargs.pop("paradigm", ApiParadigm.DATA_SCHEMA),
        format=fmt,
        identity=kwargs.pop("identity", ApiIdentity(name="Orders")),
        services=services or [],
        types=list(types),
        **kwargs,
    )


def _text(result) -> str:
    """The first emitted file as text."""
    content = result.files[0].content
    return content if isinstance(content, str) else json.dumps(content)


def _all_text(result) -> str:
    """Every emitted file, joined."""
    return "\n".join(f.content if isinstance(f.content, str) else json.dumps(f.content) for f in result.files)


def _loss_subjects(result) -> List[str]:
    """The subjects of the emit losses."""
    return [loss.subject for loss in result.losses]


def _refs(node: Any) -> List[str]:
    """Every ``$ref`` value in a JSON document."""
    found: List[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            found.append(node["$ref"])
        for value in node.values():
            found.extend(_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_refs(item))
    return found


def _rest_api(**op_extras: Any) -> CanonicalApi:
    """A small REST model (as if imported from Postman) with one ``GET /orders`` operation."""
    operation = Operation(
        key="GET /orders", name="listOrders", kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET", http_path="/orders", extras=dict(op_extras),
        messages=[Message(key="GET /orders#200", role=MessageRole.RESPONSE, status_code="200",
                          payload=TypeRef(name="Order"))],
    )
    service = Service(key="Orders", name="Orders", operations=[operation])
    return _api(_record("Order", _field("Order", "id")), services=[service], fmt="postman", paradigm=ApiParadigm.REST)


# ---------------------------------------------------------------------------
# AsyncAPI
# ---------------------------------------------------------------------------
def test_asyncapi_writes_only_the_extensions_of_another_formats_metadata():
    document = emit_canonical(_rest_api(sample_count=3, backends=["a"], **{"x-team": "orders"}), "asyncapi").files[0].content
    operation = next(iter(document["operations"].values()))
    assert operation["x-team"] == "orders"
    assert "sample_count" not in operation and "backends" not in operation


def test_asyncapi_writes_back_the_fields_of_an_asyncapi_source():
    operation = Operation(
        key="orders.created", name="onOrderCreated", kind=OperationKind.PUBLISH,
        extras={"bindings": {"kafka": {"groupId": "g"}}, "summary": "Order created"},
    )
    api = _api(services=[Service(key="orders", name="orders", operations=[operation])],
               fmt="asyncapi-3", paradigm=ApiParadigm.EVENT)
    written = next(iter(emit_canonical(api, "asyncapi").files[0].content["operations"].values()))
    assert written["bindings"] == {"kafka": {"groupId": "g"}} and written["summary"] == "Order created"


def test_asyncapi_writes_a_scalar_name_inline_instead_of_a_missing_component():
    api = _api(_record("Order", _field("Order", "qty", "int32"), _field("Order", "paid", "bool"),
                       _field("Order", "blob", "Mystery")))
    result = emit_canonical(api, "asyncapi")
    document = result.files[0].content
    props = document["components"]["schemas"]["Order"]["properties"]
    assert props["qty"] == {"type": "integer", "format": "int32"}
    assert props["paid"] == {"type": "boolean"}
    assert props["blob"] == {}
    assert "unknown-type" in _loss_subjects(result)
    assert all(ref.split("/")[-1] in document["components"]["schemas"] for ref in _refs(document)
               if ref.startswith("#/components/schemas/"))


def test_asyncapi_renames_a_component_key_it_does_not_allow_and_follows_every_reference():
    order = _record("http://example.com/orders.Order", _field("http://example.com/orders.Order", "line",
                                                               "http://example.com/orders.Line"))
    line = _record("http://example.com/orders.Line")
    document = emit_canonical(_api(order, line, fmt="wsdl"), "asyncapi").files[0].content
    schemas = document["components"]["schemas"]
    assert set(schemas) == {"http___example.com_orders.Order", "http___example.com_orders.Line"}
    assert schemas["http___example.com_orders.Order"]["properties"]["line"] == {
        "$ref": "#/components/schemas/http___example.com_orders.Line"
    }


def test_component_renames_are_unique_and_leave_safe_keys_alone():
    from app.asyncapi_emitter import AsyncApiEmitter

    renames = AsyncApiEmitter.component_renames({"a b", "a_b", "Order", "a:b"})
    assert "Order" not in renames and "a_b" not in renames
    assert sorted(renames.values()) == ["a_b_2", "a_b_3"]


def test_a_name_repeated_across_fields_is_required_once():
    owner = "pain.PmtInf"
    member = CanonicalField(key=f"{owner}.CdtTrfTxInf", name="CdtTrfTxInf", type=TypeRef(name="string", nullable=False))
    record = _record(owner, member, member, member)
    schema = SchemaEmitter().named_schema(record)
    assert schema["required"] == ["CdtTrfTxInf"]


def test_enum_values_that_repeat_are_written_once():
    enum = Type(key="Status", name="Status", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="A", name="A", value=1), EnumValue(key="B", name="B", value=1), EnumValue(key="C", name="C", value=True),
        EnumValue(key="D", name="D", value=2),
    ])
    assert SchemaEmitter().named_schema(enum)["enum"] == [1, True, 2]


def _asyncapi_parser_available() -> bool:
    return is_tool_available("asyncapi-parser")


@pytest.mark.skipif(not _asyncapi_parser_available(), reason="asyncapi-parser unavailable in this runtime")
def test_asyncapi_export_of_a_recursive_type_imports_back():
    node = _record("Node", _field("Node", "name"), _field("Node", "child", "Node"))
    operation = Operation(
        key="tree.updated", name="onTreeUpdated", kind=OperationKind.PUBLISH, channel_ref="tree",
        messages=[Message(key="tree.updated#event", role=MessageRole.EVENT, payload=TypeRef(name="Node"))],
    )
    from app.canonical_model import Channel

    api = _api(node, services=[Service(key="tree", name="tree", operations=[operation])],
               channels=[Channel(key="tree", name="tree", address="tree")], fmt="json-schema",
               paradigm=ApiParadigm.EVENT)
    result = emit_canonical(api, "asyncapi")
    model = reimport_emitted(get_import_source("asyncapi"), result, multi_file=False)
    assert model.format == "asyncapi-3"


# ---------------------------------------------------------------------------
# Protobuf / Connect RPC
# ---------------------------------------------------------------------------
def test_proto_writes_a_legal_package_and_names_its_declarations_the_same_way():
    owner = "CUSTOMER-RECORD.CUSTOMER-RECORD"
    name_type = _record("CUSTOMER-RECORD.CUST-NAME", _field("CUSTOMER-RECORD.CUST-NAME", "FIRST"))
    record = _record(owner, _field(owner, "CUST_NAME", "CUSTOMER-RECORD.CUST-NAME"))
    text = _text(emit_canonical(_api(name_type, record, fmt="cobolcopybook"), "protobuf"))
    assert "package CUSTOMER_RECORD;" in text
    assert "message CUST_NAME {" in text
    assert ".CUSTOMER_RECORD.CUST_NAME CUST_NAME = 1;" in text


def test_proto_writes_a_numeric_package_segment_as_an_identifier():
    text = _text(emit_canonical(_api(_record("FIX.4.4.Order")), "protobuf"))
    assert "package FIX._4._4;" in text


def test_proto_qualifies_a_type_whose_name_is_not_its_last_key_segment():
    address = _record("ims.CUSTDB.ADDRESS", name="CUSTDB.ADDRESS")
    customer = _record("ims.CUSTDB.CUSTOMER", _field("ims.CUSTDB.CUSTOMER", "address", "ims.CUSTDB.ADDRESS"),
                       name="CUSTDB.CUSTOMER")
    text = _text(emit_canonical(_api(address, customer, fmt="ims"), "protobuf"))
    assert "message CUSTDB_ADDRESS {" in text
    assert ".ims.CUSTDB.CUSTDB_ADDRESS address = 1;" in text


def test_proto_writes_an_alias_as_the_type_it_aliases():
    alias = Type(key="DICOM.CS", name="CS", kind=TypeKind.ALIAS, aliased=TypeRef(name="string"))
    record = _record("DICOM.Study", _field("DICOM.Study", "modality", "DICOM.CS"))
    text = _text(emit_canonical(_api(alias, record, fmt="dicom"), "protobuf"))
    assert "string modality = 1;" in text and ".DICOM.CS" not in text


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("decimal", "string balance = 1;"),
        ("timestamp", ".google.protobuf.Timestamp balance = 1;"),
        ("date", "string balance = 1;"),
        ("any", ".google.protobuf.Value balance = 1;"),
        ("GetUserResponse200", ".google.protobuf.Value balance = 1;"),
    ],
)
def test_proto_writes_a_name_with_no_declaration_as_the_closest_proto_type(ref, expected):
    result = emit_canonical(_api(_record("Account", _field("Account", "balance", ref))), "protobuf")
    text = _all_text(result)
    assert expected in text and f".{ref} " not in text
    assert "unmapped-type" in _loss_subjects(result)
    if "google.protobuf." in expected:
        assert 'import "google/protobuf/' in text


def test_proto_wraps_a_scalar_or_enum_rpc_payload_in_a_message():
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key="OK", name="OK", value=0)])
    service = Service(key="Directory", name="Directory",
                      operations=[_rpc("Directory", "lookup", request="uint32", response="Status")])
    result = emit_canonical(_api(status, services=[service], fmt="capnproto"), "protobuf")
    text = _all_text(result)
    assert "rpc lookup (.google.protobuf.UInt32Value) returns (.google.protobuf.Value);" in text
    assert 'import "google/protobuf/wrappers.proto";' in text
    assert _loss_subjects(result).count("wrapped-rpc-type") == 2


def test_proto_renumbers_a_field_number_protobuf_does_not_allow():
    owner = "Person"
    record = _record(owner, _field(owner, "id", field_number=0), _field(owner, "name", field_number=1),
                     _field(owner, "x", field_number=19500))
    result = emit_canonical(_api(record, fmt="capnproto"), "protobuf")
    text = _text(result)
    assert "string name = 1;" in text and "= 0;" not in text and "19500" not in text
    assert _loss_subjects(result).count("renumbered-field") == 2


def test_proto_suffixes_a_field_name_its_message_already_has():
    owner = "PmtInf"
    record = _record(owner, _field(owner, "order_id"), _field(owner, "order_id"), _field(owner, "orderId"))
    result = emit_canonical(_api(record, fmt="iso20022"), "protobuf")
    text = _text(result)
    assert "string order_id = 1;" in text and "string order_id_2 = 2;" in text and "string orderId_3 = 3;" in text
    assert _loss_subjects(result).count("renamed-field") == 2


def test_proto_renames_a_service_that_shares_a_messages_name():
    service = Service(key="Patient", name="Patient", operations=[_rpc("Patient", "read", response="Patient")])
    result = emit_canonical(_api(_record("Patient"), services=[service], fmt="fhir"), "protobuf")
    text = _all_text(result)
    assert "service PatientService {" in text and "message Patient {" in text
    assert "renamed-service" in _loss_subjects(result)


def test_proto_renames_a_service_that_shares_a_sub_packages_name():
    service = Service(key="examples.calculate", name="calculate",
                      operations=[_rpc("examples.calculate", "eval", request="examples.calculate.request")])
    request = _record("examples.calculate.request")
    text = _all_text(emit_canonical(_api(request, services=[service], fmt="wit"), "protobuf"))
    assert "service calculateService {" in text


def test_proto_allows_aliases_for_enum_values_that_share_a_number():
    enum = Type(key="Constants", name="Constants", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="UNKNOWN", name="UNKNOWN", value=0), EnumValue(key="CHARGING", name="CHARGING", value=1), EnumValue(key="GOOD", name="GOOD", value=1),
    ])
    assert "option allow_alias = true;" in _text(emit_canonical(_api(enum, fmt="ros2"), "protobuf"))


def test_proto_imports_the_default_package_file_into_a_named_package_service():
    service = Service(key="api.example.Users", name="Users",
                      operations=[_rpc("api.example.Users", "get", response="User")])
    result = emit_canonical(_api(_record("User"), services=[service], fmt="har"), "protobuf")
    service_file = next(f.content for f in result.files if "service Users" in f.content)
    assert 'import "api.proto";' in service_file


def test_field_number_allocator_treats_an_illegal_source_number_as_missing():
    owner = "T"
    record = _record(owner, _field(owner, "a", field_number=0), _field(owner, "b", field_number=1))
    counter = FieldNumberAllocator(record, legal=lambda n: n >= 1)
    assert counter.allocate(record.fields[0]) == (2, True)
    assert counter.allocate(record.fields[1]) == (1, False)
    # Without the predicate every source number is kept (Thrift).
    assert FieldNumberAllocator(record).allocate(record.fields[0]) == (0, False)


def _buf_available() -> bool:
    from app.proto_descriptor import BUF_TOOL_KEY

    return is_tool_available(BUF_TOOL_KEY)


@pytest.mark.skipif(not _buf_available(), reason="buf toolchain unavailable in this runtime")
@pytest.mark.parametrize("target", ["protobuf", "connectrpc"])
def test_proto_export_of_another_formats_names_compiles_and_imports_back(target):
    owner = "CUSTOMER-RECORD.CUSTOMER-RECORD"
    record = _record(owner, _field(owner, "balance", "decimal"), _field(owner, "id", field_number=0),
                     _field(owner, "id"), _field(owner, "created", "timestamp"))
    service = Service(key="CUSTOMER-RECORD.CUSTOMER-RECORD", name="CUSTOMER-RECORD",
                      operations=[_rpc("CUSTOMER-RECORD.CUSTOMER-RECORD", "lookup", request="uint32",
                                       response=owner)])
    api = _api(record, services=[service], fmt="cobolcopybook")
    result = emit_canonical(api, target)
    adapter = get_import_source("protobuf" if target == "protobuf" else "connectrpc")
    model = reimport_emitted(adapter, result, multi_file=len(result.files) > 1)
    assert any(t.name == "CUSTOMER_RECORD" for t in model.types)


# ---------------------------------------------------------------------------
# ONC RPC
# ---------------------------------------------------------------------------
def test_oncrpc_writes_another_formats_scalars_as_xdr_types():
    owner = "UserProfile"
    record = _record(owner, _field(owner, "age", "integer"),
                     _field(owner, "visits", "integer", constraints=Constraints(format="int64")),
                     _field(owner, "active", "boolean"), _field(owner, "balance", "decimal"))
    result = emit_canonical(_api(record, fmt="openapi"), "oncrpc")
    text = _text(result)
    assert "int age;" in text and "hyper visits;" in text and "bool active;" in text
    assert "double balance;" in text and "integer" not in text
    assert "unmapped-type" in _loss_subjects(result)


def test_a_file_of_xdr_structs_only_is_onc_rpc():
    text = "/* generated */\nstruct UserProfile {\n    int age;\n    string email;\n};\n"
    assert is_xdr_types_only(text) and is_oncrpc(text)


@pytest.mark.parametrize(
    "text",
    [
        "module M {\n  struct S { long a; };\n};\n",  # OMG IDL
        "#include <stdint.h>\nstruct S { int a; };\n",  # C
        "struct S @0xabc { a @0 :Int32; }\n",  # Cap'n Proto
        "struct S {\n  1: i32 a\n}\n",  # Thrift
        "",
    ],
)
def test_other_c_family_files_are_not_types_only_xdr(text):
    assert not is_xdr_types_only(text)


def test_oncrpc_export_of_a_data_schema_imports_back():
    owner = "UserProfile"
    record = _record(owner, _field(owner, "age", "integer"), _field(owner, "email"))
    result = emit_canonical(_api(record, fmt="openapi"), "oncrpc")
    model = reimport_emitted(get_import_source("oncrpc"), result, multi_file=False)
    assert [t.name for t in model.types] == ["UserProfile"]


# ---------------------------------------------------------------------------
# ASN.1 and WADL refuse a source with nothing they can hold
# ---------------------------------------------------------------------------
def _operations_only() -> CanonicalApi:
    """An agent-style model: one non-HTTP operation and no types."""
    service = Service(key="Concierge", name="Concierge", operations=[_rpc("Concierge", "search")])
    return _api(services=[service], fmt="a2a", paradigm=ApiParadigm.AGENT)


@pytest.mark.parametrize(
    "target, phrase",
    [("asn1", "ASN.1 export needs at least one type"),
     ("wadl", "WADL export needs at least one HTTP operation or one type")],
)
def test_asn1_and_wadl_refuse_a_source_with_nothing_to_write(target, phrase):
    with pytest.raises(EmitPreconditionError, match=phrase):
        resolve_emitter(target).emit(_operations_only())


def test_asn1_and_wadl_say_why_in_the_targets_list():
    from app.asn1_emitter import Asn1Emitter
    from app.wadl_emitter import WadlEmitter

    assert Asn1Emitter.source_unsupported_reason(_operations_only())
    assert WadlEmitter.source_unsupported_reason(_operations_only())
    assert Asn1Emitter.source_unsupported_reason(_api(_record("Order"))) is None
    assert WadlEmitter.source_unsupported_reason(_api(_record("Order"))) is None


def test_asn1_and_wadl_exports_of_a_type_import_back():
    api = _api(_record("Order", _field("Order", "id")))
    for target in ("asn1", "wadl"):
        result = emit_canonical(api, target)
        model = reimport_emitted(get_import_source(target), result, multi_file=len(result.files) > 1)
        assert any(t.name.endswith("Order") for t in model.types), target
