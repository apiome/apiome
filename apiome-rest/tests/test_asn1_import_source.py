"""Tests for ASN.1 catalog import/export adapters — MFI-21.5 / MFX-27.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.asn1_emitter import validate_asn1_module
from app.asn1_import_source import Asn1ImportSource
from app.asn1_normalizer import Asn1Normalizer
from app.asn1_parser import is_asn1, parse_asn1
from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError

_PERSON_ASN1 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/asn1/01-person.asn1"
).read_text(encoding="utf-8")
_IDENTIFIER_ASN1 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/asn1/02-identifier.asn1"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> Asn1ImportSource:
    return Asn1ImportSource()


def test_is_asn1_recognizes_person_module():
    assert is_asn1(_PERSON_ASN1) is True
    assert is_asn1('{"openapi":"3.0.0"}') is False


def test_parse_collects_module_types():
    doc = parse_asn1(_PERSON_ASN1)
    assert doc.module.name == "PersonModule"
    assert doc.module.tags == "AUTOMATIC"
    assert {t.name for t in doc.module.types} == {"Status", "PhoneNumber", "Address", "Person"}


def test_parse_second_fixture_covers_choice():
    doc = parse_asn1(_IDENTIFIER_ASN1)
    assert doc.module.name == "IdentifierModule"
    identifier = next(t for t in doc.module.types if t.name == "Identifier")
    assert identifier.kind == "CHOICE"
    assert {member.name for member in identifier.members} == {"id", "code"}


def test_normalizer_maps_data_schema_types():
    doc = parse_asn1(_PERSON_ASN1)
    api = Asn1Normalizer().normalize(doc)
    assert api.format == "asn1"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "PersonModule"
    person = next(t for t in api.types if t.name == "Person")
    assert person.kind is TypeKind.RECORD
    assert any(f.name == "email" for f in person.fields)
    status = next(t for t in api.types if t.name == "Status")
    assert status.kind is TypeKind.ENUM
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: Asn1ImportSource):
    detected = adapter.detect(DetectionInput(text=_PERSON_ASN1, filename="01-person.asn1"))
    assert detected.matched
    assert detected.format == "asn1"
    doc = adapter.parse(_PERSON_ASN1, source_label="01-person.asn1")
    api = adapter.normalize(doc)
    assert len(api.types) >= 4
    assert api.title == "Status"


def test_adapter_invalid_source_raises(adapter: Asn1ImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('syntax = "proto3";')


def test_emitter_round_trips_core_constructs():
    doc = parse_asn1(_PERSON_ASN1)
    api = Asn1Normalizer().normalize(doc)
    emitter = get_emitter("asn1")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "PersonModule DEFINITIONS AUTOMATIC TAGS ::= BEGIN" in text
    assert "Person ::= SEQUENCE" in text
    assert "Status ::= ENUMERATED" in text
    assert "PhoneNumberType ::= ENUMERATED" in text
    assert "createdAt GeneralizedTime" in text
    validate_asn1_module(text)


def test_emitter_preserves_choice_branch_names():
    doc = parse_asn1(_IDENTIFIER_ASN1)
    api = Asn1Normalizer().normalize(doc)
    emitter = get_emitter("asn1")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "Identifier ::= CHOICE" in text
    assert "id INTEGER" in text
    assert "code UTF8String" in text
    validate_asn1_module(text)


def test_catalog_conversion_resolves_asn1_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("asn1", _PERSON_ASN1).key == "asn1"
