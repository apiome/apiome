"""TRADACOMS native-analysis extractor — FMT-6.5 (#5449).

The TRADACOMS normalizer (:mod:`app.tradacoms_normalizer`) reads one detail message into types.
This extractor is where the rest of the document survives: it walks **every** transmission, file
and message, in source order, and describes them in TRADACOMS' own vocabulary:

.. code-block:: text

    transmission           STX — syntax, sender/recipient codes, date, references; END's count
      file                 header message type, TYP transaction code, FIL generation/version
        message            MHD — sequence number, type (ORDERS/INVOIC/…), version; MTR's count
          segment          CLO, ORD, OLD … in position order, with its repeat index
            element        OLD01 … with its position, presence and length
            composite      OLD02 — with its component sub-elements

The honesty contract — EDIFACT's, through the same code
-------------------------------------------------------
Segments and elements are EDIFACT's, so they are described by the EDIFACT analysis's own node
builders (:func:`app.edifact_analysis.segment_node`) and the shared :mod:`app.edi_analysis_base`:
every transmission, file and message is kept (the node budget is raised to fit them);
present-and-empty is not absent; business values stay in ``value``, governed by the
value-visibility policy; every segment carries the exact bytes it was read from.

**Declared versus observed.** ``MTR`` declares each message's segment count (``MHD`` to ``MTR``
inclusive) and ``END`` the transmission's message count. Both are recorded beside what was
observed, and every disagreement is stated as an informational warning — read, not rejected.

**The profile.** Every record states it was read with the TRADACOMS dialect profile
(:mod:`app.edi_dialect_profiles`) and that the TRADACOMS manual's message specifications were not
consulted, and every message records whether TRADACOMS' message set names it. The ``STX``
recipient's reference (RCRF, which some trading partners use as a password) is never lifted into
attributes.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from .edi_analysis_base import (
    ControlCount,
    canonical_subset_warning,
    control_count_warnings,
    envelope_node_budget,
    implementation_guide_statement,
    int_or_none,
    segment_location,
)
from .edifact_analysis import KIND_MESSAGE, KIND_SEGMENT, profile_warnings, segment_node
from .payload_analysis import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    AnalysisWarning,
    AnalyzerCapabilities,
    AnalyzerInfo,
    PayloadAnalysisDocument,
    analyzer_capabilities,
)
from .payload_analyzer import NativeNode, analysis_limits, build_analysis_document
from .tradacoms_normalizer import TRADACOMS_PROFILE_MATCH, canonical_message
from .tradacoms_parser import (
    TAG_SEPARATOR,
    TRADACOMS_DELIMITERS,
    TradacomsDocument,
    TradacomsFile,
    TradacomsMessage,
    TradacomsTransmission,
)

__all__ = [
    "KIND_FILE",
    "KIND_MESSAGE",
    "KIND_SEGMENT",
    "KIND_TRANSMISSION",
    "TRADACOMS_ANALYZER_KEY",
    "TRADACOMS_ANALYZER_VERSION",
    "TRADACOMS_IMPLEMENTATION_GUIDE_STATEMENT",
    "WARNING_CANONICAL_SUBSET",
    "WARNING_CONTROL_COUNT_MISMATCH",
    "analyze_tradacoms",
    "tradacoms_capabilities",
]

#: Analyzer key recorded on every record this module produces.
TRADACOMS_ANALYZER_KEY = "tradacoms"
#: Version of this extractor.
TRADACOMS_ANALYZER_VERSION = "1.0.0"

#: The TRADACOMS envelope kinds. ``message``, ``segment`` and the leaf kinds are EDIFACT's.
KIND_TRANSMISSION = "transmission"
KIND_FILE = "file"

#: Emitted when the canonical projection describes less of the document than the analysis does.
WARNING_CANONICAL_SUBSET = "tradacoms.canonical_projection_subset"
#: Emitted for every ``MTR``/``END`` control count that disagrees with what was observed.
WARNING_CONTROL_COUNT_MISMATCH = "tradacoms.control_count_mismatch"

#: The statement the capability declaration and the format registry both carry.
TRADACOMS_IMPLEMENTATION_GUIDE_STATEMENT = implementation_guide_statement(
    "TRADACOMS syntax (STX/MHD/MTR/END envelope over EDIFACT-style segments)",
    ("the TRADACOMS manual's message specifications", "trading-partner guides"),
)


def tradacoms_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """Return what this extractor models, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The :class:`~app.payload_analysis.AnalyzerCapabilities` for a TRADACOMS analysis.
    """
    return analyzer_capabilities(
        supported=[
            "tradacoms.transmission_envelope",
            "tradacoms.multiple_transmissions",
            "tradacoms.file",
            "tradacoms.message",
            "tradacoms.message_sequence",
            "tradacoms.segment",
            "tradacoms.element",
            "tradacoms.composite_elements",
            "tradacoms.empty_elements",
            "tradacoms.release_character",
            "tradacoms.message_control_totals",
            "tradacoms.transmission_control_totals",
            "tradacoms.segment_ordinals",
            "tradacoms.segment_repeat_counts",
            "tradacoms.byte_offsets",
            "tradacoms.dialect_profile",
        ],
        unsupported=[
            # The TRADACOMS manual's message specifications are not consulted.
            "tradacoms.message_specification_validation",
            "tradacoms.code_value_validation",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


# ===========================================================================
# Node construction
# ===========================================================================


def _set_if(attributes: Dict[str, object], name: str, value: str) -> None:
    """Record ``value`` under ``name`` only when the source wrote one."""
    text = value.strip()
    if text:
        attributes[name] = text


def _message_controls(message: TradacomsMessage) -> ControlCount:
    """``MTR`` NOSG — segments from ``MHD`` to ``MTR`` inclusive — beside the observed count."""
    return ControlCount(
        subject=f"message {message.reference} ({message.message_type})",
        counted="segments",
        trailer="MTR",
        declared=int_or_none(message.trailer.component(1)),
        observed=len(message.segments) + 2,
    )


def _transmission_controls(transmission: TradacomsTransmission) -> ControlCount:
    """``END`` NMST — messages in the transmission — beside the observed count."""
    return ControlCount(
        subject=f"transmission {transmission.sender_reference}",
        counted="messages",
        trailer="END",
        declared=int_or_none(transmission.trailer.component(1)),
        observed=sum(1 for _ in transmission.all_messages()),
    )


def _message_node(message: TradacomsMessage, *, ordinal: int, file_path: str) -> NativeNode:
    """Describe one message, its declared segment count and its segments."""
    path = f"{file_path}/MHD[{ordinal}]"
    controls = _message_controls(message)
    attributes: Dict[str, object] = {
        "messageReference": message.reference,
        "messageType": message.message_type,
        "fileHeader": message.is_file_header,
        "segmentCount": len(message.segments),
        "envelopeSegmentCount": controls.observed,
        "inProfileMessageSet": TRADACOMS_PROFILE_MATCH.profile.covers(message.message_type),
    }
    _set_if(attributes, "messageVersion", message.version)
    if controls.declared is not None:
        attributes["declaredSegmentCount"] = controls.declared
        attributes["controlCountConsistent"] = controls.consistent

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
            segment_node(
                segment,
                ordinal=index,
                message_path=path,
                repeat_index=repeats[index],
                repeat_count=totals[segment.tag],
            )
            for index, segment in enumerate(message.segments)
        ],
    )


def _file_node(file: TradacomsFile, *, ordinal: int, transmission_path: str) -> NativeNode:
    """Describe one file: its header's transaction type and generation, and its messages."""
    path = f"{transmission_path}/FILE[{ordinal}]"
    attributes: Dict[str, object] = {
        "messageCount": len(file.messages),
        "hasHeaderMessage": file.header is not None,
    }
    _set_if(attributes, "headerMessageType", file.header_type)
    # The transaction code names the file's transaction type (0430 ORDERS) — the sender's claim.
    _set_if(attributes, "transactionCode", file.transaction_code)
    _set_if(attributes, "transactionName", file.transaction_name)
    _set_if(attributes, "fileGenerationNumber", file.generation)
    _set_if(attributes, "fileVersionNumber", file.file_version)
    name = file.header_type or file.messages[0].message_type
    label = f"File {name}"
    if file.generation.strip():
        label += f" ({file.generation.strip()})"
    return NativeNode(
        kind=KIND_FILE,
        name=name,
        label=label,
        ordinal=ordinal,
        attributes=attributes,
        location=segment_location(file.messages[0].header, ordinal=ordinal, path=path),
        children=lambda: [
            _message_node(message, ordinal=index, file_path=path)
            for index, message in enumerate(file.messages)
        ],
    )


