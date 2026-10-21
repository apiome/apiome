"""SWIFT MT native-analysis extractor — FMT-6.3 (#5447).

Describes every MT message in a file in SWIFT's own vocabulary:

.. code-block:: text

    message        MT103 — headers as structure, the documented MX counterpart as a note
      block        1 basic header · 2 application header · 3 user header · 5 trailer
      block        4 text
        sequence   A (general information), B (underlying customer transfer, MT202 COV)
          field    32A, 50K, 61 … tag and option letter as structure
            component    currency, amount, bic, mark …       (values)
            code_word    /INV/ … the qualifier as structure   (its text a value)
            numbered_line 1/ … the line number as structure   (its text a value)
            line         a free name/address or narrative line (a value)

**Option letters and qualifiers are structure.** A field's tag, option letter, documented name and
shape sit in ``attributes``; a code word's qualifier and a numbered line's number do too. What the
message *said* — amounts, accounts, names, references — is a value, built through
:func:`~app.edi_analysis_base.observed_value_node`, so the value-visibility policy governs it exactly
as it does an X12 element.

**MX is a note.** Where a documented MX counterpart exists (MT103 → pacs.008, MT940 → camt.053 …),
the message carries it in ``attributes.mxCorrespondence`` with ``verified: false``, and an
``swift.mx_correspondence_note`` warning states the disclaimer. Nothing here translates a message.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from .edi_analysis_base import (
    canonical_subset_warning,
    envelope_node_budget,
    observed_value_node,
    segment_location,
)
from .payload_analysis import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    SEVERITY_INFO,
    AnalysisWarning,
    AnalyzerCapabilities,
    AnalyzerInfo,
    PayloadAnalysisDocument,
    SourceLocation,
    analyzer_capabilities,
)
from .payload_analyzer import NativeNode, analysis_limits, build_analysis_document
from .swift_mt_fields import MX_CORRESPONDENCE_DISCLAIMER, field_name
from .swift_mt_normalizer import mx_correspondence
from .swift_mt_parser import (
    SwiftHeaderBlock,
    SwiftMtField,
    SwiftMtFile,
    SwiftMtMessage,
    SwiftMtSequence,
)

__all__ = [
    "KIND_BLOCK",
    "KIND_CODE_WORD",
    "KIND_COMPONENT",
    "KIND_FIELD",
    "KIND_LINE",
    "KIND_MESSAGE",
    "KIND_NUMBERED_LINE",
    "KIND_SEQUENCE",
    "SWIFT_MT_ANALYZER_KEY",
    "SWIFT_MT_ANALYZER_VERSION",
    "WARNING_CANONICAL_SUBSET",
    "WARNING_FIELD_NOT_IN_CATALOGUE",
    "WARNING_FIELD_NOT_WELL_FORMED",
    "WARNING_MX_CORRESPONDENCE",
    "analyze_swift_mt",
    "swift_mt_capabilities",
]

SWIFT_MT_ANALYZER_KEY = "swift-mt"
SWIFT_MT_ANALYZER_VERSION = "1.0.0"

KIND_MESSAGE = "message"
KIND_BLOCK = "block"
KIND_SEQUENCE = "sequence"
KIND_FIELD = "field"
KIND_COMPONENT = "component"
KIND_CODE_WORD = "code_word"
KIND_NUMBERED_LINE = "numbered_line"
KIND_LINE = "line"

#: A documented MX counterpart, stated as a note with its disclaimer.
WARNING_MX_CORRESPONDENCE = "swift.mx_correspondence_note"
#: Fields whose content does not match their documented shape; kept as lines.
WARNING_FIELD_NOT_WELL_FORMED = "swift.field_not_well_formed"
#: Fields the catalogue has no shape for; kept as lines.
WARNING_FIELD_NOT_IN_CATALOGUE = "swift.field_not_in_catalogue"
#: The canonical model reads one message of several.
WARNING_CANONICAL_SUBSET = "swift.canonical_projection_subset"

_BLOCK_NAMES = {"1": "Basic header", "2": "Application header", "3": "User header", "5": "Trailer"}
#: Block 3 tags with a reviewed label; unlisted tags are reported by number.
_USER_HEADER_LABELS = {
    "103": "serviceIdentifier",
    "108": "messageUserReference",
    "111": "serviceTypeIdentifier",
    "113": "bankingPriority",
    "119": "validationFlag",
    "121": "uetr",
}


def swift_mt_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """What this extractor models, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The capability declaration.
    """
    return analyzer_capabilities(
        supported=[
            "swift.basic_header",
            "swift.application_header",
            "swift.user_header",
            "swift.trailer",
            "swift.text_block",
            "swift.sequences",
            "swift.fields",
            "swift.option_letters",
            "swift.field_components",
            "swift.code_words",
            "swift.statement_lines",
            "swift.byte_offsets",
            "swift.multiple_messages",
            "swift.mx_correspondence_notes",
        ],
        unsupported=[
            # SWIFT network-validated rules and usage rules are not evaluated.
            "swift.network_validation",
            "swift.usage_rules",
            # No message is translated to MX; the correspondence is a note.
            "swift.mx_translation",
            # BICs are not looked up; checksums and MACs are not verified.
            "swift.bic_directory",
            "swift.checksum_verification",
            # Message types beyond MT103, MT202 (COV), MT940 and MT942.
            "swift.other_message_types",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


# ===========================================================================
# Nodes
# ===========================================================================


def _header_attributes(block: SwiftHeaderBlock) -> Dict[str, object]:
    """A header block's parsed values, as structure."""
    if block.block_id == "3":
        return {_USER_HEADER_LABELS.get(tag, f"tag{tag}"): value for tag, value in block.values}
    if block.block_id == "5":
        return {f"tag{tag}": value for tag, value in block.values}
    return dict(block.values)


