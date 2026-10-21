"""Tests for SEPA recognition on the ISO 20022 adapter — FMT-6.6 (#5450).

SEPA ``pain.001`` / ``pain.008`` / ``pacs.008`` messages route to the shipped ``iso20022`` adapter,
which records their message id and the SEPA ``format_profile``; the two structural rules the profile
applies and the parser's truncation rule are exercised against the ``sepa/`` corpus and inline
documents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.import_source import DetectionInput, ImportSourceError, detect_import_source
from app.import_source_pipeline import format_profile_metadata
from app.iso20022_import_source import Iso20022ImportSource
from app.iso20022_parser import Iso20022ParseError, declared_message_id, parse_iso20022
from app.iso20022_sepa import (
    SEPA,
    SEPA_MESSAGES,
    check_sepa_document,
    parse_message_id,
    sepa_match,
    sepa_message,
    sepa_profile_extras,
)

_SEPA = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "sepa"


def _fixture(name: str) -> str:
    return (_SEPA / name).read_text(encoding="utf-8")


def _document(message_id: str, body: str) -> str:
    return f'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:{message_id}">{body}</Document>'


@pytest.fixture()
def adapter() -> Iso20022ImportSource:
    return Iso20022ImportSource()


def test_parse_message_id():
    assert parse_message_id("pain.001.001.09") == ("pain.001", "001", 9)
    assert parse_message_id(" PACS.008.001.13 ") == ("pacs.008", "001", 13)
    assert parse_message_id("pain.001") is None
    assert sepa_message("camt.053.001.08") is None
    assert sepa_message("pain.008.001.08").transaction == "DrctDbtTxInf"


@pytest.mark.parametrize(
    "name,message_id",
    [
        ("01-minimal-pain001.xml", "pain.001.001.09"),
        ("04-stress-pain008-direct-debit.xml", "pain.008.001.08"),
        ("05-real-world-pacs008-interbank.xml", "pacs.008.001.08"),
    ],
)
def test_sepa_messages_route_to_iso20022_with_message_id(
    adapter: Iso20022ImportSource, name: str, message_id: str
):
    text = _fixture(name)
    best = detect_import_source(DetectionInput(text=text, filename=name))
    assert best is not None and best[0].key == "iso20022"
    assert message_id in best[1].reason and "SEPA" in best[1].reason
    model = adapter.normalize(adapter.parse(text))
    assert model.extras["iso20022_message_id"] == message_id
    profile = format_profile_metadata(model)
    assert profile["key"] == "sepa" and profile["engine"] == "iso20022"
    assert profile["message_id"] == message_id
    assert profile["implementation_guide_consulted"] is False
    assert message_id in profile["evidence"][0]


@pytest.mark.parametrize("name", ["06-typical-camt053-statement.xml", "07-status-set/pain002.xml"])
def test_other_iso20022_messages_carry_no_profile(adapter: Iso20022ImportSource, name: str):
    text = _fixture(name)
    model = adapter.normalize(adapter.parse(text))
    assert format_profile_metadata(model) is None
    assert "SEPA" not in adapter.detect(DetectionInput(text=text)).reason


@pytest.mark.parametrize(
    "name,code",
    [
        ("negative/02-semantic-no-transactions.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-transaction.xml", "INPUT_TRUNCATED"),
        ("negative/06-version-out-of-range-pain001-099.xml", "FORMAT_VERSION_UNSUPPORTED"),
    ],
)
def test_corpus_negatives_carry_codes(adapter: Iso20022ImportSource, name: str, code: str):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_fixture(name))
    assert caught.value.code == code


def test_nacha_file_is_not_claimed(adapter: Iso20022ImportSource):
    assert not adapter.detect(DetectionInput(text=_fixture("negative/04-wrong-format-nacha.ach"))).matched


def test_unclosed_element_stays_a_syntax_fault():
    with pytest.raises(Iso20022ParseError) as caught:
        parse_iso20022(_fixture("negative/01-syntactic-unclosed-element.xml"))
    assert caught.value.code is None
    # A document that ends on a complete tag and only lacks its closing elements is not truncated.
    with pytest.raises(Iso20022ParseError) as caught:
        parse_iso20022('<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"><A><B>1</B>\n')
    assert caught.value.code is None


@pytest.mark.parametrize(
    "message_id,body,code",
    [
        (
            "pain.001.001.13",
            "<CstmrCdtTrfInitn><PmtInf><CdtTrfTxInf/></PmtInf></CstmrCdtTrfInitn>",
            "FORMAT_VERSION_UNSUPPORTED",
        ),
        (
            "pain.008.001.00",
            "<CstmrDrctDbtInitn><PmtInf><DrctDbtTxInf/></PmtInf></CstmrDrctDbtInitn>",
            "FORMAT_VERSION_UNSUPPORTED",
        ),
        (
            "pain.001.001.09",
            "<CstmrCdtTrfInitn><GrpHdr><MsgId>1</MsgId></GrpHdr></CstmrCdtTrfInitn>",
            "INPUT_SEMANTIC_INVALID",
        ),
        (
            "pain.008.001.08",
            "<CstmrDrctDbtInitn><PmtInf><DrctDbtTxInf/></PmtInf><PmtInf><PmtInfId>2</PmtInfId>"
            "</PmtInf></CstmrDrctDbtInitn>",
            "INPUT_SEMANTIC_INVALID",
        ),
        (
            "pacs.008.001.08",
            "<FIToFICstmrCdtTrf><GrpHdr><MsgId>1</MsgId></GrpHdr></FIToFICstmrCdtTrf>",
            "INPUT_SEMANTIC_INVALID",
        ),
    ],
)
def test_sepa_rules(message_id: str, body: str, code: str):
    document = parse_iso20022(_document(message_id, body))
    with pytest.raises(Iso20022ParseError) as caught:
        check_sepa_document(document)
    assert caught.value.code == code


def test_rules_leave_valid_and_non_sepa_documents_alone():
    for message_id in ("pain.001.001.12", "pacs.008.001.13", "pain.001.001.03"):
        family = parse_message_id(message_id)[0]
        tx = SEPA_MESSAGES[family].transaction
        body = f"<Root><PmtInf><{tx}/></PmtInf></Root>" if family != "pacs.008" else f"<Root><{tx}/></Root>"
        check_sepa_document(parse_iso20022(_document(message_id, body)))
    check_sepa_document(
        parse_iso20022(_document("camt.053.001.99", "<BkToCstmrStmt><GrpHdr/></BkToCstmrStmt>"))
    )


def test_profile_helpers():
    assert sepa_match("camt.053.001.08") is None
    assert sepa_profile_extras("pain.002.001.10") is None
    match = sepa_match("pain.008.001.08")
    assert match.profile is SEPA and "SEPA Direct Debit" in match.evidence[0]
    assert "pacs.008" in SEPA.message_set and "camt.053" not in SEPA.message_set
    assert declared_message_id(_fixture("01-minimal-pain001.xml")) == "pain.001.001.09"
    assert declared_message_id("<x/>") is None