def _transmission_node(transmission: TradacomsTransmission, *, ordinal: int) -> NativeNode:
    """Describe one transmission: its ``STX`` envelope, service characters, profile and files.

    ``STX`` RCRF (the recipient's reference) is deliberately not among the attributes: trading
    partners use it as a password, so it stays in its element, where value visibility governs it.
    """
    path = f"STX[{ordinal}]"
    controls = _transmission_controls(transmission)
    attributes: Dict[str, object] = {
        "syntaxIdentifier": transmission.syntax_identifier,
        "syntaxVersion": transmission.syntax_version,
        "senderCode": transmission.sender_code,
        "recipientCode": transmission.recipient_code,
        "senderReference": transmission.sender_reference,
        "fileCount": len(transmission.files),
        "messageCount": controls.observed,
        "tagSeparator": TAG_SEPARATOR,
        "componentSeparator": TRADACOMS_DELIMITERS.component,
        "elementSeparator": TRADACOMS_DELIMITERS.element,
        "segmentTerminator": TRADACOMS_DELIMITERS.segment,
        "releaseCharacter": TRADACOMS_DELIMITERS.release,
        "profile": TRADACOMS_PROFILE_MATCH.profile.key,
        "profileLabel": TRADACOMS_PROFILE_MATCH.profile.label,
        "implementationGuideConsulted": False,
    }
    _set_if(attributes, "date", transmission.date)
    _set_if(attributes, "time", transmission.time)
    _set_if(attributes, "applicationReference", transmission.application_reference)
    if controls.declared is not None:
        attributes["declaredMessageCount"] = controls.declared
        attributes["controlCountConsistent"] = controls.consistent
    return NativeNode(
        kind=KIND_TRANSMISSION,
        name="STX",
        label=f"Transmission {transmission.sender_reference}",
        ordinal=ordinal,
        attributes=attributes,
        location=segment_location(transmission.header, ordinal=ordinal, path=path),
        children=lambda: [
            _file_node(file, ordinal=index, transmission_path=path)
            for index, file in enumerate(transmission.files)
        ],
    )


