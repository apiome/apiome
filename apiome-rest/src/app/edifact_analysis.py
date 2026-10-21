"""UN/EDIFACT native-analysis extractor — FMT-6.1 (#5445).

The EDIFACT canonical normalizer (:mod:`app.edifact_normalizer`) reads the first functional group's
first message and normalizes that one message into types, exactly as the X12 normalizer reads one
transaction set. This extractor is where the rest of the interchange survives: it walks **every**
functional group and **every** message, in source order, and describes them in EDIFACT's own
vocabulary:

.. code-block:: text

    interchange            UNB — syntax, service characters (UNA or defaults), parties, controls
      functional_group     UNG — group id, application parties, controlling agency, message version
        message            UNH — type (ORDERS/INVOIC/…), directory (D:96A), association code
          segment          BGM, NAD, LIN … in position order, with its repeat index
            element        BGM01 … with its position, presence and length
              repetition   NAD02[0] … only where a syntax-4 repetition separator split the value
            composite      DTM01 — with its component sub-elements

An interchange without functional groups has its messages directly under the interchange.

The honesty contract — the X12 analyzer's, exactly
--------------------------------------------------
This module keeps the contract :mod:`app.edix12_analysis` set, through the shared
:mod:`app.edi_analysis_base`:

**Every group and message is kept.** The node budget is raised to fit every envelope node, so a
bounded analysis drops elements, never envelopes.

**Declared versus observed.** ``UNT``, ``UNE`` and ``UNZ`` each declare a control count and repeat
the control reference of the header they close. Both declarations are recorded beside what was
observed, and every disagreement is also stated as a warning, so a self-inconsistent interchange is
visibly so — it is *read*, not rejected, because the counts are a claim about the payload rather
than the payload.

**Present-and-empty is not absent.** An element position the source wrote and left empty is a node
with ``value_present`` true and ``value_length`` zero; a position the source never wrote is not a
node at all. Together with the value-visibility policy (which decides whether a value is kept or
*withheld*) and an analysis that never recorded a position (*not recorded*), that is the five-way
presence vocabulary every EDI inspector renders.

**Business values stay in ``value``.** Envelope identity, delimiters, control counts, positions and
repeat counts are *structure* and sit in ``attributes``. Every observed element, component and
repetition value sits in ``value``, which :func:`~app.payload_analysis.apply_value_visibility`
governs. The ``UNB``/``UNG`` passwords are never lifted into attributes.

**Positions are always checked.** The parser reads the text itself (it is not a library over the
bytes), so every segment carries the exact offset, length, line and column it was read from — there
is no second reading to disagree with.

Limits, stated rather than implied
----------------------------------
No implementation guide or directory (D.96A, D.01B, EANCOM, ODETTE…) is consulted at any point:
segment groups are described as the flat segments they are, not as the nesting a directory would
give them, code values are not looked up, and a message's directory and association code are the
sender's claim. This record describes what the interchange *said*, never whether it was allowed to
say it.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

from .edi_analysis_base import (
    ControlCount,
    canonical_subset_warning,
    control_count_warnings,
    envelope_node_budget,
    implementation_guide_statement,
    int_or_none,
    observed_value_node,
    segment_location,
)
from .edifact_normalizer import canonical_message
from .edifact_parser import (
    EdifactDelimiters,
    EdifactDocument,
    EdifactElement,
    EdifactFunctionalGroup,
    EdifactInterchange,
    EdifactMessage,
    EdifactSegment,
)
from .payload_analysis import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    SEVERITY_INFO,
    AnalysisWarning,
    AnalyzerCapabilities,
    AnalyzerInfo,
    PayloadAnalysisDocument,
    analyzer_capabilities,
)
from .payload_analyzer import NativeNode, analysis_limits, build_analysis_document

__all__ = [
    "EDIFACT_ANALYZER_KEY",
    "EDIFACT_ANALYZER_VERSION",
    "EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT",
    "KIND_COMPONENT",
    "KIND_COMPOSITE",
    "KIND_ELEMENT",
    "KIND_FUNCTIONAL_GROUP",
    "KIND_INTERCHANGE",
    "KIND_MESSAGE",
    "KIND_REPETITION",
    "KIND_SEGMENT",
    "WARNING_CANONICAL_SUBSET",
    "WARNING_CONTROL_COUNT_MISMATCH",
    "WARNING_CONTROL_REFERENCE_MISMATCH",
    "WARNING_UNSPECIFIED_SYNTAX_VERSION",
    "analyze_edifact",
    "edifact_capabilities",
]

#: Analyzer key recorded on every record this module produces.
EDIFACT_ANALYZER_KEY = "edifact"
#: Version of this extractor.
EDIFACT_ANALYZER_VERSION = "1.0.0"

#: The EDIFACT envelope, in nesting order. The leaf kinds are X12's, on purpose: an element is an
#: element in both syntaxes, and an inspector should not need two words for it.
KIND_INTERCHANGE = "interchange"
KIND_FUNCTIONAL_GROUP = "functional_group"
KIND_MESSAGE = "message"
KIND_SEGMENT = "segment"
KIND_ELEMENT = "element"
KIND_COMPOSITE = "composite"
KIND_COMPONENT = "component"
#: One occurrence of an element a syntax-4 repetition separator split. Emitted only where the
#: interchange has such a separator *and* the value carries it.
KIND_REPETITION = "repetition"

#: Emitted when the canonical projection describes less of the interchange than the analysis does.
WARNING_CANONICAL_SUBSET = "edifact.canonical_projection_subset"
#: Emitted for every ``UNT``/``UNE``/``UNZ`` control count that disagrees with what was observed.
WARNING_CONTROL_COUNT_MISMATCH = "edifact.control_count_mismatch"
#: Emitted for every trailer whose control reference does not repeat its header's.
WARNING_CONTROL_REFERENCE_MISMATCH = "edifact.control_reference_mismatch"
#: Emitted when ``UNB`` names no syntax version, so the repetition separator could not be settled.
WARNING_UNSPECIFIED_SYNTAX_VERSION = "edifact.syntax_version_unspecified"

#: The statement the capability declaration and the format registry both carry.
EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT = implementation_guide_statement(
    "UN/EDIFACT syntax (ISO 9735)", ("D.96A", "D.01B", "EANCOM", "ODETTE")
)

#: ``UNB`` 0035 — the test indicator. Only ``1`` is defined; anything else is reported verbatim.
_TEST_INDICATORS = {"1": "Test"}


def edifact_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """Return what this extractor models, and what it knowingly does not.

    Unlike X12, the per-record and format-wide answers are the same: the parser reads the text
    itself, so source positions and empty positions are available for every interchange it accepts.

    Args:
        max_nodes: The node budget the record was produced under — recorded because
            :func:`analyze_edifact` raises it to fit every envelope node.

    Returns:
        The :class:`~app.payload_analysis.AnalyzerCapabilities` for an EDIFACT analysis.
    """
    return analyzer_capabilities(
        supported=[
            "edifact.service_string_advice",
            "edifact.interchange_envelope",
            "edifact.functional_group",
            "edifact.message",
            "edifact.segment",
            "edifact.element",
            "edifact.composite_elements",
            "edifact.repeating_elements",
            "edifact.empty_elements",
            "edifact.delimiters",
            "edifact.release_character",
            "edifact.control_references",
            "edifact.envelope_control_totals",
            "edifact.segment_ordinals",
            "edifact.segment_repeat_counts",
            "edifact.byte_offsets",
        ],
        unsupported=[
            # Segment groups are a directory concept; without one they are flat segments.
            "edifact.segment_groups",
            # No directory or implementation guide (D.96A, D.01B, EANCOM…) is consulted.
            "edifact.implementation_guide_validation",
            "edifact.code_list_validation",
            # Interactive EDIFACT (UIB/UIH), packages (UNO/UNP) and multi-interchange files.
            "edifact.interactive_messages",
            "edifact.packages",
            "edifact.multiple_interchanges",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


# ===========================================================================
# Node construction
# ===========================================================================


def _component_nodes(
    components: Sequence[str], *, parent_path: str, reference: str
) -> List[NativeNode]:
    """Describe one composite occurrence's components, empty ones included."""
    return [
        observed_value_node(
            kind=KIND_COMPONENT,
            name=f"{reference}-{index + 1}",
            ordinal=index,
            attributes={"position": f"{index + 1:02d}", "reference": f"{reference}-{index + 1}"},
            path=f"{parent_path}/{reference}-{index + 1}",
            value=component,
        )
        for index, component in enumerate(components)
    ]


