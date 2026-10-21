"""SAP IDoc native-analysis extractor — FMT-6.2 (#5446).

Describes every IDoc in a file in SAP's own vocabulary:

.. code-block:: text

    idoc         one per IDoc — the EDI_DC40 control record, as structure
      segment    E1EDK01, E1EDP01 … nested by parent segment number, never by record order
        field    CURCY, MENGE … (or one opaque SDATA when a flat segment has no definition)
        segment  child segments, under the segment their PSGNUM names

The contract, shared with the X12, EDIFACT and copybook extractors:

**Control-record metadata is structure.** Basic type, extension, message type, partners, ports,
direction and dates sit in the ``idoc`` node's ``attributes`` — never in a ``value`` — so the
value-visibility policy never withholds what identifies the document. Field values are payload and
are built only through :func:`~app.edi_analysis_base.observed_value_node`, so the policy governs
every one of them and the five presence facts (has value, present-empty, withheld, not present, not
recorded) read off the record the same way they do for an EDI interchange.

**Offsets are conditional.** A flat field's offset and length are computed from the segment
definition under :data:`~app.idoc_parser.IDOC_LAYOUT_ASSUMPTIONS`, which the record states in a
``idoc.layout_assumptions`` warning — the copybook analyzer's "what these byte counts assume"
contract. An XML IDoc has no byte layout, so its records claim none.

**Every IDoc is kept.** A file of several IDocs is one root per IDoc; the canonical model reads the
first and the record says so.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence

from .edi_analysis_base import (
    canonical_subset_warning,
    envelope_node_budget,
    observed_value_node,
    segment_location,
)
from .idoc_parser import (
    DATA_RECORD_HEADER_LENGTH,
    FORM_FLAT,
    IDOC_LAYOUT_ASSUMPTIONS,
    Idoc,
    IdocField,
    IdocFile,
    IdocSegment,
    iter_segments,
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
    "IDOC_ANALYZER_KEY",
    "IDOC_ANALYZER_VERSION",
    "KIND_FIELD",
    "KIND_IDOC",
    "KIND_SEGMENT",
    "WARNING_CANONICAL_SUBSET",
    "WARNING_DEFINITION_MISMATCH",
    "WARNING_LAYOUT_ASSUMPTIONS",
    "WARNING_LEVEL_DISAGREEMENT",
    "WARNING_OPAQUE_SDATA",
    "analyze_idoc",
    "idoc_capabilities",
]

IDOC_ANALYZER_KEY = "idoc"
IDOC_ANALYZER_VERSION = "1.0.0"

KIND_IDOC = "idoc"
KIND_SEGMENT = "segment"
KIND_FIELD = "field"

#: The flat offsets in this record rest on assumptions the file does not state.
WARNING_LAYOUT_ASSUMPTIONS = "idoc.layout_assumptions"
#: Flat segments with no definition: their SDATA is one opaque value.
WARNING_OPAQUE_SDATA = "idoc.sdata_without_definition"
#: Declared HLEVEL disagrees with the depth the parent segment numbers give.
WARNING_LEVEL_DISAGREEMENT = "idoc.hierarchy_level_disagrees"
#: The definition supplied describes a different basic type, or misses segments the IDoc carries.
WARNING_DEFINITION_MISMATCH = "idoc.definition_mismatch"
#: The canonical model reads one IDoc of several.
WARNING_CANONICAL_SUBSET = "idoc.canonical_projection_subset"

#: ``DIRECT`` — whose point of view the IDoc is written from. Unlisted codes are reported verbatim.
_DIRECTIONS = {"1": "Outbound", "2": "Inbound"}

#: Control-record fields lifted to named attributes. Everything non-empty is also in
#: ``controlRecord``, under its SAP name.
_CONTROL_ATTRIBUTES = (
    ("DOCNUM", "documentNumber"),
    ("IDOCTYP", "basicType"),
    ("CIMTYP", "extension"),
    ("MESTYP", "messageType"),
    ("MESCOD", "messageCode"),
    ("MESFCT", "messageFunction"),
    ("DOCREL", "release"),
    ("STATUS", "status"),
    ("SNDPOR", "senderPort"),
    ("SNDPRT", "senderPartnerType"),
    ("SNDPFC", "senderPartnerFunction"),
    ("SNDPRN", "senderPartner"),
    ("RCVPOR", "receiverPort"),
    ("RCVPRT", "receiverPartnerType"),
    ("RCVPFC", "receiverPartnerFunction"),
    ("RCVPRN", "receiverPartner"),
    ("CREDAT", "createdDate"),
    ("CRETIM", "createdTime"),
    ("STD", "ediStandard"),
    ("STDVRS", "ediStandardVersion"),
    ("STDMES", "ediStandardMessage"),
)


def idoc_capabilities(*, max_nodes: int = MAX_TREE_NODES, flat: bool = True) -> AnalyzerCapabilities:
    """What this extractor modelled for **this record**, and what it knowingly did not.

    Args:
        max_nodes: The node budget the record was produced under.
        flat: Whether the record describes the flat form, which alone has byte offsets.

    Returns:
        The capability declaration.
    """
    flat_constructs = ["idoc.byte_offsets", "idoc.field_offsets"]
    return analyzer_capabilities(
        supported=[
            "idoc.control_record",
            "idoc.segment_hierarchy",
            "idoc.segment_numbers",
            "idoc.fields",
            "idoc.flat_form",
            "idoc.xml_form",
            "idoc.segment_definitions",
            "idoc.multiple_idocs",
        ]
        + (flat_constructs if flat else []),
        unsupported=([] if flat else flat_constructs)
        + [
            # Standard SAP segment layouts are not bundled: without a supplied definition a flat
            # segment's SDATA is one opaque value.
            "idoc.standard_segment_layouts",
            # Nothing is checked against the basic type's WE30 structure or the qualifier code lists.
            "idoc.basic_type_validation",
            "idoc.qualifier_semantics",
            # Status records (EDI_DS40), release 2.x record layouts, and code-page detection.
            "idoc.status_records",
            "idoc.release_2x_records",
            "idoc.code_page_detection",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


# ===========================================================================
# Nodes
# ===========================================================================


def _field_node(item: IdocField, *, ordinal: int, segment_path: str, flat: bool) -> NativeNode:
    """One field — the value is payload, the layout is structure."""
    attributes: Dict[str, object] = {"position": ordinal + 1}
    if item.name == "SDATA" and item.sap_type is None and item.description is None and flat:
        attributes["opaque"] = True
    if flat and item.offset is not None:
        attributes["offset"] = item.offset
        attributes["recordOffset"] = DATA_RECORD_HEADER_LENGTH + item.offset
    if flat and item.length is not None:
        attributes["length"] = item.length
    if item.sap_type:
        attributes["dataType"] = item.sap_type
    if item.description:
        attributes["description"] = item.description
    return observed_value_node(
        kind=KIND_FIELD,
        name=item.name,
        ordinal=ordinal,
        path=f"{segment_path}/{item.name}",
        value=item.value,
        attributes=attributes,
    )


def _segment_node(
    segment: IdocSegment, *, ordinal: int, parent_path: str, repeat_index: int, repeat_count: int,
    flat: bool,
) -> NativeNode:
    """One segment, its fields, then its child segments."""
    path = f"{parent_path}/{segment.name}[{ordinal}]"
    attributes: Dict[str, object] = {
        "segmentName": segment.name,
        "segmentNumber": segment.number,
        "parentSegmentNumber": segment.parent_number,
        "depth": segment.depth,
        "fieldCount": len(segment.fields),
        "childSegmentCount": len(segment.children),
        "repeatIndex": repeat_index,
        "repeatCount": repeat_count,
        "definitionApplied": segment.defined if flat else None,
    }
    if segment.level is not None:
        attributes["declaredLevel"] = segment.level
    if attributes["definitionApplied"] is None:
        del attributes["definitionApplied"]

    def children() -> List[NativeNode]:
        nodes = [
            _field_node(item, ordinal=index, segment_path=path, flat=flat)
            for index, item in enumerate(segment.fields)
        ]
        nodes.extend(_segment_nodes(segment.children, parent_path=path, start=len(nodes), flat=flat))
        return nodes

    location = (
        SourceLocation(
            line=segment.line, column=1, offset=segment.offset, length=segment.length,
            ordinal=ordinal, path=path,
        )
        if flat and segment.offset is not None
        else segment_location(None, ordinal=ordinal, path=path)
    )
    return NativeNode(
        kind=KIND_SEGMENT,
        name=segment.name,
        label=f"{segment.name} ({repeat_index + 1} of {repeat_count})" if repeat_count > 1 else None,
        ordinal=ordinal,
        attributes=attributes,
        location=location,
        children=children,
    )


def _segment_nodes(
    segments: Sequence[IdocSegment], *, parent_path: str, start: int, flat: bool
) -> List[NativeNode]:
    """Sibling segments, each knowing which repeat of its name it is."""
    totals = Counter(segment.name for segment in segments)
    seen: Counter = Counter()
    nodes: List[NativeNode] = []
    for index, segment in enumerate(segments):
        nodes.append(
            _segment_node(
                segment,
                ordinal=start + index,
                parent_path=parent_path,
                repeat_index=seen[segment.name],
                repeat_count=totals[segment.name],
                flat=flat,
            )
        )
        seen[segment.name] += 1
    return nodes


def _idoc_node(idoc: Idoc, *, ordinal: int, form: str) -> NativeNode:
    """One IDoc: the control record as attributes, the segments as children."""
    flat = form == FORM_FLAT
    control = idoc.control
    path = f"IDOC[{ordinal}]"
    attributes: Dict[str, object] = {"form": form, "segmentCount": idoc.segment_count}
    for sap_name, attribute in _CONTROL_ATTRIBUTES:
        value = control.get(sap_name).strip()
        if value:
            attributes[attribute] = value
    direction = control.get("DIRECT").strip()
    if direction:
        attributes["direction"] = direction
        attributes["directionLabel"] = _DIRECTIONS.get(direction, "Unrecognised code")
    if control.get("TEST").strip():
        attributes["testFlag"] = control.get("TEST").strip()
    attributes["controlRecord"] = control.non_empty()
    if flat and control.length is not None:
        attributes["controlRecordLength"] = control.length
    location = (
        SourceLocation(
            line=control.line, column=1, offset=control.offset, length=control.length,
            ordinal=ordinal, path=path,
        )
        if flat and control.offset is not None
        else segment_location(None, ordinal=ordinal, path=path)
    )
    label = f"IDoc {control.document_number or ordinal + 1} ({control.basic_type})"
    return NativeNode(
        kind=KIND_IDOC,
        name=control.basic_type,
        label=label,
        ordinal=ordinal,
        attributes=attributes,
        location=location,
        children=lambda: _segment_nodes(idoc.segments, parent_path=path, start=0, flat=flat),
    )


# ===========================================================================
# Warnings
# ===========================================================================


def _layout_warnings(document: IdocFile) -> List[AnalysisWarning]:
    """State the layout assumptions, and name segments whose SDATA had no definition."""
    if document.form != FORM_FLAT:
        return []
    warnings = [
        AnalysisWarning(
            code=WARNING_LAYOUT_ASSUMPTIONS,
            severity=SEVERITY_INFO,
            message=(
                "Record and field offsets are computed under assumptions this file does not state: "
                + " ".join(IDOC_LAYOUT_ASSUMPTIONS)
            ),
        )
    ]
    opaque = sorted(
        {
            segment.name
            for idoc in document.idocs
            for segment in iter_segments(idoc.segments)
            if not segment.defined
        }
    )
    if opaque:
        warnings.append(
            AnalysisWarning(
                code=WARNING_OPAQUE_SDATA,
                severity=SEVERITY_INFO,
                message=(
                    f"No segment definition was supplied for {', '.join(opaque)}, so each one's SDATA "
                    "is recorded as a single opaque value. Supply the segment definition (a WE60 "
                    "export) beside the IDoc to read its fields."
                ),
            )
        )
    return warnings


def _level_warnings(document: IdocFile) -> List[AnalysisWarning]:
    """Note segments whose declared HLEVEL disagrees with the parent numbers."""
    count = sum(len(idoc.level_disagreements) for idoc in document.idocs)
    if not count:
        return []
    return [
        AnalysisWarning(
            code=WARNING_LEVEL_DISAGREEMENT,
            severity=SEVERITY_INFO,
            message=(
                f"{count} segment(s) declare an HLEVEL that disagrees with the depth their parent "
                "segment numbers give. The hierarchy follows the numbers; the declared level is "
                "recorded beside it."
            ),
        )
    ]


def _definition_warnings(document: IdocFile) -> List[AnalysisWarning]:
    """Note a definition for another basic type, or segments the definition does not describe."""
    definitions = document.definitions
    if definitions is None:
        return []
    warnings: List[AnalysisWarning] = []
    basic_types = sorted({idoc.control.basic_type for idoc in document.idocs})
    if definitions.basic_type and definitions.basic_type not in basic_types:
        warnings.append(
            AnalysisWarning(
                code=WARNING_DEFINITION_MISMATCH,
                severity=SEVERITY_INFO,
                message=(
                    f"The segment definition describes basic type {definitions.basic_type}, but the "
                    f"IDoc is {', '.join(basic_types)}. Segments were matched by name."
                ),
            )
        )
    undefined = sorted(
        {
            segment.name
            for idoc in document.idocs
            for segment in iter_segments(idoc.segments)
            if segment.name not in definitions.segments
        }
    )
    if undefined:
        warnings.append(
            AnalysisWarning(
                code=WARNING_DEFINITION_MISMATCH,
                severity=SEVERITY_INFO,
                message=f"The segment definition does not describe {', '.join(undefined)}.",
            )
        )
    return warnings


def _subset_warnings(document: IdocFile) -> List[AnalysisWarning]:
    first = document.idocs[0].control
    return canonical_subset_warning(
        code=WARNING_CANONICAL_SUBSET,
        derived_from=f"IDoc {first.document_number or '1'} ({first.basic_type})",
        observed=len(document.idocs),
        unit="IDoc",
    )


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_idoc(
    document: IdocFile,
    *,
    source: Optional[str] = None,
    source_format: str = IDOC_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed IDoc file as a payload analysis.

    Args:
        document: The parsed file (:func:`app.idoc_parser.parse_idoc`).
        source: The exact text analysed; defaults to the document's retained raw text.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget, raised to keep every IDoc root.
        max_depth: Depth budget.

    Returns:
        The analysis document, values still on it for the store to govern.
    """
    text = source if source is not None else document.raw
    effective_nodes = envelope_node_budget(max_nodes, len(document.idocs))
    flat = document.form == FORM_FLAT
    warnings = (
        _subset_warnings(document)
        + _layout_warnings(document)
        + _level_warnings(document)
        + _definition_warnings(document)
    )
    return build_analysis_document(
        roots=[
            _idoc_node(idoc, ordinal=index, form=document.form)
            for index, idoc in enumerate(document.idocs)
        ],
        analyzer=AnalyzerInfo(key=IDOC_ANALYZER_KEY, version=IDOC_ANALYZER_VERSION),
        capabilities=idoc_capabilities(max_nodes=effective_nodes, flat=flat),
        source=text,
        source_format=source_format,
        warnings=warnings,
        max_nodes=effective_nodes,
        max_depth=max_depth,
    )
