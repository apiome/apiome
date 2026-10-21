"""Tests for the NACHA ACH import adapter — FMT-6.6 (#5450).

Covers the record layouts and their helpers (direction, prenote, routing check digit), the parser
and every refusal code, the declared-versus-observed control totals, the canonical normalizer
(batches and entries as native structure, no payload values), the native analysis (values governed
by value visibility, structure in attributes) and the reviewed capability and version entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from app.canonical_model import ApiParadigm
from app.fileset import IntakeFileset
from app.format_capability_registry import CapabilityProvenance, NativeHierarchy, capability_for
from app.format_version_coverage import version_coverage_for
from app.import_source import DetectionInput, ImportSourceError, detect_import_source, get_import_source
from app.nacha_analysis import (
    KIND_ADDENDA,
    KIND_BATCH,
    KIND_ENTRY,
    KIND_FIELD,
    KIND_FILE,
    KIND_RECORD,
    NACHA_OPERATING_RULES_STATEMENT,
    WARNING_ADDENDA_INDICATOR,
    WARNING_CONTROL_TOTAL_MISMATCH,
    WARNING_IAT_LAYOUT,
    WARNING_UNMODELLED_ADDENDA,
    analyze_nacha,
)
from app.nacha_controls import (
    batch_control_counts,
    control_totals_extras,
    file_control_counts,
    observed_totals,
)
from app.nacha_import_source import NachaImportSource
from app.nacha_parser import NachaParseError, is_nacha, parse_nacha
from app.nacha_records import (
    ADDENDA_LAYOUTS,
    GENERIC_ADDENDA_LAYOUT,
    RECORD_LAYOUTS,
    RECORD_LENGTH,
    credit_or_debit,
    is_prenote,
    layout_for,
    record_fields,
    routing_check_digit,
)
from app.payload_analysis import STATUS_AVAILABLE, ValueVisibility, apply_value_visibility

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _fixture(name: str) -> str:
    return (_EXAMPLES / "nacha" / name).read_text(encoding="utf-8")


_MINIMAL = _fixture("01-minimal-ppd-credit.ach")
_PPD = _fixture("02-typical-ppd-batch.ach")
_CCD = _fixture("03-composition-ccd-with-addenda.ach")
_MULTI = _fixture("04-stress-multi-batch-sec-codes.ach")
_MISMATCH = _fixture("06-stress-control-total-mismatch.ach")
_RETURN = _fixture("07-return-set/return-file.ach")

_HEADER = _MINIMAL.splitlines()[0]
_BATCH_HEADER = _MINIMAL.splitlines()[1]
_ENTRY = _MINIMAL.splitlines()[2]
_BATCH_CONTROL = _MINIMAL.splitlines()[3]
_FILE_CONTROL = _MINIMAL.splitlines()[4]
_FILLER = "9" * RECORD_LENGTH


def _file(*records: str) -> str:
    return "\n".join(records) + "\n"


def _with(record: str, position: int, text: str) -> str:
    """Overwrite ``record`` at 1-based ``position`` with ``text``."""
    return record[: position - 1] + text + record[position - 1 + len(text) :]


def _walk(node: Any) -> List[Any]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk(child))
    return nodes


def _all(document: Any) -> List[Any]:
    return [node for root in document.tree for node in _walk(root)]


@pytest.fixture()
def adapter() -> NachaImportSource:
    return NachaImportSource()


# ---------------------------------------------------------------------------
# Record layouts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layout", [*RECORD_LAYOUTS.values(), *ADDENDA_LAYOUTS.values(), GENERIC_ADDENDA_LAYOUT]
)
def test_every_layout_tiles_the_94_character_record(layout):
    position = 1
    for spec in layout:
        assert spec.start == position, spec.name
        position = spec.end + 1
    assert position - 1 == RECORD_LENGTH
    assert len({spec.name for spec in layout}) == len(layout)


def test_record_fields_cut_by_record_type():
    fields = dict((spec.name, value) for spec, value in record_fields(_ENTRY))
    assert fields["transactionCode"] == "22"
    assert fields["receivingDfiIdentification"] == "09100001"
    assert fields["amount"] == "0000015000"
    assert fields["traceNumber"] == "091000010000001"
    addenda = _CCD.splitlines()[3]
    assert layout_for(addenda) == ADDENDA_LAYOUTS["05"]
    assert layout_for("798" + addenda[3:]) == ADDENDA_LAYOUTS["98"]
    assert layout_for("702" + addenda[3:]) == GENERIC_ADDENDA_LAYOUT
    with pytest.raises(KeyError):
        layout_for("X" * RECORD_LENGTH)


@pytest.mark.parametrize(
    "code,direction,prenote",
    [
        ("22", "credit", False),
        ("23", "credit", True),
        ("27", "debit", False),
        ("28", "debit", True),
        ("32", "credit", False),
        ("37", "debit", False),
        ("21", "credit", False),
        ("26", "debit", False),
        ("55", "debit", False),
        ("20", None, False),
        ("x2", None, False),
        ("2", None, False),
    ],
)
def test_transaction_code_direction_and_prenote(code, direction, prenote):
    assert credit_or_debit(code) == direction
    assert is_prenote(code) is prenote


def test_routing_check_digit():
    # 091000019 and 021000021 are well-known valid routing numbers.
    assert routing_check_digit("09100001") == 9
    assert routing_check_digit("02100002") == 1
    assert routing_check_digit("0910000") is None
    assert routing_check_digit("0910000X") is None


# ---------------------------------------------------------------------------
# Detection and parser
# ---------------------------------------------------------------------------


def test_detection(adapter: NachaImportSource):
    result = adapter.detect(DetectionInput(text=_PPD, filename="payroll.ach"))
    assert result.matched and result.format == "nacha" and result.confidence >= 0.9
    assert not adapter.detect(DetectionInput(text="<Document/>")).matched
    assert not adapter.detect(DetectionInput(text=None)).matched
    assert is_nacha("﻿" + _MINIMAL)
    assert not is_nacha(_with(_HEADER, 35, "095"))


def test_registry_routes_ach_to_nacha_and_sepa_to_iso20022():
    assert get_import_source("nacha").key == "nacha"
    best = detect_import_source(DetectionInput(text=_CCD, filename="vendors.ach"))
    assert best is not None and best[0].key == "nacha"
    sepa = (_EXAMPLES / "nacha" / "negative" / "04-wrong-format-sepa-pain001.xml").read_text(encoding="utf-8")
    best = detect_import_source(DetectionInput(text=sepa, filename="pain001.xml"))
    assert best is not None and best[0].key == "iso20022"
    assert "pain.001.001.09" in best[1].reason


def test_parser_builds_batches_entries_and_addenda():
    file = parse_nacha(_MULTI)
    assert [batch.sec_code for batch in file.batches] == ["PPD", "CCD", "WEB", "TEL"]
    assert [len(batch.entries) for batch in file.batches] == [2, 1, 2, 1]
    ccd = file.batches[1]
    assert ccd.addenda_count == 1 and ccd.entries[0].addenda[0].addenda_type == "05"
    assert file.header.field("fileIdModifier") == "B"
    assert file.padding_records == 3 and file.record_count == 20
    entry = file.batches[0].entries[0].record
    assert entry.line == 3 and entry.offset == 2 * (RECORD_LENGTH + 1) and entry.length == RECORD_LENGTH
    with pytest.raises(KeyError):
        entry.field("noSuchField")


def test_unbroken_file_is_cut_into_records():
    text = _MINIMAL.replace("\n", "")
    file = parse_nacha(text)
    assert len(file.batches) == 1 and file.padding_records == 5
    assert file.batches[0].entries[0].record.column == 2 * RECORD_LENGTH + 1


def test_crlf_and_bom_are_accepted():
    file = parse_nacha("﻿" + _MINIMAL.replace("\n", "\r\n"))
    assert file.batches[0].entries[0].record.text == _ENTRY


@pytest.mark.parametrize(
    "name,code",
    [
        ("negative/01-syntactic-short-record.ach", "INPUT_MALFORMED"),
        ("negative/02-semantic-batch-without-entries.ach", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-entry.ach", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-sepa-pain001.xml", "FORMAT_MISMATCH"),
        ("negative/06-semantic-orphan-addenda.ach", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_corpus_negatives(name: str, code: str):
    with pytest.raises(NachaParseError) as caught:
        parse_nacha(_fixture(name), source_label=name)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "text,code,fragment",
    [
        ("", "INPUT_EMPTY", "empty"),
        (_file(_HEADER, _BATCH_HEADER, _ENTRY, _BATCH_CONTROL), "INPUT_TRUNCATED", "file control"),
        (_file(_HEADER, _BATCH_HEADER, _ENTRY), "INPUT_TRUNCATED", "open batch"),
        (_file(_HEADER, "X" + _ENTRY[1:], _FILE_CONTROL), "INPUT_MALFORMED", "record type code"),
        (_file(_HEADER, _BATCH_HEADER, _ENTRY + " ", _BATCH_CONTROL, _FILE_CONTROL), "INPUT_MALFORMED", "95"),
        (_file(_HEADER, _HEADER, _FILE_CONTROL), "INPUT_SEMANTIC_INVALID", "second file header"),
        (_file(_HEADER, _BATCH_HEADER, _BATCH_HEADER), "INPUT_SEMANTIC_INVALID", "previous batch"),
        (_file(_HEADER, _ENTRY), "INPUT_SEMANTIC_INVALID", "outside any batch"),
        (_file(_HEADER, _FILE_CONTROL), "INPUT_SEMANTIC_INVALID", "no batches"),
        (_file(_HEADER, _BATCH_HEADER, _ENTRY, _FILE_CONTROL), "INPUT_SEMANTIC_INVALID", "open batch"),
        (_file(_HEADER, _BATCH_HEADER, _ENTRY, _BATCH_CONTROL, _FILLER), "INPUT_SEMANTIC_INVALID", "padding"),
        (
            _file(_HEADER, _BATCH_HEADER, _ENTRY, _BATCH_CONTROL, _FILE_CONTROL, _ENTRY),
            "INPUT_SEMANTIC_INVALID",
            "follows the file control",
        ),
    ],
)
def test_refusals_carry_a_taxonomy_code(text: str, code: str, fragment: str):
    with pytest.raises(NachaParseError) as caught:
        parse_nacha(text)
    assert caught.value.code == code
    assert fragment in str(caught.value)


def test_encoding_faults_are_code_less():
    with pytest.raises(NachaParseError) as caught:
        parse_nacha(_MINIMAL.replace("EXAMPLE BANK", "EXAMPLE\x00BANK"))
    assert caught.value.code is None


def test_adapter_parse_carries_the_code(adapter: NachaImportSource):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_fixture("negative/03-truncated-mid-entry.ach"))
    assert caught.value.code == "INPUT_TRUNCATED"


def test_parse_fileset_reads_the_root(adapter: NachaImportSource):
    fileset = IntakeFileset(
        root="forward-file.ach",
        members={"forward-file.ach": _fixture("07-return-set/forward-file.ach"), "return-file.ach": _RETURN},
    )
    assert adapter.parse_fileset(fileset).batches[0].sec_code == "PPD"
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="missing.ach", members={"a.ach": _MINIMAL}))


# ---------------------------------------------------------------------------
# Control totals
# ---------------------------------------------------------------------------


def test_consistent_file_reconciles_every_total():
    for name in (
        "01-minimal-ppd-credit.ach",
        "02-typical-ppd-batch.ach",
        "03-composition-ccd-with-addenda.ach",
        "04-stress-multi-batch-sec-codes.ach",
        "05-real-world-payroll-and-tax.ach",
        "07-return-set/forward-file.ach",
        "07-return-set/return-file.ach",
    ):
        rows = control_totals_extras(parse_nacha(_fixture(name)))
        assert rows and all(row["consistent"] is True for row in rows), name


def test_entry_hash_and_totals_are_recomputed():
    file = parse_nacha(_PPD)
    totals = observed_totals(file.batches[0].entries)
    assert totals.entry_addenda_count == 4
    assert totals.entry_hash == 9100001 + 2100002 + 12100024 + 1140153
    assert totals.total_credit == 185050 + 242075 + 198500
    assert totals.total_debit == 32000


def test_entry_hash_keeps_ten_digits():
    entry = _with(_ENTRY, 4, "99999999")
    file = parse_nacha(_file(_HEADER, _BATCH_HEADER, *([entry] * 200), _BATCH_CONTROL, _FILE_CONTROL))
    assert observed_totals(file.batches[0].entries).entry_hash == (99999999 * 200) % 10**10


def test_mismatch_is_declared_versus_observed():
    file = parse_nacha(_MISMATCH)
    batch = {count.trailer: count for count in batch_control_counts(file.batches[0])}
    assert batch["batchControl.entryAddendaCount"].declared == 5
    assert batch["batchControl.entryAddendaCount"].observed == 2
    assert batch["batchControl.entryHash"].declared == 0
    assert batch["batchControl.entryHash"].observed == 11200003
    assert batch["batchControl.totalCreditEntryDollarAmount"].declared == 999999
    assert batch["batchControl.totalCreditEntryDollarAmount"].observed == 37000
    assert batch["batchControl.totalDebitEntryDollarAmount"].consistent is True
    whole = {count.trailer: count for count in file_control_counts(file)}
    assert (whole["fileControl.batchCount"].declared, whole["fileControl.batchCount"].observed) == (3, 1)
    assert (whole["fileControl.blockCount"].declared, whole["fileControl.blockCount"].observed) == (9, 1)


def test_unreadable_declaration_is_none_not_zero():
    control = _with(_BATCH_CONTROL, 11, "ABCDEFGHIJ")
    rows = control_totals_extras(parse_nacha(_file(_HEADER, _BATCH_HEADER, _ENTRY, control, _FILE_CONTROL)))
    hash_row = next(row for row in rows if row["record"] == "batchControl" and row["field"] == "entryHash")
    assert hash_row["declared"] is None and hash_row["consistent"] is None


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def _types(api) -> dict:
    return {item.name: item for item in api.types}


def test_batches_and_entries_are_native_structure(adapter: NachaImportSource):
    api = adapter.normalize(adapter.parse(_CCD))
    assert api.paradigm is ApiParadigm.DATA_SCHEMA and api.format == "nacha"
    types = _types(api)
    assert set(types) == {
        "AchFile",
        "Batch",
        "FileHeader",
        "BatchHeader",
        "EntryDetail",
        "Addenda05",
        "BatchControl",
        "FileControl",
    }
    batches = next(field for field in types["AchFile"].fields if field.name == "batches")
    assert batches.type.item is not None and batches.type.item.name.endswith("Batch")
    entries = next(field for field in types["Batch"].fields if field.name == "entries")
    assert entries.type.item.name.endswith("EntryDetail")
    addenda = next(field for field in types["EntryDetail"].fields if field.name == "addenda05")
    assert addenda.type.item.name.endswith("Addenda05")
    amount = next(field for field in types["EntryDetail"].fields if field.name == "amount")
    assert amount.extras["nacha_position"] == [30, 39] and amount.extras["nacha_field_kind"] == "amount"


def test_no_payload_value_enters_the_model(adapter: NachaImportSource):
    api = adapter.normalize(adapter.parse(_CCD), include_raw=False)
    dumped = api.model_dump_json()
    for value in ("EXAMPLE SUPPLIES BV", "500100200", "0004500000", "INV-10041"):
        assert value not in dumped
    assert all(field.default is None for item in api.types for field in item.fields)


def test_extras_record_batches_and_control_totals(adapter: NachaImportSource):
    api = adapter.normalize(adapter.parse(_MISMATCH))
    assert api.extras["nacha_sec_codes"] == ["PPD"]
    assert api.extras["nacha_batches"][0]["entryCount"] == 2
    assert api.extras["nacha_file"]["batchCount"] == 1
    inconsistent = [row for row in api.extras["nacha_control_totals"] if row["consistent"] is False]
    assert len(inconsistent) == 8
    assert api.title == "NACHA ACH file (PPD)"


def test_return_file_models_addenda_99(adapter: NachaImportSource):
    types = _types(adapter.normalize(adapter.parse(_RETURN)))
    assert "Addenda99" in types
    assert any(field.name == "returnReasonCode" for field in types["Addenda99"].fields)


def test_normalizer_rejects_foreign_ast(adapter: NachaImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "a file"})


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def test_analysis_hierarchy():
    document = analyze_nacha(parse_nacha(_CCD))
    assert document.status == STATUS_AVAILABLE
    (root,) = document.tree
    assert root.kind == KIND_FILE
    assert [child.kind for child in root.children] == [KIND_RECORD, KIND_BATCH, KIND_RECORD]
    batch = root.children[1]
    assert [child.kind for child in batch.children] == [KIND_RECORD, KIND_ENTRY, KIND_ENTRY, KIND_RECORD]
    entry = batch.children[1]
    assert entry.children[-1].kind == KIND_ADDENDA
    assert entry.attributes["direction"] == "debit" and entry.attributes["addendaCount"] == 1
    assert batch.attributes["controlTotalsConsistent"] is True


def test_field_locations_point_at_the_bytes():
    file = parse_nacha(_MINIMAL)
    document = analyze_nacha(file)
    amount = next(node for node in _all(document) if node.kind == KIND_FIELD and node.name == "amount")
    start = amount.location.offset
    assert file.raw[start : start + amount.location.length] == "0000015000"


def test_mismatch_attributes_and_warnings():
    document = analyze_nacha(parse_nacha(_MISMATCH))
    (root,) = document.tree
    assert root.attributes["declaredBatchCount"] == 3 and root.attributes["observedBatchCount"] == 1
    assert root.attributes["controlTotalsConsistent"] is False
    batch = root.children[1]
    assert batch.attributes["declaredEntryHash"] == 0 and batch.attributes["observedEntryHash"] == 11200003
    mismatches = [warning for warning in document.warnings if warning.code == WARNING_CONTROL_TOTAL_MISMATCH]
    assert len(mismatches) == 8
    assert all(warning.severity == "info" for warning in mismatches)
    assert document.status == STATUS_AVAILABLE


def test_values_are_values_and_structure_is_attributes():
    document = analyze_nacha(parse_nacha(_CCD))
    structural = apply_value_visibility(document, ValueVisibility.DEFAULT)
    nodes = _all(structural)
    assert all(node.value is None for node in nodes)
    name = next(node for node in nodes if node.kind == KIND_FIELD and node.name == "individualName")
    assert name.value_present and name.value_length == len("EXAMPLE SUPPLIES BV")
    for node in nodes:
        assert "EXAMPLE SUPPLIES BV" not in str(node.attributes)
        assert "500100200" not in str(node.attributes)


def test_record_warnings():
    entry_without_addenda = _with(_ENTRY, 79, "1")
    batch_iat = _with(_BATCH_HEADER, 51, "IAT")
    addenda_02 = "702" + " " * 91
    text = _file(_HEADER, batch_iat, entry_without_addenda, _ENTRY, addenda_02, _BATCH_CONTROL, _FILE_CONTROL)
    codes = [warning.code for warning in analyze_nacha(parse_nacha(text)).warnings]
    assert WARNING_IAT_LAYOUT in codes
    assert codes.count(WARNING_ADDENDA_INDICATOR) == 2
    assert WARNING_UNMODELLED_ADDENDA in codes


def test_check_digit_attribute():
    document = analyze_nacha(
        parse_nacha(_file(_HEADER, _BATCH_HEADER, _with(_ENTRY, 12, "8"), _BATCH_CONTROL, _FILE_CONTROL))
    )
    entry = next(node for node in _all(document) if node.kind == KIND_ENTRY)
    assert entry.attributes["checkDigitValid"] is False


def test_adapter_analyze(adapter: NachaImportSource):
    document = adapter.analyze(adapter.parse(_MULTI), source=_MULTI)
    assert document.analyzer.key == "nacha"
    assert "nacha.operating_rules_validation" in adapter.analysis_capabilities().unsupported
    with pytest.raises(ImportSourceError):
        adapter.analyze({"x": 1})


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


def test_capability_entry_states_the_operating_rules_boundary():
    entry = capability_for("nacha")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    assert entry.native_hierarchy is NativeHierarchy.NATIVE
    assert NACHA_OPERATING_RULES_STATEMENT in entry.notes
    assert not set(entry.supported_constructs) & set(entry.unsupported_constructs)


def test_version_coverage_is_declared():
    coverage = version_coverage_for("nacha")
    assert coverage.reads and not coverage.writes
