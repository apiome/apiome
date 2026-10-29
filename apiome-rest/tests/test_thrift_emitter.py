"""Apache Thrift IDL emitter — MFX-25.1 (#4151).

Covers what makes an export compile under the Thrift compiler:

* identifiers: type, field, method, service and enum-member names made valid, unique and
  non-reserved (renames reported);
* types: struct / enum / union (a member-list union gets one optional field per member) /
  exception / typedef (aliases and named scalars) / list / set / map, optional vs required;
* services: ``1: T arg``, a synthesized ``<Method>Request`` struct for parameters, success-response
  return types, ``throws`` holding exceptions only, ``oneway``, ``extends``;
* namespaces per language (option), a Thrift source's typedefs written back, ``uuid`` → ``string``;
* emitted-output validation: the Thrift compiler when present, else the Thrift reader;
* the acceptance check: corpus exports (typed and service-bearing sources) compile with ``thrift``
  where the toolchain has it, and every Thrift corpus file round-trips unchanged.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List

import pytest

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
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult
from app.export_validation import validate_emitted_artifact
from app.import_source import canonical_diff
from app.roundtrip_matrix import reimport_emitted
from app.thrift_compile import ThriftCompileError, compile_thrift_idl, thrift_available
from app.thrift_emitter import ThriftEmitOptions, ThriftEmitter, thrift_identifier
from app.thrift_import_source import ThriftImportSource

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

needs_thrift = pytest.mark.skipif(not thrift_available(), reason="the thrift compiler is not available here")


def _field(owner: str, name: str, ref: str = "string", *, number=None, nullable=True) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref, nullable=nullable),
                          field_number=number)


def _api(*, types: List[Type] = (), services: List[Service] = (), **kw) -> CanonicalApi:
    defaults = dict(paradigm=ApiParadigm.RPC, format="openapi-3.1", identity=ApiIdentity(name="Shop"), title="Shop",
                    types=list(types), services=list(services))
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return ThriftEmitter().emit(api, opts=ThriftEmitOptions(**opts) if opts else None)


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


# ===========================================================================
# Identifiers
# ===========================================================================


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Order", "Order"), ("com.acme.Order", "com_acme_Order"), ("order-id", "order_id"), ("1st", "_1st"),
     ("class", "class_"), ("default", "default_"), ("string", "string_"), ("", "_")],
)
def test_thrift_identifier(name: str, expected: str) -> None:
    assert thrift_identifier(name) == expected


def test_names_are_made_valid_unique_and_reported() -> None:
    types = [
        Type(key="com.acme.Order", name="com.acme.Order", kind=TypeKind.RECORD,
             fields=[_field("O", "order-id", number=1), _field("O", "order_id", number=2),
                     _field("O", "end", number=3)]),
        Type(key="Holder", name="Holder", kind=TypeKind.RECORD, fields=[_field("H", "o", "com.acme.Order", number=1)]),
    ]
    result = _emit(_api(types=types))
    text = _text(result)
    assert "struct com_acme_Order {" in text
    assert "1: optional string order_id," in text and "2: optional string order_id2," in text
    assert "3: optional string end_," in text
    assert "1: optional com_acme_Order o," in text
    assert {"renamed-type", "renamed-field"} <= _subjects(result)


# ===========================================================================
# Types
# ===========================================================================


def test_struct_enum_union_typedef_and_containers() -> None:
    types = [
        Type(key="Status", name="Status", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="Status.open", name="open", value=1), EnumValue(key="Status.in-flight", name="in-flight",
                                                                          value="in-flight")]),
        Type(key="Cat", name="Cat", kind=TypeKind.RECORD, fields=[_field("Cat", "name", number=1, nullable=False)]),
        Type(key="Dog", name="Dog", kind=TypeKind.RECORD, fields=[_field("Dog", "bark", "bool", number=1)]),
        Type(key="Pet", name="Pet", kind=TypeKind.UNION, union_members=["Cat", "Dog"]),
        Type(key="PetId", name="PetId", kind=TypeKind.ALIAS, aliased=TypeRef(name="i64")),
        Type(key="Instant", name="Instant", kind=TypeKind.SCALAR),
        Type(key="Labels", name="Labels", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
             value_type=TypeRef(item=TypeRef(name="i32"))),
        Type(key="Shelter", name="Shelter", kind=TypeKind.RECORD, fields=[
            CanonicalField(key="Shelter.pets", name="pets", type=TypeRef(item=TypeRef(name="Pet")), field_number=1),
            CanonicalField(key="Shelter.labels", name="labels", type=TypeRef(name="Labels"), field_number=2),
            CanonicalField(key="Shelter.id", name="id", type=TypeRef(name="uuid", nullable=False), field_number=3),
        ]),
    ]
    result = _emit(_api(types=types))
    text = _text(result)
    for expected in ("enum Status {\n  open = 1,\n  in_flight,\n}",
                     "union Pet {\n  1: optional Cat cat,\n  2: optional Dog dog,\n}",
                     "typedef i64 PetId", "typedef string Instant",
                     "struct Cat {\n  1: required string name,\n}",
                     "1: optional list<Pet> pets,", "2: optional map<string, list<i32>> labels,",
                     "3: required string id,"):
        assert expected in text, expected
    assert {"enum-values-dropped", "union-member-fields", "custom-scalar", "uuid-as-string"} <= _subjects(result)


# ===========================================================================
# Services
# ===========================================================================


def _rest_api() -> CanonicalApi:
    pet = Type(key="Pet", name="Pet", kind=TypeKind.RECORD, fields=[_field("Pet", "id", "i64", number=1)])
    problem = Type(key="Problem", name="Problem", kind=TypeKind.RECORD, fields=[_field("Problem", "detail", number=1)])
    get_pet = Operation(
        key="GET /pets/{id}", name="get-pet", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
        http_path="/pets/{id}",
        parameters=[Parameter(key="p", name="id", location=ParameterLocation.PATH, type=TypeRef(name="i64"),
                              required=True)],
        messages=[
            Message(key="r404", role=MessageRole.RESPONSE, status_code="404", payload=TypeRef(name="Problem")),
            Message(key="r200", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="Pet")),
            Message(key="e", role=MessageRole.ERROR, name="notFound", payload=TypeRef(name="Problem")),
        ],
    )
    add_pet = Operation(key="POST /pets", name="addPet", kind=OperationKind.REQUEST_RESPONSE,
                        messages=[Message(key="q", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"))])
    again = Operation(key="POST /pets2", name="addPet", kind=OperationKind.REQUEST_RESPONSE)
    return _api(types=[pet, problem], services=[Service(key="default", name="default",
                                                        operations=[get_pet, add_pet, again])])


def test_methods_parameters_returns_and_unique_names() -> None:
    text = _text(_emit(_rest_api()))
    assert "service default_ {" in text
    assert "struct Get_petRequest {\n  1: required i64 id,\n}" in text
    assert "Pet get_pet(1: Get_petRequest request)" in text  # the 200 response, not the 404
    assert "void addPet(1: Pet arg)," in text and "void addPet2()," in text


def test_throws_holds_exceptions_only() -> None:
    result = _emit(_rest_api())
    text = _text(result)
    # Problem is also a 404 *response* type, so it stays a struct and the throw is dropped and reported.
    assert "struct Problem" in text and "throws" not in text
    assert "throws-dropped" in _subjects(result)


def test_a_record_only_ever_thrown_becomes_an_exception() -> None:
    api = _rest_api()
    op = api.services[0].operations[0]
    op.messages = [m for m in op.messages if m.key != "r404"]
    result = _emit(api)
    assert "exception Problem {" in _text(result)
    assert "throws (1: Problem notFound)" in _text(result)
    assert "struct-as-exception" in _subjects(result)


def test_namespaces_per_language() -> None:
    text = _text(_emit(_api(types=[Type(key="T", name="T", kind=TypeKind.RECORD)]),
                       namespaces={"java": "com.acme.shop", "py": "acme-shop", "*": "acme"}))
    assert "namespace * acme" in text and "namespace java com.acme.shop" in text and "namespace py acme_shop" in text


# ===========================================================================
# Thrift sources and validation
# ===========================================================================

_THRIFT_CORPUS = sorted((_EXAMPLES / "thrift").glob("*.thrift"))


@pytest.mark.parametrize("path", _THRIFT_CORPUS, ids=lambda p: p.name)
def test_thrift_corpus_round_trips(path: Path) -> None:
    api = _corpus_api(path, "thrift")
    result = _emit(api)
    assert canonical_diff(api, reimport_emitted(ThriftImportSource(), result, multi_file=False)).entries == []


def test_a_thrift_source_writes_its_typedefs_back() -> None:
    source = 'typedef i64 UserId\nstruct User {\n  1: required UserId id,\n}\n'
    api = build_conversion_source({"id": "x", "name": "u", "source_format": "thrift",
                                   "format_metadata": {"sourceContent": source}}).api
    text = _text(_emit(api))
    # The typedef is declared (it used to be dropped); the reader resolves the field to its base type.
    assert "typedef i64 UserId" in text and "1: required i64 id" in text


async def test_validation_falls_back_to_the_reader_without_the_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.thrift_compile.thrift_available", lambda: False)
    api = _rest_api()
    verdict = await validate_emitted_artifact("thrift", _emit(api), api=api)
    assert verdict.validated and verdict.valid


async def test_compiler_errors_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.thrift_compile.thrift_available", lambda: True)

    async def reject(path, content, **kw):
        raise ThriftCompileError("bad", diagnostics=["[ERROR:Shop.thrift:3] Type \"X\" has not been defined"])

    monkeypatch.setattr("app.thrift_compile.compile_thrift_idl", reject)
    api = _rest_api()
    verdict = await validate_emitted_artifact("thrift", _emit(api), api=api)
    assert verdict.failed and "has not been defined" in verdict.findings[0].message


def test_an_unsafe_path_is_refused() -> None:
    with pytest.raises(ThriftCompileError):
        asyncio.run(compile_thrift_idl("../evil.thrift", "struct A {}"))


# ===========================================================================
# Acceptance: compiles under the Thrift compiler
# ===========================================================================

_COMPILE_CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("openapi/22-advanced-oneof-polymorphism.yaml", "openapi"),
    ("openapi/23-advanced-anyof-flexible.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    ("raml/01-simple-api.raml", "raml"),
    ("avro/01-user-event.avsc", "avro"),
    ("json-schema/02-product-types.json", "json-schema"),
    *[(f"thrift/{p.name}", "thrift") for p in _THRIFT_CORPUS if "include" not in p.read_text(encoding="utf-8")],
]


@needs_thrift
@pytest.mark.parametrize(("path", "fmt"), _COMPILE_CORPUS, ids=lambda v: str(v))
def test_corpus_export_compiles(path: str, fmt: str) -> None:
    api = _corpus_api(_EXAMPLES / path, fmt)
    emitted = _emit(api).files[0]
    asyncio.run(compile_thrift_idl(emitted.path, emitted.content))


@needs_thrift
def test_the_hand_built_models_compile() -> None:
    for api in (_rest_api(),):
        emitted = _emit(api).files[0]
        asyncio.run(compile_thrift_idl(emitted.path, emitted.content))
