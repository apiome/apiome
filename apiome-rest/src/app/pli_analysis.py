"""PL/I structure native-analysis extractor — FMT-11.1 (#5480).

The PL/I counterpart of :mod:`app.cobolcopybook_analysis`: the canonical model keeps a field's name
and type, and this keeps what makes a declaration a *layout* — level numbers, attributes as written,
dimensions, storage class, and every item's computed byte offset and length — in PL/I's own terms:

.. code-block:: text

    record   1 ORDER_REC                         offset 1    len 568
      field    2 ORDER_ID      CHAR(10)          offset 1    len 10
      group    2 SHIP_TO       LIKE ADDRESS_BLOCK offset 11  len 163
      union    2 BODY          UNION             offset …    ← members share storage
      include  %INCLUDE MISSING                  (not supplied — the record is partial)

Status follows the copybook analyzer's rules. The statement of what the byte counts assume
(:data:`~app.pli_layout.LAYOUT_ASSUMPTIONS`) is an ``info`` warning on every record. An ``%INCLUDE``
that was not supplied, and an attribute the reader does not know, are ``warning``\\s — the record is
``partial`` with that reason named, never a silently short layout.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .payload_analysis import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    AnalysisWarning,
    AnalyzerCapabilities,
    AnalyzerInfo,
    PayloadAnalysisDocument,
    SourceLocation,
    analyzer_capabilities,
)
from .payload_analyzer import NativeNode, analysis_limits, build_analysis_document
from .pli_layout import LAYOUT_ASSUMPTIONS, ItemLayout, compute_layout
from .pli_normalizer import _item_payload, _storage_payload
from .pli_parser import FORMAT_KEY, PliDocument, PliItem

__all__ = [
    "PLI_ANALYZER_KEY",
    "PLI_ANALYZER_VERSION",
    "WARNING_INCLUDE_UNRESOLVED",
    "WARNING_LAYOUT_ASSUMPTIONS",
    "WARNING_RUNTIME_EXTENT",
    "WARNING_UNREAD_ATTRIBUTE",
    "WARNING_UNSIZED_ITEM",
    "analyze_pli",
    "pli_capabilities",
    "pli_tool_versions",
]

#: Analyzer key recorded on every record this module produces.
PLI_ANALYZER_KEY = FORMAT_KEY
#: Version of this extractor.
PLI_ANALYZER_VERSION = "1.0.0"
#: Version of the in-repo reader the extractor reads through.
PLI_PARSER_VERSION = "1.0.0"

KIND_RECORD = "record"
KIND_GROUP = "group"
KIND_UNION = "union"
KIND_FIELD = "field"
KIND_INCLUDE = "include"

#: The assumptions every computed length rests on (``info``).
WARNING_LAYOUT_ASSUMPTIONS = "pli.layout_assumptions"
#: An ``%INCLUDE`` that was not supplied (``warning`` — the record is partial).
WARNING_INCLUDE_UNRESOLVED = "pli.include_unresolved"
#: An attribute the reader does not know (``warning`` — the record is partial).
WARNING_UNREAD_ATTRIBUTE = "pli.unread_attribute"
#: A REFER / ``*`` extent: lengths after it are runtime values (``info``).
WARNING_RUNTIME_EXTENT = "pli.runtime_extent"
#: An item whose storage the declaration does not describe (``info``).
WARNING_UNSIZED_ITEM = "pli.unsized_item"


def pli_tool_versions() -> Dict[str, str]:
    """Return the reader version behind a PL/I analysis."""
    return {"pli_parser": PLI_PARSER_VERSION}


def pli_capabilities() -> AnalyzerCapabilities:
    """Return what this extractor models, and what it knowingly does not."""
    return analyzer_capabilities(
        supported=[
            "pli.level_numbers",
            "pli.structures",
            "pli.data_attributes",
            "pli.language_defaults",
            "pli.dimensions",
            "pli.like",
            "pli.union",
            "pli.alignment",
            "pli.storage_class",
            "pli.include_resolution",
            "pli.storage_offsets",
            "pli.computed_storage_length",
            "pli.source_lines",
        ],
        unsupported=[
            # The compiler's structure-mapping algorithm can offset a structure's start to save
            # padding; the calculator pads forward from a doubleword (stated as an assumption).
            "pli.structure_mapping_offset",
            "pli.preprocessor_statements",
            "pli.initial_values",
            "pli.character_encoding_detection",
        ],
        limits=analysis_limits(),
    )


def _node(item: PliItem, layouts: Dict[int, ItemLayout], *, ordinal: int, parent: str, root: bool) -> NativeNode:
    """Describe one item and everything under it."""
    label = item.name if item.include is None else f"%INCLUDE {item.include}"
    path = f"{parent}/{label}" if parent else label
    layout = layouts[id(item)]
    if item.include is not None:
        kind = KIND_INCLUDE
        attributes: Dict[str, object] = {"member": item.include, "resolved": False}
    else:
        kind = KIND_RECORD if root else KIND_UNION if item.union else KIND_GROUP if item.children else KIND_FIELD
        attributes = dict(_item_payload(item))
    attributes.update(_storage_payload(layout, 1))
    return NativeNode(
        kind=kind,
        name=label,
        ordinal=ordinal,
        attributes=attributes,
        location=SourceLocation(file=item.file, line=item.line, ordinal=ordinal, path=path),
        children=[
            _node(child, layouts, ordinal=index, parent=path, root=False) for index, child in enumerate(item.children)
        ],
    )


def _warnings(document: PliDocument, layouts: Dict[int, ItemLayout]) -> List[AnalysisWarning]:
    """The record's warnings: missing includes, unread attributes, runtime extents, unsized items."""
    warnings: List[AnalysisWarning] = []
    for include in document.unresolved_includes:
        where = f"inside {include.inside}" if include.inside else "between declarations"
        consequence = (
            "the members it declares are missing and the structure has no length from that point on"
            if include.inside
            else "anything it declares is missing from this analysis"
        )
        warnings.append(
            AnalysisWarning(
                code=WARNING_INCLUDE_UNRESOLVED,
                severity=SEVERITY_WARNING,
                message=f"%INCLUDE {include.member} ({where}) was not supplied; {consequence}.",
                location=SourceLocation(file=include.file, line=include.line),
            )
        )
    unread: List[str] = []
    runtime: List[str] = []
    unsized: List[str] = []
    for structure in document.structures:
        for item in structure.walk():
            if item.unread:
                unread.append(f"{item.name}: {' '.join(item.unread)}")
            layout = layouts.get(id(item))
            if layout is None or item.children or item.include is not None:
                continue
            if layout.variable:
                runtime.append(item.name)
            elif layout.length is None:
                unsized.append(item.name)
    if unread:
        warnings.append(
            AnalysisWarning(
                code=WARNING_UNREAD_ATTRIBUTE,
                severity=SEVERITY_WARNING,
                message="Attributes this reader does not interpret (" + "; ".join(unread) + ") are kept as written.",
            )
        )
    if runtime:
        warnings.append(
            AnalysisWarning(
                code=WARNING_RUNTIME_EXTENT,
                severity=SEVERITY_INFO,
                message=(
                    "A REFER or * extent is a runtime value (" + ", ".join(runtime) + "); those items have no "
                    "fixed length and nothing after them has a single offset."
                ),
            )
        )
    if unsized:
        warnings.append(
            AnalysisWarning(
                code=WARNING_UNSIZED_ITEM,
                severity=SEVERITY_INFO,
                message="The declaration does not describe the storage of " + ", ".join(unsized) + ".",
            )
        )
    warnings.append(
        AnalysisWarning(
            code=WARNING_LAYOUT_ASSUMPTIONS,
            severity=SEVERITY_INFO,
            message=(
                "Storage offsets and lengths are computed under assumptions the declaration does not state: "
                + " ".join(LAYOUT_ASSUMPTIONS)
            ),
        )
    )
    return warnings


def analyze_pli(
    document: PliDocument,
    *,
    source: Optional[str] = None,
    source_format: str = FORMAT_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed PL/I document as a payload analysis.

    Args:
        document: The parsed document (:func:`app.pli_parser.parse_pli_text`).
        source: The exact text analysed; defaults to the document's files joined in path order.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget.
        max_depth: Depth budget.

    Returns:
        The analysis document — one root per major structure.
    """
    content = source if source is not None else "\n".join(text for _, text in sorted(document.sources.items()))
    layouts: Dict[int, ItemLayout] = {}
    for structure in document.structures:
        layouts.update(compute_layout(structure))
    roots = [
        _node(structure, layouts, ordinal=index, parent="", root=True)
        for index, structure in enumerate(document.structures)
    ]
    return build_analysis_document(
        roots=roots,
        analyzer=AnalyzerInfo(key=PLI_ANALYZER_KEY, version=PLI_ANALYZER_VERSION, tool_versions=pli_tool_versions()),
        capabilities=pli_capabilities(),
        source=content,
        source_format=source_format,
        warnings=_warnings(document, layouts),
        max_nodes=max_nodes,
        max_depth=max_depth,
    )
