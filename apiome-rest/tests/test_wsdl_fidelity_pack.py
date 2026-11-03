"""WSDL fidelity pack — MFX-14.2 (#3890).

The WSDL export writes a JSON-shaped source's types as XML Schema. The fidelity report names what that
mapping changes or loses, from the losses the WSDL writer records (so the report and the export agree):

* a union is an ``xs:choice`` of child elements — ``APPROX`` (warn); a union with no alternatives —
  ``DROP``;
* a nullable value is ``nillable="true" minOccurs="0"`` — ``APPROX`` (info);
* examples are not written — ``DROP`` (info);
* a constraint with no XSD facet (``multipleOf``, ``uniqueItems``, an untranslatable pattern) is not
  written — ``DROP`` (warn), never the shared helper's ``APPROX``;
* a WSDL or XSD source is XML already: none of these is recorded or reported;
* the output does not change: examples stay out of the schema, unions stay ``xs:choice`` s;
* WADL, which shares the schema writer, keeps reporting unwritable facets as ``APPROX``.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity
from app.wsdl_emitter import WsdlEmitter
from app.xsd_schema import schema_field_verdicts

_MAPPING_SUBJECTS = {"union-as-choice", "union-dropped", "null-as-nillable", "example-dropped"}


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    """A record field keyed ``<owner>.<name>``."""
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _record(key: str, *fields: CanonicalField) -> Type:
    """A record type named after its key."""
    return Type(key=key, name=key, kind=TypeKind.RECORD, fields=list(fields))


def _api(types: List[Type], fmt: str = "openapi") -> CanonicalApi:
    """A model of ``types`` imported from ``fmt``, with a target namespace (so the root is quiet)."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format=fmt,
        identity=ApiIdentity(name="Pets", namespace="urn:pets"),
        types=types,
    )


def _json_model() -> CanonicalApi:
    """A JSON-first model with each construct the WSDL schema maps or drops."""
    pet = _record(
        "Pet",
        _field("Pet", "name", TypeRef(name="string", nullable=False), constraints=Constraints(max_length=40)),
        _field("Pet", "nickname", TypeRef(name="string", nullable=True)),
        _field("Pet", "color", TypeRef(name="string", nullable=False), extras={"examples": ["brown", "white"]}),
        _field("Pet", "weight", TypeRef(name="number", nullable=False), constraints=Constraints(multiple_of=0.5)),
        _field("Pet", "tags", TypeRef(item=TypeRef(name="string"), nullable=False),
               constraints=Constraints(unique_items=True)),
        _field("Pet", "contact", TypeRef(name="Contact", nullable=False)),
    )
    contact = Type(key="Contact", name="Contact", kind=TypeKind.UNION, union_members=["Email", "Phone"])
    email = _record("Email", _field("Email", "address", TypeRef(name="string", nullable=False)))
    phone = _record("Phone", _field("Phone", "number", TypeRef(name="string", nullable=False)))
    nothing = Type(key="Nothing", name="Nothing", kind=TypeKind.UNION)
    return _api([pet, contact, email, phone, nothing])


def _items(api: CanonicalApi) -> Dict[str, list]:
    """The WSDL fidelity report's items, by construct key."""
    report = compute_lossiness_for_emitter(api, WsdlEmitter)
    by_key: Dict[str, list] = {}
    for item in report.items:
        by_key.setdefault(item.construct_key, []).append(item)
    return by_key


def _subjects(api: CanonicalApi) -> Dict[str, List[str]]:
    """The export's loss subjects → the pointers they were recorded at."""
    out: Dict[str, List[str]] = {}
    for loss in WsdlEmitter().emit(api).losses:
        out.setdefault(loss.subject, []).append(loss.pointer or "")
    return out


def _text(api: CanonicalApi) -> str:
    """Every file the export writes, concatenated."""
    return "".join(f.content for f in WsdlEmitter().emit(api).files)


# ===========================================================================
# The report
# ===========================================================================


