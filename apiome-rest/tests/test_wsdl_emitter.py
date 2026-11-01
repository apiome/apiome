"""WSDL 1.1 + XSD emitter (document/literal) — MFX-14.1 (#3889).

Covers, in order:

* :mod:`app.xsd_types` — scalar → XSD built-in mapping, ``NCName`` names, regex translation;
* the two layouts (``bundle``: ``.wsdl`` + ``.xsd`` joined by ``xsd:import``; ``single``);
* types → XSD: lists, nullability, facets, enums, unions (``xs:choice``), maps, aliases, scalars,
  annotations, defaults — validated by ``xmlschema`` and with instance documents;
* document/literal wrapped operations for non-WSDL sources (parameters, body, result, faults);
* names, losses and the fidelity report (renames, namespace, maps, unsupported facets, events);
* the acceptance checks: corpus exports are valid XSD and WS-I clean, and every WSDL corpus file
  round-trips with no difference through the bundle.
"""

from __future__ import annotations

import re
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
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.roundtrip_matrix import reimport_emitted
from app.wsdl_emitter import WsdlEmitOptions, WsdlEmitter
from app.wsdl_import_source import WsdlImportSource
from app.wsdl_wsi import check_wsi
from app.xsd_types import is_ncname, ncname, xsd_builtin, xsd_pattern

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_XSD = "{http://www.w3.org/2001/XMLSchema}"


# ===========================================================================
# Helpers
# ===========================================================================


def _field(name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"Pet.{name}", name=name, type=ref, **kw)


def _api(types: List[Type], services: List[Service] = (), **identity) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi",
        identity=ApiIdentity(name="Pets", **identity),
        types=list(types),
        services=list(services),
    )


def _pet(*fields: CanonicalField, key: str = "Pet", name: str = "Pet") -> Type:
    return Type(key=key, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _emit(api: CanonicalApi, **opts):
    return WsdlEmitter().emit(api, opts=WsdlEmitOptions(**opts))


def _schema(result, tmp_path: Path) -> xmlschema.XMLSchema10:
    """Write the bundle to ``tmp_path`` and load its XSD with ``xmlschema`` (raises if invalid)."""
    for emitted in result.files:
        (tmp_path / emitted.path).write_text(emitted.content, encoding="utf-8")
    return xmlschema.XMLSchema10(str(tmp_path / result.files[1].path))


def _xsd_text(result) -> str:
    return result.files[1].content if len(result.files) > 1 else result.files[0].content


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".wsdl": "wsdl", ".yaml": "openapi", ".proto": "protobuf", ".graphql": "graphql", ".thrift": "thrift"}
    return build_conversion_source(
        {
            "id": "item-1",
            "name": path.stem,
            "source_format": fmt[path.suffix],
            "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")},
        }
    ).api


def _subjects(result) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for loss in result.losses:
        out.setdefault(loss.subject, []).append(loss.pointer or "")
    return out


# ===========================================================================
# app.xsd_types
# ===========================================================================


@pytest.mark.parametrize(
    ("name", "fmt", "hint", "expected"),
    [
        ("integer", None, None, "int"),
        ("integer", "int64", None, "long"),
        ("i64", None, None, "long"),
        ("uint64", None, None, "unsignedLong"),
        ("number", None, None, "double"),
        ("number", "float", None, "float"),
        ("number", "decimal", None, "decimal"),
        ("boolean", None, None, "boolean"),
        ("string", "date-time", None, "dateTime"),
        ("string", "date", None, "date"),
        ("string", "uri", None, "anyURI"),
        ("string", "byte", None, "base64Binary"),
        ("bytes", None, None, "base64Binary"),
        ("decimal", None, None, "decimal"),
        ("double", None, "decimal", "decimal"),  # an XSD source's recorded type wins
        ("string", None, "xs:dateTime", "dateTime"),
        ("Pet", None, None, None),
        (None, None, None, None),
    ],
)
def test_xsd_builtin(name, fmt, hint, expected) -> None:
    assert xsd_builtin(name, fmt, hint) == expected


