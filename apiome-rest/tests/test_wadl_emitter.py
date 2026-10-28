"""WADL emitter with linked XSD grammars — MFX-29.1 (#4173).

Covers, in order:

* the two layouts (``bundle``: ``.wadl`` + ``.xsd`` linked by ``<grammars><include>``; ``single``)
  and a model with no grammar at all;
* resources, methods, params (template / query / header), representations and statuses;
* what is dropped and reported (non-HTTP and event operations, cookie params, status ranges, extra
  servers, wrapped bodies) and the fidelity report;
* the WADL importer fixes the round trip needs (a prefixed root, an included grammar, request
  params, an inline-restricted field);
* the acceptance check: corpus exports are schema-valid WADL (the W3C submission schema, vendored as
  ``app/data/wadl_2009_02.xsd``) with valid linked XSD grammars, and every WADL corpus file
  round-trips with no difference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest
import xmlschema

from app.canonical_model import (
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
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.roundtrip_matrix import reimport_emitted
from app.wadl_emitter import WadlEmitOptions, WadlEmitter
from app.wadl_import_source import WadlImportSource
from app.wadl_parser import is_wadl, parse_wadl

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_WADL_SCHEMA = Path(__file__).resolve().parents[1] / "src" / "app" / "data" / "wadl_2009_02.xsd"


@pytest.fixture(scope="module")
def wadl_schema() -> xmlschema.XMLSchema10:
    """The W3C WADL submission schema (its `xml.xsd` import resolves from xmlschema's own copy)."""
    return xmlschema.XMLSchema10(str(_WADL_SCHEMA), allow="local")


# ===========================================================================
# Helpers
# ===========================================================================


def _pet() -> Type:
    return Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="Pet.id", name="id", type=TypeRef(name="integer", nullable=False),
                           constraints=Constraints(format="int64")),
            CanonicalField(key="Pet.name", name="name", type=TypeRef(name="string", nullable=False)),
        ],
    )


def _param(op: str, name: str, location: ParameterLocation, type_name: str = "string", **kw) -> Parameter:
    return Parameter(key=f"{op}#{location.value}.{name}", name=name, location=location,
                     type=TypeRef(name=type_name), **kw)


def _service() -> Service:
    get_pet = Operation(
        key="GET /pets/{petId}",
        name="getPetById",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{petId}",
        description="Fetch one pet",
        parameters=[
            _param("GET /pets/{petId}", "petId", ParameterLocation.PATH, "integer", required=True,
                   constraints=Constraints(format="int64")),
            _param("GET /pets/{petId}", "X-Trace", ParameterLocation.HEADER),
            _param("GET /pets/{petId}", "session", ParameterLocation.COOKIE),
        ],
        messages=[
            Message(key="GET#200", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="Pet"),
                    content_types=["application/json"]),
            Message(key="GET#404", role=MessageRole.ERROR, status_code="404"),
            Message(key="GET#5XX", role=MessageRole.ERROR, status_code="5XX"),
        ],
    )
    list_pets = Operation(
        key="GET /pets",
        name="GET /pets",  # unnamed: no method id is written
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets",
        parameters=[
            _param("GET /pets", "limit", ParameterLocation.QUERY, "integer", default=20),
            Parameter(key="GET /pets#query.tags", name="tags", location=ParameterLocation.QUERY,
                      type=TypeRef(item=TypeRef(name="string"))),
        ],
        messages=[Message(key="LIST#200", role=MessageRole.RESPONSE, status_code="200",
                          payload=TypeRef(item=TypeRef(name="Pet")))],
    )
    ping = Operation(key="GET /", name="ping", kind=OperationKind.REQUEST_RESPONSE, http_method="GET", http_path="/",
                     messages=[Message(key="PING#200", role=MessageRole.RESPONSE, status_code="200")])
    rpc = Operation(key="svc.Rebuild", name="Rebuild", kind=OperationKind.REQUEST_RESPONSE)
    event = Operation(key="petAdded", name="petAdded", kind=OperationKind.PUBLISH)
    return Service(key="default", name="default", operations=[get_pet, list_pets, ping, rpc, event])


def _api(**kw) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi",
        identity=ApiIdentity(name="Pets"),
        types=[_pet()],
        services=[_service()],
        servers=kw.pop("servers", [Server(url="https://pets.example.com/v1")]),
        **kw,
    )


def _write(result, directory: Path) -> Path:
    for emitted in result.files:
        (directory / emitted.path).write_text(emitted.content, encoding="utf-8")
    return directory / result.files[0].path


def _subjects(result) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for loss in result.losses:
        out.setdefault(loss.subject, []).append(loss.pointer or "")
    return out


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".wadl": "wadl", ".wsdl": "wsdl", ".yaml": "openapi", ".proto": "protobuf", ".graphql": "graphql"}
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt[path.suffix],
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


