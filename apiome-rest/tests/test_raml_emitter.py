"""RAML 1.0 emitter — MFX-17.1 (#3901).

Covers, in order:

* the document envelope (the ``#%RAML 1.0`` header first, title, version, baseUri and its
  parameters, mediaType) and YAML safety;
* types: records in field-number order with optional ``name?`` properties, enums, unions, aliases,
  maps, scalars, RAML-safe names, scalar widths and formats, and facets;
* resources and methods: uriParameters on the resource, query parameters, headers, displayName,
  bodies per media type, responses by status;
* what is not carried and reported, by the writer and by :class:`RamlFidelityRulePack`;
* emitted-output validation (:func:`app.export_validation.validate_emitted_artifact`), through the
  RAML reader and through AMF;
* the acceptance check: every RAML corpus file round-trips (unchanged, or with only the reported
  resource-type / trait flattening), and corpus exports from other formats re-parse as RAML (and
  pass AMF's RAML 1.0 validation when the toolchain is present).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest
import yaml

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
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
from app.emitter import EmitResult, LossKind
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import ImportSourceError, canonical_diff
from app.lossiness import LossinessKind
from app.raml_emitter import RamlEmitOptions, RamlEmitter, raml_scalar
from app.raml_import_source import RamlImportSource
from app.raml_parser import is_raml, parse_raml
from app.roundtrip_matrix import reconcile, reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


# ===========================================================================
# Helpers
# ===========================================================================


def _api(**kw) -> CanonicalApi:
    """A small model; keyword arguments override its parts."""
    defaults = dict(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pets"),
        title="Pets",
        version="1.0",
        services=[Service(key="default", name="default", operations=kw.pop("operations", []))],
        types=kw.pop("types", []),
    )
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _field(type_key: str, name: str, type_name: str = "string", *, number=None, nullable=False, **kw) -> CanonicalField:
    return CanonicalField(
        key=f"{type_key}.{name}", name=name, type=TypeRef(name=type_name, nullable=nullable), field_number=number, **kw
    )


def _op(method: str, path: str, *, name: str | None = None, **kw) -> Operation:
    key = f"{method} {path}"
    return Operation(
        key=key, name=name or key, kind=OperationKind.REQUEST_RESPONSE, http_method=method, http_path=path, **kw
    )


def _param(op: str, name: str, location: ParameterLocation, type_name: str = "string", **kw) -> Parameter:
    return Parameter(key=f"{op}#{location.value}.{name}", name=name, location=location,
                     type=TypeRef(name=type_name), **kw)


def _response(op: str, status: str, payload: str | None = None, **kw) -> Message:
    return Message(key=f"{op}#response.{status}", role=MessageRole.RESPONSE, status_code=status,
                   payload=TypeRef(name=payload) if payload else None, **kw)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return RamlEmitter().emit(api, opts=RamlEmitOptions(**opts) if opts else None)


def _doc(result: EmitResult) -> Dict:
    return yaml.safe_load(result.files[0].content)


def _subjects(result: EmitResult) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for loss in result.losses:
        out.setdefault(loss.subject, []).append(loss.pointer or "")
    return out


def _verdicts(api: CanonicalApi) -> Dict[str, List[LossinessKind]]:
    out: Dict[str, List[LossinessKind]] = {}
    for item in compute_lossiness_for_emitter(api, RamlEmitter()).items:
        out.setdefault(item.construct_key, []).append(item.kind)
    return out


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".raml": "raml", ".wadl": "wadl", ".wsdl": "wsdl", ".yaml": "openapi", ".proto": "protobuf",
           ".graphql": "graphql"}
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt[path.suffix],
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _pet() -> Type:
    return Type(key="Pet", name="Pet", kind=TypeKind.RECORD, description="A pet.", fields=[
        _field("Pet", "name", number=2),
        _field("Pet", "id", "i64", number=1),
        _field("Pet", "tag", number=3, nullable=True, description="Free-form tag."),
    ])


# ===========================================================================
# Document
# ===========================================================================


def test_header_is_the_first_line_and_the_document_parses() -> None:
    result = _emit(_api(types=[_pet()]))
    content = result.files[0].content
    assert content.splitlines()[0] == "#%RAML 1.0"
    assert content.splitlines()[1] == "# Generated by Apiome from Pets"
    assert is_raml(content)
    assert parse_raml(content).title == "Pets"
    assert result.files[0].path == "Pets.raml"
    assert result.files[0].media_type == "application/raml+yaml"


def test_comment_can_be_left_out() -> None:
    content = _emit(_api(types=[_pet()]), include_comments=False).files[0].content
    assert content.splitlines()[:2] == ["#%RAML 1.0", "title: Pets"]


def test_document_envelope() -> None:
    server = Server(url="https://{region}.example.com/{version}", variables=[
        ServerVariable(name="region", default="eu", enum=["eu", "us"], description="Region."),
        ServerVariable(name="version", default="v1"),
    ])
    api = _api(description="All about pets: dogs\nand cats.", version="1.0", servers=[server],
               operations=[_op("GET", "/pets", messages=[_response("GET /pets", "200", "string",
                                                                   content_types=["application/xml"])])])
    doc = _doc(_emit(api))
    assert list(doc)[:6] == ["title", "description", "version", "baseUri", "baseUriParameters", "mediaType"]
    assert doc["description"] == "All about pets: dogs\nand cats."
    assert doc["version"] == "1.0"  # a string, not the float 1.0
    assert doc["baseUri"] == "https://{region}.example.com/{version}"
    # `version` is RAML's own; it is not a declared base URI parameter.
    assert doc["baseUriParameters"] == {
        "region": {"type": "string", "description": "Region.", "enum": ["eu", "us"], "default": "eu"}
    }
    # The media type the bodies use.
    assert doc["mediaType"] == "application/xml"


def test_media_type_defaults() -> None:
    assert _doc(_emit(_api(types=[_pet()])))["mediaType"] == "application/json"
    assert _doc(_emit(_api(types=[_pet()]), media_type="application/yaml"))["mediaType"] == "application/yaml"


def test_a_missing_title_is_synthesized_and_reported() -> None:
    api = _api(title=None, identity=ApiIdentity(name="Orders"), types=[_pet()])
    result = _emit(api)
    assert _doc(result)["title"] == "Orders"
    assert "title-synthesized" in _subjects(result)
    assert LossinessKind.SYNTH in _verdicts(api)[""]


# ===========================================================================
# Types
# ===========================================================================


def test_record_keeps_field_number_order_and_optional_properties() -> None:
    result = _emit(_api(types=[_pet()]))
    pet = _doc(result)["types"]["Pet"]
    assert pet["description"] == "A pet."
    assert pet["type"] == "object"
    assert list(pet["properties"]) == ["id", "name", "tag?"]
    assert pet["properties"]["id"] == {"type": "integer", "format": "int64"}
    assert pet["properties"]["name"] == "string"
    assert pet["properties"]["tag?"] == {"type": "string", "description": "Free-form tag."}
    # Field numbers 1..n are the property order: nothing to report.
    assert "field-number-dropped" not in _subjects(result)


def test_field_numbers_that_are_not_positions_are_reported() -> None:
    type_ = Type(key="T", name="T", kind=TypeKind.RECORD,
                 fields=[_field("T", "a", number=1), _field("T", "b", number=5)])
    api = _api(types=[type_])
    assert _subjects(_emit(api))["field-number-dropped"] == ["T.b"]
    assert _verdicts(api)["T.b"] == [LossinessKind.DROP]
    assert "T.a" not in _verdicts(api)


def test_enum_union_alias_map_and_scalar_types() -> None:
    types = [
        Type(key="Status", name="Status", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="Status.OPEN", name="OPEN", value=0), EnumValue(key="Status.DONE", name="DONE", value=1),
        ]),
        Type(key="Cat", name="Cat", kind=TypeKind.RECORD, fields=[_field("Cat", "meow")]),
        Type(key="Dog", name="Dog", kind=TypeKind.RECORD, fields=[_field("Dog", "bark")]),
        Type(key="Animal", name="Animal", kind=TypeKind.UNION, union_members=["Cat", "Dog"]),
        Type(key="Cats", name="Cats", kind=TypeKind.ALIAS, aliased=TypeRef(item=TypeRef(name="Cat"))),
        Type(key="Labels", name="Labels", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
             value_type=TypeRef(name="i32")),
        Type(key="Sku", name="Sku", kind=TypeKind.SCALAR, constraints=Constraints(pattern="^[A-Z]{3}$")),
    ]
    api = _api(types=types)
    result = _emit(api)
    doc = _doc(result)["types"]
    assert doc["Status"] == {"type": "string", "enum": ["OPEN", "DONE"]}
    assert doc["Animal"] == {"type": "Cat | Dog"}
    assert doc["Cats"] == {"type": "Cat[]"}
    assert doc["Labels"] == {"type": "object", "properties": {"//": "integer"}}
    assert doc["Sku"] == {"type": "string", "pattern": "^[A-Z]{3}$"}
    assert _subjects(result)["custom-scalar"] == ["Sku"]
    verdicts = _verdicts(api)
    assert verdicts["Animal"] == [LossinessKind.OK]
    assert verdicts["Status"] == [LossinessKind.OK]
    assert verdicts["Sku"] == [LossinessKind.APPROX]


def test_enum_numbers_and_value_docs_are_reported() -> None:
    type_ = Type(key="Code", name="Code", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="Code.A", name="A", value=10, description="Alpha."),
    ])
    assert set(_subjects(_emit(_api(types=[type_])))) >= {"enum-values-dropped", "enum-docs-dropped"}


def test_type_names_are_made_raml_safe_and_unique() -> None:
    types = [
        Type(key="com.acme.Order", name="Order", namespace="com.acme", kind=TypeKind.RECORD),
        Type(key="org.other.Order", name="Order", namespace="org.other", kind=TypeKind.RECORD),
        Type(key="string", name="string", kind=TypeKind.RECORD),
        Type(key="Weird Name|x", name="Weird Name|x", kind=TypeKind.RECORD),
    ]
    api = _api(types=types)
    result = _emit(api)
    assert list(_doc(result)["types"]) == ["Order", "Order2", "string2", "Weird_Name_x"]
    subjects = _subjects(result)
    assert sorted(subjects["type-renamed"]) == ["Weird Name|x", "org.other.Order", "string"]
    assert sorted(subjects["namespace-dropped"]) == ["com.acme.Order", "org.other.Order"]
    verdicts = _verdicts(api)
    # A type declared under another name: its key is dropped, the declared name is synthesized.
    assert verdicts["string"] == [LossinessKind.DROP, LossinessKind.APPROX]
    assert verdicts["string2"] == [LossinessKind.SYNTH]
    assert verdicts["com.acme.Order"] == [LossinessKind.DROP]  # its namespace note is the key drop


def test_a_reference_to_a_renamed_type_uses_the_new_name() -> None:
    types = [
        Type(key="string", name="string", kind=TypeKind.RECORD),
        Type(key="Box", name="Box", kind=TypeKind.RECORD, fields=[_field("Box", "inner", "string")]),
    ]
    # A field naming the type key `string` refers to the declared type, not the built-in.
    assert _doc(_emit(_api(types=types)))["types"]["Box"]["properties"]["inner"] == "string2"


def test_an_undeclared_type_is_written_as_any_and_reported() -> None:
    type_ = Type(key="T", name="T", kind=TypeKind.RECORD, fields=[_field("T", "x", "Missing")])
    api = _api(types=[type_])
    result = _emit(api)
    assert _doc(result)["types"]["T"]["properties"]["x"] == "any"
    assert _subjects(result)["unknown-type"] == ["T.x"]
    assert _verdicts(api)["T.x"] == [LossinessKind.APPROX]


@pytest.mark.parametrize(
    ("name", "fmt", "expected"),
    [
        ("i64", None, ("integer", "int64", False)),
        ("integer", "int64", ("integer", "int64", False)),
        ("integer", None, ("integer", None, False)),
        ("uint32", None, ("integer", None, True)),
        ("float", None, ("number", "float", False)),
        ("number", None, ("number", None, False)),
        ("bool", None, ("boolean", None, False)),
        ("bytes", None, ("file", None, False)),
        ("string", "date-time", ("datetime", None, False)),
        ("string", "date", ("date-only", None, False)),
        ("string", "time", ("time-only", None, False)),
        ("date-time", None, ("datetime", None, False)),
        ("null", None, ("nil", None, False)),
    ],
)
def test_raml_scalar(name: str, fmt, expected) -> None:
    scalar = raml_scalar(name, fmt)
    assert (scalar.type, scalar.format, scalar.unsigned) == expected
    assert scalar.format_kept


def test_raml_scalar_unknowns() -> None:
    assert raml_scalar("Pet") is None
    assert raml_scalar(None) is None
    assert not raml_scalar("string", "email").format_kept


def test_facets_by_type() -> None:
    type_ = Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _field("T", "code", constraints=Constraints(min_length=2, max_length=8, pattern="^[a-z]+$", enum=["ab", "cd"]),
               default="ab"),
        _field("T", "count", "i32", constraints=Constraints(minimum=1.0, maximum=10.0, multiple_of=1.0)),
        CanonicalField(key="T.tags", name="tags", type=TypeRef(item=TypeRef(name="string"), nullable=False),
                       constraints=Constraints(min_items=1, max_items=5, unique_items=True)),
        _field("T", "size", "uint32"),
    ])
    props = _doc(_emit(_api(types=[type_])))["types"]["T"]["properties"]
    assert props["code"] == {"type": "string", "minLength": 2, "maxLength": 8, "pattern": "^[a-z]+$",
                             "enum": ["ab", "cd"], "default": "ab"}
    assert props["count"] == {"type": "integer", "format": "int32", "minimum": 1, "maximum": 10, "multipleOf": 1}
    assert props["tags"] == {"type": "string[]", "minItems": 1, "maxItems": 5, "uniqueItems": True}
    assert props["size"] == {"type": "integer", "minimum": 0}


def test_facets_raml_cannot_carry_are_reported() -> None:
    type_ = Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _field("T", "email", constraints=Constraints(format="email")),
        _field("T", "n", "i32", constraints=Constraints(pattern="^1", exclusive_minimum=0.0)),
        _field("T", "old", deprecated=True),
    ])
    api = _api(types=[type_])
    result = _emit(api)
    props = _doc(result)["types"]["T"]["properties"]
    assert props["email"] == "string"
    assert props["n"] == {"type": "integer", "format": "int32"}
    subjects = _subjects(result)
    assert subjects["format-dropped"] == ["T.email"]
    assert subjects["facet-dropped"] == ["T.n", "T.n"]
    assert subjects["deprecated-dropped"] == ["T.old"]
    verdicts = _verdicts(api)
    for key in ("T.email", "T.n", "T.old"):
        assert verdicts[key] == [LossinessKind.APPROX]


def test_strings_that_yaml_would_misread_are_quoted() -> None:
    type_ = Type(key="T", name="T", kind=TypeKind.RECORD, description="yes: really # not a comment",
                 fields=[_field("T", "on", description="null")])
    doc = _doc(_emit(_api(types=[type_])))
    assert doc["types"]["T"]["description"] == "yes: really # not a comment"
    assert doc["types"]["T"]["properties"]["on"]["description"] == "null"


# ===========================================================================
# Resources and methods
# ===========================================================================


def _pets_api() -> CanonicalApi:
    list_op = "GET /pets"
    get_op = "GET /pets/{petId}"
    create = "POST /pets"
    return _api(types=[_pet()], operations=[
        _op("GET", "/pets", name="listPets", description="List pets.", parameters=[
            _param(list_op, "limit", ParameterLocation.QUERY, "i32", constraints=Constraints(maximum=100.0),
                   default=20),
            _param(list_op, "X-Trace", ParameterLocation.HEADER, required=True, description="Trace id."),
        ], messages=[_response(list_op, "200")]),
        _op("POST", "/pets", messages=[
            Message(key=f"{create}#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"),
                    content_types=["application/json", "application/xml"]),
            _response(create, "201", "Pet", description="Created."),
            Message(key=f"{create}#error.400", role=MessageRole.ERROR, status_code="400",
                    payload=TypeRef(name="string")),
        ]),
        _op("GET", "/pets/{petId}", parameters=[
            _param(get_op, "petId", ParameterLocation.PATH, "i64", required=True, description="Pet id."),
        ], messages=[
            Message(key=f"{get_op}#response.200", role=MessageRole.RESPONSE, status_code="200",
                    payload=TypeRef(item=TypeRef(name="Pet")),
                    headers=[_field("h", "ETag", nullable=False)]),
        ]),
    ])


def test_resources_methods_parameters_and_bodies() -> None:
    doc = _doc(_emit(_pets_api()))
    assert [key for key in doc if key.startswith("/")] == ["/pets", "/pets/{petId}"]
    pets = doc["/pets"]
    assert list(pets) == ["get", "post"]
    get = pets["get"]
    assert get["displayName"] == "listPets"
    assert get["description"] == "List pets."
    assert get["queryParameters"] == {
        "limit": {"type": "integer", "format": "int32", "maximum": 100, "default": 20, "required": False}
    }
    assert get["headers"] == {"X-Trace": {"type": "string", "description": "Trace id."}}
    assert get["responses"] == {200: {}}
    post = pets["post"]
    assert "displayName" not in post  # the source did not name it
    assert post["body"] == {"application/json": {"type": "Pet"}, "application/xml": {"type": "Pet"}}
    assert post["responses"] == {
        201: {"description": "Created.", "body": {"application/json": {"type": "Pet"}}},
        400: {"body": {"application/json": {"type": "string"}}},
    }
    one = doc["/pets/{petId}"]
    assert one["uriParameters"] == {"petId": {"type": "integer", "format": "int64", "description": "Pet id."}}
    assert one["get"]["responses"][200] == {
        "headers": {"ETag": "string"}, "body": {"application/json": {"type": "Pet[]"}}
    }


def test_the_reader_reads_the_methods_back() -> None:
    document = parse_raml(_emit(_pets_api()).files[0].content)
    by_key = {(op.method, op.path): op for op in document.operations}
    get_one = by_key[("get", "/pets/{petId}")]
    assert [(p.name, p.location, p.required) for p in get_one.parameters] == [("petId", "path", True)]
    listing = by_key[("get", "/pets")]
    assert [(p.name, p.location, p.required) for p in listing.parameters] == [
        ("limit", "query", False), ("X-Trace", "header", True)
    ]
    assert by_key[("post", "/pets")].request_type == "Pet"
    assert by_key[("post", "/pets")].response_types == (("201", "Pet"), ("400", "string"))


def test_a_clean_rest_model_reports_only_the_document() -> None:
    api = _pets_api()
    result = _emit(api)
    assert set(_subjects(result)) == {"services-merged"}
    verdicts = _verdicts(api)
    assert verdicts[""] == [LossinessKind.APPROX]
    # RAML has no services: the source's `default` service does not come back; the title's does.
    assert verdicts["default"] == [LossinessKind.DROP]
    assert verdicts["Pets"] == [LossinessKind.SYNTH]
    assert all(kinds == [LossinessKind.OK] for key, kinds in verdicts.items() if key not in ("", "default", "Pets"))


def test_dropped_operations_are_reported() -> None:
    operations = [
        _op("GET", "/a"),
        _op("GET", "/a", name="again"),
        _op("TRACE", "/a"),
        Operation(key="rpc.Call", name="Call", kind=OperationKind.REQUEST_RESPONSE),
        Operation(key="evt", name="evt", kind=OperationKind.PUBLISH, http_method="POST", http_path="/evt"),
    ]
    operations[1] = operations[1].model_copy(update={"key": "again"})
    api = _api(operations=operations, channels=[Channel(key="orders", address="orders")])
    result = _emit(api)
    doc = _doc(result)
    assert [key for key in doc if key.startswith("/")] == ["/a"]
    assert sorted(_subjects(result)["operation-dropped"]) == ["TRACE /a", "again", "evt", "rpc.Call"]
    assert _subjects(result)["channel-dropped"] == ["orders"]
    verdicts = _verdicts(api)
    for key in ("again", "TRACE /a", "rpc.Call", "evt", "orders"):
        assert verdicts[key] == [LossinessKind.DROP], key
    assert verdicts["GET /a"] == [LossinessKind.OK]
    assert all(loss.kind is LossKind.NA for loss in result.losses if loss.subject == "operation-dropped")


def test_operation_losses_are_reported() -> None:
    op = "GET /x"
    api = _api(operations=[_op("GET", "/x", deprecated=True, tags=["admin"], parameters=[
        _param(op, "session", ParameterLocation.COOKIE),
    ], messages=[
        Message(key=f"{op}#response.4XX", role=MessageRole.RESPONSE, status_code="4XX"),
        Message(key=f"{op}#response.default", role=MessageRole.RESPONSE),
        _response(op, "200", "string"),
    ])])
    result = _emit(api)
    responses = _doc(result)["/x"]["get"]["responses"]
    assert responses == {200: {"body": {"application/json": {"type": "string"}}}}
    assert "queryParameters" not in _doc(result)["/x"]["get"]
    subjects = _subjects(result)
    # The status-less response would be 200, which the real 200 already is.
    for subject in ("parameter-dropped", "status-range-dropped", "deprecated-dropped", "tags-dropped",
                    "response-dropped"):
        assert subjects[subject] == ["GET /x"], subject
    assert _verdicts(api)["GET /x"] == [LossinessKind.APPROX]


def test_a_response_with_no_status_is_written_as_200_when_free() -> None:
    op = "GET /y"
    api = _api(operations=[_op("GET", "/y", messages=[
        Message(key=f"{op}#response", role=MessageRole.RESPONSE, payload=TypeRef(name="string")),
        _response(op, "404"),
    ])])
    result = _emit(api)
    assert list(_doc(result)["/y"]["get"]["responses"]) == [404, 200]
    assert _subjects(result)["status-synthesized"] == [op]
    assert _verdicts(api)[op] == [LossinessKind.APPROX]


def test_path_parameters_are_declared_once_per_resource() -> None:
    get, put = "GET /p/{id}", "PUT /p/{id}"
    api = _api(operations=[
        _op("GET", "/p/{id}", parameters=[_param(get, "id", ParameterLocation.PATH, required=True)]),
        _op("PUT", "/p/{id}", parameters=[_param(put, "id", ParameterLocation.PATH, "i32", required=True)]),
    ])
    result = _emit(api)
    assert _doc(result)["/p/{id}"]["uriParameters"] == {"id": "string"}
    assert _subjects(result)["parameter-merged"] == ["PUT /p/{id}"]
    assert _verdicts(api)["PUT /p/{id}"] == [LossinessKind.APPROX]
    assert _verdicts(api)["GET /p/{id}"] == [LossinessKind.OK]


def test_inline_schema_body_is_a_json_schema_type() -> None:
    op = "POST /raw"
    api = _api(operations=[_op("POST", "/raw", messages=[
        Message(key=f"{op}#request", role=MessageRole.REQUEST, payload_schema={"type": "object"}),
    ])])
    result = _emit(api)
    body = _doc(result)["/raw"]["post"]["body"]["application/json"]["type"]
    assert yaml.safe_load(body) == {"type": "object"}
    assert _subjects(result)["inline-schema"] == [op]


def test_a_path_without_a_slash_gets_one() -> None:
    assert "/health" in _doc(_emit(_api(operations=[_op("GET", "health")])))


# ===========================================================================
# Fidelity report and losses agree
# ===========================================================================


def test_extra_servers_and_source_details_are_reported() -> None:
    api = _api(servers=[Server(url="https://a.example.com", description="Prod"), Server(url="https://b.example.com")],
               identity=ApiIdentity(name="pets", namespace="acme"), extras={"openapi_version": "3.1.0"},
               types=[_pet()])
    result = _emit(api)
    assert _doc(result)["baseUri"] == "https://a.example.com"
    assert {"servers-dropped", "identity-dropped", "server-details-dropped", "document-details-dropped"} <= set(
        _subjects(result)
    )
    assert _verdicts(api)[""] == [LossinessKind.APPROX]


def test_a_raml_source_reports_nothing() -> None:
    api = _corpus_api(_EXAMPLES / "raml" / "01-simple-api.raml")
    assert _emit(api).losses == []
    assert all(kind is LossinessKind.OK for kinds in _verdicts(api).values() for kind in kinds)


def test_flattened_resource_types_and_traits_are_reported() -> None:
    api = _corpus_api(_EXAMPLES / "raml" / "04-resource-types-and-traits.raml")
    result = _emit(api)
    flattened = _subjects(result)["reuse-flattened"]
    assert flattened and all(key.startswith(("GET ", "POST ")) for key in flattened)
    assert "is:" not in result.files[0].content


# ===========================================================================
# Emitted-output validation
# ===========================================================================


@pytest.fixture
def no_amf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.raml_amf.amf_available", lambda: False)


async def test_validation_reparses_without_amf(no_amf) -> None:
    api = _pets_api()
    verdict = await validate_emitted_artifact("raml", _emit(api), api=api)
    assert (verdict.applicable, verdict.validated, verdict.valid) == (True, True, True)


async def test_validation_rejects_a_broken_document_without_amf(no_amf) -> None:
    api = _pets_api()
    result = _emit(api)
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": "#%RAML 1.0\n- x\n"})]})
    verdict = await validate_emitted_artifact("raml", broken, api=api)
    assert verdict.failed
    assert verdict.findings[0].file == "Pets.raml"


async def test_amf_violations_reject_and_warnings_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pets_api()
    result = _emit(api)
    monkeypatch.setattr("app.raml_amf.amf_available", lambda: True)
    reports = {
        "warning": [{"severity": "Warning", "constraint": "w", "message": "meh"}],
        "violation": [{"severity": "Violation", "constraint": "c", "message": "bad facet", "file": "Pets.raml",
                       "line": 7, "column": 3}],
    }
    for name, report in reports.items():
        monkeypatch.setattr("app.raml_amf.validate_raml_set_with_amf", lambda members, root, r=report: r)
        verdict = await validate_emitted_artifact("raml", result, api=api)
        if name == "warning":
            assert verdict.valid and verdict.validated
        else:
            assert verdict.failed
            finding = verdict.findings[0]
            assert (finding.message, finding.file, finding.line, finding.column, finding.keyword) == (
                "bad facet", "Pets.raml", 7, 3, "c"
            )


async def test_amf_going_missing_falls_back_to_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pets_api()
    monkeypatch.setattr("app.raml_amf.amf_available", lambda: True)

    def unavailable(members, root):
        raise ImportSourceError("gone", code="ADAPTER_UNAVAILABLE")

    monkeypatch.setattr("app.raml_amf.validate_raml_set_with_amf", unavailable)
    verdict = await validate_emitted_artifact("raml", _emit(api), api=api)
    assert verdict.valid and verdict.validated


# ===========================================================================
# Acceptance: RAML round trips; other formats export to RAML that re-parses
# ===========================================================================

_RAML_CORPUS = sorted((_EXAMPLES / "raml").glob("*.raml"))


@pytest.mark.parametrize("path", _RAML_CORPUS, ids=lambda p: p.name)
def test_raml_corpus_round_trips(path: Path, no_amf) -> None:
    api = _corpus_api(path)
    result = _emit(api)
    again = reimport_emitted(RamlImportSource(), result, multi_file=False)
    diff = canonical_diff(api, again)
    if "resource-types-and-traits" in path.name:
        # Only the resource type / trait names, which the method is written without (reported).
        assert {entry.entity for entry in diff.entries} == {"operation"}
        outcome = reconcile(diff, compute_lossiness_for_emitter(api, RamlEmitter()))
        assert outcome.ok, (outcome.unexplained, outcome.overclaims)
    else:
        assert diff.entries == []


_CORPUS = [
    _EXAMPLES / "openapi" / "07-nullable-types.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "protobuf" / "02-grpc-service.proto",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
    _EXAMPLES / "wsdl" / "02-order-service.wsdl",
    _EXAMPLES / "wadl" / "04-kitchen-sink.wadl",
]


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
async def test_corpus_export_reparses_as_raml(path: Path, no_amf) -> None:
    api = _corpus_api(path)
    result = _emit(api)
    assert result.files[0].content.startswith("#%RAML 1.0\n")
    verdict = await validate_emitted_artifact("raml", result, api=api)
    assert verdict.validated and verdict.valid, verdict.errors
    # Every loss the writer reports concerns something the fidelity report also names.
    report_keys = {item.construct_key for item in compute_lossiness_for_emitter(api, RamlEmitter()).items
                   if item.kind is not LossinessKind.OK}
    for loss in result.losses:
        assert loss.pointer in report_keys or loss.pointer.rsplit(".", 1)[0] in report_keys, loss


@pytest.mark.parametrize("path", [*_CORPUS, *_RAML_CORPUS], ids=lambda p: p.name)
def test_corpus_export_passes_amf(path: Path) -> None:
    from app.raml_amf import amf_available, validate_raml_set_with_amf

    if not amf_available():
        pytest.skip("the AMF toolchain is not available here")
    emitted = _emit(_corpus_api(path)).files[0]
    results = validate_raml_set_with_amf({emitted.path: emitted.content}, emitted.path)
    assert [r for r in results if r["severity"] == "Violation"] == []