def _repetition_node(
    occurrence: Tuple[str, ...], *, index: int, reference: str, path: str
) -> NativeNode:
    """Describe one occurrence of a repeated element — a value, or a composite of components."""
    name = f"{reference}[{index}]"
    occurrence_path = f"{path}[{index}]"
    attributes: Dict[str, object] = {"repeatIndex": index}
    if len(occurrence) > 1:
        return NativeNode(
            kind=KIND_REPETITION,
            name=name,
            ordinal=index,
            attributes={**attributes, "componentCount": len(occurrence)},
            location=segment_location(None, ordinal=index, path=occurrence_path),
            children=_component_nodes(occurrence, parent_path=occurrence_path, reference=name),
        )
    return observed_value_node(
        kind=KIND_REPETITION,
        name=name,
        ordinal=index,
        attributes=attributes,
        path=occurrence_path,
        value=occurrence[0],
    )


def _element_node(element: EdifactElement, *, segment_tag: str, segment_path: str) -> NativeNode:
    """Describe one element position: a value, a composite, or a repeated element."""
    position = f"{element.position:02d}"
    reference = f"{segment_tag}{position}"
    path = f"{segment_path}/{reference}"
    ordinal = element.position - 1
    attributes: Dict[str, object] = {"position": position, "reference": reference}

    if element.is_repeated:
        return NativeNode(
            kind=KIND_ELEMENT,
            name=reference,
            label=f"{reference} ×{len(element.repetitions)}",
            ordinal=ordinal,
            attributes={**attributes, "repeatCount": len(element.repetitions)},
            location=segment_location(None, ordinal=ordinal, path=path),
            children=[
                _repetition_node(occurrence, index=index, reference=reference, path=path)
                for index, occurrence in enumerate(element.repetitions)
            ],
        )
    if element.is_composite:
        return NativeNode(
            kind=KIND_COMPOSITE,
            name=reference,
            ordinal=ordinal,
            attributes={**attributes, "componentCount": len(element.components)},
            location=segment_location(None, ordinal=ordinal, path=path),
            children=_component_nodes(element.components, parent_path=path, reference=reference),
        )
    return observed_value_node(
        kind=KIND_ELEMENT,
        name=reference,
        ordinal=ordinal,
        attributes=attributes,
        path=path,
        value=element.value,
    )


