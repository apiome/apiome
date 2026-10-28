"""Emitter fixes the X1 export conformance matrix forced — #6222.

Pins, on small hand-built models, every crash class the matrix found:

* targets that write nothing for a source without HTTP operations / record types / callables
  declare it (``requires_source``) — the targets list marks them unavailable with the reason and
  the export refuses with 422 instead of a ``ValueError`` crash;
* GraphQL: invalid source names are rewritten (and the rename reported), empty records get a
  placeholder field, a union over non-object members becomes String, untyped refs become String;
* Avro: scalar spellings map to primitives, an undeclared reference becomes ``string``, a cycle
  across schema files is cut, textual defaults are coerced, a standalone union is qualified;
* ASN.1: aliases and scalars render (the old ``alias_of`` / ``scalar`` reads crashed);
* Kafka Connect: empty nested records become bytes, empty roots are skipped (all empty → refused),
  a repeated field name is renamed.
"""

from __future__ import annotations

import pytest
from graphql import build_schema

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
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
from app.emitter import EmitPreconditionError, get_emitter, load_builtin_emitters, source_requirement_reason
from app.export_routes import build_target_fidelity_entries
from app.export_service import ExportError, emit_canonical

load_builtin_emitters()


def _field(owner: str, name: str, ref: str | None = "string", **kwargs) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref), **kwargs)


def _record(key: str, *fields: CanonicalField, name: str | None = None) -> Type:
    return Type(key=key, name=name or key.rsplit(".", 1)[-1], kind=TypeKind.RECORD, fields=list(fields))


def _api(*types: Type, operations: list[Operation] | None = None, paradigm=ApiParadigm.DATA_SCHEMA) -> CanonicalApi:
    services = [Service(key="svc", name="svc", operations=operations)] if operations else []
    return CanonicalApi(
        paradigm=paradigm, format="json-schema", identity=ApiIdentity(name="t"), services=services, types=list(types)
    )


def _losses(result) -> list[str]:
    return [loss.subject for loss in result.losses]


# ---------------------------------------------------------------------------
# requires_source: refused with a reason, never a crash
# ---------------------------------------------------------------------------
TYPES_ONLY = _api(_record("Pet", _field("Pet", "name")))
NO_RECORDS = _api(Type(key="Code", name="Code", kind=TypeKind.SCALAR))


@pytest.mark.parametrize("target", ["kong", "gateway-api", "hoppscotch", "http-file", "aws-apigateway", "traefik"])
def test_an_http_target_refuses_a_source_without_http_operations(target):
    with pytest.raises(ExportError) as excinfo:
        emit_canonical(TYPES_ONLY, target)
    assert excinfo.value.status_code == 422
    assert "needs at least one HTTP operation" in str(excinfo.value)
    entry = next(e for e in build_target_fidelity_entries(TYPES_ONLY) if e.descriptor.key == target)
    assert entry.descriptor.available is False and "HTTP operation" in entry.descriptor.unavailable_reason


@pytest.mark.parametrize(("target", "phrase"), [("odcs", "record type"), ("kafka-connect", "record type")])
def test_a_data_contract_target_refuses_a_source_without_record_types(target, phrase):
    with pytest.raises(ExportError, match=phrase):
        emit_canonical(NO_RECORDS, target)


def test_the_llm_tool_array_needs_an_operation_or_a_record():
    assert source_requirement_reason("callable", NO_RECORDS, "LLM tools") is not None
    assert source_requirement_reason("callable", TYPES_ONLY, "LLM tools") is None


def test_an_unknown_requirement_is_a_programming_error():
    with pytest.raises(KeyError):
        source_requirement_reason("http-operations", TYPES_ONLY, "X")


def test_a_precondition_raised_mid_emit_is_a_refusal(monkeypatch):
    emitter_cls = get_emitter("openapi-3.1")

    def boom(self, api, *, opts=None):
        raise EmitPreconditionError("nothing to write")

    monkeypatch.setattr(emitter_cls, "emit", boom)
    with pytest.raises(ExportError, match="nothing to write") as excinfo:
        emit_canonical(TYPES_ONLY, "openapi")
    assert excinfo.value.status_code == 422


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------
def _queries(*type_keys: str) -> list[Operation]:
    """One query per type, returning it — the GraphQL SDL prints types reachable from the roots."""
    return [
        Operation(
            key=f"get{key}", name=f"get{key.replace('.', '_').replace('-', '_')}", kind=OperationKind.QUERY,
            messages=[Message(key=f"get{key}.res", role=MessageRole.RESPONSE, payload=TypeRef(name=key))],
        )
        for key in type_keys
    ]


def _graphql(api: CanonicalApi):
    result = emit_canonical(api, "graphql")
    sdl = result.files[0].content
    build_schema(sdl)  # parses: every name is valid
    return result, sdl


