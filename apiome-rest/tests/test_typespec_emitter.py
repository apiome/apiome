"""TypeSpec emitter — MFX-15.1 (#3893).

Covers, in order:

* names: :func:`app.typespec_emitter.typespec_identifier` (backticks keep every name as is) and the
  declarations renamed off a built-in type or a clash;
* the document: ``@service({ title })`` (the form the bundled ``tsp`` 0.65 accepts), the description,
  ``@info({ version })`` with ``@typespec/openapi``, ``@server`` with variables, the namespace;
* types: models (optional members, constraint decorators, ``@format``, defaults, docs, ``#deprecated``),
  enums (string and numeric values), unions, ``Record`` maps, named lists, scalars and aliases;
* operations: interfaces, verbs and routes, ``@path`` / ``@query`` / ``@header`` / ``@cookie`` / ``@body``,
  non-JSON content types, responses (plain, status variants, ranges, a ``default`` error model, headers),
  RPC operations given a route, and what is not written and reported;
* the TypeSpec reader the round trip re-imports through: model fields, ``/** */`` docs, operation routes,
  backticked names, optional parameters, enum values, ``@service({ … })``;
* the fidelity pack agreeing with the writer, and emitted-output validation (compile, or re-parse);
* acceptance: every TypeSpec corpus file round-trips unchanged; exports of corpus files from other
  formats compile with the bundled ``tsp`` (when it is installed here).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from app.canonical_model import (
    AgentDescriptor,
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
    Server,
    ServerVariable,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, LossKind
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import ImportSourceError, canonical_diff
from app.lossiness import LossinessKind, LossinessSeverity
from app.roundtrip_matrix import reimport_emitted
from app.typespec_compile import TSP_TOOL_KEY, typespec_node_modules
from app.typespec_emitter import TypeSpecEmitOptions, TypeSpecEmitter, typespec_identifier
from app.typespec_import_source import TypeSpecImportSource
from app.typespec_normalizer import TypeSpecNormalizer
from app.typespec_parser import parse_typespec

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _live_compiler_ready() -> bool:
    from app.toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    probe = probe_tool(TSP_TOOL_KEY)
    libraries = typespec_node_modules()
    return bool(probe and probe.available and libraries and (libraries / "@typespec" / "openapi3").is_dir())


needs_tsp = pytest.mark.skipif(not _live_compiler_ready(), reason="tsp with @typespec/openapi3 is not installed")


def _field(owner: str, name: str, ref: str = "string", *, nullable: bool = True, item: str = None,
           constraints: Constraints = None, default=None, description: str = None, number: int = None,
           deprecated: bool = False) -> CanonicalField:
    type_ref = TypeRef(item=TypeRef(name=item), nullable=nullable) if item else TypeRef(name=ref, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=type_ref, constraints=constraints, default=default,
                          description=description, field_number=number, deprecated=deprecated)


def _record(name: str, *fields: CanonicalField, **kw) -> Type:
    return Type(key=kw.pop("key", name), name=name, kind=TypeKind.RECORD, fields=list(fields), **kw)


def _api(*, types=(), operations=(), service: str = "PetService", **kw) -> CanonicalApi:
    services = [Service(key="pets", name=service, operations=list(operations))] if operations else []
    defaults = dict(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Pet Store"),
                    title="Pet Store", types=list(types), services=services)
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _op(key: str, method: str = None, path: str = None, *, params=(), messages=(), **kw) -> Operation:
    return Operation(key=key, name=kw.pop("name", "op"), kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE),
                     http_method=method, http_path=path, parameters=list(params), messages=list(messages), **kw)


def _param(op: str, name: str, location: ParameterLocation, ref: str = "string", **kw) -> Parameter:
    return Parameter(key=f"{op}#{location.value}.{name}", name=name, location=location, type=TypeRef(name=ref), **kw)


def _response(op: str, status: str = "200", payload: str = None, *, role=MessageRole.RESPONSE, **kw) -> Message:
    return Message(key=f"{op}#{status}", role=role, status_code=status,
                   payload=TypeRef(name=payload) if payload else None, **kw)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return TypeSpecEmitter().emit(api, opts=TypeSpecEmitOptions(**opts) if opts else None)


def _text(api: CanonicalApi, **opts) -> str:
    return _emit(api, **opts).files[0].content


def _subjects(result: EmitResult) -> set:
    return {loss.subject for loss in result.losses}


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _pets_api() -> CanonicalApi:
    """A REST model: path, query, header and cookie parameters, a body, status variants and errors."""
    pet = _record("Pet", _field("Pet", "id", "integer", nullable=False, constraints=Constraints(format="int64")),
                  _field("Pet", "name", nullable=False, constraints=Constraints(min_length=1, max_length=40)),
                  _field("Pet", "tag", description="A free-form tag."))
    error = _record("Error", _field("Error", "code", "integer", nullable=False), _field("Error", "message"))
    get_op = "GET /pets/{pet-id}"
    operations = [
        _op("GET /pets", "GET", "/pets", name="listPets",
            params=[_param("GET /pets", "limit", ParameterLocation.QUERY, "integer",
                           constraints=Constraints(maximum=100), default=20),
                    _param("GET /pets", "X-Trace", ParameterLocation.HEADER),
                    _param("GET /pets", "session", ParameterLocation.COOKIE)],
            messages=[Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200",
                              payload=TypeRef(item=TypeRef(name="Pet"))),
                      _response("GET /pets", "default", "Error", role=MessageRole.ERROR)]),
        _op(get_op, "GET", "/pets/{pet-id}", name="showPetById",
            params=[_param(get_op, "pet-id", ParameterLocation.PATH, "integer", required=True)],
            messages=[_response(get_op, "200", "Pet"), _response(get_op, "404", "Error", role=MessageRole.ERROR),
                      _response(get_op, "5XX", None, role=MessageRole.ERROR)]),
        _op("POST /pets", "POST", "/pets", name="createPet",
            messages=[Message(key="POST /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"),
                              required=True),
                      _response("POST /pets", "201", "Pet",
                                headers=[_field("POST /pets#201", "Location", nullable=False)])]),
    ]
    return _api(types=[pet, error], operations=operations, version="1.0.0", description="Pets.",
                servers=[Server(url="https://{region}.example.com/v1", description="Production",
                                variables=[ServerVariable(name="region", default="eu")])])


# ===========================================================================
# Names
# ===========================================================================


@pytest.mark.parametrize(("name", "expected"), [
    ("Pet", "Pet"), ("order-id", "`order-id`"), ("model", "`model`"), ("1st", "`1st`"), ("", "Unnamed"),
    ("a`b", "`a'b`"),
])
def test_typespec_identifier(name: str, expected: str) -> None:
    assert typespec_identifier(name) == expected


def test_a_declaration_named_like_a_builtin_or_a_clash_is_renamed() -> None:
    result = _emit(_api(types=[_record("string", _field("string", "x")), _record("Pet", _field("Pet", "a")),
                               _record("Pet", _field("Pet2", "b"), key="other.Pet")]))
    text = result.files[0].content
    assert "model string2 {" in text and "model Pet {" in text and "model Pet2 {" in text
    assert sorted(loss.pointer for loss in result.losses if loss.subject == "renamed-declaration") == [
        "other.Pet", "string"]


def test_names_that_are_not_identifiers_are_backticked_and_kept() -> None:
    text = _text(_api(types=[_record("order-line", _field("order-line", "unit-price", "number"),
                                     _field("order-line", "model", "boolean"))]))
    assert "model `order-line` {" in text
    assert "`unit-price`?: float64;" in text and "`model`?: boolean;" in text


# ===========================================================================
# The document
# ===========================================================================


def test_the_document_header() -> None:
    text = _text(_pets_api())
    assert text.startswith("// Generated by Apiome from Pet Store.\n")
    assert 'import "@typespec/http";\nimport "@typespec/openapi";' in text
    assert "using TypeSpec.Http;\nusing TypeSpec.OpenAPI;" in text
    assert ('/** Pets. */\n@service({ title: "Pet Store" })\n@info({ version: "1.0.0" })\n'
            '@server("https://{region}.example.com/v1", "Production", { region?: string = "eu" })\n'
            "namespace Pet.Store;") in text


def test_imports_and_comments_can_be_left_out() -> None:
    text = _text(_api(types=[_record("Pet", _field("Pet", "id"))]), include_comments=False,
                 include_http_imports=False)
    assert text.startswith('@service({ title: "Pet Store" })\nnamespace Pet.Store;')
    assert "@typespec/openapi" not in _text(_api(types=[_record("Pet", _field("Pet", "id"))]))


@pytest.mark.parametrize(("identity", "expected"), [
    (ApiIdentity(name="x", namespace="com.acme.shop"), "com.acme.shop"),
    (ApiIdentity(name="Pet Store (OpenAPI 3.0)"), "Pet.Store.OpenAPI.N3.N0"),
    (ApiIdentity(name="urn:acme:model"), "urn.acme.model_"),
])
def test_the_namespace_is_dotted_identifiers(identity: ApiIdentity, expected: str) -> None:
    text = _text(_api(types=[_record("Pet", _field("Pet", "id"))], identity=identity))
    assert f"namespace {expected};" in text


def test_nothing_to_declare_is_refused() -> None:
    with pytest.raises(EmitPreconditionError):
        _emit(_api())


# ===========================================================================
# Types
# ===========================================================================


def test_models_members_constraints_defaults_and_docs() -> None:
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key="Status.active", name="active", value="active"),
                               EnumValue(key="Status.in-progress", name="in-progress", value="in-progress")])
    pet = _record(
        "Pet",
        _field("Pet", "id", "string", nullable=False, constraints=Constraints(format="uuid")),
        _field("Pet", "name", nullable=False, constraints=Constraints(min_length=1, pattern="^[a-z]+$")),
        _field("Pet", "age", "integer", constraints=Constraints(minimum=0, exclusive_maximum=30, format="int64")),
        _field("Pet", "born", constraints=Constraints(format="date-time")),
        _field("Pet", "tags", item="string", constraints=Constraints(min_items=1, max_items=5), default=["a"]),
        _field("Pet", "status", "Status", default="in-progress"),
        _field("Pet", "legacy", deprecated=True, description="Old.\nDo not use."),
        description="A pet.",
    )
    text = _text(_api(types=[status, pet]))
    assert "/** A pet. */\nmodel Pet {" in text
    assert '  @format("uuid") id: string;' in text
    assert '  @minLength(1) @pattern("^[a-z]+$") name: string;' in text
    assert "  @minValue(0) @maxValueExclusive(30) age?: int64;" in text
    assert "  born?: utcDateTime;" in text
    assert '  @minItems(1) @maxItems(5) tags?: string[] = #["a"];' in text
    assert "  status?: Status = Status.`in-progress`;" in text
    assert '  /**\n   * Old.\n   * Do not use.\n   */\n  #deprecated "Deprecated."\n  legacy?: string;' in text
    assert "enum Status {\n  active,\n  `in-progress`,\n}" in text


def test_constraints_and_defaults_typespec_cannot_carry_are_reported() -> None:
    pet = _record("Pet",
                  _field("Pet", "weight", "number", constraints=Constraints(multiple_of=0.5)),
                  _field("Pet", "ids", item="string", constraints=Constraints(unique_items=True)),
                  _field("Pet", "flag", "boolean", constraints=Constraints(max_length=2), default="yes"))
    result = _emit(_api(types=[pet]))
    dropped = {loss.pointer: loss.detail for loss in result.losses if loss.subject == "constraint-dropped"}
    assert "multipleOf" in dropped["Pet.weight"] and "uniqueItems" in dropped["Pet.ids"]
    assert "maxLength" in dropped["Pet.flag"]
    assert [loss.pointer for loss in result.losses if loss.subject == "default-dropped"] == ["Pet.flag"]
    assert "`flag`?: boolean;" in result.files[0].content  # `flag` is reserved in TypeSpec


def test_enum_values_are_all_numbers_or_names() -> None:
    def enum(name: str, *values) -> Type:
        return Type(key=name, name=name, kind=TypeKind.ENUM,
                    enum_values=[EnumValue(key=f"{name}.{n}", name=n, value=v) for n, v in values])

    result = _emit(_api(types=[enum("Code", ("OK", 0), ("FAIL", 1)), enum("Mixed", ("a", "x"), ("b", 2))]))
    text = result.files[0].content
    assert "enum Code {\n  OK: 0,\n  FAIL: 1,\n}" in text
    assert 'enum Mixed {\n  a: "x",\n  b,\n}' in text
    assert [loss.pointer for loss in result.losses if loss.subject == "enum-value-dropped"] == ["Mixed.b"]


def test_unions_maps_lists_scalars_and_aliases() -> None:
    circle = _record("Circle", _field("Circle", "r", "number"))
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION,
                 fields=[_field("Shape", "circle", "Circle"), _field("Shape", "none", "null")])
    either = Type(key="Either", name="Either", kind=TypeKind.UNION, union_members=["Circle", "string"])
    attrs = Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, key_type=TypeRef(name="integer"),
                 value_type=TypeRef(name="string"))
    names = Type(key="Names", name="Names", kind=TypeKind.ALIAS, aliased=TypeRef(item=TypeRef(name="string")),
                 constraints=Constraints(min_items=1))
    account = Type(key="AccountId", name="AccountId", kind=TypeKind.ALIAS, aliased=TypeRef(name="string"),
                   constraints=Constraints(min_length=3))
    ref = Type(key="CircleRef", name="CircleRef", kind=TypeKind.ALIAS, aliased=TypeRef(name="Circle"))
    money = Type(key="Money", name="Money", kind=TypeKind.SCALAR)
    when = Type(key="DateTime", name="DateTime", kind=TypeKind.SCALAR)
    result = _emit(_api(types=[circle, shape, either, attrs, names, account, ref, money, when]))
    text = result.files[0].content
    assert "union Shape {\n  circle: Circle,\n  none: null,\n}" in text
    assert "union Either {\n  Circle,\n  string,\n}" in text
    assert "model Attrs is Record<string>;" in text
    assert "@minItems(1)\nmodel Names is string[];" in text
    assert "@minLength(3)\nscalar AccountId extends string;" in text
    assert "alias CircleRef = Circle;" in text
    assert "scalar Money extends string;" in text and "scalar DateTime extends utcDateTime;" in text
    assert {"map-key-as-string", "alias-inlined", "custom-scalar"} <= _subjects(result)
    assert [loss.pointer for loss in result.losses if loss.subject == "custom-scalar"] == ["Money"]


def test_non_positional_field_numbers_are_reported() -> None:
    result = _emit(_api(types=[_record("Pet", _field("Pet", "b", number=5), _field("Pet", "a", number=1))]))
    assert result.files[0].content.index("  a?: string;") < result.files[0].content.index("  b?: string;")
    assert sorted(loss.pointer for loss in result.losses if loss.subject == "field-number-dropped") == [
        "Pet.a", "Pet.b"]
    positional = _emit(_api(types=[_record("Pet", _field("Pet", "a", number=1), _field("Pet", "b", number=2))]))
    assert "field-number-dropped" not in _subjects(positional)


def test_an_unknown_scalar_is_a_string_reported_on_its_field() -> None:
    result = _emit(_api(types=[_record("User", _field("User", "id", "ID"))]))
    assert "  id?: string;" in result.files[0].content
    assert [(loss.subject, loss.pointer) for loss in result.losses] == [("unknown-type", "User.id")]


# ===========================================================================
# Operations
# ===========================================================================


def test_http_operations_parameters_and_responses() -> None:
    text = _text(_pets_api())
    assert "interface PetService {" in text
    assert ('  @get @route("/pets") listPets(@query @maxValue(100) limit?: int32 = 20, '
            '@header("X-Trace") xTrace?: string, @cookie("session") session?: string): '
            "{ @statusCode statusCode: 200; @body body: Pet[]; } | ListPetsDefaultResponse;") in text
    assert "@error model ListPetsDefaultResponse {\n  @body body: Error;\n}" in text
    assert ('  @get @route("/pets/{pet-id}") showPetById(@path `pet-id`: int32): '
            "{ @statusCode statusCode: 200; @body body: Pet; } | { @statusCode statusCode: 404; @body body: Error; } | "
            "{ @minValue(500) @maxValue(599) @statusCode statusCode: int32; };") in text
    assert ('  @post @route("/pets") createPet(@body body: Pet): '
            '{ @statusCode statusCode: 201; @body body: Pet; @header("Location") location: string; };') in text


def test_a_plain_200_is_the_return_type_and_no_response_is_void() -> None:
    ops = [_op("GET /a", "GET", "/a", name="a", messages=[_response("GET /a", "200", "Pet")]),
           _op("DELETE /a", "DELETE", "/a", name="b")]
    text = _text(_api(types=[_record("Pet", _field("Pet", "id"))], operations=ops))
    assert '@get @route("/a") a(): Pet;' in text and '@delete @route("/a") b(): void;' in text


def test_a_non_json_body_names_its_content_type() -> None:
    op = _op("PUT /doc", "PUT", "/doc", name="putDoc", messages=[
        Message(key="PUT /doc#request", role=MessageRole.REQUEST, payload=TypeRef(name="bytes"),
                content_types=["application/pdf", "image/png"], required=True)])
    text = _text(_api(operations=[op]))
    assert ('putDoc(@header("Content-Type") contentType: "application/pdf" | "image/png", @body body: bytes): void;'
            in text)


def test_rpc_operations_get_a_route_and_events_are_dropped() -> None:
    rpc = _op("Pets.List", name="List", messages=[_response("Pets.List", None, "Pet")])
    event = _op("onPet", name="onPet", kind=OperationKind.SUBSCRIBE)
    result = _emit(_api(types=[_record("Pet", _field("Pet", "id"))], operations=[rpc, event], service="Pets"))
    assert '@post @route("/Pets/List") List(): Pet;' in result.files[0].content
    assert sorted((loss.subject, loss.pointer) for loss in result.losses) == [
        ("event-operation-dropped", "onPet"), ("rpc-as-http", "Pets.List")]


def test_routes_and_parameters_typespec_cannot_place_are_reported() -> None:
    ops = [
        _op("GET /a", "GET", "/a", name="first"),
        _op("GET /a#2", "GET", "/a", name="again"),
        _op("OPTIONS /a", "OPTIONS", "/a", name="opts"),
        _op("GET /b/{id}", "GET", "/b/{id}", name="byId",
            params=[_param("GET /b/{id}", "other", ParameterLocation.PATH, required=True)]),
    ]
    result = _emit(_api(operations=ops))
    text = result.files[0].content
    assert "again" not in text and "opts" not in text
    assert '@get @route("/b/{id}") byId(@path id: string): void;' in text
    found = [(loss.subject, loss.pointer) for loss in result.losses]
    assert ("operation-dropped", "GET /a#2") in found and ("operation-dropped", "OPTIONS /a") in found
    assert ("parameter-dropped", "GET /b/{id}#path.other") in found
    assert ("path-parameter-synthesized", "GET /b/{id}") in found


# ===========================================================================
# The TypeSpec reader the round trip re-imports through
# ===========================================================================

_READER_SAMPLE = '''import "@typespec/http";
using TypeSpec.Http;

@service({ title: "Shop \\"Main\\"" })
namespace Shop;

/**
 * A pet.
 * Second line.
 */
model Pet {
  /** The id. */
  @key @minLength(1) id: string;
  `order-id`?: string = "a;b";
  url?: string = "https://x.example/y";
  #deprecated "old"
  @pattern("^(a|b)$") code: string;
}

enum Kind {
  cat,
  `in-progress`: "in-progress",
}

@route("/pets")
interface Pets {
  /** Read one. */
  @get @route("/{id}/toys") toys(@path id: string, @query limit?: int32 = 5, @header("X-Trace") trace?: string): Pet[];
  @get list(): Pet[] | { @statusCode statusCode: 404; };
}
'''


def test_the_reader_reads_fields_docs_routes_and_parameters() -> None:
    doc = parse_typespec(_READER_SAMPLE)
    assert doc.service_title == 'Shop "Main"'
    pet = doc.models[0]
    assert pet.documentation == "A pet.\nSecond line."
    assert [(f.name, f.type_expr, f.optional) for f in pet.fields] == [
        ("id", "string", False), ("order-id", "string", True), ("url", "string", True), ("code", "string", False)]
    assert pet.fields[0].decorators == ("@key", "@minLength(1)") and pet.fields[0].documentation == "The id."
    assert doc.enums[0].values == ("cat", "in-progress")
    toys = doc.interfaces[0].operations[0]
    assert (toys.name, toys.route, toys.documentation) == ("toys", "/{id}/toys", "Read one.")
    assert [(p.name, p.location, p.type_expr, p.optional) for p in toys.parameters] == [
        ("id", "path", "string", False), ("limit", "query", "int32", True), ("X-Trace", "header", "string", True)]


def test_the_normalizer_uses_operation_routes_and_optional_parameters() -> None:
    api = TypeSpecNormalizer().normalize(parse_typespec(_READER_SAMPLE))
    keys = sorted(op.key for op in api.operations())
    assert keys == ["GET /pets", "GET /pets/{id}/toys"]
    toys = next(op for op in api.operations() if op.key == "GET /pets/{id}/toys")
    assert {p.name: p.required for p in toys.parameters} == {"id": True, "limit": False, "X-Trace": False}


# ===========================================================================
# Fidelity pack and validation
# ===========================================================================


def test_the_fidelity_pack_predicts_the_writer() -> None:
    api = _pets_api()
    api = api.model_copy(update={"types": [*api.types, _record("Odd", _field("Odd", "n", "number",
                                                                               constraints=Constraints(multiple_of=2)))]})
    report = compute_lossiness_for_emitter(api, TypeSpecEmitter())
    items = {(item.construct_key, item.target_mapping): item for item in report.items}
    assert items[("Pet", "model Pet")].kind is LossinessKind.OK
    assert items[("POST /pets", "op createPet @post /pets")].kind is LossinessKind.OK
    assert items[("Odd.n", "constraint-dropped")].kind is LossinessKind.DROP
    assert items[("GET /pets", "default-response-model")].kind is LossinessKind.APPROX
    root = items[("", "document → namespace Pet.Store")]
    assert root.kind is LossinessKind.APPROX and root.severity is LossinessSeverity.INFO
    predicted = {(item.target_mapping, item.kind) for item in report.items}
    for loss in _emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else LossinessKind.APPROX
        assert (loss.subject, kind) in predicted, loss


def test_a_typespec_source_root_is_not_reported_but_agents_are() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], format="typespec",
               agents=[AgentDescriptor(key="helper", name="helper", protocol="a2a")])
    root = [item for item in compute_lossiness_for_emitter(api, TypeSpecEmitter()).items if item.construct_key == ""]
    assert [(item.kind, item.target_mapping) for item in root] == [(LossinessKind.DROP, "agents → dropped")]


@pytest.fixture
def no_tsp(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(members, root, **_):
        raise ImportSourceError("no tsp", code="ADAPTER_UNAVAILABLE")

    monkeypatch.setattr("app.typespec_compile.compile_typespec_set", unavailable)


async def test_validation_reparses_without_the_compiler(no_tsp) -> None:
    api = _pets_api()
    verdict = await validate_emitted_artifact("typespec", _emit(api), api=api)
    assert (verdict.applicable, verdict.validated, verdict.valid) == (True, True, True)


async def test_validation_rejects_a_broken_document_without_the_compiler(no_tsp) -> None:
    api = _pets_api()
    result = _emit(api)
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": "namespace X;\n"})]})
    verdict = await validate_emitted_artifact("typespec", broken, api=api)
    assert verdict.failed


async def test_compile_errors_become_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(members, root, **_):
        raise ImportSourceError(
            "The TypeSpec set does not compile: Pet_Store.tsp:9:3 - error invalid-ref: Unknown identifier Nope; "
            "Pet_Store.tsp:12:1 - error token-expected: ';' expected.",
            code="INPUT_SEMANTIC_INVALID",
        )

    monkeypatch.setattr("app.typespec_compile.compile_typespec_set", failing)
    api = _pets_api()
    verdict = await validate_emitted_artifact("typespec", _emit(api), api=api)
    assert verdict.failed
    assert [(f.file, f.line, f.column, f.keyword) for f in verdict.findings] == [
        ("Pet_Store.tsp", 9, 3, "invalid-ref"), ("Pet_Store.tsp", 12, 1, "token-expected")]


@needs_tsp
async def test_validation_compiles_with_the_bundled_compiler() -> None:
    api = _pets_api()
    verdict = await validate_emitted_artifact("typespec", _emit(api), api=api)
    assert verdict.valid and verdict.validated


# ===========================================================================
# Acceptance: TypeSpec round trips; other formats export to TypeSpec that compiles
# ===========================================================================

_TYPESPEC_CORPUS = sorted((_EXAMPLES / "typespec").glob("*.tsp"))


@pytest.mark.parametrize("path", _TYPESPEC_CORPUS, ids=lambda p: p.name)
def test_typespec_corpus_round_trips(path: Path) -> None:
    api = _corpus_api(path, "typespec")
    result = _emit(api)
    assert result.losses == []
    assert canonical_diff(api, reimport_emitted(TypeSpecImportSource(), result, multi_file=False)).entries == []


_COMPILE_CORPUS: List[tuple] = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("openapi/22-advanced-oneof-polymorphism.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("avro/01-user-record.avsc", "avro"),
    ("json-schema/02-product-types.json", "json-schema"),
    ("thrift/01-user-service.thrift", "thrift"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    *[(f"typespec/{p.name}", "typespec") for p in _TYPESPEC_CORPUS],
]


@needs_tsp
@pytest.mark.parametrize(("path", "fmt"), _COMPILE_CORPUS, ids=lambda v: str(v))
def test_corpus_exports_compile(path: str, fmt: str) -> None:
    from app.typespec_compile import compile_typespec_set

    result = _emit(_corpus_api(_EXAMPLES / path, fmt))
    compile_typespec_set({result.files[0].path: result.files[0].content}, result.files[0].path)


def test_the_pets_export_reimports_through_the_reader() -> None:
    api = _pets_api()
    back = reimport_emitted(TypeSpecImportSource(), _emit(api), multi_file=False)
    assert {op.key for op in back.operations()} == {"GET /pets", "GET /pets/{pet-id}", "POST /pets"}
    pet = next(t for t in back.types if t.name == "Pet")
    assert [(f.name, f.type.nullable) for f in pet.fields] == [("id", False), ("name", False), ("tag", True)]
    assert pet.fields[2].description == "A free-form tag."