def _has_value(element: EdifactElement) -> bool:
    """Whether any occurrence of the element carried a non-empty component."""
    return any(component for occurrence in element.repetitions for component in occurrence)


def _segment_node(
    segment: EdifactSegment,
    *,
    ordinal: int,
    message_path: str,
    repeat_index: int,
    repeat_count: int,
) -> NativeNode:
    """Describe one body segment, its repeat position and its elements.

    ``elementPositionCount`` is every position the segment wrote; ``elementCount`` is how many of
    them carried a value. The two differ on any segment with an empty position, and both are kept.
    """
    path = f"{message_path}/{segment.tag}[{ordinal}]"
    attributes: Dict[str, object] = {
        "segmentId": segment.tag,
        "elementCount": sum(1 for element in segment.elements if _has_value(element)),
        "elementPositionCount": len(segment.elements),
        "repeatIndex": repeat_index,
        "repeatCount": repeat_count,
    }
    return NativeNode(
        kind=KIND_SEGMENT,
        name=segment.tag,
        label=f"{segment.tag} ({repeat_index + 1} of {repeat_count})" if repeat_count > 1 else None,
        ordinal=ordinal,
        attributes=attributes,
        location=segment_location(segment, ordinal=ordinal, path=path),
        children=lambda: [
            _element_node(element, segment_tag=segment.tag, segment_path=path)
            for element in segment.elements
        ],
    )


def _set_if(attributes: Dict[str, object], name: str, value: str) -> None:
    """Record ``value`` under ``name`` only when the source wrote one."""
    text = value.strip()
    if text:
        attributes[name] = text


def _message_controls(message: EdifactMessage) -> ControlCount:
    """``UNT`` 0074 — segments from ``UNH`` to ``UNT`` inclusive — beside the observed count."""
    return ControlCount(
        subject=f"message {message.reference} ({message.message_type})",
        counted="segments",
        trailer="UNT",
        declared=int_or_none(message.trailer.component(1)),
        observed=len(message.segments) + 2,
    )


