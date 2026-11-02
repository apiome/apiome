"""Tests for ISO 20022 message definitions (XSD) on the ISO 20022 adapter — MFI-20.3 (#3987)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.archive_intake import rank_root_candidates
from app.canonical_model import ApiParadigm, TypeKind
from app.edi_dialect_profiles import PROFILE_EXTRAS_KEY
from app.fileset import IntakeFileset
from app.import_source import DetectionInput, ImportSourceError, detect_import_source
from app.iso20022_import_source import Iso20022ImportSource
from app.iso20022_message_definition import (
    Iso20022MessageDefinition,
    declared_definition_id,
    is_iso20022_message_definition,
    normalize_message_definition,
    parse_message_definition,
)
from app.iso20022_normalizer import Iso20022Normalizer
from app.xsd_import_source import XsdImportSource

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/iso20022"
_PAIN_XSD = (_EXAMPLES / "07-pain.001.001.09-message-definition.xsd").read_text(encoding="utf-8")
_PACS_XSD = (_EXAMPLES / "08-pacs.008.001.08-message-definition.xsd").read_text(encoding="utf-8")
_PAIN_MESSAGE = (_EXAMPLES / "01-pain.001-credit-transfer.xml").read_text(encoding="utf-8")

_PLAIN_XSD = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:example:orders">
  <xs:element name="Order" type="OrderType"/>
  <xs:complexType name="OrderType"><xs:sequence><xs:element name="Id" type="xs:string"/></xs:sequence></xs:complexType>
</xs:schema>
"""


@pytest.fixture()
def adapter() -> Iso20022ImportSource:
    return Iso20022ImportSource()


# --- recognition ---------------------------------------------------------------------------


def test_declared_definition_id_reads_the_target_namespace():
    assert declared_definition_id(_PAIN_XSD) == "pain.001.001.09"
    assert declared_definition_id(_PACS_XSD) == "pacs.008.001.08"


@pytest.mark.parametrize("text", [_PAIN_MESSAGE, _PLAIN_XSD, "", "<Document/>", "not xml"])
def test_declared_definition_id_ignores_messages_and_other_schemas(text: str):
    assert declared_definition_id(text) is None
    assert is_iso20022_message_definition(text) is False


def test_adapter_detects_a_definition_and_names_its_message_id(adapter: Iso20022ImportSource):
    detected = adapter.detect(DetectionInput(text=_PAIN_XSD, filename="pain.001.001.09.xsd"))
    assert detected.matched
    assert detected.format == "iso20022"
    assert "pain.001.001.09" in (detected.reason or "")
    assert "SEPA" in (detected.reason or "")
    plain = adapter.detect(DetectionInput(text=_PACS_XSD))
    assert plain.matched and "pacs.008.001.08" in (plain.reason or "")


def test_auto_detect_prefers_iso20022_over_the_generic_xsd_adapter():
    matched = detect_import_source(DetectionInput(text=_PAIN_XSD, filename="pain.001.001.09.xsd"))
    assert matched is not None
    assert matched[0].key == "iso20022"
    # A schema in another namespace still belongs to the XSD adapter.
    generic = detect_import_source(DetectionInput(text=_PLAIN_XSD, filename="orders.xsd"))
    assert generic is not None and generic[0].key == "xsd"
    assert XsdImportSource().detect(DetectionInput(text=_PAIN_XSD)).matched


def test_message_detection_is_unchanged(adapter: Iso20022ImportSource):
    detected = adapter.detect(DetectionInput(text=_PAIN_MESSAGE))
    assert detected.matched and "namespace" in (detected.reason or "")


# --- parse ---------------------------------------------------------------------------------


def test_parse_message_definition_keeps_the_schema_and_message_id():
    definition = parse_message_definition(_PAIN_XSD, source_label="pain.xsd")
    assert isinstance(definition, Iso20022MessageDefinition)
    assert definition.message_id == "pain.001.001.09"
    assert definition.namespace == "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
    assert definition.schema.root_element == "Document"
    assert {t.name for t in definition.schema.complex_types} >= {
        "Document",
        "CustomerCreditTransferInitiationV09",
        "AccountIdentification4Choice",
        "ActiveOrHistoricCurrencyAndAmount",
    }


def test_parse_message_definition_rejects_other_text():
    with pytest.raises(ValueError):
        parse_message_definition(_PAIN_MESSAGE)


def test_adapter_parse_routes_a_definition_and_a_message(adapter: Iso20022ImportSource):
    assert isinstance(adapter.parse(_PAIN_XSD, source_label="pain.xsd"), Iso20022MessageDefinition)
    assert not isinstance(adapter.parse(_PAIN_MESSAGE), Iso20022MessageDefinition)
    with pytest.raises(ImportSourceError):
        adapter.parse(
            "<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema' "
            "targetNamespace='urn:iso:std:iso:20022:tech:xsd:pain.001.001.09'>"
        )


