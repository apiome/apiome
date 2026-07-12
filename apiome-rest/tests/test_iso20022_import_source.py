"""Tests for ISO 20022 catalog import/export adapters — MFI-22.5 / MFX-29.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.iso20022_emitter import validate_iso20022_document
from app.iso20022_import_source import Iso20022ImportSource
from app.iso20022_normalizer import Iso20022Normalizer
from app.iso20022_parser import is_iso20022, parse_iso20022

_PAIN_001 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/iso20022/01-pain.001-credit-transfer.xml"
).read_text(encoding="utf-8")
_CAMT_053 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/iso20022/02-camt.053-statement.xml"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> Iso20022ImportSource:
    return Iso20022ImportSource()


def test_is_iso20022_recognizes_pain_message():
    assert is_iso20022(_PAIN_001) is True
    assert (
        is_iso20022(
            '<?xml version="1.0"?><xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"></xs:schema>'
        )
        is False
    )


def test_parse_pain_collects_message_id_and_structure():
    doc = parse_iso20022(_PAIN_001)
    assert doc.message_id == "pain.001.001.09"
    assert doc.root.tag == "Document"
    assert doc.root.children[0].tag == "CstmrCdtTrfInitn"
    grp_hdr = next(
        child
        for child in doc.root.children[0].children
        if child.tag == "GrpHdr"
    )
    msg_id = next(field for field in grp_hdr.children if field.tag == "MsgId")
    assert msg_id.text == "MSG-20260115-0001"


def test_parse_camt_fixture_covers_statement_payload():
    doc = parse_iso20022(_CAMT_053)
    assert doc.message_id == "camt.053.001.08"
    assert doc.root.children[0].tag == "BkToCstmrStmt"
    assert any(child.tag == "Stmt" for child in doc.root.children[0].children)


def test_normalizer_maps_data_schema_types():
    doc = parse_iso20022(_PAIN_001)
    api = Iso20022Normalizer().normalize(doc)
    assert api.format == "iso20022"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "pain.001.001.09"
    grp_hdr = next(type_ for type_ in api.types if type_.name == "GrpHdr")
    assert grp_hdr.kind is TypeKind.RECORD
    assert any(field.name == "MsgId" for field in grp_hdr.fields)
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: Iso20022ImportSource):
    detected = adapter.detect(
        DetectionInput(text=_PAIN_001, filename="01-pain.001-credit-transfer.xml")
    )
    assert detected.matched
    assert detected.format == "iso20022"
    doc = adapter.parse(_PAIN_001)
    api = adapter.normalize(doc)
    assert api.extras.get("iso20022_tree")
    assert api.extras.get("iso20022_message_id") == "pain.001.001.09"


def test_adapter_invalid_source_raises(adapter: Iso20022ImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("<Document><Other/></Document>")


def test_emitter_round_trips_pain_message():
    doc = parse_iso20022(_PAIN_001)
    api = Iso20022Normalizer().normalize(doc)
    emitter = get_emitter("iso20022")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09" in text
    assert "<CstmrCdtTrfInitn>" in text
    assert "<MsgId>MSG-20260115-0001</MsgId>" in text
    validate_iso20022_document(text)


def test_emitter_round_trips_camt_fixture():
    doc = parse_iso20022(_CAMT_053)
    api = Iso20022Normalizer().normalize(doc)
    emitter = get_emitter("iso20022")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "camt.053.001.08" in text
    assert "<BkToCstmrStmt>" in text
    validate_iso20022_document(text)


def test_catalog_conversion_resolves_iso20022_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("iso20022", _PAIN_001).key == "iso20022"
