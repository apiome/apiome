"""Google API Discovery document emitter — MFX-29.2 (#4174).

Covers the acceptance criterion — **the emitted document validates against the Discovery metaschema, and a
reference client accepts it**:

* **the metaschema** — ``data/discovery_v1_meta_schema.json`` is a draft-04 schema built from the Discovery
  service's own description of its format; the published Google documents it was checked against validate, and
  every export of the corpus sources validates and keeps every rule of :mod:`app.discovery_validation`;
* **the reference client** — Google's API client library for Python (``googleapiclient.discovery``) builds a
  client from every export, and every method of it builds a request with the method's HTTP verb and URL.

Also: the document (name, id, version, URLs from the server), resources and methods (an imported Discovery
item keeps its own), parameters, bodies, the Discovery JSON Schema subset (the draft-04 mapping of MFX-21.1
spelled in Discovery terms), options, the round trip through the Discovery importer and the fidelity report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest
from googleapiclient.discovery import build_from_document
from jsonschema import Draft4Validator
from pydantic import ValidationError

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
    Server,
    ServerVariable,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.discovery_emitter import DiscoveryEmitOptions, DiscoveryEmitter
from app.discovery_import_source import DiscoveryImportSource
from app.discovery_validation import check_discovery_files, discovery_problems, meta_schema
from app.emitter import load_builtin_emitters
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

#: Corpus sources of every kind the export reads from (each imports without an external toolchain).
CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("openapi/22-advanced-oneof-polymorphism.yaml", "openapi"),
    ("openapi/07-nullable-types.yaml", "openapi"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
    ("wadl/04-kitchen-sink.wadl", "wadl"),
    ("raml/01-simple-api.raml", "raml"),
    ("json-schema/03-multiple-defs.json", "json-schema"),
    ("avro/01-user-record.avsc", "avro"),
    *[(f"discovery/{p.name}", "discovery") for p in sorted((_EXAMPLES / "discovery").glob("*.json"))],
]


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _load(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api


def _field(owner: str, name: str, ref: TypeRef, **kw: Any) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _pet() -> Type:
    return Type(key="Pet", name="Pet", kind=TypeKind.RECORD, fields=[
        _field("Pet", "id", TypeRef(name="i64", nullable=False)),
        _field("Pet", "name", TypeRef(name="string", nullable=False), constraints=Constraints(max_length=64)),
        _field("Pet", "status", TypeRef(name="Status")),
    ])


def _status() -> Type:
    return Type(key="Status", name="Status", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="Status.a", name="available", description="Ready to adopt"),
        EnumValue(key="Status.s", name="sold"),
    ])


def _operation(method: str, path: str, *, name: str = "", params=(), request=None, response=None,
               **kw: Any) -> Operation:
    key = f"{method} {path}"
    messages: List[Message] = []
    if request is not None:
        messages.append(Message(key=f"{key}#request", role=MessageRole.REQUEST, payload=request))
    if response is not None:
        messages.append(Message(key=f"{key}#response.200", role=MessageRole.RESPONSE, payload=response,
                                status_code="200"))
    return Operation(key=key, name=name or key, kind=OperationKind.REQUEST_RESPONSE, http_method=method,
                     http_path=path, parameters=list(params), messages=messages, **kw)


def _param(operation: str, name: str, location: ParameterLocation, ref: TypeRef, **kw: Any) -> Parameter:
    return Parameter(key=f"{operation}#{location.value}.{name}", name=name, location=location, type=ref, **kw)


def _petstore(*operations: Operation, servers=None, types=None) -> CanonicalApi:
    ops = list(operations) or [
        _operation("GET", "/pets", name="listPets", response=TypeRef(item=TypeRef(name="Pet")), params=[
            _param("GET /pets", "limit", ParameterLocation.QUERY, TypeRef(name="i32"),
                   constraints=Constraints(minimum=1, maximum=100), default=20),
            _param("GET /pets", "tags", ParameterLocation.QUERY, TypeRef(item=TypeRef(name="string"))),
        ]),
        _operation("POST", "/pets", name="createPet", request=TypeRef(name="Pet"), response=TypeRef(name="Pet")),
        _operation("GET", "/pets/{petId}", name="getPet", response=TypeRef(name="Pet"), params=[
            _param("GET /pets/{petId}", "petId", ParameterLocation.PATH, TypeRef(name="i64"), required=True),
        ]),
    ]
    return CanonicalApi(
        paradigm=ApiParadigm.REST, format="openapi", identity=ApiIdentity(name="Pet Store"), title="Pet Store",
        version="1.2.0", description="Pets for adoption.",
        servers=servers if servers is not None else [Server(url="https://pets.example.com/api/v1")],
        services=[Service(key="PetStore", name="PetStore", operations=ops)],
        types=types if types is not None else [_pet(), _status()],
    )


def _emit(api: CanonicalApi, **opts: Any):
    return DiscoveryEmitter().emit(api, opts=DiscoveryEmitOptions(**opts))


def _document(api: CanonicalApi, **opts: Any) -> Dict[str, Any]:
    return json.loads(_emit(api, **opts).files[0].content)


def _subjects(result) -> set:
    return {loss.subject for loss in result.losses}


def _methods(document: Dict[str, Any], resource: str) -> Dict[str, Any]:
    return document["resources"][resource]["methods"]


def _client_requests(service: Any, description: Dict[str, Any]) -> List[Any]:
    """Every method of a built client called with its required parameters (and a body when it takes one)."""
    requests = []
    for name, method in (description.get("methods") or {}).items():
        kwargs: Dict[str, Any] = {}
        for parameter in method.get("parameterOrder", []):
            schema = method["parameters"][parameter]
            value = schema["enum"][0] if schema.get("enum") else "1"
            kwargs[re.sub(r"[^A-Za-z0-9_]", "_", parameter)] = value
        if "request" in method:
            kwargs["body"] = {}
        requests.append((method, getattr(service, name)(**kwargs)))
    for name, resource in (description.get("resources") or {}).items():
        requests.extend(_client_requests(getattr(service, name)(), resource))
    return requests


# ===========================================================================
# The metaschema and the reference client (the acceptance criterion)
# ===========================================================================


def test_the_metaschema_is_a_draft_04_schema_of_the_discovery_format() -> None:
    schema = meta_schema()
    Draft4Validator.check_schema(schema)
    assert set(schema["definitions"]) == {"RestDescription", "RestResource", "RestMethod", "JsonSchema"}
    assert schema["definitions"]["RestDescription"]["properties"]["kind"]["enum"] == ["discovery#restDescription"]


def test_the_metaschema_accepts_a_published_google_document() -> None:
    sample = json.loads((_EXAMPLES / "discovery" / "05-webfonts-sample.json").read_text(encoding="utf-8"))
    assert discovery_problems(sample) == []


@pytest.mark.parametrize(("path", "fmt"), CORPUS, ids=lambda v: str(v))
def test_every_export_validates_against_the_metaschema(path: str, fmt: str) -> None:
    result = _emit(_load(path, fmt))
    assert check_discovery_files({f.path: f.content for f in result.files}) == []


@pytest.mark.parametrize(("path", "fmt"), CORPUS, ids=lambda v: str(v))
def test_the_reference_client_builds_every_export(path: str, fmt: str) -> None:
    content = _emit(_load(path, fmt)).files[0].content
    document = json.loads(content)
    service = build_from_document(content, developerKey="test-key")
    base = document["rootUrl"] + document["servicePath"]
    for method, request in _client_requests(service, document):
        assert request.method == method["httpMethod"]
        assert request.uri.startswith(document["rootUrl"])
        if not method["path"].startswith("/"):
            assert request.uri.startswith(base)


def test_the_reference_client_expands_the_path_and_query() -> None:
    content = _emit(_petstore()).files[0].content
    service = build_from_document(content, developerKey="k")
    request = service.pets().getPet(petId="42")
    assert (request.method, request.uri.split("?")[0]) == ("GET", "https://pets.example.com/api/v1/pets/42")
    listing = service.pets().listPets(limit=5, tags=["a", "b"])
    assert "limit=5" in listing.uri and "tags=a" in listing.uri and "tags=b" in listing.uri


# ===========================================================================
# The document
# ===========================================================================


def test_the_document_names_the_api_and_its_urls() -> None:
    document = _document(_petstore())
    assert {k: document[k] for k in ("kind", "discoveryVersion", "id", "name", "version", "protocol")} == {
        "kind": "discovery#restDescription", "discoveryVersion": "v1", "id": "petstore:1.2.0", "name": "petstore",
        "version": "1.2.0", "protocol": "rest"}
    assert (document["title"], document["description"]) == ("Pet Store", "Pets for adoption.")
    assert (document["rootUrl"], document["servicePath"], document["baseUrl"], document["basePath"]) == (
        "https://pets.example.com/", "api/v1/", "https://pets.example.com/api/v1/", "/api/v1/")
    assert _emit(_petstore()).files[0].path == "petstore.discovery.json"


def test_server_variables_take_their_defaults() -> None:
    api = _petstore(servers=[Server(url="https://{region}.example.com/v2",
                                    variables=[ServerVariable(name="region", default="eu")])])
    assert _document(api)["baseUrl"] == "https://eu.example.com/v2/"


def test_a_source_without_a_server_gets_a_placeholder_root() -> None:
    result = _emit(_petstore(servers=[]))
    document = json.loads(result.files[0].content)
    assert (document["rootUrl"], document["servicePath"]) == ("https://api.example.com/", "")
    assert "root-url-synthesized" in _subjects(result)


def test_servers_beyond_the_first_are_reported() -> None:
    result = _emit(_petstore(servers=[Server(url="https://a.example.com/"), Server(url="https://b.example.com/")]))
    assert json.loads(result.files[0].content)["rootUrl"] == "https://a.example.com/"
    assert "servers-dropped" in _subjects(result)


def test_name_and_version_options() -> None:
    document = _document(_petstore(), name="pets", version="v2")
    assert (document["name"], document["version"], document["id"]) == ("pets", "v2", "pets:v2")


@pytest.mark.parametrize("option", [{"name": "Pets"}, {"name": "pet-store"}, {"name": "1pets"},
                                    {"version": "v 1"}, {"indent": 9}])
def test_invalid_options_are_rejected(option: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DiscoveryEmitOptions(**option)


def test_indent_zero_writes_one_line() -> None:
    assert _emit(_petstore(), indent=0).files[0].content.count("\n") == 1


# ===========================================================================
# Resources and methods
# ===========================================================================


def test_methods_are_filed_under_their_first_path_segment() -> None:
    document = _document(_petstore())
    assert set(document["resources"]) == {"pets"}
    methods = _methods(document, "pets")
    assert set(methods) == {"listPets", "createPet", "getPet"}
    assert methods["getPet"] == {
        "id": "petstore.pets.getPet", "path": "pets/{petId}", "httpMethod": "GET",
        "parameters": {"petId": {"type": "string", "format": "int64", "location": "path", "required": True}},
        "parameterOrder": ["petId"], "response": {"$ref": "Pet"}}


def test_a_path_starting_with_a_parameter_is_a_top_level_method() -> None:
    op = _operation("GET", "/{tenant}/health", name="health", params=[
        _param("GET /{tenant}/health", "tenant", ParameterLocation.PATH, TypeRef(name="string"), required=True)])
    document = _document(_petstore(op))
    assert set(document["methods"]) == {"health"} and "resources" not in document


def test_unnamed_operations_and_name_clashes_are_reported() -> None:
    api = _petstore(_operation("GET", "/pets"), _operation("DELETE", "/pets/{id}", name="get pets"),
                    _operation("PUT", "/pets", name="getPets"))
    result = _emit(api)
    methods = _methods(json.loads(result.files[0].content), "pets")
    assert set(methods) == {"getPets", "getPets2", "deletePets"}
    assert "method-renamed" in _subjects(result)
    ids = [m["id"] for m in methods.values()]
    assert len(ids) == len(set(ids))


def test_an_imported_discovery_item_keeps_its_resources_names_and_ids() -> None:
    document = _document(_load("discovery/01-bookstore-api.json", "discovery"))
    assert (document["name"], document["id"]) == ("bookstore", "bookstore:v1")
    assert document["servicePath"] == "bookstore/v1/"
    reviews = document["resources"]["books"]["resources"]["reviews"]["methods"]
    assert reviews["list"]["id"] == "bookstore.books.reviews.list"
    assert reviews["list"]["path"] == "books/{bookId}/reviews"


def test_operations_without_an_http_binding_and_events_are_dropped() -> None:
    rpc = Operation(key="Echo", name="Echo", kind=OperationKind.REQUEST_RESPONSE)
    event = Operation(key="PetAdopted", name="PetAdopted", kind=OperationKind.PUBLISH, http_method="POST",
                      http_path="/adopted")
    result = _emit(_petstore(rpc, event))
    assert {"operation-without-http-binding", "event-operation-dropped"} <= _subjects(result)


# ===========================================================================
# Parameters and bodies
# ===========================================================================


def test_query_parameters_carry_their_facets() -> None:
    parameters = _methods(_document(_petstore()), "pets")["listPets"]["parameters"]
    assert parameters["limit"] == {"type": "integer", "format": "int32", "minimum": "1", "maximum": "100",
                                   "default": "20", "location": "query"}
    assert parameters["tags"] == {"type": "string", "location": "query", "repeated": True}


def test_an_enum_parameter_lists_its_values() -> None:
    op = _operation("GET", "/pets/search", name="search", params=[
        _param("GET /pets/search", "status", ParameterLocation.QUERY, TypeRef(name="Status"))])
    status = _methods(_document(_petstore(op)), "pets")["search"]["parameters"]["status"]
    assert status["enum"] == ["available", "sold"] and status["type"] == "string"


def test_header_and_cookie_parameters_are_dropped() -> None:
    op = _operation("GET", "/pets/me", name="me", params=[
        _param("GET /pets/me", "X-Trace", ParameterLocation.HEADER, TypeRef(name="string")),
        _param("GET /pets/me", "session", ParameterLocation.COOKIE, TypeRef(name="string"))])
    result = _emit(_petstore(op))
    assert "parameters" not in _methods(json.loads(result.files[0].content), "pets")["me"]
    assert [loss.subject for loss in result.losses].count("parameter-dropped") == 2


def test_path_parameters_are_required_and_renamed_when_not_identifiers() -> None:
    op = _operation("GET", "/pets/{pet-id}", name="getOne", params=[
        _param("GET /pets/{pet-id}", "pet-id", ParameterLocation.PATH, TypeRef(name="string"))])
    result = _emit(_petstore(op))
    method = _methods(json.loads(result.files[0].content), "pets")["getOne"]
    assert method["path"] == "pets/{petId}" and method["parameters"]["petId"]["required"] is True
    assert {"parameter-renamed", "path-parameter-required"} <= _subjects(result)


def test_an_undeclared_path_variable_becomes_a_parameter() -> None:
    result = _emit(_petstore(_operation("GET", "/pets/{id}", name="byId")))
    method = _methods(json.loads(result.files[0].content), "pets")["byId"]
    assert method["parameters"]["id"] == {"type": "string", "location": "path", "required": True}


def test_a_body_that_is_not_one_named_type_gets_a_schema() -> None:
    result = _emit(_petstore())
    document = json.loads(result.files[0].content)
    assert _methods(document, "pets")["listPets"]["response"] == {"$ref": "ListPetsResponse"}
    assert document["schemas"]["ListPetsResponse"] == {"id": "ListPetsResponse", "type": "array",
                                                       "items": {"$ref": "Pet"}}
    assert _methods(document, "pets")["createPet"]["request"] == {"$ref": "Pet"}


def test_only_the_success_response_is_written() -> None:
    op = _operation("GET", "/pets/{petId}", name="getPet", response=TypeRef(name="Pet"))
    op.messages.append(Message(key="GET /pets/{petId}#response.404", role=MessageRole.ERROR,
                               payload=TypeRef(name="Status"), status_code="404"))
    result = _emit(_petstore(op))
    assert _methods(json.loads(result.files[0].content), "pets")["getPet"]["response"] == {"$ref": "Pet"}
    assert "response-dropped" in _subjects(result)


# ===========================================================================
# Schemas: the Discovery subset
# ===========================================================================


def _schema_of(field: CanonicalField) -> Dict[str, Any]:
    api = _petstore(types=[Type(key="T", name="T", kind=TypeKind.RECORD, fields=[field])])
    return _document(api)["schemas"]["T"]["properties"][field.name]


@pytest.mark.parametrize(("scalar", "expected"), [
    ("string", {"type": "string"}),
    ("i32", {"type": "integer", "format": "int32"}),
    ("i64", {"type": "string", "format": "int64"}),
    ("integer", {"type": "integer", "format": "int32"}),
    ("double", {"type": "number", "format": "double"}),
    ("float", {"type": "number", "format": "float"}),
    ("decimal", {"type": "number", "format": "double"}),
    ("bool", {"type": "boolean"}),
    ("bytes", {"type": "string", "format": "byte"}),
    ("date", {"type": "string", "format": "date"}),
    ("datetime", {"type": "string", "format": "date-time"}),
    ("uuid", {"type": "string"}),
])
def test_scalars_use_the_discovery_type_and_format_table(scalar: str, expected: Dict[str, Any]) -> None:
    assert _schema_of(_field("T", "v", TypeRef(name=scalar))) == expected


def test_records_mark_required_properties_and_reference_by_id() -> None:
    schemas = _document(_petstore())["schemas"]
    assert schemas["Pet"] == {"id": "Pet", "type": "object", "properties": {
        "id": {"type": "string", "format": "int64", "required": True},
        "name": {"type": "string", "required": True},
        "status": {"$ref": "Status"}}}
    assert schemas["Status"] == {"id": "Status", "type": "string", "enum": ["available", "sold"],
                                 "enumDescriptions": ["Ready to adopt", ""]}


def test_facets_discovery_has_are_kept_as_strings() -> None:
    field = _field("T", "n", TypeRef(name="i32"), constraints=Constraints(minimum=0, maximum=9, pattern="^[0-9]$"),
                   default=3, description="A digit", deprecated=True)
    assert _schema_of(field) == {"type": "integer", "format": "int32", "description": "A digit", "pattern": "^[0-9]$",
                                 "minimum": "0", "maximum": "9", "default": "3", "deprecated": True}


def test_keywords_discovery_lacks_are_dropped_and_reported() -> None:
    field = _field("T", "s", TypeRef(name="string"), constraints=Constraints(max_length=5, min_length=1))
    api = _petstore(types=[Type(key="T", name="T", kind=TypeKind.RECORD, fields=[field])])
    result = _emit(api)
    assert json.loads(result.files[0].content)["schemas"]["T"]["properties"]["s"] == {"type": "string"}
    assert {loss.detail.split(";")[0] for loss in result.losses if loss.subject == "keyword-dropped"} == {
        "Discovery has no `maxLength` keyword", "Discovery has no `minLength` keyword"}


def test_unions_are_any_and_maps_are_additional_properties() -> None:
    types = [_pet(), _status(),
             Type(key="Thing", name="Thing", kind=TypeKind.UNION, union_members=["Pet", "Status"]),
             Type(key="Tags", name="Tags", kind=TypeKind.MAP, value_type=TypeRef(name="string"))]
    result = _emit(_petstore(types=types))
    schemas = json.loads(result.files[0].content)["schemas"]
    assert schemas["Thing"] == {"id": "Thing", "description": "One of: Pet, Status.", "type": "any"}
    assert schemas["Tags"] == {"id": "Tags", "type": "object", "additionalProperties": {"type": "string"}}
    assert "union-as-any" in _subjects(result)


def test_an_inline_body_resolves_its_source_references() -> None:
    op = _operation("GET", "/pets/all", name="all")
    op.messages.append(Message(key="GET /pets/all#response.200", role=MessageRole.RESPONSE, status_code="200",
                               payload_schema={"type": "object", "properties": {
                                   "data": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}}}))
    schemas = _document(_petstore(op))["schemas"]
    assert schemas["AllResponse"]["properties"]["data"]["items"] == {"$ref": "Pet"}


# ===========================================================================
# Round trip and fidelity
# ===========================================================================


@pytest.mark.parametrize("name", ["02-minimal-ping.json", "05-webfonts-sample.json"])
def test_an_imported_discovery_document_reads_back_unchanged(name: str) -> None:
    api = _load(f"discovery/{name}", "discovery")
    back = reimport_emitted(DiscoveryImportSource(), _emit(api), multi_file=False)
    assert canonical_diff(api, back).entries == []


@pytest.mark.parametrize("name", ["03-components-refs.json", "04-stress-widgets.json"])
def test_a_base_url_without_its_service_path_is_completed_and_reported(name: str) -> None:
    api = _load(f"discovery/{name}", "discovery")
    result = _emit(api)
    document = json.loads(result.files[0].content)
    assert document["baseUrl"] == document["rootUrl"] + document["servicePath"] and document["servicePath"]
    assert "base-url-completed" in _subjects(result)
    back = reimport_emitted(DiscoveryImportSource(), result, multi_file=False)
    assert [(e.entity, e.key) for e in canonical_diff(api, back).entries] == [("root", "")]
    assert back.servers[0].url == document["baseUrl"]


def test_the_report_explains_what_the_export_changes() -> None:
    report = compute_lossiness_for_emitter(_petstore(), DiscoveryEmitter(), options={})
    by_mapping = {(i.construct_key, i.target_mapping): i.kind for i in report.items}
    assert by_mapping[("", "document → Discovery restDescription")] is LossinessKind.APPROX
    assert by_mapping[("Pet.id", "int64-as-string")] is LossinessKind.APPROX
    assert by_mapping[("GET /pets", "body-schema-synthesized")] is LossinessKind.SYNTH
    assert by_mapping[("ListPetsResponse", "body → schemas/ListPetsResponse")] is LossinessKind.SYNTH


def test_an_imported_discovery_document_is_lossless() -> None:
    api = _load("discovery/05-webfonts-sample.json", "discovery")
    report = compute_lossiness_for_emitter(api, DiscoveryEmitter(), options={})
    assert [i for i in report.items if i.kind is not LossinessKind.OK] == []


# ===========================================================================
# The document's rules (app.discovery_validation)
# ===========================================================================


def _broken(mutate) -> List[str]:
    document = _document(_petstore())
    mutate(document)
    return [problem.rule for problem in discovery_problems(document)]


@pytest.mark.parametrize(("mutate", "rule"), [
    (lambda d: d.update(kind="discovery#other"), "discovery.schema"),
    (lambda d: d.pop("rootUrl"), "discovery.schema"),
    (lambda d: _methods(d, "pets")["getPet"].update(httpMethod="get"), "discovery.schema"),
    (lambda d: _methods(d, "pets")["getPet"]["parameters"]["petId"].update(location="header"), "discovery.schema"),
    (lambda d: d.update(rootUrl="pets.example.com"), "discovery.urls"),
    (lambda d: d.update(servicePath="/api/v1/"), "discovery.urls"),
    (lambda d: d.update(baseUrl="https://elsewhere.example.com/"), "discovery.urls"),
    (lambda d: d["schemas"]["Pet"].update(id="Animal"), "discovery.schema-id"),
    (lambda d: d["schemas"]["Pet"]["properties"]["status"].update({"$ref": "Missing"}), "discovery.ref"),
    (lambda d: _methods(d, "pets")["getPet"].update(response={"$ref": "Missing"}), "discovery.ref"),
    (lambda d: d["schemas"]["Pet"]["properties"]["name"].update(format="int32"), "discovery.type-format"),
    (lambda d: _methods(d, "pets")["listPets"].update(id="petstore.pets.getPet"), "discovery.method-id"),
    (lambda d: _methods(d, "pets")["getPet"].update(path="pets/{id}"), "discovery.path-parameter"),
    (lambda d: _methods(d, "pets")["getPet"]["parameters"]["petId"].pop("required"), "discovery.path-parameter"),
    (lambda d: _methods(d, "pets")["getPet"].update(parameterOrder=["petId", "petId"]), "discovery.parameter-order"),
])
def test_the_rules_reject_broken_documents(mutate, rule: str) -> None:
    assert rule in _broken(mutate)


def test_an_export_is_one_discovery_file_of_json() -> None:
    assert [p.rule for p in check_discovery_files({})] == ["discovery.files"]
    assert [p.rule for p in check_discovery_files({"a.discovery.json": "{"})] == ["discovery.schema"]
