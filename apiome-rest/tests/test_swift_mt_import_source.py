"""Tests for the SWIFT MT import adapter — FMT-6.3 (#5447).

Covers the field catalogue (option letters, code words, numbered lines, statement lines), the block
parser and every refusal code, the canonical normalizer (option letters kept as distinct shapes,
statement-line groups, MT202 COV sequence B), the native analysis (structure vs values, the MX
correspondence note and its disclaimer) and the reviewed capability entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from app.canonical_model import ApiParadigm
from app.fileset import IntakeFileset
from app.format_capability_registry import CapabilityProvenance, NativeHierarchy, capability_for
from app.import_source import DetectionInput, ImportSourceError, get_import_source
from app.payload_analysis import STATUS_AVAILABLE, ValueVisibility, apply_value_visibility
from app.swift_mt_analysis import (
    KIND_BLOCK,
    KIND_CODE_WORD,
    KIND_COMPONENT,
    KIND_FIELD,
    KIND_LINE,
    KIND_MESSAGE,
    KIND_NUMBERED_LINE,
    KIND_SEQUENCE,
    WARNING_CANONICAL_SUBSET,
    WARNING_FIELD_NOT_IN_CATALOGUE,
    WARNING_FIELD_NOT_WELL_FORMED,
    WARNING_MX_CORRESPONDENCE,
    analyze_swift_mt,
)
from app.swift_mt_fields import (
    MX_CORRESPONDENCE,
    MX_CORRESPONDENCE_DISCLAIMER,
    field_name,
    read_field,
)
from app.swift_mt_import_source import SwiftMtImportSource
from app.swift_mt_normalizer import SwiftMtNormalizer, mx_correspondence, statement_groups
from app.swift_mt_parser import SwiftMtParseError, is_swift_mt, parse_swift_mt

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "swift-mt"


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_MT103 = _fixture("02-typical-mt103.txt")
_MT202COV = _fixture("03-composition-mt202cov.txt")
_MT940 = _fixture("04-stress-mt940-statement.txt")
_MT942 = _fixture("06-typical-mt942-interim.txt")
_HEAD = "{1:F01BANKBEBBAXXX0000000000}{2:I103BANKDEFFXXXXN}"


def _message(*fields: str, head: str = _HEAD, trailer: str = "") -> str:
    return head + "{4:\n" + "\n".join(fields) + "\n-}" + trailer + "\n"


def _walk(node: Any) -> List[Any]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk(child))
    return nodes


def _all(document: Any) -> List[Any]:
    return [node for root in document.tree for node in _walk(root)]


@pytest.fixture()
def adapter() -> SwiftMtImportSource:
    return SwiftMtImportSource()


# ---------------------------------------------------------------------------
# Field catalogue
# ---------------------------------------------------------------------------


def test_option_letters_decide_the_shape():
    named = read_field("50", "K", ["/NL91ABNA0417164300", "ACME RETAIL BV"])
    structured = read_field("50", "F", ["/NL91ABNA0417164300", "1/ACME RETAIL BV", "2/COOLSINGEL 40"])
    bic = read_field("57", "A", ["EXAMPGB2L"])
    assert named.format == "party_name_address" and named.lines == ("ACME RETAIL BV",)
    assert structured.format == "party_structured"
    assert [(line.number, line.text) for line in structured.numbered_lines] == [
        ("1", "ACME RETAIL BV"),
        ("2", "COOLSINGEL 40"),
    ]
    assert dict(bic.components) == {"bic": "EXAMPGB2L"}
    assert dict(named.components) == dict(structured.components) == {"account": "NL91ABNA0417164300"}


def test_amounts_balances_and_statement_lines_have_components():
    assert dict(read_field("32", "A", ["260819EUR12500,00"]).components) == {
        "date": "260819",
        "currency": "EUR",
        "amount": "12500,00",
    }
    assert dict(read_field("60", "F", ["C260818EUR1250000,00"]).components)["mark"] == "C"
    reversal = read_field("61", None, ["2608200820RC12500,00NRTIREF20260819001//BK0000000006"])
    assert dict(reversal.components)["mark"] == "RC"
    assert dict(reversal.components)["transactionType"] == "NRTI"
    assert dict(reversal.components)["bankReference"] == "BK0000000006"
    supplementary = read_field(
        "61", None, ["2608190819D12500,00NTRFREF1//BK1", "/OCMT/EUR12500,00/CHGS/EUR7,50/"]
    )
    assert [(word.code, word.text) for word in supplementary.code_words] == [
        ("OCMT", "EUR12500,00"),
        ("CHGS", "EUR7,50"),
    ]


def test_code_words_keep_their_qualifier_and_wrapped_text():
    reading = read_field("86", None, ["/ORDP/UTILITY COMPANY NV", "/REMI/ELECTRICITY", "AUGUST 2026"])
    assert [(word.code, word.text) for word in reading.code_words] == [
        ("ORDP", "UTILITY COMPANY NV"),
        ("REMI", "ELECTRICITY\nAUGUST 2026"),
    ]
    free = read_field("86", None, ["STATEMENT COVERS 19 AUGUST"])
    assert free.lines == ("STATEMENT COVERS 19 AUGUST",) and not free.code_words


def test_content_that_does_not_match_is_kept_not_refused():
    reading = read_field("32", "A", ["NOT-A-DATE"])
    assert not reading.well_formed and reading.lines == ("NOT-A-DATE",)
    assert not read_field("50", "K", ["/ONLY-AN-ACCOUNT"]).well_formed
    assert read_field("99", None, ["anything"]).format == "lines"


def test_field_names_and_mx_table():
    assert field_name("50", "K") == "Ordering Customer"
    assert field_name("32", "A") == "Value Date/Currency/Interbank Settled Amount"
    assert field_name("99", None) is None
    assert MX_CORRESPONDENCE["MT103"].mx == "pacs.008"
    assert MX_CORRESPONDENCE["MT940"].mx == "camt.053"
    assert "does not claim" in MX_CORRESPONDENCE_DISCLAIMER


# ---------------------------------------------------------------------------
# Parser and detection
# ---------------------------------------------------------------------------


def test_detection(adapter: SwiftMtImportSource):
    assert adapter.detect(DetectionInput(text=_MT103)).confidence == pytest.approx(0.96)
    unterminated = _fixture("negative/01-syntactic-unterminated-block4.txt")
    assert adapter.detect(DetectionInput(text=unterminated)).confidence == pytest.approx(0.8)
    assert not is_swift_mt(_fixture("negative/04-wrong-format-iso20022.xml"))
    assert not is_swift_mt("{\"json\": true}")
    assert not is_swift_mt("{1:F01X}")  # no text block


def test_adapter_registered():
    source = get_import_source("swift-mt")
    assert isinstance(source, SwiftMtImportSource)
    assert source.paradigm is ApiParadigm.DATA_SCHEMA


def test_headers_are_parsed():
    message = parse_swift_mt(_MT103).messages[0]
    assert message.basic.get("applicationId") == "F" and message.basic.get("serviceId") == "01"
    assert message.basic.get("sequenceNumber") == "000042"
    assert message.application.get("messageType") == "103"
    assert message.application.get("priority") == "N"
    assert message.user.get("121") == "6b2c1a7e-0f4d-4a2b-9c31-000000000001"
    assert message.trailer.get("CHK") == "0123456789AB"
    assert message.direction == "input" and message.name == "MT103"


def test_output_header_and_statement():
    message = parse_swift_mt(_MT940).messages[0]
    assert message.direction == "output"
    assert message.application.get("mirDate") == "260819"
    assert message.application.get("outputTime") == "0930"
    assert sum(1 for item in message.fields() if item.tag == "61") == 6


def test_field_positions_point_at_the_text():
    document = parse_swift_mt(_MT103)
    for item in document.messages[0].fields():
        assert document.raw[item.offset :].startswith(f":{item.label}:")


def test_cover_sequences_from_two_text_blocks_or_one():
    two_blocks = parse_swift_mt(_MT202COV).messages[0]
    assert two_blocks.name == "MT202COV"
    assert [sequence.name for sequence in two_blocks.sequences] == ["A", "B"]
    single = _MT202COV.replace("\n-}{4:\n", "\n")
    one_block = parse_swift_mt(single).messages[0]
    assert [sequence.name for sequence in one_block.sequences] == ["A", "B"]
    assert one_block.sequences[1].fields[0].label == "50F"


def test_several_messages_in_one_file():
    text = _fixture("07-cover-set/mt103.txt") + _fixture("07-cover-set/mt202cov.txt")
    document = parse_swift_mt(text)
    assert [message.name for message in document.messages] == ["MT103", "MT202COV"]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-unterminated-block4.txt", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-transaction-reference.txt", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-field.txt", "INPUT_TRUNCATED"),
        ("negative/06-semantic-unknown-message-type.txt", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_corpus_negatives(name: str, code: str):
    with pytest.raises(SwiftMtParseError) as caught:
        parse_swift_mt(_fixture(name))
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("text", "code", "fragment"),
    [
        ("{1:F01BANKBEBBAXXX0000000000}{2:I103}{4:\n:20:X\n-}", "INPUT_MALFORMED", "application"),
        ("{1:F01BANKBEBBAXXX0000000000}{3:{108:X}}{4:\n:20:X\n-}", "INPUT_SEMANTIC_INVALID", "block 2"),
        (_HEAD + "{3:{108:X}{4:\n:20:X\n-}", "INPUT_TRUNCATED", "never closes"),
        (_HEAD + "{4:\nstray text\n:20:X\n-}", "INPUT_MALFORMED", "before its first"),
        (_HEAD + "{7:X}{4:\n:20:X\n-}", "INPUT_MALFORMED", "numbered 1 to 5"),
        (_HEAD + "{2:I103BANKDEFFXXXXN}{4:\n:20:X\n-}", "INPUT_MALFORMED", "repeats block"),
        (_HEAD + "{3:{108:X}junk}{4:\n:20:X\n-}", "INPUT_MALFORMED", "outside its"),
        (_HEAD + "{4:\n:20:X\n-}garbage", "INPUT_MALFORMED", "outside any block"),
        ("{1:F01BAD}{2:I103BANKDEFFXXXXN}{4:\n:20:X\n-}", "INPUT_MALFORMED", "basic header"),
    ],
)
def test_refusals_carry_a_taxonomy_code(text: str, code: str, fragment: str):
    with pytest.raises(SwiftMtParseError) as caught:
        parse_swift_mt(text)
    assert caught.value.code == code
    assert fragment in str(caught.value)


def test_encoding_faults_are_code_less():
    for text in ("﻿" + _MT103, _MT103.replace(":20:", ":2\x000:", 1)):
        with pytest.raises(SwiftMtParseError) as caught:
            parse_swift_mt(text)
        assert caught.value.code is None


def test_adapter_parse_carries_the_code(adapter: SwiftMtImportSource):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_fixture("negative/03-truncated-mid-field.txt"))
    assert caught.value.code == "INPUT_TRUNCATED"


def test_parse_fileset_reads_the_root(adapter: SwiftMtImportSource):
    fileset = IntakeFileset(
        root="mt103.txt",
        members={
            "mt103.txt": _fixture("07-cover-set/mt103.txt"),
            "mt202cov.txt": _fixture("07-cover-set/mt202cov.txt"),
        },
    )
    assert [message.name for message in adapter.parse_fileset(fileset).messages] == ["MT103"]
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="missing.txt", members={"a.txt": _MT103}))


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def _types(api) -> dict:
    return {item.name: item for item in api.types}


def test_option_letters_survive_as_distinct_types(adapter: SwiftMtImportSource):
    api = adapter.normalize(adapter.parse(_MT202COV))
    types = _types(api)
    assert {"Field50F", "Field59F", "Field58A", "Field52A"} <= set(types)
    assert types["Field50F"].description == "Field 50, option F: Ordering Customer"
    root = {item.name: item for item in types["MT202COV"].fields}
    assert {"20", "21", "32A", "58A", "SequenceB"} <= set(root)
    sequence_b = {item.name for item in types["MT202COVSequenceB"].fields}
    assert {"50F", "59F", "70", "33B"} <= sequence_b
    numbered = {item.name: item for item in types["Field50F"].fields}["numberedLines"]
    assert numbered.type.item is not None


def test_statement_lines_are_grouped(adapter: SwiftMtImportSource):
    api = adapter.normalize(adapter.parse(_MT940))
    types = _types(api)
    root = {item.name: item for item in types["MT940"].fields}
    assert root["StatementLines"].type.item is not None
    assert {item.name for item in types["StatementLine"].fields} == {"61", "86"}
    assert "86" in root  # the statement-level information after the closing balance
    groups = statement_groups(list(parse_swift_mt(_MT940).messages[0].fields()))
    assert sum(1 for entry in groups if isinstance(entry, tuple)) == 6


def test_repeated_fields_are_lists(adapter: SwiftMtImportSource):
    api = adapter.normalize(adapter.parse(_fixture("05-real-world-mt103-charges-chain.txt")))
    root = {item.name: item for item in _types(api)["MT103"].fields}
    assert root["71F"].type.item is not None
    assert root["71G"].type.item is None


def test_values_are_never_defaults_and_mx_is_a_note(adapter: SwiftMtImportSource):
    api = adapter.normalize(adapter.parse(_MT103))
    assert all(member.default is None for item in api.types for member in item.fields)
    note = api.extras["swift_mx_correspondence"]
    assert note["mx"] == "pacs.008" and note["verified"] is False
    assert note["disclaimer"] == MX_CORRESPONDENCE_DISCLAIMER
    assert api.extras["swift_headers"]["user"]["108"] == "MT103REF0000001"


def test_normalizer_rejects_foreign_ast(adapter: SwiftMtImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"x": 1})
    with pytest.raises(ValueError):
        SwiftMtNormalizer().normalize({"x": 1})


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def test_analysis_hierarchy():
    document = analyze_swift_mt(parse_swift_mt(_MT202COV))
    assert document.status == STATUS_AVAILABLE
    message = document.tree[0]
    assert message.kind == KIND_MESSAGE and message.attributes["messageName"] == "MT202COV"
    assert message.attributes["validationFlag"] == "COV"
    blocks = [child.name for child in message.children]
    assert blocks == ["1", "2", "3", "4", "5"]
    text = message.children[3]
    assert [child.kind for child in text.children] == [KIND_SEQUENCE, KIND_SEQUENCE]
    kinds = {node.kind for node in _all(document)}
    assert {KIND_BLOCK, KIND_FIELD, KIND_COMPONENT, KIND_CODE_WORD, KIND_NUMBERED_LINE} <= kinds


def test_option_and_qualifier_are_structure_values_are_values():
    document = analyze_swift_mt(parse_swift_mt(_MT103))
    party = next(node for node in _all(document) if node.kind == KIND_FIELD and node.name == "50K")
    assert party.attributes["tag"] == "50" and party.attributes["option"] == "K"
    assert party.attributes["fieldName"] == "Ordering Customer"
    word = next(node for node in _all(document) if node.kind == KIND_CODE_WORD)
    assert word.attributes["qualifier"] == "INV" and word.value == "INV-10042"
    lines = [node for node in party.children if node.kind == KIND_LINE]
    assert lines[0].value == "ACME RETAIL BV"
    withheld = apply_value_visibility(document, ValueVisibility.STRUCTURAL)
    assert all(node.value is None for node in _all(withheld) if node.value_present)
    kept = next(node for node in _all(withheld) if node.kind == KIND_CODE_WORD)
    assert kept.attributes["qualifier"] == "INV"
    for node in _all(document):
        assert "ACME RETAIL BV" not in str(node.attributes)


def test_mx_correspondence_is_a_note_with_a_disclaimer():
    document = analyze_swift_mt(parse_swift_mt(_MT942))
    assert document.tree[0].attributes["mxCorrespondence"] == {
        "mx": "camt.052",
        "mxName": "Bank To Customer Account Report",
        "verified": False,
    }
    note = next(w for w in document.warnings if w.code == WARNING_MX_CORRESPONDENCE)
    assert MX_CORRESPONDENCE_DISCLAIMER in note.message
    assert note.severity == "info"


def test_statement_line_indices():
    document = analyze_swift_mt(parse_swift_mt(_MT940))
    fields = [node for node in _all(document) if node.kind == KIND_FIELD]
    indexed = [(node.name, node.attributes.get("statementLineIndex")) for node in fields]
    assert ("61", 0) in indexed and ("86", 0) in indexed and ("61", 5) in indexed
    assert indexed[-1] == ("86", None)  # the statement-level 86


def test_not_well_formed_and_unknown_fields_are_flagged():
    document = analyze_swift_mt(parse_swift_mt(_fixture("05-real-world-mt103-charges-chain.txt")))
    flagged = next(w for w in document.warnings if w.code == WARNING_FIELD_NOT_WELL_FORMED)
    assert ":20:" in flagged.message
    unknown = analyze_swift_mt(parse_swift_mt(_message(":20:REF1", ":99:ODD")))
    assert WARNING_FIELD_NOT_IN_CATALOGUE in [w.code for w in unknown.warnings]


def test_multiple_messages_and_cover_link():
    text = _fixture("07-cover-set/mt103.txt") + _fixture("07-cover-set/mt202cov.txt")
    document = analyze_swift_mt(parse_swift_mt(text))
    assert [root.attributes["messageName"] for root in document.tree] == ["MT103", "MT202COV"]
    assert document.tree[1].attributes["relatesToMessage"] == 0
    assert WARNING_CANONICAL_SUBSET in [w.code for w in document.warnings]


def test_mx_correspondence_helper_for_every_supported_type():
    for text, mx in ((_MT103, "pacs.008"), (_MT202COV, "pacs.009 (COV)"), (_MT940, "camt.053")):
        assert mx_correspondence(parse_swift_mt(text).messages[0])["mx"] == mx
    plain_202 = _MT202COV.replace("{119:COV}", "")
    assert mx_correspondence(parse_swift_mt(plain_202).messages[0])["mx"] == "pacs.009"


def test_adapter_analyze(adapter: SwiftMtImportSource):
    document = adapter.analyze(adapter.parse(_MT103), source=_MT103)
    assert document.analyzer.key == "swift-mt"
    assert "swift.mx_translation" in adapter.analysis_capabilities().unsupported
    with pytest.raises(ImportSourceError):
        adapter.analyze({"x": 1})


# ---------------------------------------------------------------------------
# Capability registry
# ---------------------------------------------------------------------------


def test_capability_entry_states_the_mx_disclaimer():
    entry = capability_for("swift-mt")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    assert entry.native_hierarchy is NativeHierarchy.NATIVE
    assert any(MX_CORRESPONDENCE_DISCLAIMER in note for note in entry.notes)
    assert "swift.mx_translation" in entry.unsupported_constructs
    assert not set(entry.supported_constructs) & set(entry.unsupported_constructs)