def _block_node(block: SwiftHeaderBlock, *, ordinal: int, message_path: str) -> NativeNode:
    path = f"{message_path}/{{{block.block_id}}}"
    return NativeNode(
        kind=KIND_BLOCK,
        name=block.block_id,
        label=f"{{{block.block_id}:}} {_BLOCK_NAMES[block.block_id]}",
        ordinal=ordinal,
        attributes={"blockId": block.block_id, **_header_attributes(block)},
        location=segment_location(_Position(block.line, block.offset, block.length), ordinal=ordinal, path=path),
    )


def _point(line: int, offset: int, ordinal: int, path: str) -> SourceLocation:
    """A location where a construct starts, for one whose extent spans several blocks."""
    return SourceLocation(line=line, column=1, offset=offset, ordinal=ordinal, path=path)


class _Position:
    """A line/offset/length triple with column 1, for :func:`segment_location`."""

    def __init__(self, line: int, offset: int, length: int) -> None:
        self.line = line
        self.column = 1
        self.offset = offset
        self.length = length


def _content_nodes(item: SwiftMtField, path: str) -> List[NativeNode]:
    """A field's components, code words, numbered lines and free lines."""
    reading = item.reading
    nodes: List[NativeNode] = []
    for name, value in reading.components:
        nodes.append(
            observed_value_node(
                kind=KIND_COMPONENT, name=name, ordinal=len(nodes), path=f"{path}/{name}", value=value
            )
        )
    for index, word in enumerate(reading.code_words):
        nodes.append(
            observed_value_node(
                kind=KIND_CODE_WORD,
                name=f"/{word.code}/",
                ordinal=len(nodes),
                path=f"{path}/{word.code}[{index}]",
                value=word.text,
                attributes={"qualifier": word.code},
            )
        )
    for line in reading.numbered_lines:
        nodes.append(
            observed_value_node(
                kind=KIND_NUMBERED_LINE,
                name=f"{line.number}/",
                ordinal=len(nodes),
                path=f"{path}/line{line.number}[{len(nodes)}]",
                value=line.text,
                attributes={"lineNumber": line.number},
            )
        )
    for index, line in enumerate(reading.lines):
        nodes.append(
            observed_value_node(
                kind=KIND_LINE,
                name=f"line {index + 1}",
                ordinal=len(nodes),
                path=f"{path}/line[{index}]",
                value=line,
            )
        )
    return nodes