# ===========================================================================
# Warnings
# ===========================================================================


def _envelope_node_count(document: TradacomsDocument) -> int:
    """Count the transmission/file/message nodes an analysis must keep."""
    return sum(
        1 + len(transmission.files) + sum(1 for _ in transmission.all_messages())
        for transmission in document.transmissions
    )


def _control_counts(document: TradacomsDocument) -> List[ControlCount]:
    """Every control count in source order: each transmission's messages, then its ``END``."""
    counts: List[ControlCount] = []
    for transmission in document.transmissions:
        counts.extend(_message_controls(message) for message in transmission.all_messages())
        counts.append(_transmission_controls(transmission))
    return counts


def _canonical_subset_warnings(document: TradacomsDocument) -> List[AnalysisWarning]:
    """State when the canonical model read one message of several."""
    file, message = canonical_message(document)
    derived_from = f"message {message.message_type} ({message.reference})"
    if file.header_type:
        derived_from += f" in file {file.header_type}"
    transmissions = len(document.transmissions)
    files = sum(len(transmission.files) for transmission in document.transmissions)
    scope = f" across {files} file(s)"
    if transmissions > 1:
        scope += f" in {transmissions} transmissions"
    return canonical_subset_warning(
        code=WARNING_CANONICAL_SUBSET,
        derived_from=derived_from,
        observed=sum(1 for _ in document.all_messages()),
        unit="message",
        scope=scope,
        document="document",
    )


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_tradacoms(
    document: TradacomsDocument,
    *,
    source: Optional[str] = None,
    source_format: str = TRADACOMS_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe parsed TRADACOMS transmissions as a payload analysis.

    Args:
        document: The parsed document (:func:`app.tradacoms_parser.parse_tradacoms`).
        source: The exact text analysed, hashed into ``source_hash``; defaults to the document's
            retained ``raw`` text — the text the positions were read from.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget. Raised, if smaller, to fit every envelope node.
        max_depth: Depth budget; the envelope is at most seven levels deep.

    Returns:
        The analysis document, with observed element values still on it —
        :func:`app.payload_analysis_store.store_analysis` applies the value-visibility policy.
    """
    text = source if source is not None else document.raw
    effective_nodes = envelope_node_budget(max_nodes, _envelope_node_count(document))
    warnings = (
        _canonical_subset_warnings(document)
        + control_count_warnings(WARNING_CONTROL_COUNT_MISMATCH, _control_counts(document))
        + profile_warnings(
            TRADACOMS_PROFILE_MATCH,
            [message.message_type for message in document.all_messages()],
            prefix="tradacoms",
        )
    )
    return build_analysis_document(
        roots=[
            _transmission_node(transmission, ordinal=index)
            for index, transmission in enumerate(document.transmissions)
        ],
        analyzer=AnalyzerInfo(key=TRADACOMS_ANALYZER_KEY, version=TRADACOMS_ANALYZER_VERSION),
        capabilities=tradacoms_capabilities(max_nodes=effective_nodes),
        source=text,
        source_format=source_format,
        warnings=warnings,
        max_nodes=effective_nodes,
        max_depth=max_depth,
    )