def _message_node(message: EdifactMessage, *, ordinal: int, parent_path: str) -> NativeNode:
    """Describe one message, its declared controls and its segments."""
    path = f"{parent_path}/UNH[{ordinal}]"
    controls = _message_controls(message)
    attributes: Dict[str, object] = {
        "messageReference": message.reference,
        "messageType": message.message_type,
        "segmentCount": len(message.segments),
        "envelopeSegmentCount": controls.observed,
    }
    _set_if(attributes, "messageVersion", message.version)
    _set_if(attributes, "messageRelease", message.release)
    _set_if(attributes, "controllingAgency", message.agency)
    # The association code (EAN008, …) names the guide the sender claims to follow. Recorded as a
    # claim; nothing here checks the message against that guide.
    _set_if(attributes, "associationCode", message.association)
    _set_if(attributes, "commonAccessReference", message.header.component(3))
    if controls.declared is not None:
        attributes["declaredSegmentCount"] = controls.declared
        attributes["controlCountConsistent"] = controls.consistent
    trailer_reference = message.trailer.component(2)
    if trailer_reference:
        attributes["trailerControlReference"] = trailer_reference
        attributes["controlReferenceConsistent"] = trailer_reference == message.reference

    totals = Counter(segment.tag for segment in message.segments)
    seen: Counter = Counter()
    repeats: List[int] = []
    for segment in message.segments:
        repeats.append(seen[segment.tag])
        seen[segment.tag] += 1

    return NativeNode(
        kind=KIND_MESSAGE,
        name=message.message_type,
        label=f"Message {message.message_type} ({message.reference})",
        ordinal=ordinal,
        attributes=attributes,
        location=segment_location(message.header, ordinal=ordinal, path=path),
        children=lambda: [
            _segment_node(
                segment,
                ordinal=index,
                message_path=path,
                repeat_index=repeats[index],
                repeat_count=totals[segment.tag],
            )
            for index, segment in enumerate(message.segments)
        ],
    )


def _group_controls(group: EdifactFunctionalGroup) -> ControlCount:
    """``UNE`` 0060 — messages in the group — beside the observed count."""
    return ControlCount(
        subject=f"functional group {group.reference} ({group.group_id})",
        counted="messages",
        trailer="UNE",
        declared=int_or_none(group.trailer.component(1)),
        observed=len(group.messages),
    )


def _group_node(group: EdifactFunctionalGroup, *, ordinal: int) -> NativeNode:
    """Describe one functional group, its declared controls and its messages."""
    path = f"UNB/UNG[{ordinal}]"
    header = group.header
    controls = _group_controls(group)
    attributes: Dict[str, object] = {
        "groupId": group.group_id,
        "groupReference": group.reference,
        "messageCount": len(group.messages),
    }
    _set_if(attributes, "senderId", group.sender)
    _set_if(attributes, "senderQualifier", header.component(2, 2))
    _set_if(attributes, "recipientId", group.recipient)
    _set_if(attributes, "recipientQualifier", header.component(3, 2))
    _set_if(attributes, "date", header.component(4, 1))
    _set_if(attributes, "time", header.component(4, 2))
    _set_if(attributes, "controllingAgency", group.agency)
    _set_if(attributes, "messageVersion", header.component(7, 1))
    _set_if(attributes, "messageRelease", header.component(7, 2))
    _set_if(attributes, "associationCode", header.component(7, 3))
    if controls.declared is not None:
        attributes["declaredMessageCount"] = controls.declared
        attributes["controlCountConsistent"] = controls.consistent
    trailer_reference = group.trailer.component(2)
    if trailer_reference:
        attributes["trailerControlReference"] = trailer_reference
        attributes["controlReferenceConsistent"] = trailer_reference == group.reference

    return NativeNode(
        kind=KIND_FUNCTIONAL_GROUP,
        name=group.group_id,
        label=f"Functional group {group.group_id} ({group.reference})",
        ordinal=ordinal,
        attributes=attributes,
        location=segment_location(header, ordinal=ordinal, path=path),
        children=lambda: [
            _message_node(message, ordinal=index, parent_path=path)
            for index, message in enumerate(group.messages)
        ],
    )


def _interchange_controls(interchange: EdifactInterchange) -> ControlCount:
    """``UNZ`` 0036 — groups when the interchange uses them, else messages — beside the observed."""
    grouped = bool(interchange.functional_groups)
    return ControlCount(
        subject=f"interchange {interchange.control_reference}",
        counted="functional groups" if grouped else "messages",
        trailer="UNZ",
        declared=int_or_none(interchange.trailer.component(1)),
        observed=len(interchange.functional_groups) if grouped else len(interchange.messages),
    )