def _field_node(
    item: SwiftMtField, *, ordinal: int, sequence_path: str, repeat_index: int, repeat_count: int,
    statement_line: Optional[int],
) -> NativeNode:
    path = f"{sequence_path}/{item.label}[{ordinal}]"
    attributes: Dict[str, object] = {
        "tag": item.tag,
        "option": item.option,
        "format": item.reading.format,
        "wellFormed": item.reading.well_formed,
        "lineCount": len(item.lines),
        "repeatIndex": repeat_index,
        "repeatCount": repeat_count,
    }
    if item.option is None:
        del attributes["option"]
    name = field_name(item.tag, item.option)
    if name:
        attributes["fieldName"] = name
    if statement_line is not None:
        attributes["statementLineIndex"] = statement_line
    return NativeNode(
        kind=KIND_FIELD,
        name=item.label,
        label=f":{item.label}: {name}" if name else f":{item.label}:",
        ordinal=ordinal,
        attributes=attributes,
        location=segment_location(_Position(item.line, item.offset, item.length), ordinal=ordinal, path=path),
        children=lambda: _content_nodes(item, path),
    )


def _sequence_node(
    sequence: SwiftMtSequence, *, ordinal: int, block_path: str, statement: bool
) -> NativeNode:
    path = f"{block_path}/{sequence.name}"
    totals = Counter(item.label for item in sequence.fields)

    def children() -> List[NativeNode]:
        seen: Counter = Counter()
        nodes: List[NativeNode] = []
        line_index = -1
        for index, item in enumerate(sequence.fields):
            statement_line: Optional[int] = None
            if statement and item.tag == "61":
                line_index += 1
                statement_line = line_index
            elif statement and item.tag == "86" and index and sequence.fields[index - 1].tag == "61":
                statement_line = line_index
            nodes.append(
                _field_node(
                    item,
                    ordinal=index,
                    sequence_path=path,
                    repeat_index=seen[item.label],
                    repeat_count=totals[item.label],
                    statement_line=statement_line,
                )
            )
            seen[item.label] += 1
        return nodes

    return NativeNode(
        kind=KIND_SEQUENCE,
        name=sequence.name,
        label=f"Sequence {sequence.name}",
        ordinal=ordinal,
        attributes={"sequence": sequence.name, "fieldCount": len(sequence.fields)},
        location=segment_location(None, ordinal=ordinal, path=path),
        children=children,
    )


def _message_node(message: SwiftMtMessage, *, ordinal: int, related: Optional[int]) -> NativeNode:
    path = f"MSG[{ordinal}]"
    attributes: Dict[str, object] = {
        "messageType": message.message_type,
        "messageName": message.name,
        "direction": message.direction,
        "sequenceCount": len(message.sequences),
        "fieldCount": sum(len(sequence.fields) for sequence in message.sequences),
    }
    if message.variant:
        attributes["validationFlag"] = message.variant
    note = mx_correspondence(message)
    if note is not None:
        attributes["mxCorrespondence"] = {
            "mx": note["mx"],
            "mxName": note["mxName"],
            "verified": False,
        }
    if related is not None:
        attributes["relatesToMessage"] = related
    statement = message.message_type in ("940", "942")

    def children() -> List[NativeNode]:
        nodes: List[NativeNode] = []
        for block in (message.basic, message.application, message.user):
            if block is not None:
                nodes.append(_block_node(block, ordinal=len(nodes), message_path=path))
        text_path = f"{path}/{{4}}"
        nodes.append(
            NativeNode(
                kind=KIND_BLOCK,
                name="4",
                label="{4:} Text",
                ordinal=len(nodes),
                attributes={"blockId": "4"},
                location=_point(message.text_line, message.text_offset, len(nodes), text_path),
                children=[
                    _sequence_node(sequence, ordinal=index, block_path=text_path, statement=statement)
                    for index, sequence in enumerate(message.sequences)
                ],
            )
        )
        if message.trailer is not None:
            nodes.append(_block_node(message.trailer, ordinal=len(nodes), message_path=path))
        return nodes

    return NativeNode(
        kind=KIND_MESSAGE,
        name=message.name,
        label=f"{message.name} ({_reference(message) or 'no reference'})",
        ordinal=ordinal,
        attributes=attributes,
        location=_point(message.basic.line, message.basic.offset, ordinal, path),
        children=children,
    )


