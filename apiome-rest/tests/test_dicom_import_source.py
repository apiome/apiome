"""DICOM import — FMT-6.7 (#5451).

Covers the two readers (binary Part 10 and the DICOM JSON model), the normalizer's canonical shape
(attributes keyed by tag and typed by VR, sequences as nested types, the SR content tree as a
hierarchy), the native analysis, and the three boundaries the ticket makes contractual:

* pixel data is never read, never stored and never analysed — and its absence is stated;
* no patient-identifying attribute value is stored at the default value-visibility policy;
* the verbatim upload is not kept as the version's source.

Part 10 inputs are built byte by byte with :func:`_part10` so every transfer syntax, length form and
failure can be exercised without committing more binary fixtures.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pytest

from app import dicom_part10
from app.catalog_conversion import ConversionError, build_conversion_source
from app.dicom_analysis import (
    KIND_CONTENT_ITEM,
    KIND_PIXEL_DATA,
    WARNING_FILESET_MEMBER_SKIPPED,
    WARNING_MEDIA_STORAGE_MISMATCH,
    WARNING_PIXEL_DATA_NOT_READ,
    WARNING_PRIVATE_ATTRIBUTES,
)
from app.dicom_dictionary import (
    PIXEL_DATA_BOUNDARY_STATEMENT,
    attribute_info,
    implicit_vr,
    is_identifying,
    is_pixel_data_tag,
    pascal_name,
    sop_class_name,
    transfer_syntax,
)
from app.dicom_model import VALUE_PIXEL_SKIPPED
from app.dicom_normalizer import SOURCE_RETENTION_REASON
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.import_source import DetectionInput, ImportSourceError, get_import_source, load_builtin_import_sources
from app.import_source_pipeline import source_retention_withheld
from app.payload_analysis import ValueVisibility, apply_value_visibility

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "dicom"

CT_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.2"
BASIC_TEXT_SR = "1.2.840.10008.5.1.4.1.1.88.11"
EXPLICIT_LE = "1.2.840.10008.1.2.1"
IMPLICIT_LE = "1.2.840.10008.1.2"
EXPLICIT_BE = "1.2.840.10008.1.2.2"
DEFLATED = "1.2.840.10008.1.2.1.99"
JPEG_BASELINE = "1.2.840.10008.1.2.4.50"

#: Bytes no reader may ever copy anywhere: they stand in for image content.
PIXEL_SENTINEL = b"PIXELSENTINEL-DO-NOT-READ"
#: A synthetic patient name that must never reach the model or a default-policy record.
PATIENT = "SENTINEL^PATIENT"


@pytest.fixture(scope="module")
def adapter():
    return get_import_source("dicom")


# ---------------------------------------------------------------------------
# Part 10 byte builder
# ---------------------------------------------------------------------------

_LONG = {"OB", "OD", "OF", "OL", "OV", "OW", "SQ", "UC", "UN", "UR", "UT"}
UNDEFINED = 0xFFFFFFFF


def _pad(value: bytes, vr: str) -> bytes:
    if len(value) % 2:
        return value + (b"\x00" if vr == "UI" else b" ")
    return value


def _el(
    tag: int, vr: str, value: bytes, *, explicit: bool = True, little: bool = True, length: Optional[int] = None
) -> bytes:
    """One element. ``length`` overrides the written length (``UNDEFINED`` for delimited values)."""
    e = "<" if little else ">"
    head = struct.pack(e + "HH", tag >> 16, tag & 0xFFFF)
    size = len(value) if length is None else length
    if not explicit:
        return head + struct.pack(e + "L", size) + value
    if vr in _LONG:
        return head + vr.encode() + b"\x00\x00" + struct.pack(e + "L", size) + value
    return head + vr.encode() + struct.pack(e + "H", size) + value


def _text(tag: int, vr: str, text: str, **kwargs) -> bytes:
    return _el(tag, vr, _pad(text.encode(), vr), **kwargs)


def _item(body: bytes, *, little: bool = True, undefined: bool = False) -> bytes:
    e = "<" if little else ">"
    if undefined:
        return struct.pack(e + "HHL", 0xFFFE, 0xE000, UNDEFINED) + body + struct.pack(e + "HHL", 0xFFFE, 0xE00D, 0)
    return struct.pack(e + "HHL", 0xFFFE, 0xE000, len(body)) + body


def _seq_delim(little: bool = True) -> bytes:
    return struct.pack(("<" if little else ">") + "HHL", 0xFFFE, 0xE0DD, 0)


def _meta(ts: str, sop_class: str = CT_IMAGE_STORAGE) -> bytes:
    body = (
        _el(0x00020001, "OB", b"\x00\x01")
        + _text(0x00020002, "UI", sop_class)
        + _text(0x00020003, "UI", "1.2.826.0.1.9999999.9.9")
        + _text(0x00020010, "UI", ts)
    )
    return _el(0x00020000, "UL", struct.pack("<L", len(body))) + body


def _part10(
    dataset: bytes, *, ts: str = EXPLICIT_LE, meta: Optional[bytes] = None, sop_class: str = CT_IMAGE_STORAGE
) -> bytes:
    return b"\x00" * 128 + b"DICM" + (meta if meta is not None else _meta(ts, sop_class)) + dataset


def _base(*, explicit: bool = True, little: bool = True, sop_class: str = CT_IMAGE_STORAGE) -> bytes:
    kw = {"explicit": explicit, "little": little}
    return (
        _text(0x00080016, "UI", sop_class, **kw)
        + _text(0x00080018, "UI", "1.2.826.0.1.9999999.9.9", **kw)
        + _text(0x00080060, "CS", "CT", **kw)
        + _text(0x00100010, "PN", PATIENT, **kw)
    )


def _parse(adapter, data: bytes):
    return adapter.parse_bytes(data, source_label="probe.dcm")


def _type(model, name: str):
    return next(t for t in model.types if t.name == name)


def _field(model, type_name: str, field_name: str):
    return next(f for f in _type(model, type_name).fields if f.name == field_name)


def _walk(nodes) -> List:
    out = []
    for node in nodes:
        out.append(node)
        out.extend(_walk(node.children))
    return out


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------


def test_dictionary_lookups_name_attributes_and_classes() -> None:
    assert attribute_info(0x00100010).keyword == "PatientName"
    assert attribute_info(0x00200037).vm == "6"
    assert attribute_info(0x00091001).keyword is None  # private: not in the dictionary
    assert implicit_vr(0x00100010) == "PN"
    assert implicit_vr(0x7FE00010) == "OW"  # "OB or OW" resolves the implicit-VR way
    assert implicit_vr(0x00090010) == "LO"  # private creator
    assert implicit_vr(0x00091001) == "UN"
    assert sop_class_name(CT_IMAGE_STORAGE) == "CT Image Storage"
    assert sop_class_name(EXPLICIT_LE) is None  # a transfer syntax, not a SOP class
    assert sop_class_name("1.2.3.4") is None
    assert pascal_name("Basic Text SR Storage") == "BasicTextSRStorage"
    assert pascal_name("12-lead ECG Waveform Storage") == "Dicom12LeadECGWaveformStorage"


def test_pixel_data_tags_include_float_variants_and_overlays() -> None:
    for tag in (0x7FE00010, 0x7FE00008, 0x7FE00009, 0x60003000, 0x601E3000):
        assert is_pixel_data_tag(tag)
    for tag in (0x60013000, 0x60003001, 0x00280010):
        assert not is_pixel_data_tag(tag)


def test_identifying_tags_cover_patient_attributes_and_private_data() -> None:
    assert is_identifying(0x00100010)
    assert is_identifying(0x0020000D)
    assert is_identifying(0x00091001)  # private data element
    assert not is_identifying(0x00090010)  # private creator
    assert not is_identifying(0x00080016)  # SOP Class UID is structure


def test_unregistered_transfer_syntax_reads_as_explicit_little_endian() -> None:
    syntax = transfer_syntax("1.2.826.0.1.9999999.99")
    assert syntax.explicit_vr and syntax.little_endian and not syntax.deflated
    assert transfer_syntax(JPEG_BASELINE).encapsulated


# ---------------------------------------------------------------------------
# Detection and binary claim
# ---------------------------------------------------------------------------


def test_detects_part10_by_magic(adapter) -> None:
    result = adapter.detect(DetectionInput(data=_part10(_base())))
    assert result.matched and result.confidence >= 0.9 and result.format == "dicom"


def test_detects_dicom_json(adapter) -> None:
    text = (EXAMPLES / "01-minimal-json.json").read_text()
    assert adapter.detect(DetectionInput(text=text)).confidence >= 0.9
    assert adapter.detect(DetectionInput(document=json.loads(text))).confidence >= 0.9


def test_broken_dicom_json_is_claimed_at_lower_confidence(adapter) -> None:
    text = (EXAMPLES / "negative" / "01-syntactic-broken-json.json").read_text()
    result = adapter.detect(DetectionInput(text=text))
    assert result.matched and result.confidence < 0.9


def test_fhir_imaging_study_is_not_claimed(adapter) -> None:
    text = (EXAMPLES / "negative" / "04-wrong-format-fhir-imagingstudy.json").read_text()
    assert not adapter.detect(DetectionInput(text=text)).matched


def test_accepts_bytes_by_magic_and_by_suffix_even_when_broken(adapter) -> None:
    assert adapter.accepts_bytes(_part10(_base()))
    assert adapter.accepts_bytes(b"not dicom", filename="scan.DCM")
    assert not adapter.accepts_bytes(b"{}", filename="study.json")


# ---------------------------------------------------------------------------
# Part 10: attribute structure, VRs, sequences
# ---------------------------------------------------------------------------


def test_part10_attributes_become_fields_keyed_by_tag_and_typed_by_vr(adapter) -> None:
    model = adapter.normalize(_parse(adapter, _part10(_base())))
    field = _field(model, "CTImageStorage", "PatientName")
    assert field.key == "DICOM.CTImageStorage.00100010"
    assert field.type.name == "DICOM.PN"
    assert field.extras["dicom_tag"] == "(0010,0010)"
    assert field.extras["dicom_vr"] == "PN"
    assert field.extras["dicom_patient_identifying"] is True
    pn = _type(model, "PN")
    assert [f.name for f in pn.fields] == ["Alphabetic", "Ideographic", "Phonetic"]
    cs = _type(model, "CS")
    assert cs.kind.value == "alias" and cs.aliased.name == "string" and cs.constraints.max_length == 16
    meta = _type(model, "FileMetaInformation")
    assert "TransferSyntaxUID" in {f.name for f in meta.fields}


def test_multi_valued_attributes_are_lists(adapter) -> None:
    data = _part10(_base() + _text(0x00080008, "CS", "ORIGINAL\\PRIMARY"))
    model = adapter.normalize(_parse(adapter, data))
    image_type = _field(model, "CTImageStorage", "ImageType")
    assert image_type.type.item is not None and image_type.type.item.name == "DICOM.CS"


def test_nested_sequences_are_nested_types_for_every_length_form(adapter) -> None:
    code = _text(0x00080100, "SH", "113704") + _text(0x00080104, "LO", "Clinical Trial Protocol")
    concept = _el(0x0040A043, "SQ", _item(code))
    inner = _text(0x0040A040, "CS", "CONTAINER") + concept
    # Undefined-length ContentSequence holding an undefined-length item that nests a defined one.
    content = _el(0x0040A730, "SQ", _item(inner, undefined=True) + _seq_delim(), length=UNDEFINED)
    model = adapter.normalize(_parse(adapter, _part10(_base() + content)))
    sequence = _field(model, "CTImageStorage", "ContentSequence")
    assert sequence.type.item.name == "DICOM.ContentSequenceItem"
    item_field = _field(model, "ContentSequenceItem", "ConceptNameCodeSequence")
    assert item_field.type.item.name == "DICOM.ConceptNameCodeSequenceItem"
    assert {f.name for f in _type(model, "ConceptNameCodeSequenceItem").fields} == {"CodeValue", "CodeMeaning"}


def test_folded_items_make_missing_attributes_nullable(adapter) -> None:
    first = _text(0x00081150, "UI", CT_IMAGE_STORAGE) + _text(0x00081155, "UI", "1.2.3")
    second = _text(0x00081150, "UI", CT_IMAGE_STORAGE)
    data = _part10(_base() + _el(0x00081140, "SQ", _item(first) + _item(second)))
    model = adapter.normalize(_parse(adapter, data))
    assert _field(model, "ReferencedImageSequenceItem", "ReferencedSOPClassUID").type.nullable is False
    assert _field(model, "ReferencedImageSequenceItem", "ReferencedSOPInstanceUID").type.nullable is True


def test_unknown_vr_sequence_of_undefined_length_is_read_as_implicit_items(adapter) -> None:
    body = _text(0x00080100, "SH", "X", explicit=False)
    un = _el(0x00091010, "UN", _item(body, undefined=True) + _seq_delim(), length=UNDEFINED)
    data = _part10(_base() + _text(0x00090010, "LO", "ACME") + un)
    document = _parse(adapter, data)
    element = document.datasets[0].element(0x00091010)
    assert element.items and element.items[0].elements[0].vr == "SH"
    model = adapter.normalize(document)
    private = _field(model, "CTImageStorage", "Private_0009_1010")
    assert private.extras["dicom_private_creator"] == "ACME"
    assert private.extras["dicom_private"] is True


@pytest.mark.parametrize(
    ("ts", "explicit", "little"),
    [(IMPLICIT_LE, False, True), (EXPLICIT_BE, True, False), (JPEG_BASELINE, True, True)],
)
def test_transfer_syntaxes_are_read(adapter, ts: str, explicit: bool, little: bool) -> None:
    data = _part10(_base(explicit=explicit, little=little), ts=ts)
    document = _parse(adapter, data)
    dataset = document.datasets[0]
    assert dataset.transfer_syntax == ts
    assert dataset.first_value(0x00100010) == PATIENT
    model = adapter.normalize(document)
    assert _field(model, "CTImageStorage", "PatientName").type.name == "DICOM.PN"
    if not explicit:
        assert _field(model, "CTImageStorage", "PatientName").extras["dicom_vr_implicit"] is True


def test_deflated_dataset_is_inflated(adapter) -> None:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    deflated = compressor.compress(_base()) + compressor.flush()
    document = _parse(adapter, _part10(deflated, ts=DEFLATED))
    assert document.datasets[0].deflated
    assert document.datasets[0].first_value(0x00080060) == "CT"


def test_deflated_dataset_expansion_is_bounded(adapter, monkeypatch) -> None:
    monkeypatch.setattr(dicom_part10, "MAX_INFLATED_BYTES", 16)
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    deflated = compressor.compress(_base()) + compressor.flush()
    with pytest.raises(ImportSourceError) as caught:
        _parse(adapter, _part10(deflated, ts=DEFLATED))
    assert caught.value.code == "INPUT_EXPANSION_LIMIT"


# ---------------------------------------------------------------------------
# The pixel-data boundary
# ---------------------------------------------------------------------------


def _with_pixel_data(encapsulated: bool = False) -> bytes:
    if encapsulated:
        fragments = _item(b"") + _item(PIXEL_SENTINEL + b"!") + _item(PIXEL_SENTINEL + b"?")
        pixel = _el(0x7FE00010, "OB", fragments + _seq_delim(), length=UNDEFINED)
        return _part10(_base() + pixel, ts=JPEG_BASELINE)
    return _part10(_base() + _el(0x7FE00010, "OW", PIXEL_SENTINEL + b"!"))


@pytest.mark.parametrize("encapsulated", [False, True])
def test_pixel_data_is_skipped_and_never_read(adapter, encapsulated: bool) -> None:
    data = _with_pixel_data(encapsulated)
    document = _parse(adapter, data)
    dataset = document.datasets[0]
    element = dataset.element(0x7FE00010)
    assert element.value_form == VALUE_PIXEL_SKIPPED and element.values == ()
    (skip,) = dataset.pixel_data
    if encapsulated:
        assert skip.declared_length is None and skip.fragments == 2
    else:
        assert skip.declared_length == len(PIXEL_SENTINEL) + 1
    # The analysed material has the pixel value excised.
    assert PIXEL_SENTINEL not in document.source

    model = adapter.normalize(document)
    model_json = json.dumps(model.model_dump(mode="json"))
    assert PIXEL_SENTINEL.decode() not in model_json
    field = _field(model, "CTImageStorage", "PixelData")
    assert field.extras["dicom_pixel_data"] == {"read": False, "stored": False}
    statement = model.extras["dicom_pixel_data"]
    assert statement["present"] is True and statement["read"] is False and statement["stored"] is False
    assert statement["statement"] == PIXEL_DATA_BOUNDARY_STATEMENT

    analysis = adapter.analyze(document)
    analysis_json = analysis.model_dump_json()
    assert PIXEL_SENTINEL.decode() not in analysis_json
    pixel_nodes = [n for n in _walk(analysis.tree) if n.kind == KIND_PIXEL_DATA]
    assert len(pixel_nodes) == 1
    assert pixel_nodes[0].value is None and pixel_nodes[0].attributes["read"] is False
    assert WARNING_PIXEL_DATA_NOT_READ in {w.code for w in analysis.warnings}


def test_pixel_value_bytes_are_never_sliced(adapter, monkeypatch) -> None:
    """The reader slices element values through one place; it must never be asked for pixel bytes."""
    data = _with_pixel_data()
    start = data.index(PIXEL_SENTINEL)
    real_decode = dicom_part10._decode_values

    def guarded(ctx, vr, raw, path):
        assert PIXEL_SENTINEL not in raw
        return real_decode(ctx, vr, raw, path)

    monkeypatch.setattr(dicom_part10, "_decode_values", guarded)
    document = _parse(adapter, data)
    assert document.datasets[0].pixel_data[0].value_span == (start, len(data))


def test_absence_of_pixel_data_is_stated_too(adapter) -> None:
    model = adapter.normalize(_parse(adapter, _part10(_base())))
    statement = model.extras["dicom_pixel_data"]
    assert statement["present"] is False and statement["elements"] == []
    assert statement["statement"] == PIXEL_DATA_BOUNDARY_STATEMENT


def test_json_pixel_data_bulk_uri_is_not_followed(adapter) -> None:
    text = json.dumps(
        {
            "00080016": {"vr": "UI", "Value": [CT_IMAGE_STORAGE]},
            "7FE00010": {"vr": "OW", "BulkDataURI": "https://pacs.example.com/frames/1"},
            "60003000": {"vr": "OW", "InlineBinary": "UElYRUxT"},
        }
    )
    document = adapter.parse(text)
    skips = document.datasets[0].pixel_data
    assert [(s.tag, s.json_form) for s in skips] == [(0x60003000, "InlineBinary"), (0x7FE00010, "BulkDataURI")]
    model = adapter.normalize(document)
    assert "pacs.example.com" not in json.dumps(model.model_dump(mode="json"))


def test_corpus_stress_fixture_states_its_pixel_data(adapter) -> None:
    data = (EXAMPLES / "04-stress-part10-sequences-and-pixeldata.dcm").read_bytes()
    document = _parse(adapter, data)
    model = adapter.normalize(document)
    (entry,) = model.extras["dicom_pixel_data"]["elements"]
    assert entry == {"tag": "(7FE0,0010)", "vr": "OW", "path": "(7FE0,0010)", "read": False, "declaredLength": 8}
    warnings = {w.code for w in adapter.analyze(document).warnings}
    assert {WARNING_PIXEL_DATA_NOT_READ, WARNING_PRIVATE_ATTRIBUTES} <= warnings


# ---------------------------------------------------------------------------
# Part 10 refusals
# ---------------------------------------------------------------------------


def _code(adapter, data: bytes) -> str:
    with pytest.raises(ImportSourceError) as caught:
        _parse(adapter, data)
    return caught.value.code


def test_truncated_inside_a_value(adapter) -> None:
    data = _part10(_base())
    assert _code(adapter, data[:-3]) == "INPUT_TRUNCATED"


def test_truncated_inside_a_header_and_inside_the_magic(adapter) -> None:
    data = _part10(_base())
    assert _code(adapter, data[: len(data) - len(_text(0x00100010, "PN", PATIENT)) + 3]) == "INPUT_TRUNCATED"
    assert _code(adapter, data[:130]) == "INPUT_TRUNCATED"


def test_truncated_inside_an_undefined_length_sequence(adapter) -> None:
    content = _el(0x0040A730, "SQ", _item(_text(0x0040A040, "CS", "TEXT"), undefined=True), length=UNDEFINED)
    assert _code(adapter, _part10(_base() + content)) == "INPUT_TRUNCATED"


def test_unknown_vr_is_malformed(adapter) -> None:
    bad = struct.pack("<HH", 0x0010, 0x0020) + b"ZZ" + struct.pack("<H", 2) + b"AB"
    assert _code(adapter, _part10(_base() + bad)) == "INPUT_MALFORMED"


def test_value_overrunning_its_item_is_malformed(adapter) -> None:
    body = _text(0x00081150, "UI", CT_IMAGE_STORAGE)
    item = struct.pack("<HHL", 0xFFFE, 0xE000, 4) + body  # declares 4 bytes, holds more
    data = _part10(_base() + _el(0x00081140, "SQ", item) + _text(0x00200013, "IS", "1"))
    assert _code(adapter, data) == "INPUT_MALFORMED"


def test_missing_magic_and_missing_transfer_syntax_are_semantic(adapter) -> None:
    assert _code(adapter, b"\x00" * 128 + b"NOPE" + _base()) == "INPUT_SEMANTIC_INVALID"
    assert _code(adapter, b"short") == "INPUT_SEMANTIC_INVALID"
    meta = _el(0x00020001, "OB", b"\x00\x01")
    assert _code(adapter, _part10(_base(), meta=meta)) == "INPUT_SEMANTIC_INVALID"


def test_dataset_without_sop_class_is_semantic(adapter) -> None:
    dataset = _text(0x00100010, "PN", PATIENT)
    assert _code(adapter, _part10(dataset)) == "INPUT_SEMANTIC_INVALID"


def test_sequence_depth_is_bounded(adapter) -> None:
    nested = _text(0x00080100, "SH", "X")
    for _ in range(dicom_part10.MAX_SEQUENCE_DEPTH + 1):
        nested = _el(0x0040A730, "SQ", _item(nested))
    assert _code(adapter, _part10(_base() + nested)) == "INPUT_DEPTH_LIMIT"


def test_media_storage_mismatch_is_a_warning_not_a_refusal(adapter) -> None:
    data = _part10(_base(), sop_class=BASIC_TEXT_SR)
    document = _parse(adapter, data)
    assert WARNING_MEDIA_STORAGE_MISMATCH in {w.code for w in adapter.analyze(document).warnings}
    summary = adapter.normalize(document).extras["dicom_datasets"][0]
    assert summary["mediaStorageMatchesSopClass"] is False


# ---------------------------------------------------------------------------
# DICOM JSON and the Structured Report content tree
# ---------------------------------------------------------------------------


def test_structured_report_content_tree_imports_as_a_hierarchy(adapter) -> None:
    text = (EXAMPLES / "03-composition-structured-report-json.json").read_text()
    model = adapter.normalize(adapter.parse(text))
    (tree,) = model.extras["dicom_sr_content_trees"]
    root = tree["root"]
    assert root["valueType"] == "CONTAINER" and root["conceptName"]["meaning"] == "Radiology Report"
    findings = next(child for child in root["children"] if child.get("conceptName", {}).get("meaning") == "Findings")
    assert [child["valueType"] for child in findings["children"]] == ["TEXT", "NUM"]
    assert all(child["relationshipType"] == "CONTAINS" for child in findings["children"])
    # The recursive content item macro is one self-referencing type.
    content = _field(model, "ContentSequenceItem", "ContentSequence")
    assert content.type.item.name == "DICOM.ContentSequenceItem"
    # Content item values are payload and stay out of the tree.
    assert "TextValue" not in json.dumps(tree) and "No acute" not in json.dumps(tree)


def test_sr_content_items_are_analysis_nodes(adapter) -> None:
    text = (EXAMPLES / "03-composition-structured-report-json.json").read_text()
    analysis = adapter.analyze(adapter.parse(text), source=text)
    items = [n for n in _walk(analysis.tree) if n.kind == KIND_CONTENT_ITEM]
    assert {n.attributes.get("valueType") for n in items} >= {"CODE", "CONTAINER", "TEXT", "NUM"}
    assert analysis.tree[0].attributes["structuredReport"] is True


def test_json_array_of_datasets_and_query_results(adapter) -> None:
    text = json.dumps(
        [
            {"00080052": {"vr": "CS", "Value": ["STUDY"]}, "0020000D": {"vr": "UI", "Value": ["1.2.3"]}},
            {
                "00080016": {"vr": "UI", "Value": [CT_IMAGE_STORAGE]},
                "00100010": {"vr": "PN", "Value": [{"Alphabetic": PATIENT}]},
            },
        ]
    )
    model = adapter.normalize(adapter.parse(text))
    assert {"StudyQueryResult", "CTImageStorage"} <= {t.name for t in model.types}
    assert model.extras["dicom_study_set"]["datasets"] == 2


SOP = CT_IMAGE_STORAGE


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"00080016": {"vr": "XX", "Value": ["1"]}}, "INPUT_MALFORMED"),
        ({"00080016": {"vr": "UI", "Value": "1.2"}}, "INPUT_MALFORMED"),
        ({"00080016": {"vr": "UI", "Value": [SOP]}, "notatag": {"vr": "CS"}}, "INPUT_MALFORMED"),
        ({"00080016": {"vr": "UI", "Value": [SOP], "BulkDataURI": "x"}}, "INPUT_MALFORMED"),
        ({"00080016": {"vr": "UI", "Value": [SOP]}, "00100010": {"vr": "PN", "Value": [{"N": 1}]}}, "INPUT_MALFORMED"),
        ({"resourceType": "ImagingStudy"}, "FORMAT_MISMATCH"),
        ({"00100010": {"vr": "PN", "Value": [{"Alphabetic": PATIENT}]}}, "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_json_refusals_carry_codes(adapter, body, code: str) -> None:
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(json.dumps(body))
    assert caught.value.code == code


def test_json_syntax_error_is_left_for_the_pipeline_to_classify(adapter) -> None:
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse('{"00080016": {"vr": "UI"')
    assert caught.value.code is None


# ---------------------------------------------------------------------------
# Filesets
# ---------------------------------------------------------------------------


def test_study_set_fileset_reads_every_member(adapter) -> None:
    folder = EXAMPLES / "07-study-set"
    members = {path.name: path.read_text() for path in folder.iterdir()}
    members["README.txt"] = "not dicom"
    members["series-3/frame.dcm"] = "\x00" * 200
    document = adapter.parse_fileset(IntakeFileset.from_members(members, root="study-index.json"))
    assert len(document.datasets) == 3
    model = adapter.normalize(document)
    assert model.extras["dicom_study_set"] == {"datasets": 3, "distinctStudies": 1, "distinctSeries": 2}
    skipped = {entry["path"] for entry in model.extras["dicom_fileset"]["skippedMembers"]}
    assert skipped == {"README.txt", "series-3/frame.dcm"}
    warnings = [w for w in adapter.analyze(document).warnings if w.code == WARNING_FILESET_MEMBER_SKIPPED]
    assert len(warnings) == 2


def test_fileset_rooted_at_a_part10_member_is_refused(adapter) -> None:
    fileset = IntakeFileset.from_members({"a.dcm": "x"}, root="a.dcm")
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse_fileset(fileset)
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------
# Values: never in the model; withheld at the default policy; source not retained
# ---------------------------------------------------------------------------

_VALID = [
    "01-minimal-json.json",
    "02-typical-ct-instance-json.json",
    "03-composition-structured-report-json.json",
    "04-stress-part10-sequences-and-pixeldata.dcm",
    "05-real-world-mr-series-json.json",
    "06-typical-part10-minimal.dcm",
]
#: Patient-identifying values the corpus fixtures carry.
_FIXTURE_VALUES: Sequence[str] = ("SAMPLE^", "PAT-0", "19850214", "19620905", "CLINICIAN^", "ACC-000")


def _document(adapter, name: str):
    path = EXAMPLES / name
    if name.endswith(".dcm"):
        return adapter.parse_bytes(path.read_bytes(), source_label=name)
    return adapter.parse(path.read_text(), source_label=name)


@pytest.mark.parametrize("name", _VALID)
def test_no_attribute_value_enters_the_canonical_model(adapter, name: str) -> None:
    model = adapter.normalize(_document(adapter, name))
    dumped = json.dumps(model.model_dump(mode="json"))
    for value in _FIXTURE_VALUES:
        assert value not in dumped, f"{value!r} leaked into the {name} model"
    assert model.extras["dicom_values"]["inModel"] is False


@pytest.mark.parametrize("name", _VALID)
def test_default_value_visibility_stores_no_patient_value(adapter, name: str) -> None:
    document = _document(adapter, name)
    analysis = adapter.analyze(document, source=None)
    raw = analysis.model_dump_json()
    assert any(value in raw for value in _FIXTURE_VALUES)  # the analyzer saw them …
    stored = apply_value_visibility(analysis, ValueVisibility.DEFAULT).model_dump_json()
    for value in _FIXTURE_VALUES:  # … and the default policy keeps none of them
        assert value not in stored, f"{value!r} survived the default policy for {name}"


def test_model_asks_for_the_verbatim_source_to_be_withheld(adapter) -> None:
    model = adapter.normalize(_document(adapter, "01-minimal-json.json"))
    assert source_retention_withheld(model) == SOURCE_RETENTION_REASON
    other = get_import_source("json-schema")
    schema = other.normalize(other.parse('{"type": "object", "properties": {"a": {"type": "string"}}}'))
    assert source_retention_withheld(schema) is None


def test_conversion_explains_a_withheld_source() -> None:
    item = {
        "id": "item-1",
        "source_format": "dicom",
        "format_metadata": {"sourceContent": None, "sourceWithheld": SOURCE_RETENTION_REASON},
    }
    with pytest.raises(ConversionError) as caught:
        build_conversion_source(item)
    assert SOURCE_RETENTION_REASON in str(caught.value)


# ---------------------------------------------------------------------------
# Capability panel
# ---------------------------------------------------------------------------


def test_capability_panel_states_the_pixel_boundary_and_value_policy() -> None:
    capability = capability_for("dicom")
    assert PIXEL_DATA_BOUNDARY_STATEMENT in capability.notes
    assert capability.value_visibility.default == ValueVisibility.DEFAULT
    assert "dicom.pixel_data" in capability.canonical_projection.dropped_constructs


def _corpus_pairs() -> List[Tuple[str, str]]:
    return [(name, "dicom") for name in _VALID]


@pytest.mark.parametrize(("name", "fmt"), _corpus_pairs())
def test_every_valid_fixture_is_claimed(adapter, name: str, fmt: str) -> None:
    path = EXAMPLES / name
    if name.endswith(".dcm"):
        result = adapter.detect(DetectionInput(data=path.read_bytes(), filename=name))
    else:
        result = adapter.detect(DetectionInput(text=path.read_text(), filename=name))
    assert result.format == fmt and result.confidence >= 0.9
