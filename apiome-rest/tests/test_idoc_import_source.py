"""Tests for the SAP IDoc import adapter and emitter — FMT-6.2 (#5446).

Covers both transport forms (flat ``EDI_DC40``/``EDI_DD40`` and XML), segment definitions, the
hierarchy rebuilt from segment numbers, every refusal code, the canonical normalizer (flat and XML
forms giving the same model), the native analysis (control record as structure, field offsets under
stated assumptions, value visibility), the IDoc XML emitter and the reviewed capability entry.
Corpus-wide behaviour (every fixture imports or rejects with its declared code, goldens, the
round-trip matrix) is asserted by the corpus suites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter_instance
from app.export_validation import _VALIDATORS
from app.fileset import IntakeFileset
from app.format_capability_registry import (
    CapabilityProvenance,
    NativeHierarchy,
    ProjectionCoverage,
    capability_for,
)
from app.idoc_analysis import (
    KIND_FIELD,
    KIND_IDOC,
    KIND_SEGMENT,
    WARNING_CANONICAL_SUBSET,
    WARNING_DEFINITION_MISMATCH,
    WARNING_LAYOUT_ASSUMPTIONS,
    WARNING_LEVEL_DISAGREEMENT,
    WARNING_OPAQUE_SDATA,
    analyze_idoc,
)
from app.idoc_emitter import IdocEmitter, validate_idoc_xml
from app.idoc_import_source import IdocImportSource
from app.idoc_normalizer import IdocNormalizer
from app.idoc_parser import (
    CONTROL_RECORD_FIELDS,
    CONTROL_RECORD_LENGTH,
    DATA_RECORD_HEADER_LENGTH,
    DATA_RECORD_LENGTH,
    FORM_FLAT,
    FORM_XML,
    IDOC_LAYOUT_ASSUMPTIONS,
    IdocParseError,
    is_idoc,
    is_segment_definition,
    iter_segments,
    parse_idoc,
    parse_segment_definitions,
)
from app.import_source import DetectionInput, ImportSourceError, get_import_source
from app.payload_analysis import STATUS_AVAILABLE, ValueVisibility, apply_value_visibility

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "idoc"


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_XML_ORDERS = _fixture("02-typical-xml-orders05.xml")
_XML_NESTED = _fixture("03-composition-xml-nested-segments.xml")
_FLAT_MULTI = _fixture("04-stress-flat-multi-idoc.txt")
_FLAT_ORDERS = _fixture("06-typical-flat-orders05.txt")
_FLAT_CUSTMAS = _fixture("07-with-definition-set/custmas01.txt")
_DEFINITIONS_XML = _fixture("07-with-definition-set/segments.xml")


def _control(**values: str) -> str:
    """A 524-character EDI_DC40 record with ``values`` placed at their layout offsets."""
    defaults = {"TABNAM": "EDI_DC40", "DOCNUM": "0000000000000001", "IDOCTYP": "ZTEST01"}
    defaults.update(values)
    return "".join(defaults.get(name, "").ljust(width)[:width] for name, width in CONTROL_RECORD_FIELDS)


def _record(
    name: str, number: int, parent: int, level: int, sdata: str = "", docnum: str = "0000000000000001"
) -> str:
    """A 1063-character EDI_DD40 record."""
    return (
        name.ljust(30)
        + "100"
        + docnum
        + f"{number:06d}"
        + f"{parent:06d}"
        + f"{level:02d}"
        + sdata.ljust(1000)
    )


def _flat(*records: str) -> str:
    return "\n".join(records) + "\n"


def _walk(node: Any) -> List[Any]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk(child))
    return nodes


def _all(document: Any) -> List[Any]:
    return [node for root in document.tree for node in _walk(root)]


@pytest.fixture()
def adapter() -> IdocImportSource:
    return IdocImportSource()


@pytest.fixture()
def definition_set() -> IntakeFileset:
    return IntakeFileset(
        root="custmas01.txt",
        members={"custmas01.txt": _FLAT_CUSTMAS, "segments.xml": _DEFINITIONS_XML},
    )


# ---------------------------------------------------------------------------
# Layout constants and detection
# ---------------------------------------------------------------------------


def test_record_layouts_have_their_documented_lengths():
    assert CONTROL_RECORD_LENGTH == 524
    assert DATA_RECORD_HEADER_LENGTH == 63
    assert DATA_RECORD_LENGTH == 1063
    assert len(IDOC_LAYOUT_ASSUMPTIONS) >= 4


def test_is_idoc_recognises_both_forms():
    assert is_idoc(_XML_ORDERS)
    assert is_idoc(_FLAT_ORDERS)
    assert not is_idoc(_DEFINITIONS_XML)
    assert is_segment_definition(_DEFINITIONS_XML)


@pytest.mark.parametrize(
    "text",
    [
        "UNB+UNOC:3+A+B+260101:0000+1'UNH+1+ORDERS:D:96A:UN'",
        "<?xml version='1.0'?><Invoice><Id>1</Id></Invoice>",
        "This file talks about EDI_DC40 records.",
        "E\x00D\x00I\x00_\x00D\x00C\x004\x000\x00",
        "",
    ],
)
def test_is_idoc_refuses_lookalikes(text: str):
    assert not is_idoc(text)


def test_detection_confidences(adapter: IdocImportSource):
    flat = adapter.detect(DetectionInput(text=_FLAT_ORDERS))
    xml = adapter.detect(DetectionInput(text=_XML_ORDERS))
    bare = adapter.detect(
        DetectionInput(text="<ORDERS05><IDOC BEGIN='1'><E1X SEGMENT='1'/></IDOC></ORDERS05>")
    )
    assert (flat.confidence, xml.confidence, bare.confidence) == (0.97, 0.95, 0.75)
    assert flat.format == xml.format == "idoc"


def test_adapter_and_emitter_are_registered():
    assert isinstance(get_import_source("idoc"), IdocImportSource)
    assert get_import_source("idoc").paradigm is ApiParadigm.DATA_SCHEMA
    assert isinstance(get_emitter_instance("idoc"), IdocEmitter)


# ---------------------------------------------------------------------------
# Flat form
# ---------------------------------------------------------------------------


def test_flat_control_record_is_cut_at_its_offsets():
    control = parse_idoc(_FLAT_ORDERS).idocs[0].control
    assert control.basic_type == "ORDERS05"
    assert control.message_type == "ORDERS"
    assert control.document_number == "0000000000123456"
    assert control.get("SNDPRN") == "PRDCLNT100"
    assert control.get("RCVPRN") == "0000012345"
    assert (control.line, control.offset, control.length) == (1, 0, 524)
    assert len(control.fields) == len(CONTROL_RECORD_FIELDS)


def test_flat_hierarchy_comes_from_segment_numbers_not_order():
    # E1EDP19 (3) names E1EDP01 (1) as its parent although E1EDK01 (2) sits between them.
    text = _flat(
        _control(),
        _record("E1EDP01", 1, 0, 1, "ITEM"),
        _record("E1EDK01", 2, 0, 1, "HDR"),
        _record("E1EDP19", 3, 1, 2, "MAT"),
    )
    idoc = parse_idoc(text).idocs[0]
    assert [segment.name for segment in idoc.segments] == ["E1EDP01", "E1EDK01"]
    assert [child.name for child in idoc.segments[0].children] == ["E1EDP19"]
    assert idoc.segments[0].children[0].depth == 2


def test_flat_level_disagreement_is_recorded_not_trusted():
    text = _flat(_control(), _record("E1A", 1, 0, 1), _record("E1B", 2, 1, 5))
    idoc = parse_idoc(text).idocs[0]
    assert idoc.segments[0].children[0].level == 5
    assert idoc.segments[0].children[0].depth == 2
    assert idoc.level_disagreements == (2,)
    assert WARNING_LEVEL_DISAGREEMENT in [w.code for w in analyze_idoc(parse_idoc(text)).warnings]


def test_flat_without_definition_keeps_sdata_opaque():
    segment = parse_idoc(_FLAT_ORDERS).idocs[0].segments[0]
    assert not segment.defined
    assert [field.name for field in segment.fields] == ["SDATA"]
    assert segment.fields[0].value.startswith("   EUR  1.00000")  # leading blanks kept
    assert not segment.fields[0].value.endswith(" ")  # trailing padding removed


def test_flat_with_definition_cuts_fields(adapter: IdocImportSource, definition_set: IntakeFileset):
    document = adapter.parse_fileset(definition_set)
    header = document.idocs[0].segments[0]
    assert header.defined
    values = {field.name: field.value for field in header.fields}
    assert values == {"KUNNR": "0000012345", "NAME1": "ACME RETAIL BV", "LAND1": "NL", "WAERS": "EUR"}
    assert [(f.offset, f.length) for f in header.fields] == [(0, 10), (10, 40), (50, 3), (53, 5)]
    assert [child.name for child in header.children] == ["Z1CUSTADR", "Z1CUSTADR", "Z1CUSTBNK"]


def test_short_data_record_is_padded_back():
    text = _flat(_control(), _record("E1A", 1, 0, 1).rstrip())
    assert parse_idoc(text).idocs[0].segments[0].length == 63


def test_two_idocs_in_one_flat_file():
    document = parse_idoc(_FLAT_MULTI)
    assert document.form == FORM_FLAT
    assert [idoc.control.document_number for idoc in document.idocs] == [
        "0000000000123457",
        "0000000000123458",
    ]
    assert document.idocs[0].control.extension == "ZORDERS05_EXT"


@pytest.mark.parametrize(
    ("records", "code", "fragment"),
    [
        ((_control()[:84],), "INPUT_SEMANTIC_INVALID", "524"),
        ((_control() + "X",), "INPUT_MALFORMED", "524"),
        ((_control(IDOCTYP=""), _record("E1A", 1, 0, 1)), "INPUT_SEMANTIC_INVALID", "IDOCTYP"),
        ((_control(),), "INPUT_SEMANTIC_INVALID", "no data segment"),
        ((_control(), _record("E1A", 1, 0, 1)[:40]), "INPUT_TRUNCATED", "truncated"),
        ((_control(), _record("E1A", 1, 0, 1)[:40], _record("E1B", 2, 0, 1)), "INPUT_MALFORMED", "header"),
        ((_control(), _record("E1A", 1, 0, 1) + "X"), "INPUT_MALFORMED", "1063"),
        ((_control(), _record("E1A", 1, 9, 2)), "INPUT_SEMANTIC_INVALID", "does not precede"),
        ((_control(), _record("E1A", 1, 0, 1), _record("E1B", 1, 0, 1)), "INPUT_SEMANTIC_INVALID", "repeats"),
        (
            (_control(), _record("E1A", 1, 0, 1, docnum="0000000000000099")),
            "INPUT_SEMANTIC_INVALID",
            "belongs to",
        ),
        ((_control(), _record("", 1, 0, 1)), "INPUT_MALFORMED", "SEGNAM"),
        (
            (_control(), "E1A".ljust(30) + "100" + "0000000000000001" + "00000X000000" + "01"),
            "INPUT_MALFORMED",
            "non-numeric",
        ),
    ],
)
def test_flat_refusals_carry_a_taxonomy_code(records, code, fragment):
    with pytest.raises(IdocParseError) as caught:
        parse_idoc(_flat(*records))
    assert caught.value.code == code
    assert fragment in str(caught.value)


def test_data_record_before_any_control_record():
    # Detection needs EDI_DC40 first, so the guard is exercised through the flat reader directly.
    from app.idoc_parser import _parse_flat

    with pytest.raises(IdocParseError) as caught:
        _parse_flat(_flat(_record("E1A", 1, 0, 1)), None, None)
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------
# XML form
# ---------------------------------------------------------------------------


def test_xml_nesting_is_numbered_in_document_order():
    idoc = parse_idoc(_XML_NESTED).idocs[0]
    header = idoc.segments[0]
    assert header.name == "E1EDK01" and header.number == 1 and header.parent_number == 0
    names = [(s.name, s.number, s.parent_number, s.depth) for s in iter_segments(idoc.segments)][:6]
    assert names[1] == ("E1EDK14", 2, 1, 2)
    assert ("E1EDKA3", 4, 3, 3) in names
    assert idoc.control.extension == "ZORDERS05_EXT"


def test_xml_fields_are_exact():
    document = parse_idoc(_XML_ORDERS)
    assert document.form == FORM_XML and document.root_element == "ORDERS05"
    partner = document.idocs[0].segments[4]
    assert partner.name == "E1EDKA1"
    assert partner.field_value("NAME1") == "Acme Retail BV"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-unclosed-segment.xml", "INPUT_MALFORMED"),
        ("negative/02-semantic-missing-control-record.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-segment.xml", "INPUT_TRUNCATED"),
        ("negative/06-semantic-short-control-record.txt", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_corpus_negatives(name: str, code: str):
    with pytest.raises(IdocParseError) as caught:
        parse_idoc(_fixture(name))
    assert caught.value.code == code


def test_xml_without_idoc_element_or_basic_type():
    with pytest.raises(IdocParseError) as caught:
        parse_idoc(
            "<ORDERS05><IDOC><EDI_DC40><TABNAM>EDI_DC40</TABNAM></EDI_DC40><E1A SEGMENT='1'/></IDOC></ORDERS05>"
        )
    assert caught.value.code == "INPUT_SEMANTIC_INVALID" and "IDOCTYP" in str(caught.value)


def test_xml_guards_keep_their_own_code():
    text = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "x">]><X><IDOC><EDI_DC40/></IDOC></X>'
    with pytest.raises(IdocParseError) as caught:
        parse_idoc(text)
    assert caught.value.code == "INPUT_UNSAFE_CONSTRUCT"


def test_encoding_faults_are_code_less():
    for text in ("﻿" + _XML_ORDERS, _FLAT_ORDERS.replace("E1EDK01", "E1\x00DK01", 1)):
        with pytest.raises(IdocParseError) as caught:
            parse_idoc(text)
        assert caught.value.code is None


def test_adapter_parse_carries_the_code(adapter: IdocImportSource):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_fixture("negative/03-truncated-mid-segment.xml"))
    assert caught.value.code == "INPUT_TRUNCATED"


# ---------------------------------------------------------------------------
# Segment definitions and filesets
# ---------------------------------------------------------------------------


def test_segment_definitions_are_read():
    definitions = parse_segment_definitions(_DEFINITIONS_XML, source_label="segments.xml")
    assert (definitions.basic_type, definitions.release) == ("ZCUSTMAS01", "740")
    address = definitions.segments["Z1CUSTADR"]
    assert (address.parent, address.max_occurs) == ("Z1CUSTHDR", 9999)
    assert address.fields[1].name == "STRAS" and address.fields[1].offset == 6


@pytest.mark.parametrize(
    "text",
    [
        "<NotSegments/>",
        "<IDocSegments><Segment/></IDocSegments>",
        "<IDocSegments><Segment name='Z'><Field name='A' offset='x' length='1'/></Segment></IDocSegments>",
        "<IDocSegments><Segment name='Z'><Field name='A' offset='999' length='5'/></Segment></IDocSegments>",
        "<IDocSegments><Segment",
    ],
)
def test_bad_segment_definitions_are_refused(text: str):
    with pytest.raises(IdocParseError) as caught:
        parse_segment_definitions(text)
    assert caught.value.code == "INPUT_MALFORMED"


def test_fileset_root_may_be_the_definition(adapter: IdocImportSource):
    fileset = IntakeFileset(
        root="segments.xml", members={"custmas01.txt": _FLAT_CUSTMAS, "segments.xml": _DEFINITIONS_XML}
    )
    assert adapter.parse_fileset(fileset).idocs[0].segments[0].defined


def test_fileset_without_an_idoc(adapter: IdocImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="segments.xml", members={"segments.xml": _DEFINITIONS_XML}))


def test_unreadable_definition_member(adapter: IdocImportSource):
    fileset = IntakeFileset(
        root="custmas01.txt",
        members={"custmas01.txt": _FLAT_CUSTMAS, "bad.xml": "<IDocSegments><Segment/></IDocSegments>"},
    )
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse_fileset(fileset)
    assert caught.value.code == "INPUT_MALFORMED"


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def _types(api) -> dict:
    return {item.name: item for item in api.types}


def test_normalizer_builds_basic_type_and_segment_types(adapter: IdocImportSource):
    api = adapter.normalize(adapter.parse(_XML_ORDERS))
    assert api.format == "idoc" and api.title == "IDoc ORDERS05"
    types = _types(api)
    root = {field.name: field for field in types["ORDERS05"].fields}
    assert root["E1EDK01"].type.item is None  # one per IDoc
    assert root["E1EDKA1"].type.item is not None  # repeated → list
    item = {field.name: field for field in types["E1EDP01"].fields}
    assert {"MENGE", "E1EDP19", "E1EDP26"} <= set(item)
    assert all(t.kind is TypeKind.RECORD for t in api.types)
    # Values are never defaults; they are only in the emitter template.
    assert all(field.default is None for t in api.types for field in t.fields)
    assert api.extras["idoc_segments"][0]["fields"][0] == ["CURCY", "EUR"]


def test_flat_and_xml_twins_share_hierarchy_and_control(adapter: IdocImportSource):
    flat = adapter.normalize(adapter.parse(_FLAT_ORDERS), include_raw=False)
    xml = adapter.normalize(adapter.parse(_XML_ORDERS), include_raw=False)
    assert flat.extras["idoc_control"] == xml.extras["idoc_control"]

    def shape(api):
        return {
            t.name: sorted(
                (f.name, f.type.item is not None)
                for f in t.fields
                if f.name != "SDATA" and f.name.startswith("E1")
            )
            for t in api.types
        }

    assert shape(flat) == shape(xml)


def test_flat_and_xml_with_the_same_definitions_give_the_same_model(
    adapter: IdocImportSource, definition_set: IntakeFileset
):
    """The FMT-6.2 acceptance criterion: both forms import to the same canonical model."""
    flat = adapter.normalize(adapter.parse_fileset(definition_set), include_raw=False)
    xml_text = IdocEmitter().emit(flat).files[0].content
    xml_set = IntakeFileset(
        root="custmas01.xml", members={"custmas01.xml": xml_text, "segments.xml": _DEFINITIONS_XML}
    )
    xml_document = adapter.parse_fileset(xml_set)
    assert xml_document.form == FORM_XML
    xml = adapter.normalize(xml_document, include_raw=False)
    assert flat.model_dump() == xml.model_dump()
    header = {field.name: field for field in _types(flat)["Z1CUSTHDR"].fields}
    assert header["NAME1"].constraints.max_length == 40
    assert header["NAME1"].description == "Name"
    assert header["Z1CUSTBNK"].type.item is not None  # maxOccurs 99, observed once


def test_normalizer_rejects_foreign_ast(adapter: IdocImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "idoc"})
    with pytest.raises(ValueError):
        IdocNormalizer().normalize({"not": "idoc"})


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def test_control_record_is_structure_never_a_value():
    document = analyze_idoc(parse_idoc(_XML_ORDERS))
    root = document.tree[0]
    assert root.kind == KIND_IDOC
    assert root.attributes["basicType"] == "ORDERS05"
    assert root.attributes["messageType"] == "ORDERS"
    assert root.attributes["senderPartner"] == "PRDCLNT100"
    assert root.attributes["directionLabel"] == "Outbound"
    assert root.attributes["controlRecord"]["RCVPRN"] == "0000012345"
    structural = apply_value_visibility(document, ValueVisibility.STRUCTURAL)
    kept = structural.tree[0].attributes
    assert kept["basicType"] == "ORDERS05" and kept["senderPartner"] == "PRDCLNT100"
    assert not any(node.value_present for node in [structural.tree[0]])


def test_field_values_follow_visibility():
    document = analyze_idoc(parse_idoc(_XML_ORDERS))
    fields = [node for node in _all(document) if node.kind == KIND_FIELD]
    assert fields and all(node.value_present for node in fields)
    for node in _all(document):
        assert "Acme Retail BV" not in str(node.attributes)
    withheld = apply_value_visibility(document, ValueVisibility.STRUCTURAL)
    assert all(node.value is None for node in _all(withheld) if node.kind == KIND_FIELD)


def test_segments_nest_under_their_parents():
    document = analyze_idoc(parse_idoc(_FLAT_ORDERS))
    item = next(node for node in document.tree[0].children if node.name == "E1EDP01")
    assert [child.name for child in item.children if child.kind == KIND_SEGMENT] == ["E1EDP19", "E1EDP26"]
    assert item.attributes["segmentNumber"] == 7 and item.attributes["parentSegmentNumber"] == 0
    assert item.location.line == 8 and item.location.length == 1063


def test_flat_analysis_states_layout_assumptions_and_offsets(adapter, definition_set):
    document = adapter.analyze(adapter.parse_fileset(definition_set))
    assert document.status == STATUS_AVAILABLE
    codes = [warning.code for warning in document.warnings]
    assert codes == [WARNING_LAYOUT_ASSUMPTIONS]
    assert IDOC_LAYOUT_ASSUMPTIONS[0] in document.warnings[0].message
    name = next(node for node in _all(document) if node.kind == KIND_FIELD and node.name == "NAME1")
    assert (name.attributes["offset"], name.attributes["recordOffset"], name.attributes["length"]) == (
        10,
        73,
        40,
    )
    assert name.attributes["description"] == "Name"
    assert "idoc.field_offsets" in document.capabilities.supported


def test_flat_analysis_without_definition_names_opaque_segments():
    document = analyze_idoc(parse_idoc(_FLAT_ORDERS))
    opaque = next(w for w in document.warnings if w.code == WARNING_OPAQUE_SDATA)
    assert "E1EDK01" in opaque.message
    sdata = next(node for node in _all(document) if node.kind == KIND_FIELD)
    assert sdata.attributes["opaque"] is True


def test_xml_analysis_claims_no_byte_offsets():
    document = analyze_idoc(parse_idoc(_XML_ORDERS))
    assert "idoc.byte_offsets" in document.capabilities.unsupported
    assert WARNING_LAYOUT_ASSUMPTIONS not in [w.code for w in document.warnings]
    assert all(node.location.offset is None for node in _all(document))


def test_multi_idoc_keeps_every_idoc_and_says_which_was_converted():
    document = analyze_idoc(parse_idoc(_FLAT_MULTI), max_nodes=1)
    assert [node.kind for node in document.tree] == [KIND_IDOC, KIND_IDOC]
    subset = next(w for w in document.warnings if w.code == WARNING_CANONICAL_SUBSET)
    assert "IDoc 0000000000123457 (ORDERS05)" in subset.message


def test_definition_for_another_basic_type_is_noted():
    definitions = parse_segment_definitions(_DEFINITIONS_XML)
    document = analyze_idoc(parse_idoc(_XML_ORDERS, definitions=definitions))
    messages = [w.message for w in document.warnings if w.code == WARNING_DEFINITION_MISMATCH]
    assert any("ZCUSTMAS01" in message for message in messages)
    assert any("does not describe" in message for message in messages)


def test_adapter_analyze_rejects_foreign_ast(adapter: IdocImportSource):
    with pytest.raises(ImportSourceError):
        adapter.analyze({"not": "idoc"})
    assert "idoc.control_record" in adapter.analysis_capabilities().supported


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "01-minimal-xml-orders05.xml",
        "02-typical-xml-orders05.xml",
        "03-composition-xml-nested-segments.xml",
        "05-real-world-xml-invoic02.xml",
    ],
)
def test_xml_round_trips_exactly(adapter: IdocImportSource, name: str):
    model = adapter.normalize(adapter.parse(_fixture(name)), include_raw=False)
    emitted = IdocEmitter().emit(model)
    content = emitted.files[0].content
    validate_idoc_xml(content)
    again = adapter.normalize(adapter.parse(content), include_raw=False)
    assert again.model_dump() == model.model_dump()
    assert emitted.files[0].path.endswith(".xml")


def test_emitter_escapes_values_and_writes_empty_elements(adapter: IdocImportSource):
    text = _XML_ORDERS.replace("<NAME1>Acme Retail BV</NAME1>", "<NAME1>A &amp; B &lt;x&gt;</NAME1>", 1)
    text = text.replace("<GEWEI>KGM</GEWEI>", "<GEWEI/>")
    model = adapter.normalize(adapter.parse(text), include_raw=False)
    content = IdocEmitter().emit(model).files[0].content
    assert "<NAME1>A &amp; B &lt;x&gt;</NAME1>" in content
    assert "<GEWEI/>" in content
    assert adapter.normalize(adapter.parse(content), include_raw=False).model_dump() == model.model_dump()


def test_emitter_writes_skeletons_for_segment_types_without_occurrences(adapter: IdocImportSource):
    model = adapter.normalize(adapter.parse(_XML_ORDERS), include_raw=False)
    model.extras["idoc_segments"] = [t for t in model.extras["idoc_segments"] if t["name"] != "E1EDKA1"]
    result = IdocEmitter().emit(model)
    content = result.files[0].content
    assert content.count('<E1EDKA1 SEGMENT="1">') == 2  # a list needs two to read back as one
    assert any(loss.subject.endswith("E1EDKA1") for loss in result.losses)


def test_emitter_requires_an_idoc_model():
    from app.canonical_model import ApiIdentity, CanonicalApi

    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="x"))
    with pytest.raises(ValueError, match="idoc_control"):
        IdocEmitter().emit(api)


def test_export_validation_is_registered():
    assert "idoc" in _VALIDATORS


def test_validate_idoc_xml_refuses_flat_and_garbage():
    with pytest.raises(ValueError):
        validate_idoc_xml(_FLAT_ORDERS)
    with pytest.raises(ValueError):
        validate_idoc_xml("<nope/>")


# ---------------------------------------------------------------------------
# Capability registry
# ---------------------------------------------------------------------------


def test_capability_entry_is_reviewed_and_states_its_boundaries():
    entry = capability_for("idoc")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    assert entry.native_hierarchy is NativeHierarchy.NATIVE
    assert entry.canonical_projection.coverage is ProjectionCoverage.PARTIAL
    assert any("WE60" in note for note in entry.notes)
    assert "idoc.standard_segment_layouts" in entry.unsupported_constructs
    assert not set(entry.supported_constructs) & set(entry.unsupported_constructs)