# ===========================================================================
# Layouts
# ===========================================================================


def test_bundle_links_the_grammar(tmp_path: Path, wadl_schema) -> None:
    result = WadlEmitter().emit(_api())
    assert [f.path for f in result.files] == ["Pets.wadl", "Pets.xsd"]
    assert WadlEmitter.multi_file
    wadl = result.files[0].content
    assert '<wadl:grammars><wadl:include href="Pets.xsd" /></wadl:grammars>' in wadl
    assert 'xmlns:tns="http://example.com/service"' in wadl and 'xmlns:xsd="http://www.w3.org/2001/XMLSchema"' in wadl
    wadl_schema.validate(str(_write(result, tmp_path)))
    grammar = xmlschema.XMLSchema10(str(tmp_path / "Pets.xsd"))
    assert "Pet" in grammar.elements


def test_single_layout_inlines_the_grammar(tmp_path: Path, wadl_schema) -> None:
    result = WadlEmitter().emit(_api(), opts=WadlEmitOptions(layout="single"))
    assert [f.path for f in result.files] == ["Pets.wadl"]
    assert "<wadl:grammars><xsd:schema" in result.files[0].content
    wadl_schema.validate(str(_write(result, tmp_path)))


def test_a_model_with_no_types_or_bodies_has_no_grammar(tmp_path: Path, wadl_schema) -> None:
    ping = Operation(key="GET /status", name="getStatus", kind=OperationKind.REQUEST_RESPONSE,
                     http_method="GET", http_path="/status")
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi", identity=ApiIdentity(name="Ping"),
                       services=[Service(key="s", name="s", operations=[ping])])
    result = WadlEmitter().emit(api)
    assert [f.path for f in result.files] == ["Ping.wadl"]
    assert "grammars" not in result.files[0].content
    wadl_schema.validate(str(_write(result, tmp_path)))
    report = compute_lossiness_for_emitter(api, WadlEmitter)
    assert not any("namespace" in item.message for item in report.items)


def test_a_model_with_no_http_operations_is_a_grammar_alone(tmp_path: Path, wadl_schema) -> None:
    api = _api().model_copy(update={"services": []})
    result = WadlEmitter().emit(api)
    assert "<wadl:resources" not in result.files[0].content  # `resources` may not be empty
    wadl_schema.validate(str(_write(result, tmp_path)))


# ===========================================================================
# Resources, methods, params, representations
# ===========================================================================


def test_resources_methods_and_params() -> None:
    wadl = WadlEmitter().emit(_api()).files[0].content
    assert '<wadl:resources base="https://pets.example.com/v1">' in wadl
    assert '<wadl:resource path="/"><wadl:method name="GET" id="ping">' in wadl  # root-path operation kept
    assert (
        '<wadl:resource path="{petId}"><wadl:param name="petId" style="template" type="xsd:long" required="true" />'
    ) in wadl
    assert '<wadl:method name="GET" id="getPetById"><wadl:doc>Fetch one pet</wadl:doc>' in wadl
    assert '<wadl:param name="X-Trace" style="header" type="xsd:string" required="false" />' in wadl
    assert '<wadl:param name="limit" style="query" type="xsd:int" required="false" default="20" />' in wadl
    assert 'name="tags" style="query" type="xsd:string" required="false" repeating="true"' in wadl
    assert '<wadl:method name="GET"><wadl:request>' in wadl  # GET /pets has no explicit id
    assert (
        '<wadl:response status="200"><wadl:representation mediaType="application/json" element="tns:Pet" />'
    ) in wadl
    assert '<wadl:response status="404" />' in wadl
    assert "session" not in wadl and "Rebuild" not in wadl and "petAdded" not in wadl


def test_a_list_body_is_wrapped_in_a_grammar_element() -> None:
    result = WadlEmitter().emit(_api())
    xsd = result.files[1].content
    assert '<xsd:element name="getPetsResponse200">' in xsd
    assert 'name="item" minOccurs="0" maxOccurs="unbounded" type="tns:Pet"' in xsd
    assert "LIST#200" in _subjects(result)["body-wrapped"]


def test_dropped_constructs_are_reported() -> None:
    result = WadlEmitter().emit(_api(servers=[Server(url="https://a.example.com"), Server(url="https://b.example.com")]))
    subjects = _subjects(result)
    assert "svc.Rebuild" in subjects["operation-without-http-binding"]
    assert "petAdded" in subjects["event-operation-dropped"]
    assert "GET /pets/{petId}#cookie.session" in subjects["parameter-dropped"]
    assert "GET#5XX" in subjects["status-range-dropped"]
    assert subjects["servers-dropped"] == ["servers"]
    no_server = WadlEmitter().emit(_api(servers=[]))
    assert "base-uri-synthesized" in _subjects(no_server)
    assert '<wadl:resources base="https://api.example.com/">' in no_server.files[0].content