def _reference(message: SwiftMtMessage) -> Optional[str]:
    """Field 20's reference — structure, as a control number is in X12."""
    item = message.field("20")
    return item.lines[0] if item is not None and item.lines else None


def _related_index(messages: List[SwiftMtMessage], index: int) -> Optional[int]:
    """The earlier message whose field 20 this message's field 21 names (a cover to its payment)."""
    related = messages[index].field("21")
    if related is None or not related.lines:
        return None
    for earlier in range(index):
        if _reference(messages[earlier]) == related.lines[0]:
            return earlier
    return None


# ===========================================================================
# Warnings
# ===========================================================================


def _mx_warnings(document: SwiftMtFile) -> List[AnalysisWarning]:
    warnings: List[AnalysisWarning] = []
    for message in document.messages:
        note = mx_correspondence(message)
        if note is None:
            continue
        warnings.append(
            AnalysisWarning(
                code=WARNING_MX_CORRESPONDENCE,
                severity=SEVERITY_INFO,
                message=(
                    f"{message.name} corresponds to ISO 20022 {note['mx']} ({note['mxName']}), as "
                    f"documented by {note['basis']}. {MX_CORRESPONDENCE_DISCLAIMER}"
                ),
            )
        )
    return warnings


def _field_warnings(document: SwiftMtFile) -> List[AnalysisWarning]:
    malformed: List[str] = []
    unknown: List[str] = []
    for message in document.messages:
        for item in message.fields():
            if not item.reading.well_formed:
                malformed.append(f":{item.label}: (line {item.line})")
            elif item.reading.format == "lines":
                unknown.append(f":{item.label}:")
    warnings: List[AnalysisWarning] = []
    if malformed:
        warnings.append(
            AnalysisWarning(
                code=WARNING_FIELD_NOT_WELL_FORMED,
                severity=SEVERITY_INFO,
                message=(
                    f"{', '.join(malformed)} do(es) not match the field's documented shape, so the "
                    "content is kept as lines rather than read into components. The message is not "
                    "refused for it."
                ),
            )
        )
    if unknown:
        warnings.append(
            AnalysisWarning(
                code=WARNING_FIELD_NOT_IN_CATALOGUE,
                severity=SEVERITY_INFO,
                message=(
                    f"{', '.join(sorted(set(unknown)))} are not in the field catalogue, so their "
                    "content is kept as lines."
                ),
            )
        )
    return warnings


def _subset_warnings(document: SwiftMtFile) -> List[AnalysisWarning]:
    first = document.messages[0]
    return canonical_subset_warning(
        code=WARNING_CANONICAL_SUBSET,
        derived_from=f"message {first.name} ({_reference(first) or 'no reference'})",
        observed=len(document.messages),
        unit="message",
    )


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_swift_mt(
    document: SwiftMtFile,
    *,
    source: Optional[str] = None,
    source_format: str = SWIFT_MT_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed MT file as a payload analysis.

    Args:
        document: The parsed file (:func:`app.swift_mt_parser.parse_swift_mt`).
        source: The exact text analysed; defaults to the document's retained raw text.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget, raised to keep every message.
        max_depth: Depth budget.

    Returns:
        The analysis document, values still on it for the store to govern.
    """
    text = source if source is not None else document.raw
    messages = list(document.messages)
    effective_nodes = envelope_node_budget(max_nodes, len(messages))
    warnings = _subset_warnings(document) + _mx_warnings(document) + _field_warnings(document)
    return build_analysis_document(
        roots=[
            _message_node(message, ordinal=index, related=_related_index(messages, index))
            for index, message in enumerate(messages)
        ],
        analyzer=AnalyzerInfo(key=SWIFT_MT_ANALYZER_KEY, version=SWIFT_MT_ANALYZER_VERSION),
        capabilities=swift_mt_capabilities(max_nodes=effective_nodes),
        source=text,
        source_format=source_format,
        warnings=warnings,
        max_nodes=effective_nodes,
        max_depth=max_depth,
    )
