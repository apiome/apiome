"""Tests for the EDI dialect profiles and the TRADACOMS import adapter — FMT-6.5 (#5449).

Covers the dialect-profile registry and recognition rule (EANCOM, ODETTE/VDA, plain UN/EDIFACT), how
the EDIFACT adapter records the profile (extras, analysis, detection reason), the TRADACOMS parser
(envelope, files, positions and every refusal code), detection and the misroute in both directions,
the normalizer, the native analysis, the adapter seam, the provenance seam and the reviewed
capability entries. Corpus-wide behaviour is asserted by the corpus suites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi
from app.edi_dialect_profiles import (
    DIALECT_PROFILES,
    EANCOM,
    ODETTE,
    PROFILE_EXTRAS_KEY,
    TRADACOMS,
    UN_EDIFACT,
    detect_edifact_profile,
    dialect_profile,
    edifact_profile,
    messages_outside_set,
    profile_statement,
)
from app.edifact_analysis import (
    WARNING_DIALECT_PROFILE,
    WARNING_OUTSIDE_PROFILE_MESSAGE_SET,
    analyze_edifact,
)
from app.edifact_import_source import EdifactImportSource
from app.edifact_parser import parse_edifact
from app.fileset import IntakeFileset
from app.format_capability_registry import NativeHierarchy, SourceLocationQuality, capability_for
from app.import_source import DetectionInput, ImportSourceError, get_import_source
from app.import_source_pipeline import format_profile_metadata
from app.payload_analysis import STATUS_AVAILABLE, ValueVisibility, apply_value_visibility
from app.tradacoms_analysis import (
    KIND_FILE,
    KIND_MESSAGE,
    KIND_SEGMENT,
    KIND_TRANSMISSION,
    TRADACOMS_IMPLEMENTATION_GUIDE_STATEMENT,
    WARNING_CANONICAL_SUBSET,
    WARNING_CONTROL_COUNT_MISMATCH,
    analyze_tradacoms,
)
from app.tradacoms_import_source import TradacomsImportSource
from app.tradacoms_normalizer import TradacomsNormalizer, canonical_message
from app.tradacoms_parser import TradacomsParseError, is_tradacoms, parse_tradacoms

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _fixture(path: str) -> str:
    return (_EXAMPLES / path).read_text(encoding="utf-8")


_MINIMAL = _fixture("tradacoms/01-minimal-order-file.edi")
_INVOICE = _fixture("tradacoms/03-typical-invoice-file.edi")
_MULTI = _fixture("tradacoms/04-stress-multi-message-file.edi")
_TWO_TRANSMISSIONS = _fixture("tradacoms/07-composition-nested-files.edi")
_EANCOM = _fixture("edifact/05-real-world-eancom-orders.edi")
_ODETTE = _fixture("edifact/06-typical-odette-delfor.edi")
_PLAIN = _fixture("edifact/01-minimal-orders-d96a.edi")
_EDIFACT_MISROUTE = _fixture("tradacoms/negative/04-wrong-format-edifact.edi")
_TRADACOMS_MISROUTE = _fixture("edifact/negative/07-wrong-format-tradacoms.edi")


def _transmission(*segments: str) -> str:
    """Assemble a one-segment-per-line transmission."""
    return "\n".join(segments) + "\n"


_HEADER = ("STX=ANAA:1+5012345678901:SUP+5087654321098:BUY+260819:1030+00001+++ORDHDR'",)


def _walk(node: Any) -> List[Any]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk(child))
    return nodes


def _nodes(document: Any, kind: str) -> List[Any]:
    return [node for root in document.tree for node in _walk(root) if node.kind == kind]


def _codes(document: Any) -> List[str]:
    return [warning.code for warning in document.warnings]


@pytest.fixture()
def adapter() -> TradacomsImportSource:
    return TradacomsImportSource()


# ---------------------------------------------------------------------------
# Dialect profiles
# ---------------------------------------------------------------------------


def test_profile_registry_holds_the_four_profiles():
    assert set(DIALECT_PROFILES) == {"un-edifact", "eancom", "odette", "tradacoms"}
    assert dialect_profile("eancom") is EANCOM
    assert dialect_profile("nope") is None
    assert TRADACOMS.engine == "tradacoms"
    assert {EANCOM.engine, ODETTE.engine, UN_EDIFACT.engine} == {"edifact"}
    for profile in DIALECT_PROFILES.values():
        assert profile.boundaries, profile.key


def test_eancom_is_recognised_by_its_association_code():
    match = detect_edifact_profile(
        association_codes=["", "EAN008"], party_ids=["X"], message_types=["ORDERS"]
    )
    assert match.profile is EANCOM
    assert "EAN008" in match.evidence[0]


@pytest.mark.parametrize("code", ["OD0001", "ODETTE", "VDA4984"])
def test_odette_is_recognised_by_a_subset_designator(code: str):
    match = detect_edifact_profile(association_codes=[code], party_ids=[], message_types=["INVOIC"])
    assert match.profile is ODETTE


def test_odette_party_rule_needs_both_signals():
    both = detect_edifact_profile(
        association_codes=[], party_ids=["O0013000000ZZ"], message_types=["DELFOR", "DELJIT"]
    )
    party_only = detect_edifact_profile(
        association_codes=[], party_ids=["O0013000000ZZ"], message_types=["PRICAT"]
    )
    set_only = detect_edifact_profile(
        association_codes=[], party_ids=["SENDER01"], message_types=["DELFOR"]
    )
    assert both.profile is ODETTE and len(both.evidence) == 2
    assert party_only.profile is UN_EDIFACT
    assert set_only.profile is UN_EDIFACT


def test_eancom_takes_precedence_and_plain_needs_no_evidence():
    match = detect_edifact_profile(
        association_codes=["OD0001", "EAN010"], party_ids=[], message_types=["ORDERS"]
    )
    plain = detect_edifact_profile(association_codes=[""], party_ids=[""], message_types=[])
    assert match.profile is EANCOM
    assert plain.profile is UN_EDIFACT and plain.evidence == ()


def test_lookalike_association_codes_are_not_profiles():
    for code in ("EAN", "EAN0081", "XEAN008", "OX01"):
        match = detect_edifact_profile(association_codes=[code], party_ids=[], message_types=[])
        assert match.profile is UN_EDIFACT, code


def test_edifact_corpus_profiles():
    assert edifact_profile(parse_edifact(_EANCOM)).profile is EANCOM
    assert edifact_profile(parse_edifact(_ODETTE)).profile is ODETTE
    assert edifact_profile(parse_edifact(_PLAIN)).profile is UN_EDIFACT


def test_profile_extras_state_no_guide_was_consulted():
    extras = edifact_profile(parse_edifact(_EANCOM)).extras()
    assert extras["key"] == "eancom"
    assert extras["label"] == "EANCOM"
    assert extras["engine"] == "edifact"
    assert extras["implementation_guide_consulted"] is False
    assert extras["evidence"]


def test_messages_outside_set_and_covers():
    assert EANCOM.covers(" orders ")
    assert messages_outside_set(EANCOM, ["ORDERS", "BANSTA", "BANSTA"]) == ["BANSTA"]
    assert messages_outside_set(UN_EDIFACT, ["ANYTHING"]) == []


def test_profile_statement_names_recognition_and_boundaries():
    statement = profile_statement(ODETTE)
    assert statement.startswith("ODETTE/VDA profile (ODETTE International / VDA).")
    assert ODETTE.recognition in statement
    assert all(boundary in statement for boundary in ODETTE.boundaries)


# ---------------------------------------------------------------------------
# The EDIFACT adapter records the profile
# ---------------------------------------------------------------------------


def test_edifact_normalizer_records_the_profile():
    source = EdifactImportSource()
    model = source.normalize(source.parse(_ODETTE), include_raw=False)
    assert model.extras[PROFILE_EXTRAS_KEY]["key"] == "odette"
    plain = source.normalize(source.parse(_PLAIN), include_raw=False)
    assert plain.extras[PROFILE_EXTRAS_KEY]["key"] == "un-edifact"


def test_edifact_analysis_records_the_profile():
    document = analyze_edifact(parse_edifact(_EANCOM))
    interchange = document.tree[0]
    assert interchange.attributes["profile"] == "eancom"
    assert interchange.attributes["profileLabel"] == "EANCOM"
    assert interchange.attributes["implementationGuideConsulted"] is False
    messages = _nodes(document, "message")
    assert messages and all(node.attributes["inProfileMessageSet"] for node in messages)
    assert WARNING_DIALECT_PROFILE in _codes(document)
    assert "edifact.dialect_profiles" in document.capabilities.supported


def test_plain_edifact_analysis_has_no_profile_warning_or_membership():
    document = analyze_edifact(parse_edifact(_PLAIN))
    assert document.tree[0].attributes["profile"] == "un-edifact"
    assert WARNING_DIALECT_PROFILE not in _codes(document)
    assert all("inProfileMessageSet" not in node.attributes for node in _nodes(document, "message"))


def test_message_outside_the_profile_set_is_named_and_still_read():
    text = (
        "UNB+UNOC:3+5012345678901:14+5087654321098:14+260101:0000+1'"
        "UNH+1+BANSTA:D:96A:UN:EAN002'BGM+1'UNT+3+1'UNZ+1+1'"
    )
    document = analyze_edifact(parse_edifact(text))
    assert WARNING_OUTSIDE_PROFILE_MESSAGE_SET in _codes(document)
    assert _nodes(document, "message")[0].attributes["inProfileMessageSet"] is False
    assert document.status == STATUS_AVAILABLE


def test_edifact_detection_reason_names_the_profile():
    source = EdifactImportSource()
    assert source.detect(DetectionInput(text=_EANCOM)).reason.endswith("— EANCOM profile")
    assert source.detect(DetectionInput(text=_ODETTE)).reason.endswith("— ODETTE/VDA profile")
    assert "profile" not in source.detect(DetectionInput(text=_PLAIN)).reason


def test_edifact_detection_survives_an_unparseable_interchange():
    result = EdifactImportSource().detect(DetectionInput(text="UNB+UNOC:3+A+B'UNH+1+ORDERS'"))
    assert result.matched and "profile" not in result.reason


# ---------------------------------------------------------------------------
# Detection and the misroute, both directions
# ---------------------------------------------------------------------------


def test_is_tradacoms_is_positional():
    assert is_tradacoms(_MINIMAL)
    assert is_tradacoms("\n  " + _MINIMAL)
    for text in (_PLAIN, "ISA*00*~", "This mentions STX=ANAA in prose", "STX+ANAA", "", "S\x00T\x00X\x00=\x00"):
        assert not is_tradacoms(text), text


def test_detect_scores_messages_above_a_bare_header(adapter: TradacomsImportSource):
    full = adapter.detect(DetectionInput(text=_MINIMAL, filename="x.edi"))
    bare = adapter.detect(DetectionInput(text=_transmission(*_HEADER, "END=0'")))
    assert full.matched and full.confidence == pytest.approx(0.95)
    assert bare.matched and bare.confidence == pytest.approx(0.7)
    assert full.format == bare.format == "tradacoms"
    assert "TRADACOMS profile" in full.reason


def test_neither_adapter_claims_the_other(adapter: TradacomsImportSource):
    assert not adapter.detect(DetectionInput(text=_EDIFACT_MISROUTE)).matched
    assert not EdifactImportSource().detect(DetectionInput(text=_TRADACOMS_MISROUTE)).matched
    assert EdifactImportSource().detect(DetectionInput(text=_EDIFACT_MISROUTE)).matched


def test_misroutes_are_refused_without_a_code(adapter: TradacomsImportSource):
    with pytest.raises(ImportSourceError) as tradacoms_side:
        adapter.parse(_EDIFACT_MISROUTE)
    with pytest.raises(ImportSourceError) as edifact_side:
        EdifactImportSource().parse(_TRADACOMS_MISROUTE)
    # Code-less, so the pipeline sees the other adapter's claim and names FORMAT_MISMATCH.
    assert tradacoms_side.value.code is None
    assert edifact_side.value.code is None


def test_adapter_is_registered():
    source = get_import_source("tradacoms")
    assert isinstance(source, TradacomsImportSource)
    assert source.paradigm is ApiParadigm.DATA_SCHEMA
    assert source.formats == ("tradacoms",)
    assert ".tra" in source.file_extensions


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_envelope_and_files_are_read():
    transmission = parse_tradacoms(_INVOICE).transmissions[0]
    assert transmission.syntax_identifier == "ANAA"
    assert transmission.syntax_version == "1"
    assert transmission.sender_code == "5012345678901"
    assert transmission.recipient_code == "5087654321098"
    assert (transmission.date, transmission.time) == ("260820", "0915")
    assert transmission.sender_reference == "00003"
    (file,) = transmission.files
    assert file.header_type == "INVFIL"
    assert (file.transaction_code, file.transaction_name) == ("0700", "INVOICES")
    assert (file.generation, file.file_version) == ("00003", "1")
    assert [message.message_type for message in file.messages] == [
        "INVFIL",
        "INVOIC",
        "VATTLR",
        "INVTLR",
    ]
    assert file.messages[0].is_file_header and not file.messages[1].is_file_header


def test_stx_password_and_application_reference():
    transmission = parse_tradacoms(_MULTI).transmissions[0]
    assert transmission.application_reference == "APPREF"
    assert transmission.header.component(6) == "PASSWORD"


def test_several_transmissions_in_one_document():
    document = parse_tradacoms(_TWO_TRANSMISSIONS)
    assert len(document.transmissions) == 2
    assert [t.files[0].header_type for t in document.transmissions] == ["ORDHDR", "DELHDR"]
    assert len(list(document.all_messages())) == 7


def test_transmission_with_no_file_header_forms_one_file():
    text = _transmission(*_HEADER, "MHD=1+ORDERS:9'", "ORD=PO-1'", "MTR=3'", "END=1'")
    (file,) = parse_tradacoms(text).transmissions[0].files
    assert file.header is None and file.header_type == ""
    assert file.transaction_code == ""


def test_a_second_header_message_opens_a_second_file():
    text = _transmission(
        *_HEADER,
        "MHD=1+ORDHDR:9'",
        "TYP=0430+ORDERS'",
        "MTR=3'",
        "MHD=2+DELHDR:9'",
        "TYP=0530+DELIVERY'",
        "MTR=3'",
        "END=2'",
    )
    files = parse_tradacoms(text).transmissions[0].files
    assert [file.header_type for file in files] == ["ORDHDR", "DELHDR"]


def test_release_character_and_empty_positions():
    text = _transmission(*_HEADER, "MHD=1+ORDERS:9'", "CLO=A?+B?:C+'", "MTR=3'", "END=1'")
    segment = parse_tradacoms(text).transmissions[0].files[0].messages[0].segments[0]
    assert segment.component(1) == "A+B:C"
    assert len(segment.elements) == 2 and segment.elements[1].value == ""


def test_segments_carry_exact_source_positions():
    document = parse_tradacoms(_MINIMAL)
    for message in document.all_messages():
        for segment in (message.header, *message.segments, message.trailer):
            assert _MINIMAL[segment.offset : segment.offset + segment.length] == segment.raw + "'"
            assert segment.column == 1


@pytest.mark.parametrize(
    ("text", "code", "fragment"),
    [
        (_transmission(*_HEADER, "MHD 1+ORDERS:9'", "END=1'"), "INPUT_MALFORMED", "followed by `=`"),
        (_transmission(*_HEADER, "MHD=1+ORDERS:9'", "ORD=PO-1"), "INPUT_TRUNCATED", "mid-segment"),
        (_transmission(*_HEADER, "MHD=1+ORDERS:9'", "ORD=PO-1'"), "INPUT_TRUNCATED", "before its `MTR`"),
        (_transmission(*_HEADER, "MHD=1+ORDERS:9'", "MTR=2'"), "INPUT_SEMANTIC_INVALID", "no `END`"),
        (_transmission(*_HEADER, "END=0'"), "INPUT_SEMANTIC_INVALID", "carries no"),
        (_transmission(*_HEADER, "ORD=PO-1'", "END=0'"), "INPUT_SEMANTIC_INVALID", "outside any message"),
        (_transmission(*_HEADER, "MTR=2'", "END=0'"), "INPUT_SEMANTIC_INVALID", "closes no message"),
        (
            _transmission(*_HEADER, "MHD=1+ORDERS:9'", "MHD=2+ORDERS:9'"),
            "INPUT_SEMANTIC_INVALID",
            "has no `MTR`",
        ),
        (
            _transmission(*_HEADER, "MHD=2+ORDERS:9'", "MTR=2'", "END=1'"),
            "INPUT_SEMANTIC_INVALID",
            "count 1, 2, 3",
        ),
        (
            _transmission(*_HEADER, "MHD=1+ORDERS:9'", "MTR=2'", "END=1'", "ORD=X'"),
            "INPUT_SEMANTIC_INVALID",
            "after `END`",
        ),
        (
            _transmission(*_HEADER, "MHD=1+ORDERS:9'", "MTR=2'", *_HEADER),
            "INPUT_SEMANTIC_INVALID",
            "inside the one",
        ),
        (
            _transmission(*_HEADER, "MHD=1+ORDERS:9'", "ORD=PO-1\nOLD=1'", "MTR=3'", "END=1'"),
            "INPUT_MALFORMED",
            "no segment terminator",
        ),
    ],
)
def test_refusals_carry_a_taxonomy_code(text: str, code: str, fragment: str):
    with pytest.raises(TradacomsParseError) as caught:
        parse_tradacoms(text)
    assert caught.value.code == code
    assert fragment in str(caught.value)
    assert "TRADACOMS" in str(caught.value)


def test_encoding_faults_and_empty_input():
    with pytest.raises(TradacomsParseError) as encoded:
        parse_tradacoms("﻿" + _MINIMAL)
    with pytest.raises(TradacomsParseError) as empty:
        parse_tradacoms("  \n")
    assert encoded.value.code is None
    assert empty.value.code == "INPUT_EMPTY"


def test_adapter_parse_carries_the_code(adapter: TradacomsImportSource):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_transmission(*_HEADER, "END=0'"))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


def test_parse_fileset_reads_the_root(adapter: TradacomsImportSource):
    order = _fixture("tradacoms/08-transmission-set/order-file.edi")
    ack = _fixture("tradacoms/08-transmission-set/ack-file.edi")
    fileset = IntakeFileset(members={"order-file.edi": order, "ack-file.edi": ack}, root="order-file.edi")
    document = adapter.parse_fileset(fileset)
    assert document.transmissions[0].files[0].header_type == "ORDHDR"
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(members={"ack-file.edi": ack}, root="missing.edi"))


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def test_normalizer_maps_the_first_detail_message(adapter: TradacomsImportSource):
    model = adapter.normalize(adapter.parse(_INVOICE), include_raw=False)
    assert model.format == "tradacoms"
    assert model.title == "TRADACOMS INVOIC"
    names = {type_.name for type_ in model.types}
    assert names == {"MessageINVOIC", "ILD"}
    message = next(type_ for type_ in model.types if type_.name == "MessageINVOIC")
    fields = {field.name for field in message.fields}
    assert {"IRF01", "CLO01-1", "ILD"} <= fields
    assert model.raw is None


def test_normalizer_extras(adapter: TradacomsImportSource):
    model = adapter.normalize(adapter.parse(_INVOICE))
    extras = model.extras
    assert extras[PROFILE_EXTRAS_KEY]["key"] == "tradacoms"
    assert extras["tradacoms_message_type"] == "INVOIC"
    assert extras["tradacoms_transmission"]["sender_reference"] == "00003"
    assert extras["tradacoms_transmission"]["transmission_count"] == 1
    assert extras["tradacoms_file"]["transaction_code"] == "0700"
    assert [item["message_type"] for item in extras["tradacoms_messages"]] == [
        "INVFIL",
        "INVOIC",
        "VATTLR",
        "INVTLR",
    ]
    assert model.raw == {"tradacoms": _INVOICE}


def test_canonical_message_falls_back_to_a_header():
    text = _transmission(*_HEADER, "MHD=1+ORDHDR:9'", "TYP=0430+ORDERS'", "MTR=3'", "END=1'")
    file, message = canonical_message(parse_tradacoms(text))
    assert message.message_type == "ORDHDR" and file.header is message


def test_normalizer_rejects_foreign_ast(adapter: TradacomsImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize(object())
    with pytest.raises(ValueError):
        TradacomsNormalizer().normalize(object())


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def test_analysis_renders_the_native_hierarchy():
    document = analyze_tradacoms(parse_tradacoms(_INVOICE))
    assert document.status == STATUS_AVAILABLE
    (transmission,) = document.tree
    assert transmission.kind == KIND_TRANSMISSION
    assert [child.kind for child in transmission.children] == [KIND_FILE]
    file = transmission.children[0]
    assert file.attributes["headerMessageType"] == "INVFIL"
    assert file.attributes["transactionCode"] == "0700"
    assert [message.kind for message in file.children] == [KIND_MESSAGE] * 4
    assert file.children[1].children[0].kind == KIND_SEGMENT
    assert file.children[1].location.path == "STX[0]/FILE[0]/MHD[1]"
    assert file.children[1].children[0].location.path == "STX[0]/FILE[0]/MHD[1]/CLO[0]"


def test_analysis_records_the_profile():
    document = analyze_tradacoms(parse_tradacoms(_INVOICE))
    attributes = document.tree[0].attributes
    assert attributes["profile"] == "tradacoms"
    assert attributes["profileLabel"] == "TRADACOMS"
    assert attributes["implementationGuideConsulted"] is False
    assert attributes["tagSeparator"] == "="
    assert all(node.attributes["inProfileMessageSet"] for node in _nodes(document, KIND_MESSAGE))
    assert "tradacoms.dialect_profile_applied" in _codes(document)


def test_consistent_controls_are_recorded_without_warnings():
    document = analyze_tradacoms(parse_tradacoms(_INVOICE))
    assert document.tree[0].attributes["declaredMessageCount"] == 4
    assert document.tree[0].attributes["controlCountConsistent"] is True
    assert all(node.attributes["controlCountConsistent"] for node in _nodes(document, KIND_MESSAGE))
    assert WARNING_CONTROL_COUNT_MISMATCH not in _codes(document)


def test_self_inconsistent_transmission_is_visibly_so():
    text = _transmission(*_HEADER, "MHD=1+ORDERS:9'", "ORD=PO-1'", "MTR=9'", "END=4'")
    document = analyze_tradacoms(parse_tradacoms(text))
    mismatches = [w for w in document.warnings if w.code == WARNING_CONTROL_COUNT_MISMATCH]
    assert len(mismatches) == 2
    assert document.status == STATUS_AVAILABLE
    message = _nodes(document, KIND_MESSAGE)[0]
    assert message.attributes["declaredSegmentCount"] == 9
    assert message.attributes["envelopeSegmentCount"] == 3


def test_canonical_subset_is_stated_across_transmissions():
    document = analyze_tradacoms(parse_tradacoms(_TWO_TRANSMISSIONS))
    (subset,) = [w for w in document.warnings if w.code == WARNING_CANONICAL_SUBSET]
    assert "message ORDERS (2) in file ORDHDR" in subset.message
    assert "This document carries 7 message(s) across 2 file(s) in 2 transmissions" in subset.message
    assert len(document.tree) == 2


def test_message_outside_the_tradacoms_set_is_named():
    text = _transmission(*_HEADER, "MHD=1+PRIHDR:9'", "TYP=0200+PRICES'", "MTR=3'", "END=1'")
    document = analyze_tradacoms(parse_tradacoms(text))
    assert "tradacoms.message_outside_profile_set" in _codes(document)
    assert _nodes(document, KIND_MESSAGE)[0].attributes["inProfileMessageSet"] is False


def test_recipient_reference_is_not_an_attribute():
    document = analyze_tradacoms(parse_tradacoms(_MULTI))
    for node in document.tree:
        assert "PASSWORD" not in node.attributes.values()


def test_values_stay_in_value_and_visibility_governs_them():
    document = analyze_tradacoms(parse_tradacoms(_MINIMAL))
    leaves = [node for node in _nodes(document, "element") if node.value]
    assert any(node.value == "PO-0001" for node in leaves)
    withheld = apply_value_visibility(document, ValueVisibility.DEFAULT)
    assert all(node.value is None for node in _nodes(withheld, "element"))


def test_budget_keeps_every_envelope_node():
    document = analyze_tradacoms(parse_tradacoms(_TWO_TRANSMISSIONS), max_nodes=1)
    assert len(_nodes(document, KIND_MESSAGE)) == 7
    assert len(_nodes(document, KIND_FILE)) == 2


def test_adapter_analyze_and_capabilities(adapter: TradacomsImportSource):
    document = adapter.analyze(adapter.parse(_MINIMAL))
    assert document.source_format == "tradacoms"
    capabilities = adapter.analysis_capabilities()
    assert "tradacoms.dialect_profile" in capabilities.supported
    assert "tradacoms.message_specification_validation" in capabilities.unsupported
    with pytest.raises(ImportSourceError):
        adapter.analyze(object())


# ---------------------------------------------------------------------------
# Provenance and the capability panel
# ---------------------------------------------------------------------------


def test_format_profile_metadata_is_lifted_from_extras(adapter: TradacomsImportSource):
    model = adapter.normalize(adapter.parse(_MINIMAL), include_raw=False)
    assert format_profile_metadata(model)["key"] == "tradacoms"
    bare = model.model_copy(update={"extras": {}})
    malformed = model.model_copy(update={"extras": {PROFILE_EXTRAS_KEY: {"label": "x"}}})
    assert format_profile_metadata(bare) is None
    assert format_profile_metadata(malformed) is None
    assert isinstance(model, CanonicalApi)


def test_tradacoms_capability_entry_names_the_profile_and_its_boundaries():
    entry = capability_for("tradacoms")
    assert entry.native_hierarchy is NativeHierarchy.NATIVE
    assert entry.source_location.quality is SourceLocationQuality.BYTE_OFFSETS
    assert TRADACOMS_IMPLEMENTATION_GUIDE_STATEMENT in entry.notes
    assert profile_statement(TRADACOMS) in entry.notes
    assert any("format mismatch" in note for note in entry.notes)


def test_edifact_capability_entry_names_both_dialect_profiles():
    notes = capability_for("edifact").notes
    assert profile_statement(EANCOM) in notes
    assert profile_statement(ODETTE) in notes
