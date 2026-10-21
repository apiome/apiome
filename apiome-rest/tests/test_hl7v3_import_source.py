"""Tests for the HL7 v3 / CDA import adapter — FMT-6.4 (#5448).

Covers the RIM data-type table and element binding, detection, the parser (header and section
hierarchy, template claims, the transmission-wrapper fileset) and every refusal code, the canonical
normalizer (RIM classes folded into record types, data types mapped or declared as limits, template
ids recorded as asserted, unvalidated claims, no payload values) and the reviewed capability entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, Type, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import CapabilityProvenance, capability_for
from app.format_version_coverage import version_coverage_for
from app.hl7v3_datatypes import (
    DATATYPES,
    KNOWN_TEMPLATES,
    NARRATIVE,
    TEMPLATE_CLAIM_STATEMENT,
    UNSUPPORTED_DATATYPE_STATEMENT,
    datatype_for,
    template_name,
)
from app.hl7v3_import_source import Hl7V3ImportSource
from app.hl7v3_normalizer import Hl7V3Normalizer, section_tree, template_claims
from app.hl7v3_parser import Hl7V3ParseError, is_hl7v3, parse_hl7v3, parse_hl7v3_fileset
from app.import_source import DetectionInput, ImportSourceError, get_import_source

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "hl7v3"


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_MINIMAL = _fixture("01-minimal-clinical-document.xml")
_CCD = _fixture("02-typical-ccd.xml")
_NESTED = _fixture("03-composition-nested-entries.xml")
_STRESS = _fixture("04-stress-rim-datatypes.xml")
_DISCHARGE = _fixture("05-real-world-discharge-summary.xml")
_UNKNOWN = _fixture("06-typical-unknown-template.xml")

_HEADER = """
  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>
  <id root="2.16.840.1.113883.19.5" extension="T-1"/>
  <code code="34133-9" codeSystem="2.16.840.1.113883.6.1"/>
  <effectiveTime value="20260101"/>
  <recordTarget><patientRole><id root="1.2.3" extension="P"/></patientRole></recordTarget>
  <author><time value="20260101"/><assignedAuthor><id root="1.2.3" extension="A"/></assignedAuthor></author>
  <custodian><assignedCustodian><representedCustodianOrganization>
    <id root="1.2.3" extension="O"/></representedCustodianOrganization></assignedCustodian></custodian>
