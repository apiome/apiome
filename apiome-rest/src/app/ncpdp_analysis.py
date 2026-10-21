"""NCPDP native-analysis extractor — FMT-6.8 (#5452).

The normalizer (:mod:`app.ncpdp_normalizer`) turns a document's structure into types. This extractor
describes the document itself, in NCPDP's own vocabulary, for each sub-format:

.. code-block:: text

    SCRIPT                                      Telecommunication D.0
    message     transaction type, message id    transmission  version, transaction code,
      element   …Header, Body, NewRx, Patient     │           declared vs observed transactions
        element …leaf elements carry the value    header      the 56-character header — its fields
        attribute  Qualifier, version …           segment     AM01 Patient, AM04 Insurance
                                                  transaction one transaction's segments
                                                    segment   AM07 Claim, AM11 Pricing …
                                                      field   C2, D2, D7 …

The honesty contract — the shared EDI base's (:mod:`app.edi_analysis_base`)
----------------------------------------------------------------------------
* **Declared versus observed.** The Telecom header's transaction count (``109-A9``) is recorded beside
  the transactions observed and, for the claim codes B1/B2/B3, a disagreement is an informational
  warning (:func:`~app.edi_analysis_base.control_count_warnings`): read, not rejected.
* **Values are payload.** Patient names, dates of birth, drug codes, quantities, identifiers and
  amounts sit only in value nodes' ``value``
  (:func:`~app.edi_analysis_base.observed_value_node`), which the value-visibility policy governs.
  Attributes carry structure: transaction types, segment ids, field ids, counts.
* **Positions where they were checked.** Telecom segments and header fields carry the offset and
  length they were cut from (:func:`~app.edi_analysis_base.segment_location`); a SCRIPT node locates
  by its element path only, because the XML reader keeps no positions.
* **No implementation guide is consulted**
  (:func:`~app.edi_analysis_base.implementation_guide_statement`): a structurally readable message is
  never presented as a conformant one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .edi_analysis_base import (
    ControlCount,
    control_count_warnings,
    envelope_node_budget,
    implementation_guide_statement,
    observed_value_node,
    segment_location,
)
from .ncpdp_parser import SUB_FORMAT_SCRIPT, NcpdpDocument
from .ncpdp_script import ScriptDocument, ScriptMessage, element_children, local_name
from .ncpdp_telecom import (
    CLAIM_TRANSACTION_CODES,
    FIELD_LABELS,
    HEADER_LAYOUT,
    SEGMENT_NAMES,
    TelecomSegment,
    TelecomTransmission,
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

__all__ = [
    "KIND_ATTRIBUTE",
    "KIND_ELEMENT",
    "KIND_FIELD",
    "KIND_HEADER",
    "KIND_MESSAGE",
    "KIND_SEGMENT",
    "KIND_TRANSACTION",
    "KIND_TRANSMISSION",
    "NCPDP_ANALYZER_KEY",
    "NCPDP_ANALYZER_VERSION",
    "NCPDP_IMPLEMENTATION_GUIDE_STATEMENT",
    "WARNING_SEGMENT_NOT_NAMED",
    "WARNING_TRANSACTION_COUNT_MISMATCH",
    "WARNING_UNRECOGNIZED_TRANSACTION",
    "analyze_ncpdp",
    "ncpdp_capabilities",
]

#: Analyzer key recorded on every record this module produces.
NCPDP_ANALYZER_KEY = "ncpdp"
#: Version of this extractor.
NCPDP_ANALYZER_VERSION = "1.0.0"

KIND_MESSAGE = "message"
KIND_ELEMENT = "element"
KIND_ATTRIBUTE = "attribute"
KIND_TRANSMISSION = "transmission"
KIND_HEADER = "header"
KIND_TRANSACTION = "transaction"
KIND_SEGMENT = "segment"
KIND_FIELD = "field"

#: The Telecom header's transaction count disagrees with the transactions observed.
WARNING_TRANSACTION_COUNT_MISMATCH = "ncpdp.transaction_count_mismatch"
#: A SCRIPT Body carries a transaction element outside the recognised set.
WARNING_UNRECOGNIZED_TRANSACTION = "ncpdp.transaction_not_recognized"
#: A Telecom segment id outside the named request segments.
WARNING_SEGMENT_NOT_NAMED = "ncpdp.segment_not_named"

#: The statement the capability declaration and the format registry both carry.
NCPDP_IMPLEMENTATION_GUIDE_STATEMENT = implementation_guide_statement(
    "NCPDP SCRIPT element structure and Telecommunication D.0 segment/field syntax",
    (
        "the SCRIPT Implementation Guide",
        "the Telecommunication D.0 Implementation Guide and data dictionary",
        "payer sheets",
    ),
)


def ncpdp_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """Return what this extractor models, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The :class:`~app.payload_analysis.AnalyzerCapabilities` for an NCPDP analysis.
    """
    return analyzer_capabilities(
        supported=[
            "ncpdp.script_message",
            "ncpdp.script_transaction_type",
            "ncpdp.script_elements",
            "ncpdp.script_attributes",
            "ncpdp.script_relates_to",
            "ncpdp.telecom_header",
            "ncpdp.telecom_transaction_code",
            "ncpdp.telecom_segments",
            "ncpdp.telecom_fields",
            "ncpdp.telecom_transaction_count",
            "ncpdp.telecom_byte_offsets",
        ],
        unsupported=[
            "ncpdp.implementation_guide_validation",
            "ncpdp.telecom_response_transmissions",
            "ncpdp.telecom_data_dictionary",
            "ncpdp.script_source_positions",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


def _info(code: str, message: str) -> AnalysisWarning:
    return AnalysisWarning(code=code, severity=SEVERITY_INFO, message=message)


# ===========================================================================
# SCRIPT
# ===========================================================================


def _indexed_children(element: ET.Element) -> List[tuple]:
    """``(child, name)`` per child element, the name indexed (``Name[2]``) when it repeats."""
    children = element_children(element)
    totals: Dict[str, int] = {}
    for child in children:
        totals[local_name(child)] = totals.get(local_name(child), 0) + 1
    seen: Dict[str, int] = {}
    out = []
    for child in children:
        name = local_name(child)
        seen[name] = seen.get(name, 0) + 1
        out.append((child, f"{name}[{seen[name]}]" if totals[name] > 1 else name))
    return out


def _element_nodes(element: ET.Element, path: str) -> List[NativeNode]:
    """Attribute value nodes, then one node per child element, in document order."""
    nodes: List[NativeNode] = []
    for key, value in element.attrib.items():
        if "}" in key:
            continue
        nodes.append(
            observed_value_node(kind=KIND_ATTRIBUTE, name=key, ordinal=len(nodes), path=f"{path}/@{key}", value=value)
        )
    for child, name in _indexed_children(element):
        nodes.append(_element_node(child, ordinal=len(nodes), path=f"{path}/{name}"))
    return nodes


def _element_node(element: ET.Element, *, ordinal: int, path: str) -> NativeNode:
    """A record element (its children lazily) or a leaf element carrying its value."""
    name = local_name(element)
    if element_children(element) or any("}" not in key for key in element.attrib):
        return NativeNode(
            kind=KIND_ELEMENT,
            name=name,
            ordinal=ordinal,
            attributes={"childCount": len(element_children(element))},
            location=SourceLocation(ordinal=ordinal, path=path),
            children=lambda: _element_nodes(element, path),
        )
    return observed_value_node(
        kind=KIND_ELEMENT, name=name, ordinal=ordinal, path=path, value=(element.text or "").strip()
    )


def _message_node(message: ScriptMessage, *, ordinal: int, ids: set) -> NativeNode:
    attributes: Dict[str, object] = {
        "transactionType": message.transaction_type,
        "recognized": message.recognized,
        "implementationGuideConsulted": False,
    }
    if message.message_id:
        attributes["messageId"] = message.message_id
    if message.relates_to:
        attributes["relatesToMessageId"] = message.relates_to
        attributes["relatesToResolved"] = message.relates_to in ids
    if message.version_label:
        attributes["version"] = message.version_label
    if message.source_label:
        attributes["sourceFile"] = message.source_label
    path = message.path
    return NativeNode(
        kind=KIND_MESSAGE,
        name=message.transaction_type,
        label=f"{message.transaction_type} {message.message_id or ''}".strip(),
        ordinal=ordinal,
        attributes=attributes,
        location=SourceLocation(ordinal=ordinal, path=path),
        children=lambda: _element_nodes(message.element, path),
    )


def _script_warnings(script: ScriptDocument) -> List[AnalysisWarning]:
    warnings: List[AnalysisWarning] = []
    for message in script.messages:
        if not message.recognized:
            warnings.append(
                _info(
                    WARNING_UNRECOGNIZED_TRANSACTION,
                    f"{message.path} carries transaction element <{message.transaction_type}>, which is "
                    "not a recognised SCRIPT transaction. It is read and recorded under that name.",
                )
            )
    return warnings


# ===========================================================================
# Telecom D.0
# ===========================================================================


def _header_node(transmission: TelecomTransmission, *, ordinal: int) -> NativeNode:
    """The fixed header: one value node per positional field, each with its exact columns."""
    path = "TRANSMISSION/header"

    def fields() -> List[NativeNode]:
        nodes: List[NativeNode] = []
        for index, spec in enumerate(HEADER_LAYOUT):
            value = transmission.header[spec.name].rstrip()
            nodes.append(
                NativeNode(
                    kind=KIND_FIELD,
                    name=spec.name,
                    label=spec.label,
                    ordinal=index,
                    attributes={"start": spec.start, "end": spec.end},
                    location=SourceLocation(
                        line=1,
                        column=spec.start,
                        offset=spec.start - 1,
                        length=spec.length,
                        ordinal=index,
                        path=f"{path}/{spec.name}",
                    ),
                    value_present=True,
                    value_length=len(value),
                    value=value,
                )
            )
        return nodes

    last = HEADER_LAYOUT[-1]
    return NativeNode(
        kind=KIND_HEADER,
        name="header",
        label="Transaction header",
        ordinal=ordinal,
        attributes={"length": last.end},
        location=SourceLocation(line=1, column=1, offset=0, length=last.end, ordinal=ordinal, path=path),
        children=fields,
    )


def _segment_node(segment: TelecomSegment, *, ordinal: int, parent: str) -> NativeNode:
    path = f"{parent}/{segment.tag}[{ordinal}]"

    def fields() -> List[NativeNode]:
        return [
            observed_value_node(
                kind=KIND_FIELD,
                name=item.field_id,
                label=FIELD_LABELS.get(item.field_id),
                ordinal=index,
                path=f"{path}/{item.field_id}",
                value=item.value,
                attributes={"fieldId": item.field_id},
            )
            for index, item in enumerate(segment.fields)
        ]

    return NativeNode(
        kind=KIND_SEGMENT,
        name=segment.tag,
        label=segment.name,
        ordinal=ordinal,
        attributes={
            "segmentId": segment.tag,
            "named": segment.segment_id in SEGMENT_NAMES,
            "separator": segment.separator,
            "fieldCount": len(segment.fields),
        },
        location=segment_location(segment, ordinal=ordinal, path=path),
        children=fields,
    )


def _transaction_node(group: List[TelecomSegment], *, ordinal: int, code: str) -> NativeNode:
    path = f"TRANSMISSION/transaction[{ordinal}]"
    return NativeNode(
        kind=KIND_TRANSACTION,
        name=code,
        label=f"Transaction {ordinal}",
        ordinal=ordinal,
        attributes={"transactionCode": code, "segmentCount": len(group)},
        location=segment_location(group[0], ordinal=ordinal, path=path),
        children=lambda: [_segment_node(segment, ordinal=index, parent=path) for index, segment in enumerate(group)],
    )


def _transaction_count(transmission: TelecomTransmission) -> Optional[ControlCount]:
    """The header's transaction count as a control count, for the claim codes only."""
    if transmission.transaction_code not in CLAIM_TRANSACTION_CODES:
        return None
    return ControlCount(
        subject="the transmission",
        counted="transactions",
        trailer="The transaction header (109-A9 Transaction Count)",
        declared=transmission.declared_transaction_count,
        observed=len(transmission.transactions),
    )