@pytest.mark.parametrize(
    ("raw", "pascal", "expected"),
    [
        ("Pet", False, "Pet"),
        ("first_name", False, "first_name"),  # already legal: unchanged
        ("GET /pets/{petId}", False, "getPetsPetId"),
        ("pet store", True, "PetStore"),
        ("2xx", False, "_2xx"),
        ("", False, "item"),
    ],
)
def test_ncname(raw: str, pascal: bool, expected: str) -> None:
    assert ncname(raw, pascal=pascal) == expected
    assert is_ncname(expected)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("^[A-Z]{3}$", "[A-Z]{3}"),
        ("abc", ".*abc.*"),
        ("^a", "a.*"),
        ("b$", ".*b"),
        (r"cost\$", r".*cost\$.*"),  # an escaped dollar is a literal, not an anchor
        ("(?=x)a", None),
        ("a+?", None),
        (r"\bword", None),
        (r"^https?:\/\/.+$", "https?://.+"),  # `\/` is not an XSD escape; `/` means the same
        ("(a|b", None),  # not a valid regular expression at all
    ],
)
def test_xsd_pattern(pattern: str, expected) -> None:
    assert xsd_pattern(pattern) == expected


# ===========================================================================
# Layouts
# ===========================================================================


def test_bundle_is_a_wsdl_and_an_xsd_joined_by_an_import(tmp_path: Path) -> None:
    result = _emit(_api([_pet(_field("id", TypeRef(name="string")))]))
    assert [f.path for f in result.files] == ["Pets.wsdl", "Pets.xsd"]
    assert WsdlEmitter.multi_file
    wsdl, xsd = result.files[0].content, result.files[1].content
    assert '<xsd:import namespace="http://example.com/service" schemaLocation="Pets.xsd" />' in wsdl
    assert 'xmlns:tns="http://example.com/service"' in wsdl
    assert 'xmlns:tns="http://example.com/service"' in xsd and 'targetNamespace="http://example.com/service"' in xsd
    _schema(result, tmp_path)


def test_single_layout_inlines_the_schema() -> None:
    result = _emit(_api([_pet(_field("id", TypeRef(name="string")))]), layout="single")
    assert [f.path for f in result.files] == ["Pets.wsdl"]
    assert "<xsd:complexType name=\"Pet\">" in result.files[0].content
    assert "schemaLocation" not in result.files[0].content


# ===========================================================================
# Types → XSD
# ===========================================================================


def _rich_model() -> CanonicalApi:
    status = Type(
        key="Status",
        name="Status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.a", name="available", value="available"),
            EnumValue(key="Status.s", name="sold"),
        ],
    )
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Circle", "Square"])
    circle = Type(key="Circle", name="Circle", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Circle.r", name="r", type=TypeRef(name="number", nullable=False))
    ])
    square = Type(key="Square", name="Square", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Square.side", name="side", type=TypeRef(name="number", nullable=False))
    ])
    labels = Type(
        key="Labels",
        name="Labels",
        kind=TypeKind.MAP,
        key_type=TypeRef(name="string"),
        value_type=TypeRef(name="integer"),
    )
    pet_id = Type(key="PetId", name="PetId", kind=TypeKind.ALIAS, aliased=TypeRef(name="integer"))
    email = Type(key="Email", name="Email", kind=TypeKind.SCALAR, constraints=Constraints(pattern="^.+@.+$"))
    pet = _pet(
        _field("id", TypeRef(name="integer", nullable=False), constraints=Constraints(format="int64"),
               description="Unique id"),
        _field("name", TypeRef(name="string", nullable=False), constraints=Constraints(min_length=1, max_length=40)),
        _field("age", TypeRef(name="integer"), constraints=Constraints(minimum=0, exclusive_maximum=100)),
        _field("currency", TypeRef(name="string"), constraints=Constraints(pattern="^[A-Z]{3}$"), default="USD"),
        _field("tags", TypeRef(item=TypeRef(name="string")), constraints=Constraints(min_items=1, max_items=5)),
        _field("grid", TypeRef(item=TypeRef(item=TypeRef(name="integer")))),
        _field("status", TypeRef(name="Status")),
        _field("shape", TypeRef(name="Shape")),
        _field("labels", TypeRef(name="Labels")),
        _field("born", TypeRef(name="string"), constraints=Constraints(format="date-time")),
        _field("extra", TypeRef()),
    )
    return _api([pet, status, shape, circle, square, labels, pet_id, email])