def test_a_union_is_an_approximated_choice_never_ok() -> None:
    items = _items(_json_model())["Contact"]
    assert [(i.kind, i.severity) for i in items] == [(LossinessKind.APPROX, LossinessSeverity.WARN)]
    assert "xs:choice" in items[0].message and "email, phone" in items[0].message


def test_a_union_with_no_alternatives_is_dropped() -> None:
    items = _items(_json_model())["Nothing"]
    assert [i.kind for i in items] == [LossinessKind.DROP]
    assert "no alternatives" in items[0].message


def test_a_nullable_field_is_an_info_approximation() -> None:
    items = _items(_json_model())["Pet.nickname"]
    assert [(i.kind, i.severity) for i in items] == [(LossinessKind.APPROX, LossinessSeverity.INFO)]
    assert 'nillable="true"' in items[0].message


def test_examples_are_an_info_drop() -> None:
    items = _items(_json_model())["Pet.color"]
    assert [(i.kind, i.severity) for i in items] == [(LossinessKind.DROP, LossinessSeverity.INFO)]
    assert "example" in items[0].message


@pytest.mark.parametrize(("key", "rule"), [("Pet.weight", "multipleOf"), ("Pet.tags", "uniqueItems")])
def test_a_constraint_with_no_facet_is_dropped_not_approximated(key: str, rule: str) -> None:
    items = _items(_json_model())[key]
    assert [(i.kind, i.severity) for i in items] == [(LossinessKind.DROP, LossinessSeverity.WARN)]
    assert rule in items[0].message


def test_an_untranslatable_pattern_is_dropped() -> None:
    pet = _record("Pet", _field("Pet", "code", TypeRef(name="string", nullable=False),
                                constraints=Constraints(pattern="(?=x)a")))
    items = _items(_api([pet]))["Pet.code"]
    assert [i.kind for i in items] == [LossinessKind.DROP]
    assert "pattern" in items[0].message


def test_a_field_xsd_keeps_whole_gets_no_item() -> None:
    """A required string with a length facet is written as it is: nothing to report."""
    assert "Pet.name" not in _items(_json_model())


def test_the_report_files_every_mapping_loss_the_export_records() -> None:
    """Each JSON → XSD mapping loss the export records has a report item on the same construct."""
    api = _json_model()
    items = _items(api)
    for subject, pointers in _subjects(api).items():
        if subject not in _MAPPING_SUBJECTS | {"unsupported-facet"}:
            continue
        for pointer in pointers:
            assert pointer in items, (subject, pointer)
            assert any(i.kind is not LossinessKind.OK for i in items[pointer]), (subject, pointer)


@pytest.mark.parametrize("fmt", ["wsdl", "xsd"])
def test_an_xml_source_records_no_mapping_losses(fmt: str) -> None:
    api = _json_model().model_copy(update={"format": fmt})
    assert not set(_subjects(api)) & _MAPPING_SUBJECTS
    items = _items(api)
    assert not any("xs:choice" in i.message for i in items.get("Contact", []))
    assert not any("nillable" in i.message for i in items.get("Pet.nickname", []))


# ===========================================================================
# The export does not change
# ===========================================================================


def test_examples_are_not_written_and_unions_stay_choices() -> None:
    text = _text(_json_model())
    assert "brown" not in text and "white" not in text
    assert "<xsd:choice" in text


def test_the_flag_only_records() -> None:
    """The output of a JSON source is byte-identical to the same model read as an XML source."""
    json_text = _text(_json_model())
    xml_text = _text(_json_model().model_copy(update={"format": "xsd"}))
    assert json_text == xml_text


# ===========================================================================
# WADL keeps the shared helper's behaviour
# ===========================================================================


def test_the_shared_helper_still_approximates_facets_by_default() -> None:
    field = _field("Pet", "weight", TypeRef(name="number"), constraints=Constraints(multiple_of=0.5))
    default = schema_field_verdicts(field, target_label="WADL")
    assert [v.kind for v in default] == [LossinessKind.APPROX]
    assert schema_field_verdicts(field, target_label="WSDL", facets=False) == []
