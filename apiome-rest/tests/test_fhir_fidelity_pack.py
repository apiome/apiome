"""FHIR fidelity pack — MFX-26.2 (#4158).

:class:`app.fhir_emitter.FhirFidelityRulePack` enumerates what FHIR logical models cannot express, construct
by construct, with the kind the epic sets:

* operations → ``APPROX`` into the CapabilityStatement (``DROP`` without it), and the source as a whole warns;
* unions → a choice element (``field[x]``) where the shapes allow (``APPROX``), else ``DROP``;
* maps → ``DROP`` (the type and every element typed by it);
* regex / format constraints → FHIRPath ``matches()`` (``APPROX``); a format with no pattern ``DROP``;
* recursive types → ``APPROX`` with a depth note;
* naming → ``SYNTH`` for each sanitized name.

The prediction agrees with the writer, the per-construct detail holds on corpus fixtures, and the output stays
valid and re-imports (choice elements included).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest

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
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import LossKind
from app.fhir_emitter import FhirEmitOptions, FhirEmitter, validate_fhir_document
from app.fhir_import_source import FhirImportSource
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind, LossinessSeverity, LossItem
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_BASE = "http://example.org/fhir/StructureDefinition"


def _field(owner: str, name: str, ref: str = "string", **kw) -> CanonicalField:
    item = kw.pop("item", None)
    type_ref = TypeRef(item=TypeRef(name=item)) if item else TypeRef(name=ref, nullable=kw.pop("nullable", True))
    return CanonicalField(key=f"{owner}.{name}", name=name, type=type_ref, **kw)


def _record(name: str, *fields: CanonicalField) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*, types=(), operations=()) -> CanonicalApi:
    services = [Service(key="svc", name="Svc", operations=list(operations))] if operations else []
    return CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Shop"),
                        types=list(types), services=services)


def _report(api: CanonicalApi, **opts) -> Dict[str, List[LossItem]]:
    items: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, FhirEmitter()).items:
        items.setdefault(item.construct_key, []).append(item)
    return items


def _by_mapping(items: List[LossItem]) -> Dict[str, LossItem]:
    return {item.target_mapping: item for item in items}


def _elements(api: CanonicalApi, model: str, **opts) -> Dict[str, dict]:
    result = FhirEmitter().emit(api, opts=FhirEmitOptions(**opts) if opts else None)
    for file in result.files:
        validate_fhir_document(file.content)
    bundle = json.loads(result.files[0].content)
    resource = next(e["resource"] for e in bundle["entry"] if e["resource"].get("name") == model)
    return {e["path"]: e for e in resource["differential"]["element"]}


# ===========================================================================
# Operations
# ===========================================================================


def _op(key: str) -> Operation:
    return Operation(key=key, name=key.split(" ")[-1].strip("/") or "root", kind=OperationKind.REQUEST_RESPONSE,
                     http_method="GET", http_path=key.split(" ")[-1],
                     messages=[Message(key=f"{key}#200", role=MessageRole.RESPONSE, payload=TypeRef(name="Pet"))])


def test_an_operation_bearing_source_warns_and_each_operation_is_approximated() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], operations=[_op("GET /pets"), _op("GET /owners")])
    report = _report(api)
    root = _by_mapping(report[""])
    warning = root["operations-summarized"]
    assert warning.kind is LossinessKind.APPROX and warning.severity is LossinessSeverity.WARN
    assert "2 operation(s)" in warning.message
    (op,) = report["GET /pets"]
    assert op.kind is LossinessKind.APPROX and op.target_mapping == "operation-documented"


def test_without_the_capability_statement_operations_are_dropped() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], operations=[_op("GET /pets")])
    result = FhirEmitter().emit(api, opts=FhirEmitOptions(capability_statement=False))
    subjects = {(loss.subject, loss.kind) for loss in result.losses}
    assert ("operations-dropped", LossKind.NA) in subjects and ("operation-dropped", LossKind.NA) in subjects


# ===========================================================================
# Unions
# ===========================================================================


def test_a_union_of_distinct_alternatives_is_a_choice_element() -> None:
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key="Status.a", name="a", value="a")])
    owner = _record("Owner", _field("Owner", "name"))
    value = Type(key="Value", name="Value", kind=TypeKind.UNION, union_members=["string", "integer", "Owner", "Status"])
    pet = _record("Pet", _field("Pet", "value", "Value", nullable=False))
    api = _api(types=[status, owner, value, pet])
    elements = _elements(api, "Pet")
    choice = elements["Pet.value[x]"]
    assert choice["min"] == 1 and choice["max"] == "1"
    assert choice["type"] == [{"code": "string"}, {"code": "integer"}, {"code": f"{_BASE}/Owner"}, {"code": "code"}]
    assert choice["binding"]["strength"] == "required"
    (item,) = _report(api)["Value"]
    assert item.kind is LossinessKind.APPROX and item.target_mapping == "union-as-choice-type"


def test_a_union_whose_shapes_do_not_allow_a_choice_is_dropped() -> None:
    twice = Type(key="Twice", name="Twice", kind=TypeKind.UNION,
                 fields=[_field("Twice", "a"), _field("Twice", "b")])
    pet = _record("Pet", _field("Pet", "twice", "Twice"))
    api = _api(types=[twice, pet])
    (item,) = _report(api)["Twice"]
    assert item.kind is LossinessKind.DROP and item.target_mapping == "union-dropped"
    elements = _elements(api, "Twice")
    assert "iif(a.exists(), 1, 0) + iif(b.exists(), 1, 0) = 1" in elements["Twice"]["constraint"][0]["expression"]


def test_a_list_of_a_union_is_not_a_choice() -> None:
    either = Type(key="Either", name="Either", kind=TypeKind.UNION, union_members=["string", "integer"])
    api = _api(types=[either, _record("Pet", _field("Pet", "values", item="Either"))])
    assert _by_mapping(_report(api)["Either"])["union-dropped"].kind is LossinessKind.DROP


# ===========================================================================
# Maps, regex / format, recursion, naming
# ===========================================================================


def test_maps_are_dropped() -> None:
    attrs = Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, value_type=TypeRef(name="string"))
    api = _api(types=[attrs, _record("Pet", _field("Pet", "attrs", "Attrs"), _field("Pet", "id"))])
    report = _report(api)
    assert _by_mapping(report["Attrs"])["map-dropped"].kind is LossinessKind.DROP
    assert _by_mapping(report["Pet.attrs"])["map-dropped"].kind is LossinessKind.DROP
    assert "Pet.attrs" not in _elements(api, "Pet")


def test_regex_and_formats_become_fhirpath_or_are_dropped() -> None:
    pet = _record("Pet", _field("Pet", "code", constraints=Constraints(pattern="^[A-Z]{3}$")),
                  _field("Pet", "mail", constraints=Constraints(format="email")),
                  _field("Pet", "slug", constraints=Constraints(format="slug")))
    api = _api(types=[pet])
    report = _report(api)
    assert _by_mapping(report["Pet.code"])["regex-as-fhirpath"].kind is LossinessKind.APPROX
    assert _by_mapping(report["Pet.mail"])["regex-as-fhirpath"].kind is LossinessKind.APPROX
    assert _by_mapping(report["Pet.slug"])["constraint-dropped"].kind is LossinessKind.DROP
    elements = _elements(api, "Pet")
    assert elements["Pet.code"]["constraint"][0]["expression"] == "matches('^[A-Z]{3}$')"
    assert elements["Pet.mail"]["constraint"][0]["expression"].startswith("matches('^[^@")


def test_recursive_types_carry_a_depth_note() -> None:
    node = _record("Node", _field("Node", "children", item="Node"))
    a = _record("A", _field("A", "b", "B"))
    b = _record("B", _field("B", "a", "A"))
    leaf = _record("Leaf", _field("Leaf", "x"))
    report = _report(_api(types=[node, a, b, leaf]))
    for key in ("Node", "A", "B"):
        assert _by_mapping(report[key])["recursive-type"].kind is LossinessKind.APPROX, key
    assert "recursive-type" not in _by_mapping(report["Leaf"])


def test_sanitized_names_are_synthesized() -> None:
    report = _report(_api(types=[_record("order-line", _field("order-line", "unit-price", "number"))]))
    for key in ("order-line", "order-line.unit-price"):
        assert _by_mapping(report[key])["renamed-element"].kind is LossinessKind.SYNTH, key


# ===========================================================================
# Agreement with the writer, re-import, fixtures
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    value = Type(key="Value", name="Value", kind=TypeKind.UNION, union_members=["string", "integer"])
    attrs = Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, value_type=TypeRef(name="string"))
    node = _record("Node", _field("Node", "next", "Node"), _field("Node", "value", "Value"),
                   _field("Node", "attrs", "Attrs"), _field("Node", "my-mail", constraints=Constraints(format="email")))
    api = _api(types=[value, attrs, node], operations=[_op("GET /nodes")])
    predicted = {(item.target_mapping, item.kind) for items in _report(api).values() for item in items}
    for loss in FhirEmitter().emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else (
            LossinessKind.SYNTH if loss.subject == "renamed-element" else LossinessKind.APPROX)
        assert (loss.subject, kind) in predicted, loss


def test_choice_elements_round_trip_fhir_to_fhir() -> None:
    value = Type(key="Value", name="Value", kind=TypeKind.UNION, union_members=["string", "integer"])
    api = _api(types=[value, _record("Pet", _field("Pet", "value", "Value"), _field("Pet", "other", "Value"))])
    once = reimport_emitted(FhirImportSource(), FhirEmitter().emit(api), multi_file=False)
    union = next(t for t in once.types if t.name == "Value")
    assert union.kind is TypeKind.UNION and union.union_members == ["string", "i32"]
    again = reimport_emitted(FhirImportSource(), FhirEmitter().emit(once), multi_file=False)
    assert canonical_diff(once, again).entries == []


@pytest.mark.parametrize(("path", "fmt", "expected"), [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi", {"operations-summarized", "operation-documented"}),
    ("graphql/06-union-types.graphql", "graphql", {"union-as-choice-type", "operations-summarized"}),
    ("protobuf/02-grpc-service.proto", "protobuf", {"operations-summarized"}),
])
def test_fixture_detail(path: str, fmt: str, expected: set) -> None:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {file} is not checked out")
    api = build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                   "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api
    mappings = {item.target_mapping for item in compute_lossiness_for_emitter(api, FhirEmitter()).items}
    assert expected <= mappings, mappings
    for version in ("R4", "R5"):
        for emitted in FhirEmitter().emit(api, opts=FhirEmitOptions(fhir_version=version)).files:
            validate_fhir_document(emitted.content)