def test_rich_model_is_a_valid_schema_with_the_expected_shapes(tmp_path: Path) -> None:
    result = _emit(_rich_model())
    schema = _schema(result, tmp_path)
    xsd = _xsd_text(result)
    assert '<xsd:element name="id" type="xsd:long">' in xsd  # int64 keeps its width
    assert "<xsd:documentation>Unique id</xsd:documentation>" in xsd
    assert '<xsd:minLength value="1" /><xsd:maxLength value="40" />' in xsd
    assert '<xsd:minInclusive value="0" /><xsd:maxExclusive value="100" />' in xsd
    assert '<xsd:pattern value="[A-Z]{3}" />' in xsd  # anchors removed: XSD patterns are anchored
    assert 'name="tags" minOccurs="1" maxOccurs="5" type="xsd:string"' in xsd
    assert 'name="age" minOccurs="0" nillable="true"' in xsd
    assert 'name="born" minOccurs="0" nillable="true" type="xsd:dateTime"' in xsd
    assert 'name="extra" minOccurs="0" nillable="true" type="xsd:anyType"' in xsd
    assert (
        '<xsd:simpleType name="Status"><xsd:restriction base="xsd:string">'
        '<xsd:enumeration value="available" />'
    ) in xsd
    assert '<xsd:complexType name="Shape"><xsd:choice><xsd:element name="circle" type="tns:Circle" />' in xsd
    assert '<xsd:element name="entry" minOccurs="0" maxOccurs="unbounded">' in xsd
    assert '<xsd:simpleType name="PetId"><xsd:restriction base="xsd:int" />' in xsd
    assert '<xsd:simpleType name="Email"><xsd:restriction base="xsd:string"><xsd:pattern value=".+@.+" />' in xsd
    assert "Pet" in schema.elements and "Shape" in schema.elements


def test_facets_are_enforced_on_instances(tmp_path: Path) -> None:
    schema = _schema(_emit(_rich_model()), tmp_path)
    ns = "http://example.com/service"
    valid = (
        f'<p:Pet xmlns:p="{ns}"><id>9007199254740993</id><name>Rex</name><age>3</age><currency>USD</currency>'
        "<tags>a</tags><status>sold</status></p:Pet>"
    )
    schema.validate(valid)
    for bad in (
        valid.replace("<age>3</age>", "<age>100</age>"),  # exclusive maximum
        valid.replace("<currency>USD</currency>", "<currency>usd</currency>"),  # pattern
        valid.replace("<name>Rex</name>", "<name></name>"),  # minLength
        valid.replace("<status>sold</status>", "<status>lost</status>"),  # enumeration
    ):
        assert not schema.is_valid(bad), bad


def test_the_default_satisfies_the_pattern(tmp_path: Path) -> None:
    """A JSON Schema default must stay valid under its translated pattern (it did not before)."""
    xsd = _xsd_text(_emit(_rich_model()))
    assert re.search(r'name="currency"[^>]*default="USD"', xsd)
    _schema(_emit(_rich_model()), tmp_path)


# ===========================================================================
# Operations (document/literal wrapped)
# ===========================================================================


