"""OMG IDL 4.2 emitter (CORBA / DDS) — MFX-28.1 (#4168).

Covers what makes an export parse under a reference IDL compiler:

* identifiers: valid, unique case-insensitively in their scope, unlike their enclosing scope, no
  keyword in any case; enumerators unique in the module (renames reported);
* types: struct / discriminated union (fields or member types; ``void`` arms) / enum / typedef
  (aliases, named scalars) / map (entry struct + sequence) / sequence, ``@optional``, empty
  placeholders, declare-before-use ordering, recursion (forward declaration, bounded self reference,
  dropped mutual recursion), fully scoped references;
* interfaces: ``in`` parameters and body, success-response return, ``raises`` of exceptions only
  (a record only ever returned as an error becomes one), typedef'd sequences in signatures;
* modules from the namespace (and the ``module`` option), a CORBA source written back as declared;
* the DDS profile: no interfaces or exceptions, ``@key`` on identifier fields (or the ``key_fields``
  option), no recursion, no wide characters, refusal when there is no data type;
* the acceptance check: corpus exports (typed and interface-bearing sources) and the hand-built
  models parse under omniidl and Cyclone DDS ``idlc`` where installed, and re-read with the CORBA
  IDL reader.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from omg_idl_reference import IDLC, OMNIIDL, check_with_reference_compilers

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.corbaidl_emitter import CorbaIdlEmitOptions, CorbaIdlEmitter, idl_identifier
from app.corbaidl_import_source import CorbaIdlImportSource
from app.corbaidl_parser import parse_corbaidl
from app.emitter import EmitPreconditionError, EmitResult
from app.import_source import canonical_diff
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

needs_compiler = pytest.mark.skipif(
    not (OMNIIDL or IDLC), reason="no reference IDL compiler (omniidl / idlc) is installed here"
)


def _field(owner: str, name: str, ref: str = "string", *, nullable: bool = False, item: str = None) -> CanonicalField:
    type_ref = TypeRef(name=item, item=TypeRef(name=item), nullable=nullable) if item else TypeRef(
        name=ref, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=type_ref)


def _record(name: str, *fields: CanonicalField, key: str = None) -> Type:
    return Type(key=key or name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*, types: List[Type] = (), services: List[Service] = (), **kw) -> CanonicalApi:
    defaults = dict(paradigm=ApiParadigm.RPC, format="openapi-3.1", identity=ApiIdentity(name="Shop"), title="Shop",
                    types=list(types), services=list(services))
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return CorbaIdlEmitter().emit(api, opts=CorbaIdlEmitOptions(**opts) if opts else None)


def _text(result: EmitResult) -> str:
    return result.files[0].content


def _subjects(result: EmitResult) -> set:
    return {loss.subject for loss in result.losses}


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _rest_api() -> CanonicalApi:
    """A REST-shaped model: parameters, a body, list responses, an error-only record, a nullable field."""
    pet = _record("Pet", _field("Pet", "id", "i64"), _field("Pet", "name"), _field("Pet", "tag", nullable=True),
                  _field("Pet", "pet", "string"))
    error = _record("Error", _field("Error", "code", "i32"), _field("Error", "message"))
    list_pets = Operation(
        key="GET /pets", name="listPets", kind=OperationKind.REQUEST_RESPONSE, http_method="GET", http_path="/pets",
        parameters=[Parameter(key="GET /pets#query.limit", name="limit", location=ParameterLocation.QUERY,
                              type=TypeRef(name="integer"))],
        messages=[
            Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200",
                    payload=TypeRef(name="Pet", item=TypeRef(name="Pet"))),
            Message(key="GET /pets#default", role=MessageRole.ERROR, status_code="default",
                    payload=TypeRef(name="Error")),
        ],
    )
    create_pet = Operation(
        key="POST /pets", name="createPet", kind=OperationKind.REQUEST_RESPONSE, http_method="POST",
        http_path="/pets",
        messages=[
            Message(key="POST /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet")),
            Message(key="POST /pets#201", role=MessageRole.RESPONSE, status_code="201", payload=TypeRef(name="Pet")),
            Message(key="POST /pets#400", role=MessageRole.ERROR, status_code="400", payload=TypeRef(name="string")),
        ],
    )
    return _api(types=[pet, error], services=[Service(key="pets", name="Pets", operations=[list_pets, create_pet])],
                identity=ApiIdentity(name="Pet Store", namespace="com.acme.store"))


# ===========================================================================
# Identifiers
# ===========================================================================


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Order", "Order"), ("com.acme.Order", "com_acme_Order"), ("order-id", "order_id"), ("1st", "n1st"),
     ("_private", "private_"), ("module", "module_"), ("Module", "Module_"), ("STRING", "STRING_"),
     ("Finder", "Finder"), ("", "x")],
)
def test_idl_identifier(name: str, expected: str) -> None:
    assert idl_identifier(name) == expected


def test_names_are_unique_case_insensitively_and_reported() -> None:
    order = _record("Order", _field("Order", "abc"), _field("Order", "ABC"), _field("Order", "order"),
                    _field("Order", "interface"))
    clash = _record("order", _field("order", "x"), key="v2.order")
    result = _emit(_api(types=[order, clash]))
    text = _text(result)
    assert "struct Order {" in text and "struct order2 {" in text
    # Members: unique ignoring case, never named like the struct, never a keyword.
    assert "string abc;" in text and "string ABC2;" in text and "string order2;" in text
    assert "string interface_;" in text
    assert {"renamed-type", "renamed-field"} <= _subjects(result)


def test_enumerators_are_unique_in_the_module() -> None:
    first = Type(key="A", name="A", kind=TypeKind.ENUM,
                 enum_values=[EnumValue(key="A.ACTIVE", name="ACTIVE"), EnumValue(key="A.in-progress",
                                                                                  name="in-progress")])
    second = Type(key="B", name="B", kind=TypeKind.ENUM, enum_values=[EnumValue(key="B.ACTIVE", name="ACTIVE")])
    result = _emit(_api(types=[first, second]))
    text = _text(result)
    assert "enum A {\n    ACTIVE,\n    in_progress\n  };" in text
    assert "enum B {\n    B_ACTIVE\n  };" in text
    assert "renamed-enumerator" in _subjects(result)


# ===========================================================================
# Types
# ===========================================================================


def test_struct_optional_sequences_and_scoped_references() -> None:
    customer = _record("Customer", _field("Customer", "name"))
    order = _record("Order", _field("Order", "customer", "Customer"), _field("Order", "note", nullable=True),
                    _field("Order", "tags", item="string"), _field("Order", "total", "number"),
                    _field("Order", "count", "integer"), _field("Order", "big", "int64"),
                    _field("Order", "blob", "bytes"), _field("Order", "nested", item="Customer"))
    text = _text(_emit(_api(types=[order, customer], identity=ApiIdentity(name="Shop", namespace="com.acme"))))
    assert "module com {\n  module acme {" in text
    # Declared before use, although Order comes first; the member named like its type is scoped.
    assert text.index("struct Customer") < text.index("struct Order")
    assert "::com::acme::Customer customer;" in text
    assert "@optional string note;" in text
    assert "sequence<string> tags;" in text and "sequence<::com::acme::Customer> nested;" in text
    assert "double total;" in text and "long count;" in text and "long long big;" in text
    assert "sequence<octet> blob;" in text


def test_union_of_fields_is_discriminated_with_a_kind_enum() -> None:
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION,
                 fields=[_field("Shape", "circle", "double"), _field("Shape", "square", "double"),
                         _field("Shape", "none", "void")])
    text = _text(_emit(_api(types=[shape])))
    assert "enum ShapeKind {\n    Shape_circle,\n    Shape_square,\n    Shape_none\n  };" in text
    assert "union Shape switch (::Shop::ShapeKind) {" in text
    assert "case ::Shop::Shape_circle: double circle;" in text
    # A void arm selects no member.
    assert "Shape_none:" not in text


def test_union_of_member_types() -> None:
    cat = _record("Cat", _field("Cat", "lives", "i32"))
    dog = _record("Dog", _field("Dog", "breed"))
    pet = Type(key="Pet", name="Pet", kind=TypeKind.UNION, union_members=["Cat", "Dog"])
    result = _emit(_api(types=[pet, cat, dog]))
    text = _text(result)
    assert "case ::Shop::Pet_cat: ::Shop::Cat cat;" in text and "case ::Shop::Pet_dog: ::Shop::Dog dog;" in text
    assert text.index("struct Cat") < text.index("union Pet")
    assert "union-member-cases" in _subjects(result)


def test_aliases_scalars_and_maps() -> None:
    alias = Type(key="Ids", name="Ids", kind=TypeKind.ALIAS, aliased=TypeRef(name="i64", item=TypeRef(name="i64")))
    scalar = Type(key="Money", name="Money", kind=TypeKind.SCALAR)
    labels = Type(key="Labels", name="Labels", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                  value_type=TypeRef(name="i32"))
    holder = _record("Holder", _field("Holder", "labels", "Labels"), _field("Holder", "ids", "Ids"))
    result = _emit(_api(types=[holder, alias, scalar, labels]))
    text = _text(result)
    assert "typedef sequence<long long> Ids;" in text
    assert "typedef string Money;" in text
    assert "struct LabelsEntry {\n    string key;\n    long value;\n  };" in text
    assert "typedef sequence<::Shop::LabelsEntry> Labels;" in text
    assert {"map-as-sequence", "custom-scalar"} <= _subjects(result)


def test_empty_struct_and_union_get_placeholders() -> None:
    empty = _record("Empty")
    nothing = Type(key="Nothing", name="Nothing", kind=TypeKind.UNION)
    result = _emit(_api(types=[empty, nothing]))
    text = _text(result)
    assert "struct Empty {\n    octet reserved;\n  };" in text
    assert "struct Nothing {\n    octet reserved;\n  };" in text
    assert {"empty-struct-placeholder", "empty-union-placeholder"} <= _subjects(result)


def test_recursion_corba_profile() -> None:
    node = _record("Node", _field("Node", "children", item="Node"), _field("Node", "parent", "Node"))
    a = _record("A", _field("A", "b", "B"))
    b = _record("B", _field("B", "as", item="A"))
    result = _emit(_api(types=[node, a, b]))
    text = _text(result)
    # Self recursion: forward-declared; through a sequence as is, directly as a bounded sequence.
    assert "struct Node;" in text
    assert "sequence<::Shop::Node> children;" in text and "sequence<::Shop::Node, 1> parent;" in text
    # Mutual recursion cannot be declared in IDL: B's member back to A is dropped.
    assert "struct B {\n    octet reserved;\n  };" in text
    assert {"recursive-member-bounded", "recursive-member-dropped"} <= _subjects(result)


def test_free_form_and_unknown_types_are_strings() -> None:
    record = _record("R", _field("R", "meta", "object"), _field("R", "when", "date-time"),
                     _field("R", "odd", "Undeclared"))
    result = _emit(_api(types=[record]))
    text = _text(result)
    assert "string meta;" in text and "string when;" in text and "string odd;" in text
    assert {"free-form-as-string", "unknown-type"} <= _subjects(result)


# ===========================================================================
# Interfaces
# ===========================================================================


def test_interface_operations_parameters_and_raises() -> None:
    result = _emit(_rest_api())
    text = _text(result)
    assert "module com {\n  module acme {\n    module store {" in text
    assert "exception Error {" in text and "struct-as-exception" in _subjects(result)
    # A list response is a typedef'd sequence; parameters and the body are `in` arguments.
    assert "typedef sequence<::com::acme::store::Pet> PetSeq;" in text
    assert ("::com::acme::store::PetSeq listPets(in long limit) raises (::com::acme::store::Error);" in text)
    assert "::com::acme::store::Pet createPet(in ::com::acme::store::Pet body);" in text
    # A string error is not an exception: reported, not raised.
    assert "raises-dropped" in _subjects(result)
    # A member named like its type ("pet" in Pet) is renamed: it may not repeat its enclosing scope.
    assert "string pet2;" in text


def test_operation_names_are_unique_and_events_dropped() -> None:
    ops = [Operation(key="get", name="get", kind=OperationKind.REQUEST_RESPONSE),
           Operation(key="Get", name="Get", kind=OperationKind.REQUEST_RESPONSE),
           Operation(key="tick", name="tick", kind=OperationKind.PUBLISH),
           Operation(key="feed", name="feed", kind=OperationKind.REQUEST_RESPONSE, streaming="server")]
    result = _emit(_api(services=[Service(key="Svc", name="Svc", operations=ops)]))
    text = _text(result)
    assert "void get();" in text and "void Get2();" in text and "tick" not in text
    assert {"renamed-operation", "event-operation-dropped", "streaming-dropped"} <= _subjects(result)


def test_module_option_and_channels() -> None:
    api = _api(types=[_record("A", _field("A", "x"))], channels=[Channel(key="c", address="c")])
    result = _emit(api, module="acme::orders")
    assert _text(result).count("module ") == 2 and "module orders {" in _text(result)
    assert "channels-dropped" in _subjects(result)


def test_nothing_to_declare_is_refused() -> None:
    with pytest.raises(EmitPreconditionError):
        _emit(_api())


# ===========================================================================
# DDS profile
# ===========================================================================


def test_dds_profile_keys_and_no_interfaces() -> None:
    result = _emit(_rest_api(), profile="dds")
    text = _text(result)
    assert "interface" not in text and "exception" not in text
    assert "struct Error {" in text
    assert "@key long long id;" in text and "@optional string tag;" in text
    assert "interface-dropped" in _subjects(result)
    assert "// Generated OMG IDL 4.2 (DDS profile) for Pet Store" in text


def test_dds_key_fields_option() -> None:
    order = _record("Order", _field("Order", "region"), _field("Order", "number", "i32"), _field("Order", "id"))
    result = _emit(_api(types=[order]), profile="dds", key_fields={"Order": ["region", "number", "missing"]})
    text = _text(result)
    assert "@key string region;" in text and "@key long number;" in text and "  string id;" in text
    assert "key-field-missing" in _subjects(result)


def test_dds_profile_writes_no_recursion() -> None:
    node = _record("Node", _field("Node", "id"), _field("Node", "children", item="Node"))
    result = _emit(_api(types=[node]), profile="dds")
    text = _text(result)
    assert "children" not in text and "struct Node;" not in text
    assert "recursive-member-dropped" in _subjects(result)


def test_dds_profile_refuses_a_source_without_data_types() -> None:
    service = Service(key="S", name="S", operations=[Operation(key="op", name="op",
                                                               kind=OperationKind.REQUEST_RESPONSE)])
    with pytest.raises(EmitPreconditionError, match="DDS profile"):
        _emit(_api(services=[service]), profile="dds")


# ===========================================================================
# CORBA sources
# ===========================================================================

_CORBA_CORPUS = sorted((_EXAMPLES / "corba-idl").glob("*.idl"))


@pytest.mark.parametrize("path", _CORBA_CORPUS, ids=lambda p: p.name)
def test_corba_corpus_round_trips(path: Path) -> None:
    api = _corpus_api(path, "corbaidl")
    result = _emit(api)
    diff = canonical_diff(api, reimport_emitted(CorbaIdlImportSource(), result, multi_file=False)).entries
    if path.name == "03-minimal-echo.idl":
        # The fixture names an operation like its interface (`Echo.echo`), which IDL refuses.
        assert "renamed-operation" in _subjects(result)
        assert {entry.key for entry in diff} == {"Ping.Echo.echo", "Ping.Echo.echo2"}
    else:
        assert diff == []


def test_a_corba_source_is_written_as_declared() -> None:
    text = _text(_emit(_corpus_api(_EXAMPLES / "corba-idl" / "01-bank.idl", "corbaidl")))
    assert "module Banking {" in text and "typedef string AccountId;" in text
    assert text.index("enum AccountKind") < text.index("struct Account {")
    assert ("double withdraw(in string id, in double amount) raises (::Banking::AccountNotFound, "
            "::Banking::InsufficientFunds);") in text


def test_nested_sequences_close_with_a_space() -> None:
    text = _text(_emit(_corpus_api(_EXAMPLES / "corba-idl" / "05-trading-stress.idl", "corbaidl")))
    assert "typedef sequence<sequence<double> > Matrix;" in text
    dds = _emit(_corpus_api(_EXAMPLES / "corba-idl" / "05-trading-stress.idl", "corbaidl"), profile="dds")
    assert "wstring" not in _text(dds) and "wide-character-narrowed" in _subjects(dds)


def test_the_reader_reads_annotations_scoped_names_and_wide_integers() -> None:
    doc = parse_corbaidl(
        "module A { module B {\n  struct T { @key long long id; @optional ::A::B::U u; unsigned long n; "
        "sequence<::A::B::U, 1> one; };\n  struct U { long x; };\n}; };\n"
    )
    fields = {field.name: field.type_expr for field in doc.structs[0].fields}
    assert fields == {"id": "long long", "u": "U", "n": "unsigned long", "one": "sequence<U, 1>"}


# ===========================================================================
# Acceptance: parses under a reference IDL compiler
# ===========================================================================

_COMPILE_CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("openapi/22-advanced-oneof-polymorphism.yaml", "openapi"),
    ("openapi/07-nullable-types.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    ("avro/01-user-record.avsc", "avro"),
    ("json-schema/02-product-types.json", "json-schema"),
    ("thrift/01-user-service.thrift", "thrift"),
    ("onc-rpc/01-key-value-store.x", "oncrpc"),
    *[(f"corba-idl/{p.name}", "corbaidl") for p in _CORBA_CORPUS],
]


@pytest.mark.parametrize("profile", ["corba", "dds"])
@pytest.mark.parametrize(("path", "fmt"), _COMPILE_CORPUS, ids=lambda v: str(v))
def test_corpus_export_parses(path: str, fmt: str, profile: str) -> None:
    api = _corpus_api(_EXAMPLES / path, fmt)
    try:
        text = _text(_emit(api, profile=profile))
    except EmitPreconditionError:
        assert profile == "dds" and not api.types
        return
    parse_corbaidl(text)
    if OMNIIDL or IDLC:
        check_with_reference_compilers(text, profile=profile)


@needs_compiler
@pytest.mark.parametrize("profile", ["corba", "dds"])
def test_the_hand_built_models_compile(profile: str) -> None:
    node = _record("Node", _field("Node", "id"), _field("Node", "children", item="Node"),
                   _field("Node", "parent", "Node"))
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION,
                 fields=[_field("Shape", "circle", "double"), _field("Shape", "label", "string")])
    labels = Type(key="Labels", name="Labels", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                  value_type=TypeRef(name="Shape"))
    keyword = _record("Module", _field("Module", "module"), _field("Module", "Shape", "Shape"))
    models = [
        _rest_api(),
        _api(types=[node, shape, labels, keyword, _record("Empty")]),
    ]
    for api in models:
        check_with_reference_compilers(_text(_emit(api, profile=profile)), profile=profile)


def test_a_type_named_like_its_module_renames_the_module() -> None:
    result = _emit(_api(types=[_record("Product", _field("Product", "sku"))], identity=ApiIdentity(name="Product")))
    text = _text(result)
    assert "module ProductModule {" in text and "struct Product {" in text
    assert "renamed-module" in _subjects(result)