def _delimiter_attributes(delimiters: EdifactDelimiters) -> Dict[str, object]:
    """The service characters, and whether ``UNA`` declared them or the defaults applied."""
    attributes: Dict[str, object] = {
        "serviceStringAdviceDeclared": delimiters.declared,
        "componentSeparator": delimiters.component,
        "elementSeparator": delimiters.element,
        "decimalMark": delimiters.decimal,
        "segmentTerminator": delimiters.segment,
        # No release character is a different fact from a release character nobody used.
        "releaseCharacterDeclared": delimiters.release is not None,
        # Before syntax version 4 there is no repetition separator at all — the flag says which of
        # "none exists" and "one exists and nothing repeated" is true here.
        "repetitionSeparatorDeclared": delimiters.repetition is not None,
    }
    if delimiters.release is not None:
        attributes["releaseCharacter"] = delimiters.release
    if delimiters.repetition is not None:
        attributes["repetitionSeparator"] = delimiters.repetition
    return attributes


def _interchange_node(interchange: EdifactInterchange) -> NativeNode:
    """Describe the interchange envelope, its service characters and its groups or messages.

    Envelope identifiers, the service characters and the declared controls sit in ``attributes``:
    they are the interchange's *structure*, they are what the canonical model records in its
    ``edifact_envelope`` extras, and a renderer needs them to label the tree at all. ``UNB`` 0022
    (the recipient's reference/password) is deliberately not among them.
    """
    controls = _interchange_controls(interchange)
    header = interchange.header
    grouped = bool(interchange.functional_groups)
    attributes: Dict[str, object] = {
        "syntaxIdentifier": interchange.syntax_identifier,
        "syntaxVersion": interchange.syntax_version,
        "senderId": interchange.sender_id,
        "recipientId": interchange.recipient_id,
        "controlReference": interchange.control_reference,
        "functionalGroupCount": len(interchange.functional_groups),
        "messageCount": sum(1 for _ in interchange.all_messages()),
        **_delimiter_attributes(interchange.delimiters),
    }
    _set_if(attributes, "senderQualifier", interchange.sender_qualifier)
    _set_if(attributes, "recipientQualifier", interchange.recipient_qualifier)
    _set_if(attributes, "date", interchange.date)
    _set_if(attributes, "time", interchange.time)
    _set_if(attributes, "applicationReference", interchange.application_reference)
    _set_if(attributes, "processingPriority", header.component(8))
    _set_if(attributes, "acknowledgementRequested", header.component(9))
    _set_if(attributes, "agreementIdentifier", header.component(10))
    if interchange.test_indicator.strip():
        attributes["testIndicator"] = interchange.test_indicator.strip()
        attributes["testIndicatorLabel"] = _TEST_INDICATORS.get(
            interchange.test_indicator.strip(), "Unrecognised code"
        )
    if controls.declared is not None:
        attributes[
            "declaredFunctionalGroupCount" if grouped else "declaredMessageCount"
        ] = controls.declared
        attributes["controlCountConsistent"] = controls.consistent
    trailer_reference = interchange.trailer.component(2)
    if trailer_reference:
        attributes["trailerControlReference"] = trailer_reference
        attributes["controlReferenceConsistent"] = (
            trailer_reference == interchange.control_reference
        )

    def children() -> List[NativeNode]:
        """Realise the groups, or the messages carried directly."""
        if grouped:
            return [
                _group_node(group, ordinal=index)
                for index, group in enumerate(interchange.functional_groups)
            ]
        return [
            _message_node(message, ordinal=index, parent_path="UNB")
            for index, message in enumerate(interchange.messages)
        ]

    return NativeNode(
        kind=KIND_INTERCHANGE,
        name="UNB",
        label=f"Interchange {interchange.control_reference}",
        ordinal=0,
        attributes=attributes,
        location=segment_location(header, ordinal=0, path="UNB"),
        children=children,
    )


# ===========================================================================
# Warnings
# ===========================================================================


def _envelope_node_count(interchange: EdifactInterchange) -> int:
    """Count the interchange/group/message nodes an analysis must keep."""
    return 1 + len(interchange.functional_groups) + sum(1 for _ in interchange.all_messages())