def test_graphql_rewrites_invalid_names_and_says_so():
    api = _api(
        _record(
            "com.example.Order",
            _field("com.example.Order", "order-id"),
            _field("com.example.Order", "s", "Status"),
            name="com.example.Order",
        ),
        Type(key="Status", name="Status", kind=TypeKind.ENUM,
             enum_values=[EnumValue(key="Status.in-flight", name="in-flight")]),
        operations=_queries("com.example.Order"),
    )
    result, sdl = _graphql(api)
    assert "com_example_Order" in sdl and "order_id" in sdl and "in_flight" in sdl
    assert {"renamed-type", "renamed-field", "renamed-enum value"} <= set(_losses(result))


def test_graphql_gives_an_empty_record_a_placeholder_field():
    result, sdl = _graphql(
        _api(_record("Empty"), _record("Pet", _field("Pet", "name")), operations=_queries("Empty", "Pet"))
    )
    assert "_empty: Boolean" in sdl
    assert "empty-record" in _losses(result)


def test_graphql_writes_a_union_of_non_objects_as_string():
    api = _api(
        Type(key="Choice", name="Choice", kind=TypeKind.UNION, union_members=["string", "int"]),
        _record("Holder", _field("Holder", "choice", "Choice")),
        operations=_queries("Holder"),
    )
    result, sdl = _graphql(api)
    assert "union" not in sdl
    assert "union-non-object-members" in _losses(result)


def test_graphql_writes_an_untyped_value_as_string():
    result, sdl = _graphql(_api(_record("Bag", _field("Bag", "anything", None)), operations=_queries("Bag")))
    assert "anything: String" in sdl
    assert "untyped-reference" in _losses(result)


# ---------------------------------------------------------------------------
# Avro
# ---------------------------------------------------------------------------
def _avro(api: CanonicalApi):
    result = emit_canonical(api, "avro")  # validates the bundle with fastavro
    return result, {f.path: f.content for f in result.files}


def test_avro_maps_scalar_spellings_and_cuts_undeclared_references():
    api = _api(
        _record("Row", _field("Row", "count", "uint64"), _field("Row", "flag", "Bool"), _field("Row", "x", "Mystery"))
    )
    result, files = _avro(api)
    fields = {f["name"]: f["type"] for f in files["Row.avsc"]["fields"]}
    assert "long" in str(fields["count"]) and "boolean" in str(fields["flag"])
    assert "string" in str(fields["x"])
    assert "dangling-type-reference" in _losses(result)


def test_avro_cuts_a_cycle_between_schema_files():
    api = _api(
        _record("Customer", _field("Customer", "orders", "Order")),
        _record("Order", _field("Order", "placedBy", "Customer")),
    )
    result, files = _avro(api)
    assert "Order" in str(files["Customer.avsc"]) or "Customer" in str(files["Order.avsc"])
    assert "cyclic-reference" in _losses(result)


def test_avro_coerces_a_textual_default():
    api = _api(_record("Monster", _field("Monster", "hp", "int", default="100")))
    _result, files = _avro(api)
    assert files["Monster.avsc"]["fields"][0]["default"] == 100


def test_avro_qualifies_a_standalone_union():
    entry = Type(key="KV.entry", name="entry", kind=TypeKind.RECORD, fields=[_field("KV.entry", "k")])
    union = Type(key="KV.res", name="res", kind=TypeKind.UNION, union_members=["KV.entry", "string"])
    _result, files = _avro(_api(entry, union))
    assert files["KV/res.avsc"][0] == "KV.entry"


# ---------------------------------------------------------------------------
# ASN.1 and Kafka Connect
# ---------------------------------------------------------------------------
def test_asn1_renders_aliases_and_scalars():
    api = _api(
        Type(key="Id", name="Id", kind=TypeKind.SCALAR),
        Type(key="Ids", name="Ids", kind=TypeKind.ALIAS, aliased=TypeRef(item=TypeRef(name="string"))),
        _record("Row", _field("Row", "id", "Id")),
    )
    text = emit_canonical(api, "asn1").files[0].content
    assert "Id ::= UTF8String" in text and "Ids ::= SEQUENCE OF UTF8String" in text


def test_kafka_connect_handles_empty_and_repeated_members():
    api = _api(
        _record("Holder", _field("Holder", "inner", "Empty"), _field("Holder", "v"), _field("Holder", "v")),
        _record("Empty"),
    )
    result = emit_canonical(api, "kafka-connect")
    holder = next(f.content for f in result.files if "Holder" in f.path)
    names = [f["field"] for f in holder["fields"]]
    assert names == ["inner", "v", "v_2"] or sorted(names) == ["inner", "v", "v_2"]
    inner = next(f for f in holder["fields"] if f["field"] == "inner")
    assert inner["type"] in ("bytes", ["null", "bytes"]) or inner.get("type") == "bytes"
    assert {"duplicate-field", "empty-struct"} <= set(_losses(result))


def test_kafka_connect_refuses_when_every_record_is_empty():
    with pytest.raises(ExportError, match="at least one field"):
        emit_canonical(_api(_record("A"), _record("B")), "kafka-connect")