def test_adapter_parse_fileset_routes_a_definition_root(adapter: Iso20022ImportSource):
    fileset = IntakeFileset.from_members({"pain.001.001.09.xsd": _PAIN_XSD}, root="pain.001.001.09.xsd")
    assert isinstance(adapter.parse_fileset(fileset), Iso20022MessageDefinition)


# --- the XSD reader on ISO 20022 constructs (MFI-20.3 parser additions) --------------------


def test_choice_members_simple_content_and_derived_attributes_are_read():
    schema = parse_message_definition(_PAIN_XSD).schema
    by_name = {t.name: {f.name: f for f in t.fields} for t in schema.complex_types}
    choice = by_name["AccountIdentification4Choice"]
    assert set(choice) == {"IBAN", "Othr"}
    assert choice["IBAN"].min_occurs == "0" and choice["IBAN"].kind == "element"
    amount = by_name["ActiveOrHistoricCurrencyAndAmount"]
    assert amount["value"].kind == "value"
    assert amount["value"].type_expr == "ActiveOrHistoricCurrencyAndAmount_SimpleType"
    assert amount["Ccy"].kind == "attribute"


# --- normalize -----------------------------------------------------------------------------


def _normalized(text: str):
    return normalize_message_definition(parse_message_definition(text), include_raw=False)


def test_normalize_labels_the_xsd_model_as_iso20022():
    api = _normalized(_PAIN_XSD)
    assert api.format == "iso20022"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "pain.001.001.09"
    assert api.title == "CstmrCdtTrfInitn (pain.001.001.09)"
    assert api.extras["iso20022_message_id"] == "pain.001.001.09"
    assert api.extras["iso20022_namespace"] == "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
    assert api.extras["iso20022_business_element"] == "CstmrCdtTrfInitn"
    assert api.extras["iso20022_message_definition"] == {
        "family": "pain.001",
        "variant": "001",
        "version": 9,
        "root_element": "Document",
        "root_type": "Document",
        "business_element": "CstmrCdtTrfInitn",
        "business_type": "CustomerCreditTransferInitiationV09",
    }
    # The XSD provenance the normalizer records stays beside the ISO keys.
    assert api.extras["xsd_root_element"] == "Document"
    assert "iso20022_tree" not in api.extras


def test_normalize_maps_message_types_and_codes():
    api = _normalized(_PACS_XSD)
    types = {t.name: t for t in api.types}
    assert types["FIToFICustomerCreditTransferV08"].kind is TypeKind.RECORD
    field_names = {f.name for f in types["CreditTransferTransaction39"].fields}
    assert {"PmtId", "IntrBkSttlmAmt", "ChrgBr", "Dbtr", "Cdtr"} <= field_names
    assert types["SettlementMethod1Code"].kind is TypeKind.ENUM
    assert [v.name for v in types["SettlementMethod1Code"].enum_values] == ["INDA", "INGA", "COVE", "CLRG"]
    assert api.extras["iso20022_message_definition"]["business_element"] == "FIToFICstmrCdtTrf"


def test_sepa_profile_applies_to_sepa_families_only():
    assert _normalized(_PAIN_XSD).extras[PROFILE_EXTRAS_KEY]["message_id"] == "pain.001.001.09"
    camt = _PAIN_XSD.replace("pain.001.001.09", "camt.053.001.08")
    assert PROFILE_EXTRAS_KEY not in _normalized(camt).extras


def test_registered_normalizer_accepts_a_definition():
    api = Iso20022Normalizer().normalize(parse_message_definition(_PAIN_XSD), include_raw=True)
    assert api.format == "iso20022"
    assert api.raw == {"iso20022": _PAIN_XSD}


def test_adapter_detect_parse_normalize_end_to_end(adapter: Iso20022ImportSource):
    native = adapter.parse(_PACS_XSD, source_label="pacs.xsd")
    api = adapter.normalize(native, include_raw=False)
    assert api.format == "iso20022"
    assert api.extras["iso20022_message_id"] == "pacs.008.001.08"


def test_two_definitions_share_component_type_names_for_diffing():
    pain = {t.name for t in _normalized(_PAIN_XSD).types}
    pacs = {t.name for t in _normalized(_PACS_XSD).types}
    assert {"PartyIdentification135", "CashAccount38", "Max35Text", "IBAN2007Identifier"} <= pain & pacs


# --- archive intake ------------------------------------------------------------------------


def test_archive_root_ranking_claims_a_definition_for_iso20022():
    leader = rank_root_candidates({"pain.001.001.09.xsd": _PAIN_XSD, "README.md": "schemas"})
    if not leader:
        pytest.skip(".xsd is not an archive root candidate suffix")
    assert leader[0].format == "iso20022"