"""


def _document(body: str, *, header: str = _HEADER, attributes: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ClinicalDocument xmlns="urn:hl7-org:v3" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' + attributes + ">"
        + header
        + "<component><structuredBody>"
        + body
        + "</structuredBody></component></ClinicalDocument>"
    )


def _section(inner: str) -> str:
    return "<component><section>" + inner + "</section></component>"


def _types(api: CanonicalApi) -> Dict[str, Type]:
    return {item.name: item for item in api.types}


def _field_type(api: CanonicalApi, type_name: str, field_name: str):
    record = _types(api)[type_name]
    return next(item.type for item in record.fields if item.name == field_name)


@pytest.fixture()
def adapter() -> Hl7V3ImportSource:
    return Hl7V3ImportSource()


def _model(adapter: Hl7V3ImportSource, text: str) -> CanonicalApi:
    return adapter.normalize(adapter.parse(text), include_raw=False)


# ---------------------------------------------------------------------------
# Data types and templates
# ---------------------------------------------------------------------------


def test_every_issue_named_datatype_is_mapped():
    for name in ("II", "CD", "CE", "IVL_TS", "AD", "PN"):
        assert name in DATATYPES
    assert DATATYPES["ST"].primitive == "string"
    assert DATATYPES[NARRATIVE].primitive == "string"
    # Every record member names a primitive or another mapped data type.
    for shape in DATATYPES.values():
        for member in shape.fields:
            assert member.type in {"string", "bool", "i32", "double"} or member.type in DATATYPES
        if not shape.primitive:
            assert shape.fields[-1].name == "nullFlavor"


@pytest.mark.parametrize(
    "name,kwargs,expected",
    [
        ("id", {}, "II"),
        ("templateId", {}, "II"),
        ("code", {}, "CD"),
        ("statusCode", {}, "CS"),
        ("administrativeGenderCode", {}, "CE"),
        ("effectiveTime", {"parent": "ClinicalDocument"}, "TS"),
        ("effectiveTime", {"parent": "observation"}, "IVL_TS"),
        ("effectiveTime", {"parent": "ClinicalDocument", "child_names": ("low",)}, "IVL_TS"),
        ("name", {"child_names": ("given", "family")}, "PN"),
        ("name", {}, "ON"),
        ("text", {"parent": "section"}, NARRATIVE),
        ("text", {"parent": "observation"}, "ED"),
        ("value", {"xsi_type": "PQ"}, "PQ"),
        ("value", {"xsi_type": "PIVL_TS"}, "PIVL_TS"),
        ("patient", {}, None),
        ("section", {}, None),
    ],
)
def test_datatype_binding(name, kwargs, expected):
    arguments = {"xsi_type": None, "parent": None, "child_names": (), "has_text": False}
    arguments.update(kwargs)
    assert datatype_for(name, **arguments) == expected


def test_template_names_are_names_not_verdicts():
    assert template_name("2.16.840.1.113883.10.20.22.1.2") == "Continuity of Care Document (CCD)"
    assert template_name("1.2.826.0.1.9999999.1.4.99") is None
    assert template_name(None) is None
    assert "2.16.840.1.113883.10.20.22.1.8" in KNOWN_TEMPLATES
    assert "not validated" in TEMPLATE_CLAIM_STATEMENT


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_adapter_registered():
    found = get_import_source("hl7v3")
    assert isinstance(found, Hl7V3ImportSource)
    assert found.paradigm is ApiParadigm.DATA_SCHEMA


def test_detection(adapter: Hl7V3ImportSource):
    assert adapter.detect(DetectionInput(text=_CCD)).confidence == pytest.approx(0.97)
    wrapper = _fixture("07-transmission-set/transmission-wrapper.xml")
    assert adapter.detect(DetectionInput(text=wrapper)).confidence == pytest.approx(0.9)
    assert not adapter.detect(DetectionInput(text=_fixture("negative/04-wrong-format-fhir.json"))).matched
    assert not adapter.detect(DetectionInput(text='<schema xmlns="http://www.w3.org/2001/XMLSchema"/>')).matched
    # A truncated document is still claimed so the parser can name the fault.
    assert adapter.detect(DetectionInput(text=_fixture("negative/03-truncated-mid-entry.xml"))).matched


def test_sniffer_reads_the_first_element_only():
    assert is_hl7v3(_MINIMAL) == "ClinicalDocument"
    assert is_hl7v3('<!-- <x xmlns="urn:hl7-org:v3"> -->\n<root/>') is None
    assert is_hl7v3('<v3:ClinicalDocument xmlns:v3="urn:hl7-org:v3"/>') == "ClinicalDocument"
    assert is_hl7v3('<root><ClinicalDocument xmlns="urn:hl7-org:v3"/></root>') is None
    assert is_hl7v3("") is None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_header_and_section_hierarchy():
    document = parse_hl7v3(_CCD)
    assert document.type_id == ("2.16.840.1.113883.1.3", "POCD_HD000040")
    assert document.body == "structuredBody"
    assert [section.title for section in document.sections] == [
        "Allergies and Intolerances",
        "Medications",
        "Problems",
    ]
    allergies = document.sections[0]
    assert allergies.code["code"] == "48765-2"
    assert allergies.path == "ClinicalDocument/component/structuredBody/component[1]/section"
    assert allergies.template_ids == [("2.16.840.1.113883.10.20.22.2.6.1", "2015-08-01")]
    assert [(entry.type_code, entry.statement) for entry in allergies.entries] == [("DRIV", "act")]
    assert document.sections[1].entries[0].statement == "substanceAdministration"


def test_nested_sections_are_kept():
    text = _document(
        _section(
            "<title>Outer</title>"
            + "<component><section><title>Inner</title></section></component>"
        )
    )
    outer = parse_hl7v3(text).sections[0]
    assert outer.title == "Outer"
    assert [section.title for section in outer.sections] == ["Inner"]
    assert outer.sections[0].path.endswith("section/component/section")


def test_template_claims_are_collected_in_document_order():
    claims = parse_hl7v3(_UNKNOWN).template_claims
    assert [(claim.root, claim.extension) for claim in claims] == [
        ("2.16.840.1.113883.10.20.22.1.1", "2015-08-01"),
        ("1.2.826.0.1.9999999.1.4.2", "2026-01-01"),
        ("1.2.826.0.1.9999999.1.4.99", None),
        ("1.2.826.0.1.9999999.2.7.1", None),
    ]
    assert claims[0].path == "ClinicalDocument"
    assert claims[-1].path == "ClinicalDocument/component/structuredBody/component/section"


@pytest.mark.parametrize(
    "name,code",
    [
        ("negative/01-syntactic-unclosed-section.xml", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-record-target.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-entry.xml", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-fhir.json", "FORMAT_MISMATCH"),
        ("negative/06-unresolvable-narrative-reference.xml", "INPUT_REFERENCE_UNRESOLVED"),
    ],
)
def test_corpus_negatives(name: str, code: str):
    with pytest.raises(Hl7V3ParseError) as caught:
        parse_hl7v3(_fixture(name), source_label=name)
    assert caught.value.code == code
    assert name in str(caught.value)


@pytest.mark.parametrize(
    "text,code,fragment",
    [
        ('<Foo xmlns="urn:example"/>', "FORMAT_MISMATCH", "not in the urn:hl7-org:v3"),
        ('<PRPA_IN201301UV02 xmlns="urn:hl7-org:v3"/>', "INPUT_SEMANTIC_INVALID", "not a <ClinicalDocument>"),
        (
            '<MCCI_IN000002UV01 xmlns="urn:hl7-org:v3"><ControlActProcess/></MCCI_IN000002UV01>',
            "INPUT_REFERENCE_UNRESOLVED",
            "transmission wrapper",
        ),
        (_document("", header="<id root='1'/>"), "INPUT_SEMANTIC_INVALID", "code, effectiveTime"),
        ("   ", "INPUT_EMPTY", "empty"),
        (
            '<!DOCTYPE x [<!ENTITY a "b">]><ClinicalDocument xmlns="urn:hl7-org:v3">&a;</ClinicalDocument>',
            "INPUT_UNSAFE_CONSTRUCT",
            "DTD",
        ),
    ],
)
def test_refusals_carry_a_taxonomy_code(text: str, code: str, fragment: str):
    with pytest.raises(Hl7V3ParseError) as caught:
        parse_hl7v3(text)
    assert caught.value.code == code
    assert fragment in str(caught.value)


def test_external_references_are_not_narrative_anchors():
    text = _document(
        _section(
            "<text><content ID='a1'>x</content></text>"
            "<entry><observationMedia classCode='OBS' moodCode='EVN'>"
            "<value xsi:type='ED' mediaType='image/png'><reference value='chart.png'/></value>"
            "</observationMedia></entry>"
            "<entry><observation classCode='OBS' moodCode='EVN'><text><reference value='#a1'/></text>"
            "</observation></entry>"
        )
    )
    assert len(parse_hl7v3(text).sections[0].entries) == 2


def test_encoding_faults_are_code_less():
    with pytest.raises(Hl7V3ParseError) as caught:
        parse_hl7v3("��<\x00?\x00x\x00m\x00l")
    assert caught.value.code is None


def test_adapter_parse_carries_the_code(adapter: Hl7V3ImportSource):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_fixture("negative/02-semantic-no-record-target.xml"))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------
# Fileset: the transmission wrapper
# ---------------------------------------------------------------------------


def _transmission_members() -> Dict[str, str]:
    folder = _EXAMPLES / "07-transmission-set"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.iterdir())}


def test_wrapper_fileset_reads_its_payload(adapter: Hl7V3ImportSource):
    fileset = IntakeFileset.from_members(_transmission_members(), root="transmission-wrapper.xml")
    document = adapter.parse_fileset(fileset)
    assert document.transmission is not None
    assert document.transmission.interaction == "MCCI_IN000002UV01"
    assert document.transmission.interaction_id == "MCCI_IN000002UV01"
    assert document.transmission.payload == "discharge-summary.xml"
    assert document.transmission.payload_id_matches is True
    api = adapter.normalize(document, include_raw=False)
    assert api.title == "Discharge Summary"
    assert api.extras["cda_transmission"]["payload"] == "discharge-summary.xml"


def test_wrapper_fileset_in_a_folder_resolves_relative_paths():
    members = {f"set/{name}": text for name, text in _transmission_members().items()}
    document = parse_hl7v3_fileset(members, "set/transmission-wrapper.xml")
    assert document.transmission.payload == "set/discharge-summary.xml"


def test_wrapper_without_its_payload_is_unresolved(adapter: Hl7V3ImportSource):
    members = _transmission_members()
    del members["discharge-summary.xml"]
    members["other.xml"] = _MINIMAL
    fileset = IntakeFileset.from_members(members, root="transmission-wrapper.xml")
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse_fileset(fileset)
    assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_wrapper_naming_another_document_id_is_recorded():
    members = _transmission_members()
    members["discharge-summary.xml"] = members["discharge-summary.xml"].replace(
        'extension="DS-2026-004471"', 'extension="DS-OTHER"'
    )
    document = parse_hl7v3_fileset(members, "transmission-wrapper.xml")
    assert document.transmission.payload_id_matches is False


def test_fileset_rooted_at_a_document(adapter: Hl7V3ImportSource):
    fileset = IntakeFileset.from_members({"ccd.xml": _CCD}, root="ccd.xml")
    document = adapter.parse_fileset(fileset)
    assert document.transmission is None
    assert len(document.sections) == 3


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def test_header_hierarchy_is_preserved_as_types(adapter: Hl7V3ImportSource):
    api = _model(adapter, _CCD)
    assert api.format == "hl7v3"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "POCD_HD000040"
    root = _types(api)["ClinicalDocument"]
    names = {item.name for item in root.fields}
    assert {"id", "code", "effectiveTime", "recordTarget", "author", "custodian", "component"} <= names
    assert _field_type(api, "ClinicalDocument", "recordTarget").name == "POCD_HD000040.RecordTarget"
    assert _field_type(api, "RecordTarget", "patientRole").name == "POCD_HD000040.PatientRole"
    assert _field_type(api, "ClinicalDocument", "component").name == "POCD_HD000040.ClinicalDocumentComponent"
    assert _field_type(api, "ClinicalDocumentComponent", "structuredBody").name == "POCD_HD000040.StructuredBody"
    # The body's components repeat, so they are a list of the context-named component type.
    body = _field_type(api, "StructuredBody", "component")
    assert body.item.name == "POCD_HD000040.StructuredBodyComponent"
    assert _field_type(api, "StructuredBodyComponent", "section").name == "POCD_HD000040.Section"
    # One section has no entries, so Section.entry is optional.
    assert _field_type(api, "Section", "entry").nullable is True


def test_section_hierarchy_is_recorded(adapter: Hl7V3ImportSource):
    api = _model(adapter, _DISCHARGE)
    sections = api.extras["cda_sections"]
    assert [section["code"]["code"] for section in sections] == ["42346-7", "11535-2", "47519-4", "8653-8"]
    assert sections[1]["templateIds"] == [
        {"root": "2.16.840.1.113883.10.20.22.2.5.1", "extension": "2015-08-01"}
    ]
    assert sections[1]["entries"][0]["statement"] == "act"
    assert api.extras["cda_document_code"]["code"] == "18842-5"
    assert api.extras["cda_body"] == "structuredBody"


def test_context_named_components_stay_apart(adapter: Hl7V3ImportSource):
    api = _model(adapter, _NESTED)
    types = _types(api)
    assert "OrganizerComponent" in types
    assert "StructuredBodyComponent" in types
    assert _field_type(api, "OrganizerComponent", "observation").name == "POCD_HD000040.Observation"
    # entryRelationship → observation folds into the same Observation class.
    assert _field_type(api, "EntryRelationship", "observation").name == "POCD_HD000040.Observation"


def test_rim_datatypes_map_onto_canonical_types(adapter: Hl7V3ImportSource):
    api = _model(adapter, _STRESS)
    types = _types(api)
    assert {item.name for item in types["II"].fields} == {
        "root",
        "extension",
        "assigningAuthorityName",
        "displayable",
        "nullFlavor",
    }
    assert types["II"].extras["hl7v3_datatype"] == "II"
    assert _field_type(api, "PatientRole", "addr").name == "POCD_HD000040.AD"
    assert _field_type(api, "Patient", "name").item.name == "POCD_HD000040.PN"
    assert _field_type(api, "PN", "given").item.name == "string"
    assert _field_type(api, "AD", "useablePeriod").name == "POCD_HD000040.IVL_TS"
    assert _field_type(api, "IVL_TS", "low").name == "POCD_HD000040.TS"
    ts_value = next(item for item in types["TS"].fields if item.name == "value")
    assert ts_value.constraints is not None and ts_value.constraints.pattern
    assert _field_type(api, "CD", "translation").item.name == "POCD_HD000040.CD"
    assert _field_type(api, "PQ", "value").name == "double"
    assert _field_type(api, "BL", "value").name == "bool"
    assert _field_type(api, "ParentDocument", "versionNumber").name == "POCD_HD000040.INT"
    # The organization name is ON → text; the section narrative is text.
    assert _field_type(api, "RepresentedCustodianOrganization", "name").name == "string"
    assert _field_type(api, "Section", "text").name == "string"
    # SDTC extension elements keep their prefix and namespace.
    deceased = next(item for item in types["Patient"].fields if item.name == "sdtc:deceasedInd")
    assert deceased.extras["hl7v3_namespace"] == "urn:hl7-org:sdtc"
    assert api.extras["cda_datatype_limits"] == []


def test_xsi_type_choices_become_a_union(adapter: Hl7V3ImportSource):
    api = _model(adapter, _STRESS)
    choice = _types(api)["ObservationValueChoice"]
    assert choice.kind is TypeKind.UNION
    assert choice.union_members == [
        "POCD_HD000040.RTO_PQ_PQ",
        "POCD_HD000040.PQ",
        "POCD_HD000040.CD",
        "POCD_HD000040.ST",
    ]
    assert _types(api)["ST"].kind is TypeKind.SCALAR
    assert _field_type(api, "Observation", "value").name == "POCD_HD000040.ObservationValueChoice"


def test_unmapped_datatype_is_a_declared_limit(adapter: Hl7V3ImportSource):
    text = _document(
        _section(
            "<entry><substanceAdministration classCode='SBADM' moodCode='INT'>"
            "<effectiveTime xsi:type='PIVL_TS'><period value='12' unit='h'/></effectiveTime>"
            "</substanceAdministration></entry>"
        )
    )
    api = _model(adapter, text)
    assert _field_type(api, "SubstanceAdministration", "effectiveTime").name == "string"
    assert api.extras["cda_datatype_limits"] == [
        {
            "datatype": "PIVL_TS",
            "field": "SubstanceAdministration.effectiveTime",
            "statement": UNSUPPORTED_DATATYPE_STATEMENT,
        }
    ]


def test_unmapped_datatype_inside_a_union_is_a_scalar_limit(adapter: Hl7V3ImportSource):
    text = _document(
        _section(
            "<entry><observation classCode='OBS' moodCode='EVN'><value xsi:type='PQ' value='1' unit='m'/>"
            "</observation></entry>"
            "<entry><observation classCode='OBS' moodCode='EVN'><value xsi:type='MO' value='1' currency='EUR'/>"
            "</observation></entry>"
        )
    )
    api = _model(adapter, text)
    assert _types(api)["ObservationValueChoice"].union_members == ["POCD_HD000040.PQ", "POCD_HD000040.MO"]
    assert UNSUPPORTED_DATATYPE_STATEMENT in _types(api)["MO"].description
    assert api.extras["cda_datatype_limits"][0]["datatype"] == "MO"


def test_template_ids_are_asserted_unvalidated_claims(adapter: Hl7V3ImportSource):
    api = _model(adapter, _UNKNOWN)
    claims = api.extras["cda_template_claims"]
    assert len(claims) == 4
    assert all(claim["status"] == "asserted" and claim["validated"] is False for claim in claims)
    assert claims[0]["recognised"] is True and claims[0]["name"] == "US Realm Header"
    assert [claim["recognised"] for claim in claims[1:]] == [False, False, False]
    assert api.extras["cda_template_statement"] == TEMPLATE_CLAIM_STATEMENT


def test_payload_values_are_never_recorded(adapter: Hl7V3ImportSource):
    api = _model(adapter, _STRESS)
    serialized = api.model_dump_json()
    for value in ("PAT-0099", "Sammy", "Leeds", "1 Example Way", "patient@example.com", "128", "Never smoked"):
        assert value not in serialized
    assert all(item.default is None for record in api.types for item in record.fields)


def test_attributes_become_fields(adapter: Hl7V3ImportSource):
    api = _model(adapter, _CCD)
    class_code = next(item for item in _types(api)["Act"].fields if item.name == "classCode")
    assert class_code.extras == {"hl7v3_xml": "attribute"}
    assert class_code.type.name == "string"


def test_minimal_document_without_type_id_uses_cda_namespace(adapter: Hl7V3ImportSource):
    text = _document("", header=_HEADER.replace(
        '<typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>', ""
    ))
    api = _model(adapter, text)
    assert api.identity.namespace == "CDA"
    assert api.title == "Clinical Document"
    assert api.extras["cda_type_id"] is None


def test_normalize_is_deterministic(adapter: Hl7V3ImportSource):
    assert _model(adapter, _DISCHARGE).model_dump() == _model(adapter, _DISCHARGE).model_dump()


def test_raw_is_kept_when_asked(adapter: Hl7V3ImportSource):
    api = adapter.normalize(adapter.parse(_MINIMAL))
    assert api.raw == {"hl7v3": _MINIMAL}


def test_helpers_are_plain_data():
    document = parse_hl7v3(_CCD)
    assert template_claims(document)[0]["validated"] is False
    tree = section_tree(document.sections)
    assert tree[0]["sections"] == []
    assert tree[2]["entries"] == []


def test_normalizer_rejects_foreign_ast(adapter: Hl7V3ImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize(object())
    with pytest.raises(ValueError):
        Hl7V3Normalizer().normalize(object())


# ---------------------------------------------------------------------------
# Capability registry and version coverage
# ---------------------------------------------------------------------------


def test_capability_entry_states_template_ids_are_not_validated():
    entry = capability_for("hl7v3")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    notes = " ".join(entry.notes)
    assert "not validated" in notes
    assert TEMPLATE_CLAIM_STATEMENT in notes
    assert "declared parsing limit" in entry.canonical_projection.note


def test_version_coverage_is_declared():
    coverage = version_coverage_for("hl7v3")
    assert coverage.declared
    assert coverage.reads[0].format_key == "hl7v3"
    assert not coverage.writes
