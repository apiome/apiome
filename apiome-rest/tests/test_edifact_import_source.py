"""Tests for the UN/EDIFACT import adapter — FMT-6.1 (#5445).

Covers the parser (service string advice, defaults, release characters, repetition, positions and
every refusal code), detection, the canonical normalizer (first group's first message), the native
analysis (hierarchy, declared-versus-observed controls, presence, value visibility), the adapter
seam, the shared EDI analysis base and the reviewed capability entry. Corpus-wide behaviour (every
fixture imports or rejects with its declared code, goldens) is asserted by the corpus suites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.edi_analysis_base import (
    ControlCount,
    canonical_subset_warning,
    control_count_warnings,
    envelope_node_budget,
    implementation_guide_statement,
    int_or_none,
    observed_value_node,
)
from app.edifact_analysis import (
    EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT,
    KIND_COMPONENT,
    KIND_COMPOSITE,
    KIND_ELEMENT,
    KIND_FUNCTIONAL_GROUP,
    KIND_INTERCHANGE,
    KIND_MESSAGE,
    KIND_REPETITION,
    KIND_SEGMENT,
    WARNING_CANONICAL_SUBSET,
    WARNING_CONTROL_COUNT_MISMATCH,
    WARNING_CONTROL_REFERENCE_MISMATCH,
    WARNING_UNSPECIFIED_SYNTAX_VERSION,
    analyze_edifact,
    edifact_capabilities,
)
from app.edifact_import_source import EdifactImportSource
from app.edifact_normalizer import EdifactNormalizer, element_values
from app.edifact_parser import (
    DEFAULT_DELIMITERS,
    EdifactParseError,
    is_edifact,
    parse_edifact,
)
from app.fileset import IntakeFileset
from app.format_capability_registry import (
    CapabilityProvenance,
    NativeHierarchy,
    ProjectionCoverage,
    SourceLocationQuality,
    capability_for,
)
from app.import_source import DetectionInput, ImportSourceError, get_import_source
from app.payload_analysis import STATUS_AVAILABLE, ValueVisibility, apply_value_visibility

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "edifact"


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_MINIMAL = _fixture("01-minimal-orders-d96a.edi")
_INVOIC = _fixture("02-typical-invoic-d96a.edi")
_MULTI = _fixture("04-stress-multi-message-group.edi")
_MISMATCH = _fixture("07-stress-control-count-mismatch.edi")


def _interchange(*segments: str, una: str = "") -> str:
    """Assemble a one-segment-per-line interchange."""
    return una + "\n".join(segments) + "\n"


def _walk(node: Any) -> List[Any]:
    """Every node of an analysis tree, depth first."""
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk(child))
    return nodes


def _nodes(document: Any, kind: str) -> List[Any]:
    return [node for root in document.tree for node in _walk(root) if node.kind == kind]


def _codes(document: Any) -> List[str]:
    return [warning.code for warning in document.warnings]


@pytest.fixture()
def adapter() -> EdifactImportSource:
    return EdifactImportSource()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_is_edifact_recognises_both_header_forms():
    assert is_edifact(_MINIMAL)
    assert is_edifact(_INVOIC)
    assert is_edifact("\n\n  " + _MINIMAL)


@pytest.mark.parametrize(
    "text",
    [
        "ISA*00*          *00*~GS*PO~ST*850*0001~",
        "This file mentions UNB+UNOC and UNH+1 in prose.",
        '{"openapi": "3.0.0"}',
        "UNA:+",
        "UNBX+UNOC:3",
        "U\x00N\x00B\x00+\x00",
        "",
    ],
)
def test_is_edifact_refuses_lookalikes(text: str):
    assert not is_edifact(text)


def test_detect_scores_messages_above_a_bare_header(adapter: EdifactImportSource):
    full = adapter.detect(DetectionInput(text=_MINIMAL, filename="x.edi"))
    bare = adapter.detect(
        DetectionInput(text=_interchange("UNB+UNOC:3+A+B+260101:0000+1'", "UNZ+0+1'"))
    )
    assert full.matched and full.confidence == pytest.approx(0.95)
    assert bare.matched and bare.confidence == pytest.approx(0.7)
    assert full.format == bare.format == "edifact"


def test_detect_never_claims_x12(adapter: EdifactImportSource):
    x12 = (_EXAMPLES / "negative" / "04-wrong-format-x12.edi").read_text(encoding="utf-8")
    assert not adapter.detect(DetectionInput(text=x12, filename="po.edi")).matched


def test_adapter_is_registered():
    registered = get_import_source("edifact")
    assert isinstance(registered, EdifactImportSource)
    assert registered.paradigm is ApiParadigm.DATA_SCHEMA
    assert ".edifact" in registered.file_extensions


# ---------------------------------------------------------------------------
# Parser — delimiters
# ---------------------------------------------------------------------------


def test_defaults_apply_without_una():
    delimiters = parse_edifact(_MINIMAL).interchange.delimiters
    assert delimiters == DEFAULT_DELIMITERS
    assert not delimiters.declared
    assert delimiters.repetition is None


def test_una_declared_characters_are_honoured():
    text = _interchange(
        "UNB|UNOC;3|SENDER;14|RECEIVER;14|260101;0000|42~",
        "UNH|1|ORDERS;D;96A;UN~",
        "FTX|AAI||| one !| two !~ three!! four~",
        "UNT|3|1~",
        "UNZ|1|42~",
        una="UNA;|,! ~",
    )
    interchange = parse_edifact(text).interchange
    delimiters = interchange.delimiters
    assert delimiters.declared
    assert (delimiters.component, delimiters.element, delimiters.decimal) == (";", "|", ",")
    assert (delimiters.release, delimiters.segment) == ("!", "~")
    ftx = interchange.messages[0].segments[0]
    assert ftx.elements[3].value == " one | two ~ three! four"
    assert interchange.sender_id == "SENDER" and interchange.sender_qualifier == "14"


def test_comma_decimal_and_release_from_corpus():
    message = parse_edifact(_MULTI).interchange.functional_groups[0].messages[0]
    assert parse_edifact(_MULTI).interchange.delimiters.decimal == ","
    ftx = next(segment for segment in message.segments if segment.tag == "FTX")
    assert ftx.elements[3].value == "Delivery window is firm, do not split"


def test_release_character_escapes_the_segment_terminator():
    text = _interchange(
        "UNB+UNOC:3+A+B+260101:0000+1'",
        "UNH+1+ORDERS:D:96A:UN'",
        "FTX+AAI+++It?'s here?+now?:ok'",
        "UNT+3+1'",
        "UNZ+1+1'",
    )
    ftx = parse_edifact(text).interchange.messages[0].segments[0]
    assert ftx.elements[3].value == "It's here+now:ok"


def test_syntax_version_four_has_a_repetition_separator():
    text = _interchange(
        "UNB+UNOC:4+A+B+260101:0000+1'",
        "UNH+1+ORDERS:D:01B:UN'",
        "NAD+BY+111::9*222::9'",
        "UNT+3+1'",
        "UNZ+1+1'",
    )
    interchange = parse_edifact(text).interchange
    assert interchange.delimiters.repetition == "*"
    nad = interchange.messages[0].segments[0]
    assert nad.elements[1].repetitions == (("111", "", "9"), ("222", "", "9"))


def test_reserved_una_position_does_not_split_before_version_four():
    text = _interchange(
        "UNB+UNOC:3+A+B+260101:0000+1'",
        "UNH+1+ORDERS:D:96A:UN'",
        "FTX+AAI+++a*b'",
        "UNT+3+1'",
        "UNZ+1+1'",
        una="UNA:+.?*'",
    )
    interchange = parse_edifact(text).interchange
    assert interchange.delimiters.repetition is None
    assert interchange.messages[0].segments[0].elements[3].value == "a*b"


def test_level_b_control_character_defaults():
    text = "\x1c".join(
        [
            "UNB\x1dUNOB\x1f3\x1dA\x1dB\x1d260101\x1f0000\x1d1",
            "UNH\x1d1\x1dORDERS\x1fD\x1f96A\x1fUN",
            "BGM\x1d220\x1dPO-1",
            "UNT\x1d3\x1d1",
            "UNZ\x1d1\x1d1",
        ]
    ) + "\x1c"
    interchange = parse_edifact(text).interchange
    assert interchange.delimiters.element == "\x1d"
    assert interchange.messages[0].segments[0].elements[1].value == "PO-1"


def test_empty_positions_are_kept_as_written():
    message = parse_edifact(_MULTI).interchange.functional_groups[0].messages[0]
    empty_lin = [segment for segment in message.segments if segment.tag == "LIN"][1]
    assert [element.value for element in empty_lin.elements] == ["2", "", "", "", ""]


def test_segments_carry_exact_source_positions():
    document = parse_edifact(_INVOIC)
    for message in document.interchange.all_messages():
        for segment in (message.header, *message.segments, message.trailer):
            assert document.raw[segment.offset : segment.offset + segment.length - 1] == segment.raw
            assert document.raw[segment.offset + segment.length - 1] == "'"
    una = document.interchange.service_string_advice
    assert una is not None and (una.line, una.column, una.offset) == (1, 1, 0)
    assert document.interchange.header.line == 2


# ---------------------------------------------------------------------------
# Parser — envelopes
# ---------------------------------------------------------------------------


def test_ungrouped_and_grouped_interchanges():
    minimal = parse_edifact(_MINIMAL).interchange
    assert not minimal.functional_groups
    assert [message.message_type for message in minimal.messages] == ["ORDERS"]
    multi = parse_edifact(_MULTI).interchange
    assert not multi.messages
    assert [len(group.messages) for group in multi.functional_groups] == [2, 1]
    assert [message.reference for message in multi.all_messages()] == ["1", "2", "3"]


def test_message_header_fields():
    message = parse_edifact(_fixture("05-real-world-eancom-orders.edi")).interchange.messages[0]
    assert (message.message_type, message.directory, message.agency) == ("ORDERS", "D:96A", "UN")
    assert message.association == "EAN008"


_GOOD_HEAD = "UNB+UNOC:3+A+B+260101:0000+1'"


@pytest.mark.parametrize(
    ("text", "code", "fragment"),
    [
        (_interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "BGM+220+PO"), "INPUT_TRUNCATED", "mid-segment"),
        (
            _interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "BGM+220'", "UNT+3+1'"),
            "INPUT_TRUNCATED",
            "UNZ",
        ),
        (
            _interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "BGM+220'"),
            "INPUT_TRUNCATED",
            "UNT",
        ),
        (
            _interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "BGM+220", "DTM+137'", "UNT+4+1'", "UNZ+1+1'"),
            "INPUT_MALFORMED",
            "no segment terminator",
        ),
        (_interchange(_GOOD_HEAD, "UNZ+0+1'"), "INPUT_SEMANTIC_INVALID", "no `UNH`"),
        (
            _interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "BGM+220'", "UNZ+1+1'"),
            "INPUT_SEMANTIC_INVALID",
            "no `UNT`",
        ),
        (
            _interchange(_GOOD_HEAD, "BGM+220'", "UNZ+0+1'"),
            "INPUT_SEMANTIC_INVALID",
            "outside any message",
        ),
        (
            _interchange(
                _GOOD_HEAD,
                "UNH+1+ORDERS:D:96A:UN'",
                "UNT+2+1'",
                "UNG+ORDERS+A+B+260101:0000+1+UN+D:96A'",
                "UNE+0+1'",
                "UNZ+2+1'",
            ),
            "INPUT_SEMANTIC_INVALID",
            "mixes",
        ),
        (
            _interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "UNT+2+1'", "UNZ+1+1'", "UNB+UNOC:3+A+B'"),
            "INPUT_SEMANTIC_INVALID",
            "after its `UNZ`",
        ),
        (
            _interchange(_GOOD_HEAD, "UNE+0+1'", "UNZ+0+1'"),
            "INPUT_SEMANTIC_INVALID",
            "closes no functional group",
        ),
        (
            _interchange(_GOOD_HEAD, "UNH+1+ORDERS:D:96A:UN'", "b@d+1'", "UNT+3+1'", "UNZ+1+1'"),
            "INPUT_MALFORMED",
            "segment tag",
        ),
        ("UNA:+.", "INPUT_MALFORMED", "nine characters"),
        ("UNA:::? 'UNB:UNOC'", "INPUT_MALFORMED", "same character"),
    ],
)
def test_refusals_carry_a_taxonomy_code(text: str, code: str, fragment: str):
    if text.startswith("UNA") and len(text) < 9:
        # A short UNA is not even claimed by detection; the parser's own guard is what is tested.
        from app.edifact_parser import _resolve_delimiters

        with pytest.raises(EdifactParseError) as caught:
            _resolve_delimiters(text, 0)
    else:
        with pytest.raises(EdifactParseError) as caught:
            parse_edifact(text)
    assert caught.value.code == code
    assert fragment in str(caught.value)


def test_encoding_faults_are_refused_without_a_code():
    for text in ("﻿" + _MINIMAL, _MINIMAL.replace("BGM", "B\x00M"), _MINIMAL + "�"):
        with pytest.raises(EdifactParseError) as caught:
            parse_edifact(text)
        assert caught.value.code is None


def test_empty_document_is_input_empty():
    with pytest.raises(EdifactParseError) as caught:
        parse_edifact("   \n")
    assert caught.value.code == "INPUT_EMPTY"


def test_adapter_parse_carries_the_code(adapter: EdifactImportSource):
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(_interchange(_GOOD_HEAD, "UNZ+0+1'"))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


def test_parse_fileset_reads_the_root(adapter: EdifactImportSource):
    fileset = IntakeFileset(
        root="orders.edi",
        members={
            "orders.edi": _fixture("09-interchange-set/orders.edi"),
            "contrl.edi": _fixture("09-interchange-set/contrl.edi"),
        },
    )
    document = adapter.parse_fileset(fileset)
    assert document.interchange.messages[0].message_type == "ORDERS"


def test_parse_fileset_without_root_member(adapter: EdifactImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="missing.edi", members={"a.edi": _MINIMAL}))


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def test_normalizer_maps_the_first_message(adapter: EdifactImportSource):
    api = adapter.normalize(adapter.parse(_MINIMAL))
    assert api.format == "edifact"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.title == "EDIFACT ORDERS"
    names = {type_.name for type_ in api.types}
    assert names == {"MessageORDERS", "NAD"}
    message_type = next(type_ for type_ in api.types if type_.name == "MessageORDERS")
    fields = {field.name: field for field in message_type.fields}
    assert fields["BGM02"].default == "PO-0001"
    assert fields["DTM01-2"].default == "20260815"
    # A repeating segment becomes a list of its own record type.
    assert fields["NAD"].type.item is not None
    nad = next(type_ for type_ in api.types if type_.name == "NAD")
    assert nad.kind is TypeKind.RECORD
    assert [field.name for field in nad.fields] == ["NAD01", "NAD02-1", "NAD02-3"]


def test_normalizer_reads_first_group_first_message_and_keeps_siblings_in_extras():
    api = EdifactNormalizer().normalize(parse_edifact(_MULTI))
    assert api.title == "EDIFACT ORDERS"
    envelope = api.extras["edifact_envelope"]
    assert envelope["group_id"] == "ORDERS" and envelope["message_reference"] == "1"
    assert envelope["decimal_mark"] == "," and envelope["service_string_advice"] is True
    assert [item["reference"] for item in api.extras["edifact_messages"]] == ["1", "2"]
    assert api.extras["edifact_directory"] == "D:96A"


def test_normalizer_include_raw_toggle():
    document = parse_edifact(_MINIMAL)
    assert EdifactNormalizer().normalize(document).raw == {"edifact": _MINIMAL}
    assert EdifactNormalizer().normalize(document, include_raw=False).raw is None


def test_normalizer_rejects_foreign_ast(adapter: EdifactImportSource):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "edifact"})


def test_element_values_skip_empty_positions():
    lin = [
        segment
        for segment in parse_edifact(_MULTI).interchange.functional_groups[0].messages[0].segments
        if segment.tag == "LIN"
    ][1]
    assert element_values(lin) == [("LIN01", "2")]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def test_analysis_renders_the_native_hierarchy():
    document = analyze_edifact(parse_edifact(_MULTI))
    assert document.status == STATUS_AVAILABLE
    root = document.tree[0]
    assert root.kind == KIND_INTERCHANGE and root.name == "UNB"
    groups = [child for child in root.children]
    assert [group.kind for group in groups] == [KIND_FUNCTIONAL_GROUP] * 2
    assert [len(group.children) for group in groups] == [2, 1]
    assert {node.kind for node in _walk(root)} >= {
        KIND_MESSAGE,
        KIND_SEGMENT,
        KIND_ELEMENT,
        KIND_COMPOSITE,
        KIND_COMPONENT,
    }
    message = groups[0].children[0]
    assert message.attributes["messageType"] == "ORDERS"
    assert message.location.path == "UNB/UNG[0]/UNH[0]"
    assert message.location.offset is not None and message.location.line == 4


def test_ungrouped_messages_sit_under_the_interchange():
    root = analyze_edifact(parse_edifact(_MINIMAL)).tree[0]
    assert [child.kind for child in root.children] == [KIND_MESSAGE]
    assert root.children[0].location.path == "UNB/UNH[0]"


def test_delimiters_are_recorded_declared_or_default():
    defaults = analyze_edifact(parse_edifact(_MINIMAL)).tree[0].attributes
    assert defaults["serviceStringAdviceDeclared"] is False
    assert defaults["elementSeparator"] == "+" and defaults["releaseCharacter"] == "?"
    assert defaults["repetitionSeparatorDeclared"] is False
    declared = analyze_edifact(parse_edifact(_MULTI)).tree[0].attributes
    assert declared["serviceStringAdviceDeclared"] is True
    assert declared["decimalMark"] == ","


def test_consistent_controls_are_recorded_without_warnings():
    document = analyze_edifact(parse_edifact(_MULTI))
    root = document.tree[0]
    assert root.attributes["declaredFunctionalGroupCount"] == 2
    assert root.attributes["functionalGroupCount"] == 2
    assert root.attributes["controlCountConsistent"] is True
    group = root.children[0]
    assert (group.attributes["declaredMessageCount"], group.attributes["messageCount"]) == (2, 2)
    message = group.children[0]
    assert message.attributes["declaredSegmentCount"] == message.attributes["envelopeSegmentCount"]
    assert WARNING_CONTROL_COUNT_MISMATCH not in _codes(document)


def test_self_inconsistent_interchange_is_visibly_so():
    document = analyze_edifact(parse_edifact(_MISMATCH))
    assert document.status == STATUS_AVAILABLE  # read, not rejected
    root = document.tree[0]
    assert root.attributes["declaredMessageCount"] == 7
    assert root.attributes["messageCount"] == 1
    assert root.attributes["controlCountConsistent"] is False
    message = root.children[0]
    assert message.attributes["declaredSegmentCount"] == 99
    assert message.attributes["envelopeSegmentCount"] == 9
    assert message.attributes["controlCountConsistent"] is False
    mismatches = [w for w in document.warnings if w.code == WARNING_CONTROL_COUNT_MISMATCH]
    assert len(mismatches) == 2
    assert "UNT declares 99 segments" in mismatches[0].message
    assert "9 were observed" in mismatches[0].message
    assert "UNZ declares 7 messages" in mismatches[1].message


def test_control_reference_mismatch_is_stated():
    text = _interchange(
        _GOOD_HEAD,
        "UNH+1+ORDERS:D:96A:UN'",
        "BGM+220'",
        "UNT+3+9'",
        "UNZ+1+2'",
    )
    document = analyze_edifact(parse_edifact(text))
    messages = [w.message for w in document.warnings if w.code == WARNING_CONTROL_REFERENCE_MISMATCH]
    assert len(messages) == 2
    assert "UNT carries control reference '9'" in messages[0]
    assert document.tree[0].attributes["controlReferenceConsistent"] is False


def test_canonical_subset_is_stated_explicitly():
    document = analyze_edifact(parse_edifact(_MULTI))
    subset = [w for w in document.warnings if w.code == WARNING_CANONICAL_SUBSET]
    assert len(subset) == 1
    assert "message ORDERS (1) in functional group ORDERS (1)" in subset[0].message
    assert "3 message(s) across 2 functional group(s)" in subset[0].message
    assert WARNING_CANONICAL_SUBSET not in _codes(analyze_edifact(parse_edifact(_MINIMAL)))


def test_unspecified_syntax_version_is_noted():
    text = _interchange(
        "UNB+UNOC+A+B+260101:0000+1'", "UNH+1+ORDERS:D:96A:UN'", "UNT+2+1'", "UNZ+1+1'"
    )
    assert WARNING_UNSPECIFIED_SYNTAX_VERSION in _codes(analyze_edifact(parse_edifact(text)))


def test_present_empty_elements_are_distinct_from_absent_ones():
    document = analyze_edifact(parse_edifact(_MULTI))
    lin = [node for node in _nodes(document, KIND_SEGMENT) if node.name == "LIN"][1]
    assert lin.attributes["elementPositionCount"] == 5
    assert lin.attributes["elementCount"] == 1
    elements = {child.name: child for child in lin.children}
    assert set(elements) == {"LIN01", "LIN02", "LIN03", "LIN04", "LIN05"}  # nothing past 05
    assert (elements["LIN02"].value_present, elements["LIN02"].value_length) == (True, 0)
    assert (elements["LIN01"].value_present, elements["LIN01"].value_length) == (True, 1)


def test_repetitions_become_occurrence_nodes():
    text = _interchange(
        "UNB+UNOC:4+A+B+260101:0000+1'",
        "UNH+1+ORDERS:D:01B:UN'",
        "NAD+BY+111::9*222'",
        "UNT+3+1'",
        "UNZ+1+1'",
    )
    document = analyze_edifact(parse_edifact(text))
    repeated = next(node for node in _nodes(document, KIND_ELEMENT) if node.name == "NAD02")
    assert repeated.attributes["repeatCount"] == 2
    first, second = repeated.children
    assert first.kind == second.kind == KIND_REPETITION
    assert [child.kind for child in first.children] == [KIND_COMPONENT] * 3
    assert second.value == "222"


def test_segment_repeat_positions_are_counted_per_message():
    document = analyze_edifact(parse_edifact(_MINIMAL))
    nads = [node for node in _nodes(document, KIND_SEGMENT) if node.name == "NAD"]
    assert [(n.attributes["repeatIndex"], n.attributes["repeatCount"]) for n in nads] == [(0, 2), (1, 2)]
    assert nads[1].label == "NAD (2 of 2)"


def test_values_stay_in_value_and_visibility_governs_them():
    document = analyze_edifact(parse_edifact(_MINIMAL))
    # Business values are never attributes.
    for node in (n for root in document.tree for n in _walk(root)):
        assert "PO-0001" not in str(node.attributes)
    structural = apply_value_visibility(document, ValueVisibility.STRUCTURAL)
    values = [n for root in structural.tree for n in _walk(root) if n.value_present]
    assert values and all(n.value is None for n in values)
    assert any(n.redacted for n in values)
    assert all(n.value_length is not None for n in values)
    none = apply_value_visibility(document, ValueVisibility.NONE)
    assert all(n.value_present is None for root in none.tree for n in _walk(root) if n.redacted)


def test_recipient_password_is_not_an_attribute():
    text = _interchange(
        "UNB+UNOC:3+A+B+260101:0000+1+S3CR3T:PW'", "UNH+1+ORDERS:D:96A:UN'", "UNT+2+1'", "UNZ+1+1'"
    )
    attributes: Dict[str, Any] = analyze_edifact(parse_edifact(text)).tree[0].attributes
    assert "S3CR3T" not in str(attributes)


def test_budget_keeps_every_envelope_node():
    document = analyze_edifact(parse_edifact(_MULTI), max_nodes=2)
    assert len(_nodes(document, KIND_MESSAGE)) == 3
    assert len(_nodes(document, KIND_FUNCTIONAL_GROUP)) == 2


def test_adapter_analyze_and_capabilities(adapter: EdifactImportSource):
    document = adapter.analyze(adapter.parse(_MINIMAL), source=_MINIMAL)
    assert document.analyzer.key == "edifact"
    assert document.source_format == "edifact"
    capabilities = adapter.analysis_capabilities()
    assert "edifact.envelope_control_totals" in capabilities.supported
    assert "edifact.implementation_guide_validation" in capabilities.unsupported
    assert not set(capabilities.supported) & set(capabilities.unsupported)
    assert capabilities == edifact_capabilities()
    with pytest.raises(ImportSourceError):
        adapter.analyze({"not": "edifact"})


# ---------------------------------------------------------------------------
# Capability registry — the panel's statement
# ---------------------------------------------------------------------------


def test_capability_entry_states_no_implementation_guide_was_consulted():
    entry = capability_for("edifact")
    assert entry.provenance is CapabilityProvenance.REVIEWED
    assert entry.native_hierarchy is NativeHierarchy.NATIVE
    assert entry.source_location.quality is SourceLocationQuality.BYTE_OFFSETS
    assert entry.canonical_projection.coverage is ProjectionCoverage.PARTIAL
    assert EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT in entry.notes
    for guide in ("D.96A", "D.01B", "EANCOM"):
        assert guide in EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT
    assert "edifact.implementation_guide_validation" in entry.unsupported_constructs
    for construct in ("edifact.functional_group", "edifact.envelope_control_totals"):
        assert construct in entry.canonical_projection.dropped_constructs
        assert construct in entry.supported_constructs
    assert not set(entry.supported_constructs) & set(entry.unsupported_constructs)


# ---------------------------------------------------------------------------
# Shared EDI analysis base
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("12", 12), (" 7 ", 7), ("+3", 3), ("", None), ("x1", None), (None, None)],
)
def test_int_or_none_never_invents_a_zero(text, expected):
    assert int_or_none(text) == expected


def test_control_count_consistency_and_warnings():
    agreeing = ControlCount("m", "segments", "UNT", 5, 5)
    disagreeing = ControlCount("m", "segments", "UNT", 6, 5)
    undeclared = ControlCount("m", "segments", "UNT", None, 5)
    assert (agreeing.consistent, disagreeing.consistent, undeclared.consistent) == (True, False, None)
    warnings = control_count_warnings("x.code", [agreeing, disagreeing, undeclared])
    assert [w.code for w in warnings] == ["x.code"]
    assert warnings[0].severity == "info"


def test_canonical_subset_warning_only_when_more_than_one():
    assert canonical_subset_warning(code="c", derived_from="d", observed=1, unit="message") == []
    [warning] = canonical_subset_warning(
        code="c", derived_from="message X", observed=3, unit="message", scope=" across 2 group(s)"
    )
    assert warning.message.startswith("The canonical model is derived from message X alone.")
    assert "carries 3 message(s) across 2 group(s); the remaining 2" in warning.message


def test_envelope_budget_and_value_node():
    assert envelope_node_budget(10, 3) == 10
    assert envelope_node_budget(2, 30) == 30
    node = observed_value_node(kind="element", name="BGM01", ordinal=0, path="p", value="")
    assert (node.value_present, node.value_length, node.value) == (True, 0, "")
    assert "D.96A" in implementation_guide_statement("syntax", ["D.96A"])


# ---------------------------------------------------------------------------
# Round trip against the emitter (#4146), once both exist
# ---------------------------------------------------------------------------


def test_round_trip_is_asserted_once_the_emitter_exists():
    """The round-trip matrix pairs every importable source with every emitter, so the day #4146
    registers an ``edifact`` emitter the ``edifact -> edifact`` cell appears in it. This pins the
    acceptance criterion: that cell must then *pass*, not be waved through as an xfail."""
    import json

    from roundtrip_xfails import KNOWN_ROUNDTRIP_XFAILS

    from app.emitter import get_emitter

    if get_emitter("edifact") is None:
        pytest.skip("No UN/EDIFACT emitter is registered yet (#4146); the round trip waits on it.")
    matrix = json.loads(
        (Path(__file__).resolve().parent / "golden" / "roundtrip" / "matrix.json").read_text()
    )
    cells = [
        cell
        for cell in matrix["cells"]
        if cell["corpus_path"].startswith("edifact/") and cell["emit_key"] == "edifact"
    ]
    assert cells and all(cell["status"] == "pass" for cell in cells)
    assert ("edifact", "edifact") not in KNOWN_ROUNDTRIP_XFAILS


def test_detect_finds_messages_after_a_declared_terminator(adapter: EdifactImportSource):
    text = "UNA:+.? ~UNB+UNOC:3+A+B+260101:0000+1~UNH+1+ORDERS:D:96A:UN~UNT+2+1~UNZ+1+1~"
    assert adapter.detect(DetectionInput(text=text)).confidence == pytest.approx(0.95)
    assert parse_edifact(text).interchange.messages[0].message_type == "ORDERS"


def test_newline_terminator_with_crlf_line_ends():
    text = "UNA:+.? \nUNB+UNOC:3+A+B+260101:0000+1\r\nUNH+1+ORDERS:D:96A:UN\r\nBGM+220+PO-9\r\nUNT+3+1\r\nUNZ+1+1\r\n"
    interchange = parse_edifact(text).interchange
    assert interchange.delimiters.segment == "\n"
    assert interchange.messages[0].segments[0].elements[1].value == "PO-9"
    assert interchange.trailer.component(2) == "1"