def _transmission_node(transmission: TelecomTransmission) -> NativeNode:
    attributes: Dict[str, object] = {
        "version": transmission.version,
        "transactionCode": transmission.transaction_code,
        "transactionName": transmission.transaction_name,
        "segmentCount": len(transmission.segments),
        "observedTransactionCount": len(transmission.transactions),
        "implementationGuideConsulted": False,
    }
    if transmission.declared_transaction_count is not None:
        attributes["declaredTransactionCount"] = transmission.declared_transaction_count
    count = _transaction_count(transmission)
    if count is not None and count.consistent is not None:
        attributes["transactionCountConsistent"] = count.consistent

    def children() -> List[NativeNode]:
        nodes = [_header_node(transmission, ordinal=0)]
        for segment in transmission.transmission_segments:
            nodes.append(_segment_node(segment, ordinal=len(nodes), parent="TRANSMISSION"))
        for index, group in enumerate(transmission.transactions, start=1):
            nodes.append(_transaction_node(group, ordinal=index, code=transmission.transaction_code))
        return nodes

    return NativeNode(
        kind=KIND_TRANSMISSION,
        name=transmission.transaction_code,
        label=f"Telecom D.0 {transmission.transaction_code} ({transmission.transaction_name})",
        ordinal=0,
        attributes=attributes,
        location=SourceLocation(
            line=1, column=1, offset=0, length=len(transmission.raw.rstrip("\r\n")), ordinal=0, path="TRANSMISSION"
        ),
        children=children,
    )