def _service() -> Service:
    get_pet = Operation(
        key="GET /pets/{petId}",
        name="getPetById",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{petId}",
        parameters=[
            Parameter(
                key="GET /pets/{petId}#path.petId", name="petId", location=ParameterLocation.PATH,
                type=TypeRef(name="integer"), required=True, constraints=Constraints(format="int64"),
            ),
            Parameter(
                key="GET /pets/{petId}#header.X-Trace", name="X-Trace", location=ParameterLocation.HEADER,
                type=TypeRef(name="string"),
            ),
        ],
        messages=[
            Message(key="GET#200", role=MessageRole.RESPONSE, payload=TypeRef(name="Pet")),
            Message(key="GET#404", role=MessageRole.ERROR, status_code="404"),
        ],
    )
    create = Operation(
        key="POST /pets",
        name="POST /pets",
        kind=OperationKind.REQUEST_RESPONSE,
        messages=[Message(key="POST#req", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"), required=True)],
    )
    event = Operation(key="petAdded", name="petAdded", kind=OperationKind.PUBLISH)
    return Service(key="default", name="default", operations=[get_pet, create, event])


def test_wrapped_operations(tmp_path: Path) -> None:
    result = _emit(_api([_pet(_field("id", TypeRef(name="string")))], [_service()]))
    wsdl, xsd = result.files[0].content, _xsd_text(result)
    _schema(result, tmp_path)
    assert (
        '<xsd:element name="getPetById"><xsd:complexType><xsd:sequence>'
        '<xsd:element name="petId" type="xsd:long" />'
        '<xsd:element name="X-Trace" minOccurs="0" nillable="true" type="xsd:string" />'  # a legal NCName is kept
    ) in xsd
    assert (
        '<xsd:element name="getPetByIdResponse"><xsd:complexType><xsd:sequence>'
        '<xsd:element name="result" type="tns:Pet" />'
    ) in xsd
    assert '<xsd:element name="getPetByIdStatus404Fault">' in xsd
    assert (
        '<xsd:element name="postPets"><xsd:complexType><xsd:sequence>'
        '<xsd:element name="body" type="tns:Pet" />'
    ) in xsd
    assert '<wsdl:part name="parameters" element="tns:getPetById" />' in wsdl
    assert '<wsdl:fault name="Status404" message="tns:getPetByIdStatus404Fault" />' in wsdl
    assert '<soap:fault name="Status404" use="literal" />' in wsdl
    assert "petAdded" not in wsdl  # events are dropped (and reported)
    subjects = _subjects(result)
    assert "GET /pets/{petId}" in subjects["http-binding-dropped"]
    assert "petAdded" in subjects["event-operation-dropped"]
    assert "POST /pets" in subjects["renamed-identifier"]


def test_wrapped_export_is_ws_i_clean() -> None:
    result = _emit(_api([_pet(_field("id", TypeRef(name="string")))], [_service()]))
    issues, total = check_wsi(
        result.files[0].content, version="1.1", members={f.path: f.content for f in result.files}
    )
    assert total == 0, issues


# ===========================================================================
# Names, losses and the fidelity report
# ===========================================================================


def test_illegal_names_are_renamed_deduplicated_and_reported(tmp_path: Path) -> None:
    pet = _pet(
        _field("first name", TypeRef(name="string")),
        _field("firstName", TypeRef(name="string")),
        key="pet store",
        name="pet store",
    )
    other = Type(key="PetStore", name="PetStore", kind=TypeKind.RECORD)
    result = _emit(_api([pet, other]))
    xsd = _xsd_text(result)
    assert '<xsd:complexType name="PetStore">' in xsd and '<xsd:complexType name="PetStore2">' in xsd
    assert 'name="firstName"' in xsd and 'name="firstName2"' in xsd
    _schema(result, tmp_path)
    renamed = _subjects(result)["renamed-identifier"]
    assert "pet store" in renamed and "Pet.first name" in renamed

    report = compute_lossiness_for_emitter(_api([pet, other]), WsdlEmitter)
    rename_items = {i.construct_key: i for i in report.items if "style rules" in i.message}
    assert {"pet store", "Pet.first name"} <= set(rename_items)


def test_report_names_the_synthesized_target_namespace() -> None:
    report = compute_lossiness_for_emitter(_api([_pet()]), WsdlEmitter)
    root = [i for i in report.items if i.construct_key == ""]
    assert root and root[0].kind is LossinessKind.SYNTH and "http://example.com/service" in root[0].message
    with_ns = compute_lossiness_for_emitter(_api([_pet()], namespace="urn:pets"), WsdlEmitter)
    root = [i for i in with_ns.items if i.construct_key == ""]
    assert root and root[0].kind is LossinessKind.APPROX and "urn:pets" in root[0].message


def test_report_and_losses_for_xsd_gaps() -> None:
    labels = Type(key="Labels", name="Labels", kind=TypeKind.MAP, value_type=TypeRef(name="string"))
    pet = _pet(
        _field("score", TypeRef(name="number"), constraints=Constraints(multiple_of=0.5)),
        _field("code", TypeRef(name="string"), constraints=Constraints(pattern="(?=x)a")),
        _field("old", TypeRef(name="string"), deprecated=True),
    )
    api = _api([pet, labels])
    result = _emit(api)
    subjects = _subjects(result)
    assert "Labels" in subjects["map-as-entry-list"]
    assert {"Pet.score", "Pet.code"} <= set(subjects["unsupported-facet"])
    assert "Pet.old" in subjects["deprecated-dropped"]
    assert "pattern" not in _xsd_text(result)  # an untranslatable pattern is not written

    report = compute_lossiness_for_emitter(api, WsdlEmitter)
    by_key: Dict[str, List[str]] = {}
    for item in report.items:
        by_key.setdefault(item.construct_key, []).append(item.message)
    assert any("map" in m for m in by_key["Labels"])
    assert any("multipleOf" in m for m in by_key["Pet.score"])
    assert any("pattern" in m for m in by_key["Pet.code"])
    assert any("deprecat" in m for m in by_key["Pet.old"])


def test_capability_profile_matches_the_output() -> None:
    profile = WsdlEmitter.capability_profile()
    assert profile.unions and profile.nullability and profile.constraints and profile.operations
    assert not profile.field_identity and not profile.events


def test_header_comment_cannot_break_out() -> None:
    result = _emit(_api([_pet()]).model_copy(update={"identity": ApiIdentity(name="a -- b")}))
    assert result.files[0].content.startswith("<!-- Generated WSDL for a - - b -->")


# ===========================================================================
# Acceptance: corpus exports
# ===========================================================================

_CORPUS = [
    _EXAMPLES / "openapi" / "07-nullable-types.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "23-advanced-anyof-flexible.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "protobuf" / "01-simple-user.proto",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
]


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
def test_corpus_export_is_valid_xsd_and_ws_i_clean(path: Path, tmp_path: Path) -> None:
    result = WsdlEmitter().emit(_corpus_api(path))
    _schema(result, tmp_path)
    issues, total = check_wsi(
        result.files[0].content, version="1.1", members={f.path: f.content for f in result.files}
    )
    assert total == 0, issues


_WSDL_CORPUS = sorted((_EXAMPLES / "wsdl").glob("*.wsdl"))


@pytest.mark.parametrize("path", _WSDL_CORPUS, ids=lambda p: p.name)
def test_wsdl_corpus_round_trips_through_the_bundle_unchanged(path: Path) -> None:
    api = _corpus_api(path)
    result = WsdlEmitter().emit(api)
    again = reimport_emitted(WsdlImportSource(), result, multi_file=True)
    assert canonical_diff(api, again).entries == []


def test_wsdl_source_keeps_its_notification_operations() -> None:
    """WSDL 2.0 out-only operations are WSDL 1.1 notifications: written, not dropped."""
    path = _EXAMPLES / "wsdl2" / "04-stress-message-exchange-patterns.wsdl"
    api = _corpus_api(path.with_suffix(".wsdl"))
    result = WsdlEmitter().emit(api)
    assert "event-operation-dropped" not in _subjects(result)
    names = {op.name for service in api.services for op in service.operations}
    again = reimport_emitted(WsdlImportSource(), result, multi_file=True)
    assert {op.name for service in again.services for op in service.operations} == names


def test_losses_are_inferred_or_not_applicable() -> None:
    result = _emit(_rich_model())
    assert {loss.kind for loss in result.losses} <= {LossKind.INFERRED, LossKind.NA}


# ===========================================================================
# Field numbers and one-way operations in the report (MFX-14.4, #3892)
# ===========================================================================
#
# A WSDL or XSD import numbers every field by its sequence position, which the export keeps, so a WSDL
# source must not be reported as dropping them (the WSDL card read "lossy, 40% preserved" for a WSDL
# source). Real field numbers (Protobuf, Thrift) are still dropped. A one-way operation is written
# input-only, but WSDL 1.1 reads it back as request/response: an APPROX, never an OK.


def _numbered(fmt: str) -> CanonicalApi:
    pet = _pet(
        _field("id", TypeRef(name="string"), field_number=1),
        _field("name", TypeRef(name="string"), field_number=2),
    )
    return _api([pet]).model_copy(update={"format": fmt})


def _field_number_items(api: CanonicalApi) -> list:
    report = compute_lossiness_for_emitter(api, WsdlEmitter)
    return [item for item in report.items if "field number" in item.message]


@pytest.mark.parametrize("fmt", ["wsdl", "xsd"])
def test_a_wsdl_or_xsd_sources_positional_field_numbers_are_kept(fmt: str) -> None:
    assert _field_number_items(_numbered(fmt)) == []


@pytest.mark.parametrize("fmt", ["protobuf", "thrift", "openapi"])
def test_real_field_numbers_from_other_sources_are_still_dropped(fmt: str) -> None:
    items = _field_number_items(_numbered(fmt))
    assert {item.construct_key for item in items} == {"Pet.id", "Pet.name"}
    assert {item.kind for item in items} == {LossinessKind.DROP}


def test_an_imported_wsdl_exports_losslessly() -> None:
    report = compute_lossiness_for_emitter(_corpus_api(_EXAMPLES / "wsdl" / "02-order-service.wsdl"), WsdlEmitter)
    assert {item.kind for item in report.items} == {LossinessKind.OK}


def _one_way_api(name: str = "cancelOrder") -> CanonicalApi:
    operation = Operation(key=f"Orders.{name}", name=name, kind=OperationKind.ONE_WAY)
    return _api([_pet()], [Service(key="Orders", name="Orders", operations=[operation])])


def test_a_one_way_operation_is_reported_as_reading_back_as_request_response() -> None:
    report = compute_lossiness_for_emitter(_one_way_api(), WsdlEmitter)
    items = [item for item in report.items if item.construct_key == "Orders.cancelOrder"]
    assert [item.kind for item in items] == [LossinessKind.APPROX]
    assert "reads back as a request/response operation" in items[0].message


def test_a_renamed_one_way_operation_keeps_its_rename_beside_the_one_way_note() -> None:
    report = compute_lossiness_for_emitter(_one_way_api("cancel order"), WsdlEmitter)
    items = [item for item in report.items if item.construct_key == "Orders.cancel order"]
    assert len(items) == 2 and {item.kind for item in items} == {LossinessKind.APPROX}
    assert any("reads back as a request/response" in item.message for item in items)


def test_a_request_response_operation_gets_no_one_way_note() -> None:
    operation = Operation(key="Orders.getOrder", name="getOrder", kind=OperationKind.REQUEST_RESPONSE)
    report = compute_lossiness_for_emitter(
        _api([_pet()], [Service(key="Orders", name="Orders", operations=[operation])]), WsdlEmitter
    )
    assert not any("reads back as a request/response" in item.message for item in report.items)