def _control_counts(interchange: EdifactInterchange) -> List[ControlCount]:
    """Every control count, innermost first in source order: messages, then groups, then UNZ."""
    counts: List[ControlCount] = []
    for group in interchange.functional_groups:
        counts.extend(_message_controls(message) for message in group.messages)
        counts.append(_group_controls(group))
    counts.extend(_message_controls(message) for message in interchange.messages)
    counts.append(_interchange_controls(interchange))
    return counts


def _reference_warnings(interchange: EdifactInterchange) -> List[AnalysisWarning]:
    """Name every trailer whose control reference does not repeat its header's."""
    pairs: List[Tuple[str, str, str, str]] = []
    for group in interchange.functional_groups:
        for message in group.messages:
            pairs.append(("UNT", message.trailer.component(2), "UNH", message.reference))
        pairs.append(("UNE", group.trailer.component(2), "UNG", group.reference))
    for message in interchange.messages:
        pairs.append(("UNT", message.trailer.component(2), "UNH", message.reference))
    pairs.append(
        ("UNZ", interchange.trailer.component(2), "UNB", interchange.control_reference)
    )
    return [
        AnalysisWarning(
            code=WARNING_CONTROL_REFERENCE_MISMATCH,
            severity=SEVERITY_INFO,
            message=(
                f"{trailer} carries control reference {declared!r}, but the {header} it closes "
                f"declared {expected!r}. Both are recorded."
            ),
        )
        for trailer, declared, header, expected in pairs
        if declared and declared != expected
    ]


def _canonical_subset_warnings(document: EdifactDocument) -> List[AnalysisWarning]:
    """State when the canonical model read one message of several."""
    interchange = document.interchange
    observed = sum(1 for _ in interchange.all_messages())
    group, message = canonical_message(document)
    derived_from = f"message {message.message_type} ({message.reference})"
    if group is not None:
        derived_from += f" in functional group {group.group_id} ({group.reference})"
    groups = len(interchange.functional_groups)
    return canonical_subset_warning(
        code=WARNING_CANONICAL_SUBSET,
        derived_from=derived_from,
        observed=observed,
        unit="message",
        scope=f" across {groups} functional group(s)" if groups else "",
    )


def _syntax_warnings(interchange: EdifactInterchange) -> List[AnalysisWarning]:
    """Note an interchange that names no syntax version, so repetition could not be settled."""
    if interchange.syntax_version.strip():
        return []
    return [
        AnalysisWarning(
            code=WARNING_UNSPECIFIED_SYNTAX_VERSION,
            severity=SEVERITY_INFO,
            message=(
                "UNB names no syntax version, so no repetition separator was applied: a value "
                "containing the syntax-4 separator is read as one occurrence."
            ),
        )
    ]


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_edifact(
    document: EdifactDocument,
    *,
    source: Optional[str] = None,
    source_format: str = EDIFACT_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed EDIFACT interchange as a payload analysis.

    Args:
        document: The parsed interchange (:func:`app.edifact_parser.parse_edifact`).
        source: The exact interchange text analysed, hashed into ``source_hash``. Defaults to the
            document's own retained ``raw`` text — the text the positions were read from.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget. Raised, if smaller, to fit every envelope node.
        max_depth: Depth budget; the envelope is at most eight levels deep, so the default is ample.

    Returns:
        The analysis document, with observed element values still on it —
        :func:`app.payload_analysis_store.store_analysis` applies the value-visibility policy.
    """
    interchange = document.interchange
    text = source if source is not None else document.raw
    effective_nodes = envelope_node_budget(max_nodes, _envelope_node_count(interchange))

    warnings = (
        _canonical_subset_warnings(document)
        + control_count_warnings(WARNING_CONTROL_COUNT_MISMATCH, _control_counts(interchange))
        + _reference_warnings(interchange)
        + _syntax_warnings(interchange)
    )

    return build_analysis_document(
        roots=[_interchange_node(interchange)],
        analyzer=AnalyzerInfo(key=EDIFACT_ANALYZER_KEY, version=EDIFACT_ANALYZER_VERSION),
        capabilities=edifact_capabilities(max_nodes=effective_nodes),
        source=text,
        source_format=source_format,
        warnings=warnings,
        max_nodes=effective_nodes,
        max_depth=max_depth,
    )
