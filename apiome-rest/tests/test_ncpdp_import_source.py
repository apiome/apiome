"""Tests for the NCPDP SCRIPT and Telecom import adapter — FMT-6.8 (#5452).

Covers detection of both sub-formats, the SCRIPT reader (transaction type per message, batches,
filesets, every refusal code), the Telecom D.0 reader (header, segments, transaction grouping,
separators, every refusal code), the canonical normalizer (native structure, transaction types
recorded, no payload values), the native analysis (the shared EDI contract: declared versus observed
transaction count, values governed by value visibility) and the reviewed capability and version
entries that name the supported versions and the implementation-guide boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import pytest

from app.canonical_model import ApiParadigm
from app.fileset import IntakeFileset
from app.format_capability_registry import CapabilityProvenance, NativeHierarchy, capability_for
from app.format_version_coverage import VersionSupport, version_coverage_for
from app.import_source import DetectionInput, ImportSourceError, detect_import_source, get_import_source
from app.import_source_pipeline import format_profile_metadata
from app.ncpdp_analysis import (
    KIND_ATTRIBUTE,
    KIND_ELEMENT,
    KIND_FIELD,
    KIND_HEADER,
    KIND_MESSAGE,
    KIND_SEGMENT,
    KIND_TRANSACTION,
    KIND_TRANSMISSION,
    NCPDP_IMPLEMENTATION_GUIDE_STATEMENT,
    WARNING_SEGMENT_NOT_NAMED,
    WARNING_TRANSACTION_COUNT_MISMATCH,
    WARNING_UNRECOGNIZED_TRANSACTION,
    analyze_ncpdp,
)
from app.ncpdp_import_source import NcpdpImportSource
from app.ncpdp_normalizer import segment_field_name, segment_type_name, telecom_transaction_count
from app.ncpdp_parser import (
    SUB_FORMAT_SCRIPT,
    SUB_FORMAT_TELECOM,
    NcpdpParseError,
    is_ncpdp,
    parse_ncpdp,
    parse_ncpdp_fileset,
)
from app.ncpdp_script import SCRIPT_TRANSACTIONS
from app.ncpdp_telecom import HEADER_LAYOUT, HEADER_LENGTH, segment_name
from app.payload_analysis import STATUS_AVAILABLE, ValueVisibility, apply_value_visibility

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

FS, GS, SS = "\x1c", "\x1d", "\x1e"


def _fixture(name: str) -> str:
    return (_EXAMPLES / "ncpdp" / name).read_text(encoding="utf-8")


_NEWRX = _fixture("01-minimal-newrx.xml")
_TYPICAL = _fixture("02-typical-newrx.xml")
_CHANGE = _fixture("03-composition-rxchangerequest.xml")
_BATCH = _fixture("04-stress-multiple-transactions.xml")
_B1 = _fixture("05-real-world-telecom-b1-claim.dat")
_B2 = _fixture("06-typical-telecom-b2-reversal.dat")


def _header(*, version: str = "D0", code: str = "B1", count: str = "1", bin_: str = "610011") -> str:
    """A 56-character request header."""
    text = f"{bin_}{version}{code}PCN0000001{count}01{'1234567890':<15}20260819EXAMPLESW1"
    assert len(text) == HEADER_LENGTH
    return text


def _segment(segment_id: str, *fields: str, opener: str = SS, fs_before_id: bool = True) -> str:
    return opener + (FS if fs_before_id else "") + f"AM{segment_id}" + "".join(FS + item for item in fields)


def _script(body: str, *, root_attrs: str = 'version="010" release="006"', header: str = "") -> str:
    return (
        f'<Message xmlns="http://www.ncpdp.org/schema/SCRIPT" {root_attrs}>'
        f'<Header><To Qualifier="P">1</To><From Qualifier="D">2</From><MessageID>M-1</MessageID>{header}</Header>'
        f"<Body>{body}</Body></Message>"
    )


def _all(document: Any) -> List[Any]:
    out: List[Any] = []
    stack = list(document.tree)
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(node.children or [])
    return out


@pytest.fixture
def adapter() -> NcpdpImportSource:
    return NcpdpImportSource()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detection_claims_both_sub_formats(adapter: NcpdpImportSource):
    script = adapter.detect(DetectionInput(text=_NEWRX, filename="newrx.xml"))
    assert script.matched and script.format == "ncpdp" and script.confidence >= 0.95
    telecom = adapter.detect(DetectionInput(text=_B1, filename="claim.dat"))
    assert telecom.matched and telecom.confidence >= 0.9 and "D0" in telecom.reason
    other_version = adapter.detect(DetectionInput(text=_fixture("negative/06-semantic-unknown-telecom-version.dat")))
    assert other_version.matched and other_version.confidence < telecom.confidence
    assert not adapter.detect(DetectionInput(text=_fixture("negative/04-wrong-format-hl7v2.hl7"))).matched
    assert not adapter.detect(DetectionInput(text="<Document/>")).matched
    assert not adapter.detect(DetectionInput(text=None)).matched


def test_is_ncpdp_names_the_sub_format():
    assert is_ncpdp(_BATCH) == SUB_FORMAT_SCRIPT
    assert is_ncpdp(_B2) == SUB_FORMAT_TELECOM
    assert is_ncpdp("<!-- <Message xmlns='http://www.ncpdp.org/schema/SCRIPT'> -->\n<Other/>") is None
    assert is_ncpdp(_header()) is None  # a header with no segment after it is not claimed
    assert is_ncpdp("") is None


def test_registry_routes_both_sub_formats_to_ncpdp():
    assert get_import_source("ncpdp").key == "ncpdp"
    for text, name in ((_TYPICAL, "rx.xml"), (_B1, "claim.dat")):
        best = detect_import_source(DetectionInput(text=text, filename=name))
        assert best is not None and best[0].key == "ncpdp"


# ---------------------------------------------------------------------------
# SCRIPT reader
# ---------------------------------------------------------------------------


def test_newrx_transaction_type_is_detected_and_recorded():
    document = parse_ncpdp(_TYPICAL)
    assert document.sub_format == SUB_FORMAT_SCRIPT and document.script is not None
    (message,) = document.script.messages
    assert message.transaction_type == "NewRx" and message.recognized
    assert message.message_id == "MSG-20260819-0002"
    assert message.relates_to == "MSG-20260819-0000"
    assert message.version_label == "10.6"


def test_transaction_type_is_detected_per_message():
    script = parse_ncpdp(_BATCH).script
    assert script is not None and script.root_name == "Messages"
    assert [message.transaction_type for message in script.messages] == [
        "RxFill",
        "RxRenewalRequest",
        "CancelRx",
        "Status",
        "Error",
    ]
    assert script.messages[2].path == "Messages/Message[3]"


def test_transaction_version_attribute_wins_over_version_release():
    text = _script("<NewRx/>", root_attrs='TransactionDomain="SCRIPT" TransactionVersion="2017071"')
    (message,) = parse_ncpdp(text).script.messages  # type: ignore[union-attr]
    assert message.version_label == "2017071"


def test_unrecognised_transaction_is_read_and_flagged():
    text = _script("<FutureRx><Note>x</Note></FutureRx>")
    (message,) = parse_ncpdp(text).script.messages  # type: ignore[union-attr]
    assert message.transaction_type == "FutureRx" and not message.recognized
    codes = [warning.code for warning in analyze_ncpdp(parse_ncpdp(text)).warnings]
    assert codes == [WARNING_UNRECOGNIZED_TRANSACTION]


def test_core_transactions_are_recognised():
    for name in ("NewRx", "RxFill", "RxChangeRequest", "Status", "Error", "CancelRx"):
        assert name in SCRIPT_TRANSACTIONS


@pytest.mark.parametrize(
    "name, code",
    [
        ("negative/01-syntactic-unclosed-body.xml", "INPUT_MALFORMED"),
        ("negative/02-semantic-empty-body.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-medication.xml", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-hl7v2.hl7", "FORMAT_MISMATCH"),
        ("negative/06-semantic-unknown-telecom-version.dat", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_corpus_negatives(name: str, code: str):
    with pytest.raises(NcpdpParseError) as info:
        parse_ncpdp(_fixture(name), source_label=name)
    assert info.value.code == code


def test_encoding_fault_is_code_less():
    raw = (_EXAMPLES / "ncpdp" / "negative" / "05-encoding-utf16.xml").read_bytes()
    with pytest.raises(NcpdpParseError) as info:
        parse_ncpdp(raw.decode("utf-8", errors="replace"))
    assert info.value.code is None


@pytest.mark.parametrize(
    "text, code, fragment",
    [
        (
            '<Message xmlns="http://www.ncpdp.org/schema/SCRIPT"><Body><NewRx/></Body></Message>',
            "INPUT_SEMANTIC_INVALID",
            "Header",
        ),
        (_script("<NewRx/><RxFill/>"), "INPUT_SEMANTIC_INVALID", "2 transaction elements"),
        ('<Messages xmlns="http://www.ncpdp.org/schema/SCRIPT"/>', "INPUT_SEMANTIC_INVALID", "no Message"),
        (
            '<Message xmlns="urn:example"><Header/><Body><NewRx/></Body></Message>',
            "FORMAT_MISMATCH",
            "not NCPDP SCRIPT",
        ),
        ("<Message", "INPUT_TRUNCATED", "truncated"),
        ("   ", "INPUT_EMPTY", "empty"),
        ("plain text", "FORMAT_MISMATCH", "neither"),
    ],
)
def test_script_refusals_carry_a_code(text: str, code: str, fragment: str):
    with pytest.raises(NcpdpParseError) as info:
        parse_ncpdp(text)
    assert info.value.code == code
    assert fragment in str(info.value)


def test_fileset_reads_the_conversation(adapter: NcpdpImportSource):
    members = {
        "newrx.xml": _fixture("07-transaction-set/newrx.xml"),
        "status.xml": _fixture("07-transaction-set/status.xml"),
        "notes.txt": "not ncpdp",
    }
    document = adapter.parse_fileset(IntakeFileset(root="newrx.xml", members=members))
    assert document.script is not None and document.script.members == ["status.xml"]
    assert [message.transaction_type for message in document.script.messages] == ["NewRx", "Status"]
    assert document.script.messages[1].path == "status.xml:Message"
    model = adapter.normalize(document, include_raw=False)
    status = model.extras["ncpdp_transactions"][1]
    assert status["relatesToMessageId"] == "MSG-20260824-0100" and status["relatesToResolved"] is True
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="missing.xml", members=members))


def test_fileset_member_fault_is_refused():
    members = {"a.xml": _NEWRX, "b.xml": _fixture("negative/01-syntactic-unclosed-body.xml")}
    with pytest.raises(NcpdpParseError) as info:
        parse_ncpdp_fileset(members, "a.xml")
    assert info.value.code == "INPUT_MALFORMED"


def test_telecom_fileset_reads_the_root_alone():
    document = parse_ncpdp_fileset({"claim.dat": _B1, "rx.xml": _NEWRX}, "claim.dat")
    assert document.sub_format == SUB_FORMAT_TELECOM


# ---------------------------------------------------------------------------
# Telecom reader
# ---------------------------------------------------------------------------


def test_header_layout_tiles_56_columns():
    assert HEADER_LENGTH == 56
    columns = [column for spec in HEADER_LAYOUT for column in range(spec.start, spec.end + 1)]
    assert columns == list(range(1, 57))


def test_b1_claim_segments_and_transactions():
    transmission = parse_ncpdp(_B1).telecom
    assert transmission is not None
    assert transmission.version == "D0" and transmission.transaction_code == "B1"
    assert transmission.transaction_name == "Billing"
    assert [segment.tag for segment in transmission.segments] == ["AM04", "AM01", "AM07", "AM11", "AM03"]
    assert [segment.tag for segment in transmission.transmission_segments] == ["AM04", "AM01"]
    assert [[segment.tag for segment in group] for group in transmission.transactions] == [["AM07", "AM11", "AM03"]]
    claim = transmission.segments[2]
    assert claim.name == "Claim" and claim.separator == "GS"
    assert [item.field_id for item in claim.fields][:3] == ["EM", "D2", "E1"]


def test_segment_and_field_positions_point_at_the_bytes():
    transmission = parse_ncpdp(_B1).telecom
    assert transmission is not None
    segment = transmission.segments[0]
    assert _B1[segment.offset : segment.offset + segment.length].startswith(GS + "AM04")
    field = segment.fields[0]
    assert _B1[field.offset : field.offset + field.length] == "C2MEM-000112233"


def test_multi_claim_transmission_groups_by_claim_segment():
    text = (
        _header(count="2")
        + _segment("04", "C2X")
        + _segment("07", "D21", opener=GS)
        + _segment("11", "DU1")
        + _segment("07", "D22", opener=GS)
        + _segment("11", "DU2", fs_before_id=False)
    )
    transmission = parse_ncpdp(text).telecom
    assert transmission is not None
    assert [[segment.tag for segment in group] for group in transmission.transactions] == [
        ["AM07", "AM11"],
        ["AM07", "AM11"],
    ]
    assert telecom_transaction_count(transmission) == {
        "declared": 2,
        "observed": 2,
        "compared": True,
        "consistent": True,
    }


def test_transaction_count_mismatch_is_declared_versus_observed():
    text = _header(count="3") + _segment("07", "D21")
    document = parse_ncpdp(text)
    assert telecom_transaction_count(document.telecom) == {  # type: ignore[arg-type]
        "declared": 3,
        "observed": 1,
        "compared": True,
        "consistent": False,
    }
    analysis = analyze_ncpdp(document)
    (root,) = analysis.tree
    assert root.attributes["declaredTransactionCount"] == 3
    assert root.attributes["observedTransactionCount"] == 1
    assert root.attributes["transactionCountConsistent"] is False
    (warning,) = [item for item in analysis.warnings if item.code == WARNING_TRANSACTION_COUNT_MISMATCH]
    assert warning.severity == "info" and "declares 3 transactions" in warning.message
    assert analysis.status == STATUS_AVAILABLE


def test_count_is_not_compared_for_non_claim_codes():
    transmission = parse_ncpdp(_header(code="E1", count="1") + _segment("04", "C2X")).telecom
    assert transmission is not None and transmission.transactions == []
    assert telecom_transaction_count(transmission)["compared"] is False
    assert not analyze_ncpdp(parse_ncpdp(_header(code="E1") + _segment("04", "C2X"))).warnings


@pytest.mark.parametrize(
    "text, code, fragment",
    [
        (_header()[:30], "INPUT_TRUNCATED", "truncated"),
        (
            _header(version="51") + _segment("07", "D21"),
            "INPUT_SEMANTIC_INVALID",
            "only Telecommunication Standard D.0",
        ),
        (_header(code="Z9") + _segment("07", "D21"), "INPUT_SEMANTIC_INVALID", "transaction code 'Z9'"),
        (_header(count="X") + _segment("07", "D21"), "INPUT_SEMANTIC_INVALID", "transaction count"),
        (_header() + SS + FS + "XX01" + FS + "D21", "INPUT_MALFORMED", "AM"),
        (_header() + _segment("07", "D"), "INPUT_MALFORMED", "two-character field id"),
        (_header() + _segment("07", "D21") + "\n" + _segment("11", "DU1"), "INPUT_MALFORMED", "line break"),
    ],
)
def test_telecom_refusals_carry_a_code(text: str, code: str, fragment: str):
    with pytest.raises(NcpdpParseError) as info:
        parse_ncpdp(text)
    assert info.value.code == code
    assert fragment in str(info.value)


def test_header_shaped_text_reaches_the_telecom_reader():
    for text, code in ((_header(), "INPUT_SEMANTIC_INVALID"), (_header() + "AM07", "INPUT_MALFORMED")):
        with pytest.raises(NcpdpParseError) as info:
            parse_ncpdp(text)
        assert info.value.code == code


def test_non_numeric_bin_is_malformed():
    from app.ncpdp_telecom import TelecomParseError, parse_telecom

    with pytest.raises(TelecomParseError) as info:
        parse_telecom(_header(bin_="61001A") + _segment("07"))
    assert info.value.code == "INPUT_MALFORMED"


def test_trailing_line_break_is_tolerated():
    assert parse_ncpdp(_B2 + "\r\n").telecom is not None


def test_unnamed_segment_is_kept_and_stated():
    text = _header() + _segment("07", "D21") + _segment("31", "ZZ1")
    document = parse_ncpdp(text)
    assert document.telecom is not None and document.telecom.segments[1].name == "Segment AM31"
    codes = [warning.code for warning in analyze_ncpdp(document).warnings]
    assert codes == [WARNING_SEGMENT_NOT_NAMED]


def test_segment_names():
    assert segment_name("07") == "Claim"
    assert segment_type_name("07") == "ClaimSegment"
    assert segment_type_name("05") == "CoordinationOfBenefitsOtherPaymentsSegment"
    assert segment_type_name("31") == "SegmentAM31"
    assert segment_field_name("08") == "dURPPS"
    assert segment_field_name("31") == "segmentAM31"


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def _types(model) -> dict:
    return {item.name: item for item in model.types}


def _fields(item) -> dict:
    return {field.name: field for field in item.fields}


def test_script_model_is_inferred_structure(adapter: NcpdpImportSource):
    model = adapter.normalize(adapter.parse(_TYPICAL), include_raw=False)
    assert model.paradigm is ApiParadigm.DATA_SCHEMA and model.format == "ncpdp"
    assert model.title == "NCPDP SCRIPT NewRx"
    types = _types(model)
    assert {"Message", "Header", "Body", "NewRx", "Patient", "MedicationPrescribed"} <= set(types)
    message = _fields(types["Message"])
    assert message["version"].extras["ncpdp_xml"] == "attribute"
    assert message["Body"].type.name == "NCPDP-SCRIPT.Body"
    to = _fields(types["To"])
    assert set(to) == {"Qualifier", "value"} and to["value"].extras["ncpdp_xml"] == "text"
    assert _fields(types["DrugCoded"])["ProductCode"].type.name == "string"


def test_script_batch_body_fields_are_optional_per_transaction(adapter: NcpdpImportSource):
    model = adapter.normalize(adapter.parse(_BATCH), include_raw=False)
    body = _fields(_types(model)["Body"])
    assert set(body) == {"RxFill", "RxRenewalRequest", "CancelRx", "Status", "Error"}
    assert all(field.type.nullable for field in body.values())
    header = _fields(_types(model)["Header"])
    assert header["MessageID"].type.nullable is False and header["RelatesToMessageID"].type.nullable is True
    assert model.extras["ncpdp_transaction_types"] == ["RxFill", "RxRenewalRequest", "CancelRx", "Status", "Error"]
    assert model.extras["ncpdp_script"]["messageCount"] == 5


def test_repeated_elements_become_lists(adapter: NcpdpImportSource):
    text = _script("<Status><Code>1</Code><Code>2</Code></Status>")
    status = _fields(_types(adapter.normalize(adapter.parse(text), include_raw=False))["Status"])
    assert status["Code"].type.item is not None


def test_telecom_model_is_segment_structure(adapter: NcpdpImportSource):
    model = adapter.normalize(adapter.parse(_B1), include_raw=False)
    assert model.title == "NCPDP Telecom D.0 B1 (Billing)"
    types = _types(model)
    root = _fields(types["TelecomTransmission"])
    assert set(root) == {"header", "insurance", "patient", "transactions"}
    assert root["transactions"].type.item is not None
    assert set(_fields(types["Transaction"])) == {"claim", "pricing", "prescriber"}
    cardholder = _fields(types["InsuranceSegment"])["C2"]
    assert cardholder.description == "302-C2 Cardholder ID"
    assert cardholder.extras == {"ncpdp_field_id": "C2", "ncpdp_data_element": "302-C2"}
    assert types["ClaimSegment"].extras["ncpdp_segment_id"] == "AM07"
    bin_field = _fields(types["TransactionHeader"])["binNumber"]
    assert bin_field.extras["ncpdp_position"] == [1, 6]


def test_telecom_extras_record_transaction_type_and_count(adapter: NcpdpImportSource):
    model = adapter.normalize(adapter.parse(_B2), include_raw=False)
    telecom = model.extras["ncpdp_telecom"]
    assert telecom["version"] == "D0" and telecom["transactionCode"] == "B2"
    assert telecom["transactionName"] == "Reversal"
    assert telecom["transactionCount"]["consistent"] is True
    assert model.extras["ncpdp_transactions"] == [
        {"index": 1, "transactionType": "B2", "transactionName": "Reversal", "segments": ["AM07"]}
    ]


@pytest.mark.parametrize(
    "text, probes",
    [
        (_TYPICAL, ("Amoxicillin 500 MG oral capsule", "Jordan", "12 Example Street", "AC1234563")),
        (_B1, ("MEM-000112233", "JORDAN", "00093310501", "19850214")),
    ],
)
def test_no_payload_value_enters_the_model(adapter: NcpdpImportSource, text: str, probes):
    model = adapter.normalize(adapter.parse(text), include_raw=False)
    dumped = json.dumps(model.model_dump(mode="json"))
    for probe in probes:
        assert probe not in dumped


def test_sub_format_is_lifted_into_provenance(adapter: NcpdpImportSource):
    script = format_profile_metadata(adapter.normalize(adapter.parse(_NEWRX), include_raw=False))
    assert script is not None and script["key"] == "ncpdp-script"
    assert script["implementation_guide_consulted"] is False
    assert "Version claimed: 10.6." in script["evidence"]
    telecom = format_profile_metadata(adapter.normalize(adapter.parse(_B1), include_raw=False))
    assert telecom is not None and telecom["key"] == "ncpdp-telecom"


def test_normalizer_rejects_foreign_ast(adapter: NcpdpImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"x": 1})


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def test_script_analysis_hierarchy():
    document = analyze_ncpdp(parse_ncpdp(_BATCH))
    assert document.status == STATUS_AVAILABLE
    assert [node.kind for node in document.tree] == [KIND_MESSAGE] * 5
    assert [node.attributes["transactionType"] for node in document.tree][-1] == "Error"
    first = document.tree[0]
    assert first.attributes["implementationGuideConsulted"] is False
    kinds = {node.kind for node in _all(document)}
    assert {KIND_ELEMENT, KIND_ATTRIBUTE} <= kinds
    cancel = document.tree[2]
    assert cancel.attributes["relatesToMessageId"] == "MSG-20260819-0002"
    assert cancel.attributes["relatesToResolved"] is False


def test_telecom_analysis_hierarchy():
    document = analyze_ncpdp(parse_ncpdp(_B1))
    (root,) = document.tree
    assert root.kind == KIND_TRANSMISSION and root.attributes["transactionCode"] == "B1"
    assert [child.kind for child in root.children] == [KIND_HEADER, KIND_SEGMENT, KIND_SEGMENT, KIND_TRANSACTION]
    transaction = root.children[-1]
    assert [child.name for child in transaction.children] == ["AM07", "AM11", "AM03"]
    claim = transaction.children[0]
    assert claim.location.offset is not None and claim.label == "Claim"
    header = root.children[0]
    version = next(child for child in header.children if child.name == "versionReleaseNumber")
    assert _B1[version.location.offset : version.location.offset + version.location.length] == "D0"


@pytest.mark.parametrize(
    "text, probes",
    [(_TYPICAL, ("Amoxicillin 500 MG oral capsule", "Jordan")), (_B1, ("MEM-000112233", "JORDAN"))],
)
def test_values_are_values_and_structure_is_attributes(text: str, probes):
    document = analyze_ncpdp(parse_ncpdp(text))
    structural = apply_value_visibility(document, ValueVisibility.DEFAULT)
    nodes = _all(structural)
    assert all(node.value is None for node in nodes)
    assert any(node.value_present and node.value_length for node in nodes if node.kind in (KIND_ELEMENT, KIND_FIELD))
    for node in nodes:
        for probe in probes:
            assert probe not in str(node.attributes)


def test_adapter_analyze(adapter: NcpdpImportSource):
    document = adapter.analyze(adapter.parse(_CHANGE), source=_CHANGE)
    assert document.analyzer.key == "ncpdp"
    assert "ncpdp.implementation_guide_validation" in adapter.analysis_capabilities().unsupported
    with pytest.raises(ImportSourceError):
        adapter.analyze({"x": 1})


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


def test_capability_entry_names_versions_and_the_guide_boundary():
    entry = capability_for("ncpdp")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    assert entry.native_hierarchy is NativeHierarchy.NATIVE
    assert NCPDP_IMPLEMENTATION_GUIDE_STATEMENT in entry.notes
    assert "No implementation guide" in NCPDP_IMPLEMENTATION_GUIDE_STATEMENT
    versions = " ".join(entry.notes)
    assert "Telecommunication D.0" in versions and "2017071" in versions
    assert not set(entry.supported_constructs) & set(entry.unsupported_constructs)


def test_version_coverage_names_both_sub_formats():
    coverage = version_coverage_for("ncpdp")
    assert not coverage.writes
    script, telecom = coverage.reads
    assert "SCRIPT" in script.version and script.support is VersionSupport.UNGATED
    assert "D.0" in telecom.version and telecom.support is VersionSupport.FULL