def _telecom_warnings(transmission: TelecomTransmission) -> List[AnalysisWarning]:
    count = _transaction_count(transmission)
    warnings = control_count_warnings(WARNING_TRANSACTION_COUNT_MISMATCH, [count] if count else [])
    unnamed: List[str] = []
    for segment in transmission.segments:
        if segment.segment_id not in SEGMENT_NAMES and segment.tag not in unnamed:
            unnamed.append(segment.tag)
    for tag in unnamed:
        warnings.append(
            _info(
                WARNING_SEGMENT_NOT_NAMED,
                f"Segment {tag} is not one of the named request segments (AM01–AM16); its fields are "
                "read and kept under their ids.",
            )
        )
    return warnings


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_ncpdp(
    document: NcpdpDocument,
    *,
    source: Optional[str] = None,
    source_format: str = NCPDP_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed NCPDP document as a payload analysis.

    Args:
        document: The parsed document (:func:`app.ncpdp_parser.parse_ncpdp`).
        source: The exact text analysed; defaults to the document's retained text.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget. Raised, if smaller, to fit every message, segment and transaction.
        max_depth: Depth budget.

    Returns:
        The analysis document, with observed values still on it —
        :func:`app.payload_analysis_store.store_analysis` applies the value-visibility policy.
    """
    text = source if source is not None else document.raw
    if document.sub_format == SUB_FORMAT_SCRIPT:
        script = document.script
        assert script is not None
        ids = {message.message_id for message in script.messages if message.message_id}
        roots = [_message_node(message, ordinal=index, ids=ids) for index, message in enumerate(script.messages)]
        envelope = len(script.messages)
        warnings = _script_warnings(script)
    else:
        transmission = document.telecom
        assert transmission is not None
        roots = [_transmission_node(transmission)]
        envelope = 2 + len(transmission.transactions) + len(transmission.segments)
        warnings = _telecom_warnings(transmission)
    effective_nodes = envelope_node_budget(max_nodes, envelope)
    return build_analysis_document(
        roots=roots,
        analyzer=AnalyzerInfo(key=NCPDP_ANALYZER_KEY, version=NCPDP_ANALYZER_VERSION),
        capabilities=ncpdp_capabilities(max_nodes=effective_nodes),
        source=text,
        source_format=source_format,
        warnings=warnings,
        max_nodes=effective_nodes,
        max_depth=max_depth,
    )
