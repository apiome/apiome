"""Smithy emitter — MFX-20.1 (#3914).

Covers the model the emitter builds (one JSON AST, rendered as IDL too) and what makes it validate:

* shapes: structure / union (fields or member types) / enum (values) / list (named and synthesized) /
  map (string keys) / simple shapes for named scalars, an alias of a named shape inlined;
* traits: ``@required`` from nullability, ``@default``, constraint traits on the shapes they apply to
  (``@length`` / ``@range`` / ``@pattern``, ``@uniqueItems`` on an ``<Element>Set``), doc comments,
  ``@deprecated``, ``@jsonName`` for a renamed member (never two members on one wire name);
* names: Smithy identifiers unique ignoring case, never a prelude shape; a trait shadowed by a shape
  of the model written fully qualified; a cycle of required members broken;
* operations: a structure payload as input / output, else a synthesized ``<Operation>Input`` /
  ``Output``; HTTP binding traits (``@http``, ``@httpLabel`` / ``@httpQuery`` / ``@httpHeader`` /
  ``@httpPayload``, ``@readonly`` / ``@idempotent``), GET bodies and transport headers dropped, bad or
  duplicate routes unbound; error-only records as ``@error`` / ``@httpError`` structures;
* options: ``output`` (IDL, JSON AST, both), ``protocol`` (service protocol trait);
* the IDL reader fixes the round trip needs (member traits holding ``:`` / ``)``, enum values, doc
  comments on the right shape), and Smithy corpus round trips;
* the acceptance check: corpus exports and the hand-built models validate under ``smithy validate``
  where the CLI is installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
from smithy_reference import SMITHY, check_with_smithy

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
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult
from app.import_source import canonical_diff
from app.roundtrip_matrix import reimport_emitted
from app.smithy_emitter import SmithyEmitOptions, SmithyEmitter, smithy_identifier
from app.smithy_import_source import SmithyImportSource
from app.smithy_parser import parse_smithy

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

needs_smithy = pytest.mark.skipif(SMITHY is None, reason="the Smithy CLI is not installed here")


def _field(owner: str, name: str, ref: str = "string", *, nullable: bool = True, item: str = None,
           constraints: Constraints = None, default=None, description: str = None) -> CanonicalField:
    type_ref = TypeRef(name=item, item=TypeRef(name=item), nullable=nullable) if item else TypeRef(
        name=ref, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=type_ref, constraints=constraints, default=default,
                          description=description)


def _record(name: str, *fields: CanonicalField, key: str = None) -> Type:
    return Type(key=key or name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*, types: List[Type] = (), services: List[Service] = (), **kw) -> CanonicalApi:
    defaults = dict(paradigm=ApiParadigm.REST, format="openapi-3.1",
                    identity=ApiIdentity(name="Shop", namespace="com.acme.shop"), title="Shop",
                    types=list(types), services=list(services))
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return SmithyEmitter().emit(api, opts=SmithyEmitOptions(**opts) if opts else None)


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
    """A REST-shaped model: labels, query and header parameters, bodies, list responses, errors."""
    pet = _record("Pet", _field("Pet", "id", "integer", nullable=False), _field("Pet", "name", nullable=False),
                  _field("Pet", "tag"))
    error = _record("Error", _field("Error", "code", "integer", nullable=False), _field("Error", "message"))
    pet_id = Parameter(key="GET /pets/{pet-id}#path.pet-id", name="pet-id", location=ParameterLocation.PATH,
                       type=TypeRef(name="integer"), required=True)
    operations = [
        Operation(
            key="GET /pets", name="listPets", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
            http_path="/pets",
            parameters=[
                Parameter(key="GET /pets#query.limit", name="limit", location=ParameterLocation.QUERY,
                          type=TypeRef(name="integer"), constraints=Constraints(maximum=100)),
                Parameter(key="GET /pets#header.X-Trace", name="X-Trace", location=ParameterLocation.HEADER,
                          type=TypeRef(name="string")),
                Parameter(key="GET /pets#header.Authorization", name="Authorization",
                          location=ParameterLocation.HEADER, type=TypeRef(name="string")),
            ],
            messages=[
                Message(key="GET /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet")),
                Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200",
                        payload=TypeRef(name="Pet", item=TypeRef(name="Pet"))),
                Message(key="GET /pets#default", role=MessageRole.ERROR, status_code="default",
                        payload=TypeRef(name="Error")),
            ],
        ),
        Operation(
            key="GET /pets/{pet-id}", name="showPetById", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
            http_path="/pets/{pet-id}", parameters=[pet_id],
            messages=[
                Message(key="GET /pets/{pet-id}#200", role=MessageRole.RESPONSE, status_code="200",
                        payload=TypeRef(name="Pet")),
                Message(key="GET /pets/{pet-id}#404", role=MessageRole.ERROR, status_code="404",
                        payload=TypeRef(name="Error")),
                Message(key="GET /pets/{pet-id}#400", role=MessageRole.ERROR, status_code="400",
                        payload=TypeRef(name="string")),
            ],
        ),
        Operation(
            key="PUT /pets/{pet-id}", name="updatePet", kind=OperationKind.REQUEST_RESPONSE, http_method="PUT",
            http_path="/pets/{pet-id}", parameters=[pet_id.model_copy(update={"key": "PUT#path"})],
            messages=[
                Message(key="PUT#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet")),
                Message(key="PUT#201", role=MessageRole.RESPONSE, status_code="201", payload=TypeRef(name="Pet")),
            ],
        ),
    ]
    return _api(types=[pet, error], services=[Service(key="pets", name="PetService", operations=operations)],
                version="1.0.0")


# ===========================================================================
# Identifiers and names
# ===========================================================================


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Order", "Order"), ("com.acme.Order", "com_acme_Order"), ("order-id", "order_id"), ("1st", "n1st"),
     ("_private", "private"), ("", "Shape")],
)
def test_smithy_identifier(name: str, expected: str) -> None:
    assert smithy_identifier(name) == expected


def test_names_are_unique_ignoring_case_and_never_a_prelude_shape() -> None:
    order = _record("Order", _field("Order", "abc"), _field("Order", "ABC"), _field("Order", "order-id"))
    result = _emit(_api(types=[order, _record("order", key="v2.order"), _record("String")]))
    text = _text(result)
    assert "structure Order {" in text and "structure order2 {" in text and "structure String2 {" in text
    assert "    ABC2: String" in text
    # A renamed member keeps its wire name.
    assert '@jsonName("order-id")\n    order_id: String' in text
    assert {"renamed-shape", "renamed-member"} <= _subjects(result)


def test_repeated_field_names_do_not_share_a_json_name() -> None:
    order = _record("Order", _field("Order", "line"), _field("Order", "line"))
    ast = json.loads(_emit(_api(types=[order]), output="json-ast").files[0].content)
    members = ast["shapes"]["com.acme.shop#Order"]["members"]
    assert "traits" not in members["line2"]


def test_a_trait_shadowed_by_a_shape_is_qualified() -> None:
    record = _record("Settings", _field("Settings", "mode", nullable=False, default="fast"))
    text = _text(_emit(_api(types=[record, _record("default", _field("default", "x"))])))
    assert '@smithy.api#default("fast")' in text


# ===========================================================================
# Shapes and traits
# ===========================================================================


def test_structure_traits_constraints_and_lists() -> None:
    order = _record(
        "Order",
        _field("Order", "id", nullable=False, description="The order id."),
        _field("Order", "code", constraints=Constraints(min_length=3, max_length=8, pattern="^[A-Z]+$")),
        _field("Order", "count", "integer", constraints=Constraints(exclusive_minimum=0, maximum=10)),
        _field("Order", "price", "double", constraints=Constraints(exclusive_maximum=1.5, multiple_of=0.5)),
        _field("Order", "tags", item="string", constraints=Constraints(min_items=1, unique_items=True)),
        _field("Order", "notes", item="string"),
        _field("Order", "mislabeled", constraints=Constraints(minimum=1)),
        _field("Order", "size", "integer", default=3),
        _field("Order", "flag", "boolean", default="yes"),
    )
    result = _emit(_api(types=[order]))
    text = _text(result)
    assert "    /// The order id.\n    @required\n    id: String" in text
    assert '@length(min: 3, max: 8)\n    @pattern("^[A-Z]+$")\n    code: String' in text
    # An exclusive integer bound becomes inclusive; a float's is written inclusive and reported.
    assert "@range(min: 1, max: 10)\n    count: Integer" in text
    assert "@range(max: 1.5)\n    price: Double" in text
    # uniqueItems goes on a list shape, never a member.
    assert "@length(min: 1)\n    tags: StringSet" in text
    assert "@uniqueItems\nlist StringSet {\n    member: String\n}" in text
    assert "notes: StringList" in text and "list StringList {" in text
    assert "@default(3)\n    size: Integer" in text and "@default" not in text.split("flag")[0].split("size")[1]
    assert {"constraint-dropped", "default-dropped"} <= _subjects(result)


def test_enums_unions_maps_and_simple_shapes() -> None:
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key="Status.ACTIVE", name="ACTIVE"),
                               EnumValue(key="Status.in-progress", name="in-progress", value="in-progress")])
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION,
                 fields=[_field("Shape", "circle", "double", nullable=False), _field("Shape", "none", "void")])
    pet = Type(key="Pet", name="Pet", kind=TypeKind.UNION, union_members=["Cat", "Dog"])
    labels = Type(key="Labels", name="Labels", kind=TypeKind.MAP, key_type=TypeRef(name="integer"),
                  value_type=TypeRef(name="string"))
    money = Type(key="Money", name="Money", kind=TypeKind.SCALAR)
    sku = Type(key="Sku", name="Sku", kind=TypeKind.ALIAS, aliased=TypeRef(name="string"),
               constraints=Constraints(pattern="^[0-9]+$"))
    owner = Type(key="Owner", name="Owner", kind=TypeKind.ALIAS, aliased=TypeRef(name="Cat"))
    holder = _record("Holder", _field("Holder", "owner", "Owner"))
    result = _emit(_api(types=[status, shape, pet, labels, money, sku, owner, holder,
                               _record("Cat", _field("Cat", "lives", "integer")), _record("Dog")]))
    text = _text(result)
    assert 'enum Status {\n    ACTIVE\n    in_progress = "in-progress"\n}' in text
    # Union members are never @required; a void member targets Unit.
    assert "union Shape {\n    circle: Double\n\n    none: Unit\n}" in text
    assert "union Pet {\n    cat: Cat\n\n    dog: Dog\n}" in text
    assert "map Labels {\n    key: String\n    value: String\n}" in text
    assert "string Money" in text and '@pattern("^[0-9]+$")\nstring Sku' in text
    # Smithy has no alias of a named shape: references go to the aliased shape.
    assert "owner: Cat" in text and "Owner" not in text
    assert {"renamed-enum-member", "map-key-as-string", "custom-scalar", "alias-inlined"} <= _subjects(result)


def test_a_cycle_of_required_members_is_broken() -> None:
    a = _record("A", _field("A", "b", "B", nullable=False))
    b = _record("B", _field("B", "a", "A", nullable=False))
    result = _emit(_api(types=[a, b]))
    assert _text(result).count("@required") == 1
    assert "recursive-member-optional" in _subjects(result)


def test_null_fields_in_structures_are_documents() -> None:
    result = _emit(_api(types=[_record("R", _field("R", "nothing", "null"))]))
    assert "nothing: Document" in _text(result) and "null-as-document" in _subjects(result)


# ===========================================================================
# Services and operations
# ===========================================================================


def test_http_operations_and_errors() -> None:
    result = _emit(_rest_api())
    text = _text(result)
    assert 'service PetService {\n    version: "1.0.0"\n    operations: [listPets, showPetById, updatePet]\n}' in text
    assert ('@http(method: "GET", uri: "/pets", code: 200)\n@readonly\noperation listPets {\n'
            "    input: ListPetsInput\n    output: ListPetsOutput\n    errors: [Error]\n}") in text
    assert '@httpQuery("limit")\n    limit: Integer' in text and "@range(max: 100)" in text
    assert '@httpHeader("X-Trace")\n    X_Trace: String' in text
    # The path label follows the member it binds; a GET carries no body; transport headers are not bound.
    assert 'uri: "/pets/{pet_id}"' in text and "@httpLabel\n    @required\n    pet_id: Integer" in text
    assert "Authorization" not in text
    assert "@httpPayload\n    body: PetList" not in text and "listPets" in text
    assert '@http(method: "PUT", uri: "/pets/{pet_id}", code: 201)\n@idempotent' in text
    assert "@httpPayload\n    body: Pet" in text
    # A list response is the payload member of a synthesized output; the error-only record is an @error.
    assert "structure ListPetsOutput {\n    body: PetList\n}" in text
    assert '@error("client")\n@httpError(404)\nstructure Error {' in text
    assert {"body-dropped", "parameter-dropped", "error-dropped", "structure-as-error",
            "payload-wrapped"} <= _subjects(result)


def test_unbindable_and_duplicate_routes_lose_their_http_trait() -> None:
    ops = [Operation(key=k, name=n, kind=OperationKind.REQUEST_RESPONSE, http_method="GET", http_path=p)
           for k, n, p in [("a", "a", "/files/{id}.json"), ("b", "b", "/x/{id}"), ("c", "c", "/x/{other}")]]
    result = _emit(_api(services=[Service(key="S", name="S", operations=ops)]))
    text = _text(result)
    assert '"/x/{id}"' in text and "/files" not in text and "/x/{other}" not in text
    assert "http-binding-dropped" in _subjects(result)


def test_rpc_operations_reference_their_structures() -> None:
    req, res = _record("GetReq", _field("GetReq", "id")), _record("GetRes", _field("GetRes", "name"))
    op = Operation(key="S.get", name="Get", kind=OperationKind.REQUEST_RESPONSE, messages=[
        Message(key="S.get#req", role=MessageRole.REQUEST, payload=TypeRef(name="GetReq")),
        Message(key="S.get#res", role=MessageRole.RESPONSE, payload=TypeRef(name="GetRes")),
    ])
    tick = Operation(key="S.tick", name="tick", kind=OperationKind.PUBLISH)
    result = _emit(_api(types=[req, res], services=[Service(key="S", name="S", operations=[op, tick])]))
    assert "operation Get {\n    input: GetReq\n    output: GetRes\n}" in _text(result)
    assert "event-operation-dropped" in _subjects(result)


def test_protocol_and_output_options() -> None:
    both = _emit(_rest_api(), output="both", protocol="restJson1")
    assert [f.path for f in both.files] == ["PetService.smithy", "PetService.json"]
    assert "use aws.protocols#restJson1\n" in both.files[0].content and "@restJson1\nservice PetService" in \
        both.files[0].content
    ast = json.loads(both.files[1].content)
    assert ast["smithy"] == "2.0"
    service = ast["shapes"]["com.acme.shop#PetService"]
    assert service["traits"] == {"aws.protocols#restJson1": {}}
    pet = ast["shapes"]["com.acme.shop#Pet"]["members"]["id"]
    assert pet == {"target": "smithy.api#Integer", "traits": {"smithy.api#required": {}}}
    assert _emit(_rest_api(), output="json-ast").files[0].media_type == "application/json"


def test_nothing_to_declare_is_refused() -> None:
    with pytest.raises(EmitPreconditionError):
        _emit(_api())


# ===========================================================================
# The IDL reader and Smithy sources
# ===========================================================================


def test_the_reader_reads_member_traits_enum_values_and_docs() -> None:
    doc = parse_smithy(
        '$version: "2.0"\nnamespace a\n\n/// Pets.\n@readonly\noperation Get {\n    output: Pet\n}\n\n'
        'structure Pet {\n    @pattern("^(a|b):x$")\n    @required\n    code: String\n'
        "    @range(min: 1) @required count: Integer\n}\n\n"
        'enum Status {\n    ACTIVE\n    in_progress = "in-progress"\n}\n'
    )
    pet = doc.structures[0]
    assert [(f.name, f.required, f.traits) for f in pet.fields] == [
        ("code", True, ("pattern", "required")), ("count", True, ("range", "required"))]
    assert doc.enums[0].values == ("ACTIVE", "in_progress")
    assert doc.operations[0].documentation == "Pets." and pet.documentation is None


_SMITHY_CORPUS = sorted((_EXAMPLES / "smithy").glob("*.smithy"))


@pytest.mark.parametrize("path", _SMITHY_CORPUS, ids=lambda p: p.name)
def test_smithy_corpus_round_trips(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Both imports read the IDL with the built-in reader, so the round trip does not depend on
    # whether the Smithy CLI is installed (its JSON AST path keeps member doc comments as a trait name
    # without the text, and orders a resource's operations by lifecycle).
    monkeypatch.setattr("app.smithy_import_source.smithy_cli_available", lambda: False)
    api = _corpus_api(path, "smithy")
    result = _emit(api)
    diff = canonical_diff(api, reimport_emitted(SmithyImportSource(), result, multi_file=False)).entries
    changed = {f"{entry.change.value} {entry.key}" for entry in diff}
    if path.name == "03-bookstore-resource.smithy":
        # A resource was imported as a record of its lifecycle bindings; it is not written back.
        assert changed == {"removed example.bookstore.Book"} and "resource-dropped" in _subjects(result)
    elif path.name == "04-grammar-corners.smithy":
        # Its @length / @range / @pattern were imported by name only, without their values.
        assert changed == {"changed example.payments.SubmitPaymentInput"}
        assert "trait-value-unknown" in _subjects(result)
    else:
        assert diff == []


# ===========================================================================
# Acceptance: validates under the Smithy CLI
# ===========================================================================

_VALIDATE_CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("openapi/22-advanced-oneof-polymorphism.yaml", "openapi"),
    ("openapi/02-array-contains.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    ("avro/01-user-record.avsc", "avro"),
    ("json-schema/02-product-types.json", "json-schema"),
    ("thrift/01-user-service.thrift", "thrift"),
    *[(f"smithy/{p.name}", "smithy") for p in _SMITHY_CORPUS],
]


@needs_smithy
@pytest.mark.parametrize(("path", "fmt"), _VALIDATE_CORPUS, ids=lambda v: str(v))
def test_corpus_export_validates(path: str, fmt: str) -> None:
    result = _emit(_corpus_api(_EXAMPLES / path, fmt), output="both")
    check_with_smithy(result.files[0].content, file_name="model.smithy")
    check_with_smithy(result.files[1].content, file_name="model.json")


@needs_smithy
def test_the_hand_built_models_validate() -> None:
    a = _record("A", _field("A", "b", "B", nullable=False), _field("A", "tags", item="string",
                                                                    constraints=Constraints(unique_items=True)))
    b = _record("B", _field("B", "a", "A", nullable=False), _field("B", "n", "null"))
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, fields=[_field("Shape", "none", "void")])
    for api in (_rest_api(), _api(types=[a, b, shape, _record("default", _field("default", "x", default="y"))])):
        result = _emit(api, output="both")
        check_with_smithy(result.files[0].content, file_name="model.smithy")
        check_with_smithy(result.files[1].content, file_name="model.json")
    restjson = _emit(_rest_api(), protocol="restJson1")
    check_with_smithy(restjson.files[0].content, allow_unknown_traits=True)