def test_fidelity_report() -> None:
    report = compute_lossiness_for_emitter(_api(servers=[]), WadlEmitter)
    by_key: Dict[str, List] = {}
    for item in report.items:
        by_key.setdefault(item.construct_key, []).append(item)
    assert any(i.kind is LossinessKind.DROP for i in by_key["svc.Rebuild"])
    root_messages = " ".join(i.message for i in by_key[""])
    assert "target namespace" in root_messages and "base URI" in root_messages
    profile = WadlEmitter.capability_profile()
    assert profile.unions and profile.nullability and profile.constraints and not profile.field_identity


def test_illegal_method_id_is_renamed_and_reported() -> None:
    op = Operation(key="GET /x", name="get thing", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
                   http_path="/x")
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi", identity=ApiIdentity(name="X"),
                       services=[Service(key="s", name="s", operations=[op])])
    result = WadlEmitter().emit(api)
    assert 'id="getThing"' in result.files[0].content
    assert "GET /x" in _subjects(result)["renamed-identifier"]
    report = compute_lossiness_for_emitter(api, WadlEmitter)
    assert any("style rules" in i.message for i in report.items if i.construct_key == "GET /x")


# ===========================================================================
# Importer: what the round trip needs
# ===========================================================================


def test_a_prefixed_application_root_is_wadl() -> None:
    text = (
        '<wadl:application xmlns:wadl="http://wadl.dev.java.net/2009/02">'
        '<wadl:resources base="x"/></wadl:application>'
    )
    assert is_wadl(text)
    assert not is_wadl('<applicationX xmlns="http://wadl.dev.java.net/2009/02"/>')


def test_an_included_grammar_and_request_params_are_read() -> None:
    wadl = """<application xmlns="http://wadl.dev.java.net/2009/02" xmlns:tns="urn:g">
      <grammars><include href="g.xsd"/></grammars>
      <resources base="https://x/"><resource path="items"><method name="GET" id="list">
        <request><param name="q" style="query" type="xsd:string" required="false"/></request>
        <response status="200"><representation mediaType="application/xml" element="tns:Item"/></response>
      </method></resource></resources></application>"""
    grammar = """<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:tns="urn:g" targetNamespace="urn:g">
      <xsd:complexType name="Item"><xsd:sequence>
        <xsd:element name="code"><xsd:simpleType><xsd:restriction base="xsd:string"><xsd:maxLength value="3"/>
        </xsd:restriction></xsd:simpleType></xsd:element>
      </xsd:sequence></xsd:complexType><xsd:element name="Item" type="tns:Item"/></xsd:schema>"""
    document = parse_wadl(wadl, members={"g.xsd": grammar})
    assert document.target_namespace == "urn:g"
    assert [(t.name, [(f.name, f.type_expr) for f in t.fields]) for t in document.complex_types] == [
        ("Item", [("code", "string")])
    ]
    (operation,) = document.operations
    assert [(p.name, p.location, p.required) for p in operation.parameters] == [("q", "query", False)]
    assert operation.response_types == (("200", "Item"),)
    # Without the set's members the resources still import.
    assert parse_wadl(wadl).complex_types == ()


# ===========================================================================
# Acceptance: schema-valid WADL + linked XSD grammars; WADL round trips
# ===========================================================================

_CORPUS = [
    _EXAMPLES / "openapi" / "07-nullable-types.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "protobuf" / "02-grpc-service.proto",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
    _EXAMPLES / "wsdl" / "02-order-service.wsdl",
]


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
def test_corpus_export_is_schema_valid_wadl_with_a_valid_grammar(path: Path, tmp_path: Path, wadl_schema) -> None:
    result = WadlEmitter().emit(_corpus_api(path))
    wadl_schema.validate(str(_write(result, tmp_path)))
    if len(result.files) > 1:
        xmlschema.XMLSchema10(str(tmp_path / result.files[1].path))


@pytest.mark.parametrize("path", sorted((_EXAMPLES / "wadl").glob("*.wadl")), ids=lambda p: p.name)
def test_wadl_corpus_round_trips_unchanged(path: Path) -> None:
    api = _corpus_api(path)
    again = reimport_emitted(WadlImportSource(), WadlEmitter().emit(api), multi_file=True)
    assert canonical_diff(api, again).entries == []


@pytest.mark.parametrize("path", sorted((_EXAMPLES / "wadl").glob("*.wadl")), ids=lambda p: p.name)
def test_wadl_corpus_single_layout_round_trips_unchanged(path: Path) -> None:
    api = _corpus_api(path)
    result = WadlEmitter().emit(api, opts=WadlEmitOptions(layout="single"))
    again = WadlImportSource().normalize(WadlImportSource().parse(result.files[0].content))
    assert canonical_diff(api, again).entries == []
