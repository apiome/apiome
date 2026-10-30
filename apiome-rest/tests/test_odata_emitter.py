"""OData emitter — MFX-16.1 (#3897).

Covers, in order:

* CSDL JSON 4.01 as the canonical output, CSDL XML on request (``output``), both views of one model;
* primitive coercion (:func:`app.odata_emitter.edm_type`): widths, formats, temporal and GUID types, unsigned
  widening and unknown spellings reported;
* types: entity vs complex types, ``$Key`` from the source / inferred from an id-like property / synthesized
  (``SYNTH``), enums, type definitions, unions and maps approximated, aliases inlined, renames;
* properties: collections, nullability, navigation properties, ``$MaxLength`` / ``$DefaultValue``, the
  ``Validation`` and ``Core`` annotations, constraints with no CSDL form reported;
* operations: CRUD served by entity sets, every other operation an unbound Function or Action with an
  import, headers / cookies / errors / events / streams reported;
* OData 2 / 3 sources: facets kept, ``sap:`` / ``m:`` annotations and the version upgrade reported;
* the fidelity pack agreeing with the writer, and emitted-output validation (OASIS CSDL JSON schema / CSDL
  XML schemas, then a re-parse);
* acceptance: every OData 4 corpus file round-trips (unchanged, or with only its reported synthesized
  keys); exports of the whole corpus are valid CSDL JSON and CSDL XML.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, LossKind
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.odata_emitter import ODataEmitOptions, ODataEmitter, edm_type, validate_odata_document
from app.odata_import_source import ODataImportSource
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_NS = "Pet.Store"


def _field(owner: str, name: str, ref: str = "string", **kw) -> CanonicalField:
    item = kw.pop("item", None)
    type_ref = TypeRef(item=TypeRef(name=item), nullable=kw.pop("nullable", True)) if item else TypeRef(
        name=ref, nullable=kw.pop("nullable", True))
    return CanonicalField(key=f"{owner}.{name}", name=name, type=type_ref, **kw)


def _record(name: str, *fields: CanonicalField, **kw) -> Type:
    return Type(key=kw.pop("key", name), name=name, kind=TypeKind.RECORD, fields=list(fields), **kw)


def _api(*, types=(), operations=(), **kw) -> CanonicalApi:
    services = [Service(key="svc", name="Pets", operations=list(operations))] if operations else []
    defaults = dict(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Pet Store"),
                    title="Pet Store", types=list(types), services=services)
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _msg(key: str, role: MessageRole, payload: Any = None, **kw) -> Message:
    ref = payload if isinstance(payload, TypeRef) or payload is None else TypeRef(name=payload)
    return Message(key=key, role=role, payload=ref, **kw)


def _op(key: str, method: str = None, path: str = None, **kw) -> Operation:
    return Operation(key=key, name=kw.pop("name", "op"), kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE),
                     http_method=method, http_path=path, **kw)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return ODataEmitter().emit(api, opts=ODataEmitOptions(**opts) if opts else None)


def _doc(api: CanonicalApi) -> Dict[str, Any]:
    return json.loads(_emit(api).files[0].content)


def _schema(doc: Dict[str, Any]) -> Dict[str, Any]:
    return next(v for k, v in doc.items() if not k.startswith("$"))


def _losses(result: EmitResult) -> List[tuple]:
    return sorted((loss.subject, loss.pointer or "") for loss in result.losses)


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _pets_api() -> CanonicalApi:
    pet = _record("Pet", _field("Pet", "id", "integer", nullable=False, constraints=Constraints(format="int64")),
                  _field("Pet", "name", nullable=False, constraints=Constraints(max_length=40, pattern="^[a-z]+$")),
                  _field("Pet", "tags", item="string"), _field("Pet", "owner", "Owner"),
                  _field("Pet", "born", constraints=Constraints(format="date-time"), description="Birth time."))
    owner = _record("Owner", _field("Owner", "name"))
    ops = [
        _op("GET /pets", "GET", "/pets", name="listPets",
            parameters=[Parameter(key="GET /pets#query.limit", name="limit", location=ParameterLocation.QUERY,
                                  type=TypeRef(name="integer"))],
            messages=[_msg("GET /pets#200", MessageRole.RESPONSE, TypeRef(item=TypeRef(name="Pet")),
                           status_code="200")]),
        _op("GET /pets/{id}", "GET", "/pets/{id}", name="getPet",
            messages=[_msg("GET /pets/{id}#200", MessageRole.RESPONSE, "Pet", status_code="200")]),
        _op("POST /pets", "POST", "/pets", name="createPet",
            messages=[_msg("POST /pets#request", MessageRole.REQUEST, "Pet", required=True),
                      _msg("POST /pets#201", MessageRole.RESPONSE, "Pet", status_code="201")]),
        _op("GET /pets/search", "GET", "/pets/search", name="searchPets",
            parameters=[Parameter(key="GET /pets/search#query.q", name="q", location=ParameterLocation.QUERY,
                                  type=TypeRef(name="string"), required=True),
                        Parameter(key="GET /pets/search#header.X-Trace", name="X-Trace",
                                  location=ParameterLocation.HEADER, type=TypeRef(name="string"))],
            messages=[_msg("GET /pets/search#200", MessageRole.RESPONSE, TypeRef(item=TypeRef(name="Pet")),
                           status_code="200"),
                      _msg("GET /pets/search#400", MessageRole.ERROR, status_code="400")]),
        _op("POST /pets/{id}/feed", "POST", "/pets/{id}/feed", name="feedPet",
            messages=[_msg("POST /pets/{id}/feed#request", MessageRole.REQUEST, "integer")]),
    ]
    return _api(types=[pet, owner], operations=ops, version="1.0.0", servers=[Server(url="https://x")])


# ===========================================================================
# Output forms
# ===========================================================================


def test_csdl_json_is_the_default_and_xml_is_on_request() -> None:
    api = _pets_api()
    (json_file,) = _emit(api).files
    assert json_file.path == f"{_NS}.csdl.json" and json_file.media_type == "application/json"
    doc = json.loads(json_file.content)
    assert doc["$Version"] == "4.01" and doc["$EntityContainer"] == f"{_NS}.Container"
    (xml_file,) = _emit(api, output="xml").files
    assert xml_file.path == f"{_NS}.edmx" and xml_file.content.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert [f.path for f in _emit(api, output="both").files] == [f"{_NS}.csdl.json", f"{_NS}.edmx"]
    for file in _emit(api, output="both").files:
        validate_odata_document(file.content)


def test_nothing_to_describe_is_refused() -> None:
    with pytest.raises(EmitPreconditionError):
        _emit(_api())


@pytest.mark.parametrize(("name", "fmt", "expected"), [
    ("integer", None, ("Edm.Int32", True)), ("integer", "int64", ("Edm.Int64", True)),
    ("i64", None, ("Edm.Int64", True)), ("number", "float", ("Edm.Single", True)),
    ("bool", None, ("Edm.Boolean", True)),
    ("string", "date-time", ("Edm.DateTimeOffset", True)), ("string", "uuid", ("Edm.Guid", True)),
    ("timestamp", None, ("Edm.DateTimeOffset", True)), ("date", None, ("Edm.Date", True)),
    ("decimal", None, ("Edm.Decimal", True)), ("bytes", None, ("Edm.Binary", True)),
    ("uint32", None, ("Edm.Int64", False)), ("uint64", None, ("Edm.Decimal", False)),
    ("any", None, ("Edm.Untyped", True)), ("ID", None, ("Edm.String", True)),
    ("Snowflake", None, ("Edm.String", False)),
    ("Edm.Guid", None, ("Edm.Guid", True)),
])
def test_edm_type(name: str, fmt: str, expected: tuple) -> None:
    assert edm_type(name, fmt) == expected


# ===========================================================================
# Types and properties
# ===========================================================================


def test_entities_keys_properties_and_annotations() -> None:
    result = _emit(_pets_api())
    doc = json.loads(result.files[0].content)
    schema = _schema(doc)
    pet = schema["Pet"]
    assert pet["$Kind"] == "EntityType" and pet["$Key"] == ["id"]
    assert pet["id"] == {"$Type": "Edm.Int64"}
    assert pet["name"] == {"$MaxLength": 40, "@Validation.Pattern": "^[a-z]+$"}
    assert pet["tags"] == {"$Collection": True}
    assert pet["owner"] == {"$Type": f"{_NS}.Owner", "$Nullable": True}
    assert pet["born"] == {"$Type": "Edm.DateTimeOffset", "$Nullable": True, "@Core.Description": "Birth time."}
    assert schema["Owner"]["$Kind"] == "ComplexType"
    assert set(doc["$Reference"]) == {
        "https://oasis-tcs.github.io/odata-vocabularies/vocabularies/Org.OData.Core.V1.json",
        "https://oasis-tcs.github.io/odata-vocabularies/vocabularies/Org.OData.Validation.V1.json"}
    assert ("key-inferred", "Pet") in _losses(result)


def test_a_key_is_synthesized_when_there_is_no_id() -> None:
    note = _record("Note", _field("Note", "text"))
    op = _op("GET /notes", "GET", "/notes", messages=[_msg("GET /notes#200", MessageRole.RESPONSE,
                                                            TypeRef(item=TypeRef(name="Note")), status_code="200")])
    result = _emit(_api(types=[note], operations=[op]))
    member = _schema(json.loads(result.files[0].content))["Note"]
    assert member["$Key"] == ["Id"] and "@Core.Description" in member["Id"]
    report = compute_lossiness_for_emitter(_api(types=[note], operations=[op]), ODataEmitter())
    (synth,) = [item for item in report.items if item.construct_key == "Note"]
    assert synth.kind is LossinessKind.SYNTH and synth.target_mapping == "key-synthesized"


def test_a_navigation_property_targets_an_entity() -> None:
    owner = _record("Owner", _field("Owner", "id", nullable=False), _field("Owner", "pets", item="Pet"))
    pet = _record("Pet", _field("Pet", "id", nullable=False), _field("Pet", "owner", "Owner"))
    ops = [_op(f"GET /{n.lower()}s", "GET", f"/{n.lower()}s", name=f"list{n}",
               messages=[_msg(f"GET /{n}#200", MessageRole.RESPONSE, TypeRef(item=TypeRef(name=n)),
                              status_code="200")]) for n in ("Pet", "Owner")]
    schema = _schema(_doc(_api(types=[owner, pet], operations=ops)))
    assert schema["Owner"]["pets"] == {"$Kind": "NavigationProperty", "$Type": f"{_NS}.Pet", "$Collection": True}
    assert schema["Pet"]["owner"] == {"$Kind": "NavigationProperty", "$Type": f"{_NS}.Owner", "$Nullable": True}


def test_enums_type_definitions_unions_maps_and_aliases() -> None:
    color = Type(key="Color", name="Color", kind=TypeKind.ENUM,
                 enum_values=[EnumValue(key="Color.red", name="red", value="RED"),
                              EnumValue(key="Color.green", name="green", value="green")])
    code = Type(key="Code", name="Code", kind=TypeKind.ENUM,
                enum_values=[EnumValue(key="Code.a", name="a", value=10), EnumValue(key="Code.b", name="b", value=20)])
    account = Type(key="AccountId", name="AccountId", kind=TypeKind.ALIAS, aliased=TypeRef(name="string"),
                   constraints=Constraints(max_length=12))
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION,
                 fields=[_field("Shape", "Circle", "number"), _field("Shape", "label")])
    attrs = Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, value_type=TypeRef(name="string"))
    ref = Type(key="PetRef", name="PetRef", kind=TypeKind.ALIAS, aliased=TypeRef(name="AccountId"))
    holder = _record("Holder", _field("Holder", "ref", "PetRef"))
    result = _emit(_api(types=[color, code, account, shape, attrs, ref, holder]))
    schema = _schema(json.loads(result.files[0].content))
    assert schema["Color"] == {"$Kind": "EnumType", "red": 0, "green": 1}
    assert schema["Code"] == {"$Kind": "EnumType", "a": 10, "b": 20}
    assert schema["AccountId"] == {"$Kind": "TypeDefinition", "$UnderlyingType": "Edm.String", "$MaxLength": 12}
    assert schema["Shape"] == {"$Kind": "ComplexType", "circle": {"$Nullable": True, "$Type": "Edm.Double"},
                               "label": {"$Nullable": True}}
    assert schema["Attrs"] == {"$Kind": "ComplexType", "$OpenType": True}
    assert "PetRef" not in schema and schema["Holder"]["ref"]["$Type"] == f"{_NS}.AccountId"
    found = set(_losses(result))
    assert {("enum-value-as-name", "Color.red"), ("union-as-complex", "Shape"), ("map-as-open-type", "Attrs"),
            ("alias-inlined", "PetRef")} <= found


def test_constraints_defaults_and_coercions_without_a_csdl_form_are_reported() -> None:
    pet = _record("Pet",
                  _field("Pet", "n", "number", constraints=Constraints(multiple_of=2, minimum=1, exclusive_maximum=9)),
                  _field("Pet", "s", constraints=Constraints(min_length=1, enum=["a", "b"])),
                  _field("Pet", "u", "uint32"), _field("Pet", "odd", "Snowflake"),
                  _field("Pet", "flag", "bool", default="yes"), _field("Pet", "count", "integer", default=3),
                  _field("Pet", "my-name"))
    result = _emit(_api(types=[pet]))
    member = _schema(json.loads(result.files[0].content))["Pet"]
    assert member["n"]["@Validation.Minimum"] == 1 and member["n"]["@Validation.Maximum@Validation.Exclusive"] is True
    assert member["s"]["@Validation.AllowedValues"] == [{"Value": "a"}, {"Value": "b"}]
    assert member["u"]["$Type"] == "Edm.Int64" and member["count"]["$DefaultValue"] == 3
    assert "my_name" in member and "$DefaultValue" not in member["flag"]
    found = set(_losses(result))
    assert {("constraint-dropped", "Pet.n"), ("constraint-dropped", "Pet.s"), ("primitive-coerced", "Pet.u"),
            ("primitive-coerced", "Pet.odd"), ("default-dropped", "Pet.flag"),
            ("renamed-element", "Pet.my-name")} <= found


# ===========================================================================
# Operations
# ===========================================================================


def test_crud_is_served_by_entity_sets_and_the_rest_are_functions_and_actions() -> None:
    result = _emit(_pets_api())
    schema = _schema(json.loads(result.files[0].content))
    assert schema["Container"] == {
        "$Kind": "EntityContainer",
        "pets": {"$Collection": True, "$Type": f"{_NS}.Pet"},
        "searchPets": {"$Function": f"{_NS}.searchPets"},
        "feedPet": {"$Action": f"{_NS}.feedPet"},
    }
    assert schema["searchPets"] == [{"$Kind": "Function", "$Parameter": [{"$Name": "q"}],
                                     "$ReturnType": {"$Type": f"{_NS}.Pet", "$Collection": True}}]
    assert schema["feedPet"] == [{"$Kind": "Action", "$Parameter": [{"$Name": "body", "$Type": "Edm.Int32",
                                                                      "$Nullable": True}]}]
    found = set(_losses(result))
    assert {("crud-as-entity-set", "GET /pets"), ("crud-as-entity-set", "GET /pets/{id}"),
            ("crud-as-entity-set", "POST /pets"), ("operation-as-function", "GET /pets/search"),
            ("operation-as-action", "POST /pets/{id}/feed"), ("parameter-dropped", "GET /pets/search"),
            ("errors-dropped", "GET /pets/search"), ("servers-dropped", ""), ("title-dropped", ""),
            ("version-dropped", "")} <= found


def test_rpc_events_and_streams() -> None:
    ops = [_op("Svc.Get", name="Get", kind=OperationKind.QUERY,
               messages=[_msg("Svc.Get#r", MessageRole.RESPONSE, "string")]),
           _op("Svc.Do", name="Do", messages=[_msg("Svc.Do#q", MessageRole.REQUEST, "string")]),
           _op("Svc.Watch", name="Watch", streaming=StreamingMode.SERVER,
               messages=[_msg("Svc.Watch#r", MessageRole.RESPONSE, "string")]),
           _op("onEvent", name="onEvent", kind=OperationKind.PUBLISH)]
    result = _emit(_api(operations=ops, paradigm=ApiParadigm.RPC, format="protobuf"))
    schema = _schema(json.loads(result.files[0].content))
    assert schema["Get"][0]["$Kind"] == "Function" and schema["Do"][0]["$Kind"] == "Action"
    assert {("event-operation-dropped", "onEvent"), ("stream-as-collection", "Svc.Watch")} <= set(_losses(result))


def test_a_types_only_source_exposes_its_root_records() -> None:
    order = _record("Order", _field("Order", "id", nullable=False), _field("Order", "line", "Line"))
    line = _record("Line", _field("Line", "sku"))
    schema = _schema(_doc(_api(types=[order, line], paradigm=ApiParadigm.DATA_SCHEMA, format="avro")))
    assert schema["Order"]["$Kind"] == "EntityType" and schema["Line"]["$Kind"] == "ComplexType"
    assert schema["Container"]["Orders"] == {"$Collection": True, "$Type": f"{_NS}.Order"}


# ===========================================================================
# Fidelity pack and validation
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    api = _pets_api().model_copy(update={"agents": [AgentDescriptor(key="a", name="a", protocol="a2a")]})
    report = compute_lossiness_for_emitter(api, ODataEmitter())
    predicted = {(item.target_mapping, item.kind) for item in report.items}
    for loss in _emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else (
            LossinessKind.SYNTH if loss.subject == "key-synthesized" else LossinessKind.APPROX)
        assert (loss.subject, kind) in predicted, loss
    items = {(item.construct_key, item.target_mapping): item for item in report.items}
    assert items[("Pet", "key-inferred")].kind is LossinessKind.APPROX
    assert items[("Owner", "ComplexType Owner")].kind is LossinessKind.OK
    assert items[("", f"document → CSDL {_NS}")].kind is LossinessKind.APPROX
    assert ("", "agents → dropped") in items


async def test_emitted_output_validation() -> None:
    api = _pets_api()
    for output in ("json", "xml"):
        verdict = await validate_emitted_artifact("odata", _emit(api, output=output), api=api)
        assert (verdict.applicable, verdict.validated, verdict.valid) == (True, True, True), output
    result = _emit(api)
    doc = json.loads(result.files[0].content)
    _schema(doc)["Pet"]["id"]["$Type"] = 42
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": json.dumps(doc)})]})
    verdict = await validate_emitted_artifact("odata", broken, api=api)
    assert verdict.failed and verdict.findings[0].keyword == "odata.csdl-schema"
    # The import's resolution cannot finish on a non-string `$Type`; the schema finding still names the spot.
    assert verdict.findings[0].path == "/Pet.Store/Pet/id/$Type"


# ===========================================================================
# OData 2 / 3 sources
# ===========================================================================


def test_a_v2_source_keeps_facets_and_reports_annotations_and_the_upgrade() -> None:
    api = _corpus_api(_EXAMPLES / "odata-v2" / "05-real-world-sap-gateway-service.xml", "odata")
    result = _emit(api, output="both")
    for file in result.files:
        validate_odata_document(file.content)
    partner = _schema(json.loads(result.files[0].content))["BusinessPartner"]
    assert partner["BusinessPartnerID"]["$MaxLength"] == 10
    assert partner["CreatedAt"]["$Type"] == "Edm.DateTimeOffset" and partner["CreatedAt"]["$Precision"] == 7
    subjects = {loss.subject for loss in result.losses}
    assert {"version-upgraded", "annotations-dropped", "primitive-coerced"} <= subjects


# ===========================================================================
# Acceptance
# ===========================================================================

_ODATA_CORPUS = sorted(p for p in (_EXAMPLES / "odata").glob("*.*") if p.suffix in (".edmx", ".json"))


@pytest.mark.parametrize("path", _ODATA_CORPUS, ids=lambda p: p.name)
def test_odata_corpus_round_trips(path: Path) -> None:
    api = _corpus_api(path, "odata")
    for output in ("json", "xml"):
        result = _emit(api, output=output)
        validate_odata_document(result.files[0].content)
        diff = canonical_diff(api, reimport_emitted(ODataImportSource(), result, multi_file=False)).entries
        synthesized = {loss.pointer for loss in result.losses if loss.subject == "key-synthesized"}
        # A derived entity's key lives on its base type, which a v4 import does not keep: it gets a synthesized key.
        # A property typed with a type the import did not keep (a TypeDefinition) is written from its canonical
        # type, so its type changes too (MFX-16.3: every re-emitted name must resolve).
        undeclared = {loss.pointer for loss in result.losses if loss.subject == "stored-type-undeclared"}
        assert {(e.change.value, e.key) for e in diff} == {("changed", key) for key in synthesized | undeclared}, output


_OTHER_CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"), ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"), ("graphql/06-union-types.graphql", "graphql"),
    ("avro/01-user-record.avsc", "avro"), ("json-schema/02-product-types.json", "json-schema"),
    ("thrift/01-user-service.thrift", "thrift"), ("wsdl/02-order-service.wsdl", "wsdl"),
    ("odata-v2/02-typical-v2-orders.xml", "odata"), ("odata-v2/03-composition-v3-inheritance.xml", "odata"),
]


@pytest.mark.parametrize(("path", "fmt"), _OTHER_CORPUS, ids=lambda v: str(v))
def test_corpus_exports_are_valid_csdl(path: str, fmt: str) -> None:
    for file in _emit(_corpus_api(_EXAMPLES / path, fmt), output="both").files:
        validate_odata_document(file.content)
