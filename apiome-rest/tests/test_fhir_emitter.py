"""FHIR emitter — MFX-26.1 (#4157).

Covers, in order:

* logical models: ``kind: logical``, ``derivation: specialization``, R4 vs R5 (``fhirVersion``,
  ``baseDefinition``, ``integer64``), the root element, ids equal to paths;
* cardinality from nullability, lists, ``minItems`` / ``maxItems``;
* the primitive mapping (:func:`app.fhir_emitter.fhir_primitive`);
* enums → a CodeSystem and a ValueSet and a ``required`` binding;
* constraints → ``maxLength``, ``minValue[x]`` / ``maxValue[x]``, ``defaultValue[x]``, FHIRPath ``constraint``\\ s;
* element paths from nesting (``BackboneElement`` + ``explicit-type-name``) vs references by canonical URL;
* unions, maps, aliases; the CapabilityStatement; ``bundle`` vs ``per-type`` packaging;
* what is not carried and reported, by the writer and :class:`FhirFidelityRulePack`;
* the logical-model reader (:mod:`app.fhir_logical`) and the FHIR → FHIR round trip;
* validation: Apiome's structural FHIR rules, the HL7 validator seam (:mod:`app.fhir_validation`) and the
  export-validation fallback;
* acceptance: corpus exports from other formats are valid R4 and R5, and re-import unchanged as FHIR.
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
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, LossKind
from app.export_validation import validate_emitted_artifact
from app.fhir_emitter import EXPLICIT_TYPE_NAME, FhirEmitOptions, FhirEmitter, fhir_primitive, validate_fhir_document
from app.fhir_import_source import FhirImportSource
from app.fhir_validation import structural_issues, validate_with_fhir_validator
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import ImportSourceError, canonical_diff
from app.lossiness import LossinessKind
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_BASE = "http://example.org/fhir"


def _field(owner: str, name: str, ref: str = "string", **kw) -> CanonicalField:
    item = kw.pop("item", None)
    nullable = kw.pop("nullable", True)
    type_ref = TypeRef(item=TypeRef(name=item), nullable=nullable) if item else TypeRef(name=ref, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=type_ref, **kw)


def _record(name: str, *fields: CanonicalField, **kw) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields), **kw)


def _api(*, types=(), operations=(), **kw) -> CanonicalApi:
    services = [Service(key="svc", name="Pets", operations=list(operations))] if operations else []
    defaults = dict(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Pet Store"),
                    types=list(types), services=services)
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return FhirEmitter().emit(api, opts=FhirEmitOptions(**opts) if opts else None)


def _resources(api: CanonicalApi, **opts) -> Dict[str, Dict[str, Any]]:
    bundle = json.loads(_emit(api, **opts).files[0].content)
    return {f"{e['resource']['resourceType']}/{e['resource']['id']}": e["resource"] for e in bundle["entry"]}


def _elements(resource: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {e["path"]: e for e in resource["differential"]["element"]}


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
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM, description="Pet status.",
                  enum_values=[EnumValue(key="Status.available", name="available", value="available"),
                               EnumValue(key="Status.sold", name="sold", value="sold", description="Gone.")])
    owner = _record("Owner", _field("Owner", "name", nullable=False))
    pet = _record(
        "Pet",
        _field("Pet", "id", "integer", nullable=False, constraints=Constraints(format="int64", minimum=1)),
        _field("Pet", "name", nullable=False, description="The pet's name.",
               constraints=Constraints(max_length=40, min_length=1, pattern="^[A-Za-z ]+$")),
        _field("Pet", "status", "Status"),
        _field("Pet", "tags", item="string", constraints=Constraints(min_items=1, max_items=5)),
        _field("Pet", "owner", "Owner"),
        _field("Pet", "weight", "number", constraints=Constraints(exclusive_maximum=500, multiple_of=0.5)),
        _field("Pet", "born", constraints=Constraints(format="date")),
        _field("Pet", "vaccinated", "bool", default=False),
        description="A pet.",
    )
    list_pets = Operation(key="GET /pets", name="listPets", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
                          http_path="/pets", description="List pets.",
                          messages=[Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200",
                                            payload=TypeRef(item=TypeRef(name="Pet")))])
    return _api(types=[status, owner, pet], operations=[list_pets], title="Pet Store", version="1.0.0",
                description="Pets.")


# ===========================================================================
# Logical models, versions, cardinality
# ===========================================================================


@pytest.mark.parametrize(("version", "fhir_version", "base", "id_type"), [
    ("R4", "4.0.1", "http://hl7.org/fhir/StructureDefinition/Element", "integer"),
    ("R5", "5.0.0", "http://hl7.org/fhir/StructureDefinition/Base", "integer64"),
])
def test_logical_models_per_version(version: str, fhir_version: str, base: str, id_type: str) -> None:
    pet = _resources(_pets_api(), fhir_version=version)["StructureDefinition/Pet"]
    assert {k: pet[k] for k in ("url", "name", "status", "fhirVersion", "kind", "abstract", "type",
                                "baseDefinition", "derivation", "version", "description")} == {
        "url": f"{_BASE}/StructureDefinition/Pet", "name": "Pet", "status": "draft", "fhirVersion": fhir_version,
        "kind": "logical", "abstract": False, "type": f"{_BASE}/StructureDefinition/Pet", "baseDefinition": base,
        "derivation": "specialization", "version": "1.0.0", "description": "A pet.",
    }
    elements = _elements(pet)
    assert elements["Pet"] == {"id": "Pet", "path": "Pet", "short": "A pet.", "definition": "A pet.", "min": 0,
                               "max": "*"}
    assert all(e["id"] == path for path, e in elements.items())
    assert elements["Pet.id"]["type"] == [{"code": id_type}]


def test_cardinality() -> None:
    elements = _elements(_resources(_pets_api())["StructureDefinition/Pet"])
    assert (elements["Pet.id"]["min"], elements["Pet.id"]["max"]) == (1, "1")
    assert (elements["Pet.status"]["min"], elements["Pet.status"]["max"]) == (0, "1")
    assert (elements["Pet.tags"]["min"], elements["Pet.tags"]["max"]) == (1, "5")
    unbounded = _elements(_resources(_api(types=[_record("A", _field("A", "xs", item="string"))]))[
        "StructureDefinition/A"])
    assert (unbounded["A.xs"]["min"], unbounded["A.xs"]["max"]) == (0, "*")


@pytest.mark.parametrize(("name", "fmt", "version", "expected"), [
    ("string", None, "R4", ("string", True)), ("bool", None, "R4", ("boolean", True)),
    ("integer", None, "R4", ("integer", True)), ("i64", None, "R5", ("integer64", True)),
    ("i64", None, "R4", ("integer", False)), ("number", None, "R4", ("decimal", True)),
    ("string", "date-time", "R4", ("dateTime", True)), ("string", "date", "R4", ("date", True)),
    ("string", "uri", "R4", ("uri", True)), ("string", "uuid", "R4", ("uuid", True)),
    ("bytes", None, "R4", ("base64Binary", True)), ("timestamp", None, "R5", ("dateTime", True)),
    ("uint64", None, "R5", ("decimal", False)), ("Snowflake", None, "R4", ("string", False)),
])
def test_fhir_primitive(name: str, fmt: str, version: str, expected: tuple) -> None:
    assert fhir_primitive(name, fmt, version) == expected


# ===========================================================================
# Enums and constraints
# ===========================================================================


def test_enums_are_code_systems_value_sets_and_required_bindings() -> None:
    resources = _resources(_pets_api())
    code_system = resources["CodeSystem/Status"]
    assert code_system["url"] == f"{_BASE}/CodeSystem/Status" and code_system["content"] == "complete"
    assert code_system["concept"] == [{"code": "available", "display": "available"},
                                      {"code": "sold", "display": "sold", "definition": "Gone."}]
    value_set = resources["ValueSet/Status"]
    assert value_set["compose"] == {"include": [{"system": f"{_BASE}/CodeSystem/Status"}]}
    status = _elements(resources["StructureDefinition/Pet"])["Pet.status"]
    assert status["type"] == [{"code": "code"}]
    assert status["binding"] == {"strength": "required", "valueSet": f"{_BASE}/ValueSet/Status"}


def test_constraints_become_element_properties_and_fhirpath_invariants() -> None:
    result = _emit(_pets_api())
    elements = _elements(json.loads(result.files[0].content)["entry"][2]["resource"])
    assert elements["Pet.id"]["minValueInteger"] == 1
    name = elements["Pet.name"]
    assert name["maxLength"] == 40
    assert [c["expression"] for c in name["constraint"]] == ["length() >= 1", "matches('^[A-Za-z ]+$')"]
    assert all(c["severity"] == "error" and c["key"].startswith("apiome-") for c in name["constraint"])
    assert [c["expression"] for c in elements["Pet.weight"]["constraint"]] == ["$this < 500", "($this mod 0.5) = 0"]
    assert elements["Pet.born"]["type"] == [{"code": "date"}]
    assert elements["Pet.vaccinated"]["defaultValueBoolean"] is False


def test_constraints_without_a_fhir_form_are_reported() -> None:
    a = _record("A", _field("A", "ids", item="string", constraints=Constraints(unique_items=True)),
                _field("A", "slug", constraints=Constraints(format="slug")),
                _field("A", "flag", "bool", default="yes"))
    found = set(_losses(_emit(_api(types=[a]))))
    assert {("constraint-dropped", "A.ids"), ("constraint-dropped", "A.slug"), ("default-dropped", "A.flag")} <= found


# ===========================================================================
# Nesting, references, unions, maps, aliases
# ===========================================================================


def test_a_record_used_once_is_nested_and_a_shared_one_is_referenced() -> None:
    address = _record("Address", _field("Address", "city"))
    person = _record("Person", _field("Person", "home", "Address"), _field("Person", "friend", "Person"),
                     _field("Person", "tag", "Tag"))
    pet = _record("Pet", _field("Pet", "tag", "Tag"))
    tag = _record("Tag", _field("Tag", "label"))
    resources = _resources(_api(types=[address, person, pet, tag]))
    assert "StructureDefinition/Address" not in resources
    elements = _elements(resources["StructureDefinition/Person"])
    assert elements["Person.home"]["type"] == [{"code": "BackboneElement"}]
    assert elements["Person.home"]["extension"] == [{"url": EXPLICIT_TYPE_NAME, "valueString": "Address"}]
    assert elements["Person.home.city"]["type"] == [{"code": "string"}]
    assert elements["Person.friend"]["type"] == [{"code": f"{_BASE}/StructureDefinition/Person"}]
    assert elements["Person.tag"]["type"] == [{"code": f"{_BASE}/StructureDefinition/Tag"}]
    assert "StructureDefinition/Tag" in resources


def test_unions_maps_and_aliases() -> None:
    # MFX-26.2: a union of distinct single alternatives is a choice element; a map is dropped.
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION,
                 fields=[_field("Shape", "circle", "number"), _field("Shape", "label")])
    attrs = Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, value_type=TypeRef(name="integer"))
    code = Type(key="Code", name="Code", kind=TypeKind.ALIAS, aliased=TypeRef(name="string"))
    holder = _record("Holder", _field("Holder", "code", "Code"), _field("Holder", "attrs", "Attrs"))
    result = _emit(_api(types=[shape, attrs, code, holder]))
    resources = {e["resource"]["id"]: e["resource"] for e in json.loads(result.files[0].content)["entry"]}
    assert _elements(resources["Shape"])["Shape.value[x]"]["type"] == [{"code": "decimal"}, {"code": "string"}]
    assert "Attrs" not in resources and "Holder.attrs" not in _elements(resources["Holder"])
    assert _elements(resources["Holder"])["Holder.code"]["type"] == [{"code": "string"}]
    found = set(_losses(result))
    assert {("map-dropped", "Attrs"), ("map-dropped", "Holder.attrs"), ("alias-inlined", "Code")} <= found


def test_names_are_made_fhir_identifiers() -> None:
    result = _emit(_api(types=[_record("order-line", _field("order-line", "unit-price", "number"))]))
    resource = json.loads(result.files[0].content)["entry"][0]["resource"]
    assert resource["name"] == "OrderLine" and "OrderLine.unitPrice" in _elements(resource)
    assert {("renamed-element", "order-line"), ("renamed-element", "order-line.unit-price")} <= set(_losses(result))


# ===========================================================================
# Operations, packaging
# ===========================================================================


def test_operations_are_summarized_in_a_capability_statement() -> None:
    resources = _resources(_pets_api(), fhir_version="R5")
    statement = resources["CapabilityStatement/PetStore"]
    assert {k: statement[k] for k in ("kind", "fhirVersion", "format", "title", "version", "description")} == {
        "kind": "capability", "fhirVersion": "5.0.0", "format": ["json"], "title": "Pet Store", "version": "1.0.0",
        "description": "Pets."}
    assert statement["software"] == {"name": "Pet Store"}
    assert "- `GET /pets` (listPets) returns a list of Pet — List pets." in statement["rest"][0]["documentation"]
    without = _emit(_pets_api(), capability_statement=False)
    assert ("operation-dropped", "GET /pets") in _losses(without) and ("title-dropped", "") in _losses(without)


def test_per_type_packaging_writes_one_file_per_resource() -> None:
    result = _emit(_pets_api(), packaging="per-type")
    # Owner is used once, so it is nested in Pet rather than written as a model of its own.
    assert [f.path for f in result.files] == [
        "CodeSystem-Status.json", "ValueSet-Status.json", "StructureDefinition-Pet.json",
        "CapabilityStatement-PetStore.json"]
    for file in result.files:
        validate_fhir_document(file.content)


def test_events_servers_and_nothing_to_describe() -> None:
    event = Operation(key="onPet", name="onPet", kind=OperationKind.PUBLISH)
    api = _api(types=[_record("Pet", _field("Pet", "id"))], operations=[event],
               servers=[__import__("app.canonical_model", fromlist=["Server"]).Server(url="https://x")])
    assert {("event-operation-dropped", "onPet"), ("servers-dropped", "")} <= set(_losses(_emit(api)))
    with pytest.raises(EmitPreconditionError):
        _emit(_api())


# ===========================================================================
# Fidelity pack
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    api = _pets_api().model_copy(update={"agents": [AgentDescriptor(key="a", name="a", protocol="a2a")]})
    report = compute_lossiness_for_emitter(api, FhirEmitter())
    predicted = {(item.target_mapping, item.kind) for item in report.items}
    for loss in _emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else LossinessKind.APPROX
        assert (loss.subject, kind) in predicted, loss
    items = {(item.construct_key, item.target_mapping): item for item in report.items}
    assert items[("Pet", "logical model Pet")].kind is LossinessKind.OK
    assert items[("Owner", "BackboneElement Pet.owner")].kind is LossinessKind.OK
    assert items[("Status", "CodeSystem + ValueSet Status")].kind is LossinessKind.OK
    assert items[("", "document → FHIR logical models")].kind is LossinessKind.APPROX
    assert ("", "agents → dropped") in items


# ===========================================================================
# Reading logical models back; FHIR → FHIR
# ===========================================================================


def test_the_export_reads_back_as_types_and_enums() -> None:
    back = reimport_emitted(FhirImportSource(), _emit(_pets_api()), multi_file=False)
    assert back.format == "fhir" and back.extras["fhir_kind"] == "logical"
    assert (back.title, back.description, back.version) == ("Pet Store", "Pets.", "1.0.0")
    types = {t.name: t for t in back.types}
    assert types["Status"].kind is TypeKind.ENUM and [v.value for v in types["Status"].enum_values] == [
        "available", "sold"]
    pet = {f.name: f for f in types["Pet"].fields}
    assert pet["id"].type.nullable is False and pet["tags"].type.item is not None
    assert pet["status"].type.name == "Status" and pet["owner"].type.name == "Owner"


@pytest.mark.parametrize("version", ["R4", "R5"])
def test_fhir_to_fhir_round_trips(version: str) -> None:
    once = reimport_emitted(FhirImportSource(), _emit(_pets_api(), fhir_version=version), multi_file=False)
    again = _emit(once, fhir_version=version)
    assert again.files[0].content.replace(json.loads(again.files[0].content)["entry"][-1]["resource"]["date"], "") \
        and canonical_diff(once, reimport_emitted(FhirImportSource(), again, multi_file=False)).entries == []


def test_a_fhir_profile_source_is_written_back_as_a_profile() -> None:
    api = _corpus_api(_EXAMPLES / "fhir" / "02-patient-structuredefinition.json", "fhir")
    result = _emit(api)
    resource = json.loads(result.files[0].content)
    assert resource["resourceType"] == "StructureDefinition" and resource["kind"] != "logical"
    assert canonical_diff(api, reimport_emitted(FhirImportSource(), result, multi_file=False)).entries == []


# ===========================================================================
# Validation
# ===========================================================================


def test_the_structural_rules_catch_broken_resources() -> None:
    bundle = json.loads(_emit(_pets_api()).files[0].content)
    assert structural_issues(bundle) == []
    pet = bundle["entry"][2]["resource"]
    elements = pet["differential"]["element"]
    elements[1]["min"], elements[1]["max"] = 2, "1"
    elements[2]["path"] = "Other.name"
    elements[3]["binding"]["valueSet"] = "http://nowhere/ValueSet/X"
    bundle["entry"][0]["resource"]["concept"].append({"code": "sold"})
    issues = "\n".join(structural_issues(bundle))
    for expected in ("min > max", "must start with 'Pet'", "is not in the bundle", "is repeated (csd-1)"):
        assert expected in issues, expected
    del pet["kind"]
    assert any("kind: required" in issue for issue in structural_issues(bundle))


def test_the_validator_seam_reads_the_operation_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[list] = []

    def fake_run(key, args, **kw):
        calls.append(args)
        out = Path(args[args.index("-output") + 1])
        out.write_text(json.dumps({"resourceType": "OperationOutcome", "issue": [
            {"severity": "error", "code": "structure", "diagnostics": "Bad element",
             "expression": ["StructureDefinition.differential.element[1]"]},
            {"severity": "warning", "code": "informational", "diagnostics": "meh"}]}))

    monkeypatch.setattr("app.fhir_validation.run_tool_blocking", fake_run)
    issues = validate_with_fhir_validator({"x.bundle.json": "{}"}, "5.0.0")
    assert [(i.message, i.file, i.location, i.code) for i in issues] == [
        ("Bad element", "x.bundle.json", "StructureDefinition.differential.element[1]", "structure")]
    assert calls[0][-6:-2] == ["-version", "5.0.0", "-tx", "n/a"]


async def test_export_validation_uses_the_validator_or_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pets_api()
    result = _emit(api, fhir_version="R5")
    monkeypatch.setattr("app.fhir_validation.fhir_validator_available", lambda: False)
    verdict = await validate_emitted_artifact("fhir", result, api=api)
    assert (verdict.validated, verdict.valid) == (True, True)
    monkeypatch.setattr("app.fhir_validation.fhir_validator_available", lambda: True)
    seen: List[str] = []

    def fake_validate(members, version):
        seen.append(version)
        from app.fhir_validation import FhirValidationIssue
        return [FhirValidationIssue(message="nope", file="a.json", location="X", code="invariant")]

    monkeypatch.setattr("app.fhir_validation.validate_with_fhir_validator", fake_validate)
    verdict = await validate_emitted_artifact("fhir", result, api=api)
    assert seen == ["5.0.0"] and verdict.failed and verdict.findings[0].keyword == "invariant"

    def unavailable(members, version):
        raise ImportSourceError("gone", code="ADAPTER_UNAVAILABLE")

    monkeypatch.setattr("app.fhir_validation.validate_with_fhir_validator", unavailable)
    assert (await validate_emitted_artifact("fhir", result, api=api)).valid


# ===========================================================================
# Acceptance: corpus exports are valid R4 and R5 and re-import unchanged
# ===========================================================================

_CORPUS = [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"), ("openapi/31-paths-comprehensive.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"), ("graphql/06-union-types.graphql", "graphql"),
    ("avro/01-user-record.avsc", "avro"), ("json-schema/02-product-types.json", "json-schema"),
    ("thrift/01-user-service.thrift", "thrift"), ("xsd/01-purchase-order.xsd", "xsd"),
]


@pytest.mark.parametrize("version", ["R4", "R5"])
@pytest.mark.parametrize(("path", "fmt"), _CORPUS, ids=lambda v: str(v))
def test_corpus_exports_are_valid_and_round_trip(path: str, fmt: str, version: str) -> None:
    result = _emit(_corpus_api(_EXAMPLES / path, fmt), fhir_version=version)
    for file in result.files:
        validate_fhir_document(file.content)
    once = reimport_emitted(FhirImportSource(), result, multi_file=False)
    again = reimport_emitted(FhirImportSource(), _emit(once, fhir_version=version), multi_file=False)
    assert canonical_diff(once, again).entries == []
