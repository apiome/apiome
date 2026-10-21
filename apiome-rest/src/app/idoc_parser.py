"""SAP IDoc parser — FMT-6.2 (#5446).

Reads an SAP IDoc in either of its two transport forms into one typed :class:`IdocFile` AST, so the
normalizer and the analysis never need to know which form arrived:

.. code-block:: text

    flat file   EDI_DC40 control record (524 characters, fixed-width)
                EDI_DD40 data records   (63-character header + 1000-character SDATA)
    XML         <BASICTYPE> → <IDOC BEGIN="1"> → <EDI_DC40 SEGMENT="1"> + E1…/Z1… segments

**The hierarchy comes from the numbers.** A flat data record names its own segment number
(``SEGNUM``) and its parent's (``PSGNUM``; ``000000`` is the top level), and that is what nests it —
never the order the records happen to be in. ``HLEVEL`` is kept as the sender's claim beside the
depth the numbers give. An XML IDoc nests the same relationships with elements, and is numbered here
in document order, so both forms produce the same tree of :class:`IdocSegment`.

**Fields need a definition in the flat form.** A flat record's 1000-character ``SDATA`` has no field
boundaries of its own. Where a segment definition is supplied (a WE60-style ``<IDocSegments>`` export,
see :func:`parse_segment_definitions`), ``SDATA`` is cut at the offsets it declares; where none is,
``SDATA`` is kept as one opaque value. Every cut rests on :data:`IDOC_LAYOUT_ASSUMPTIONS`.

**Errors** are :class:`IdocParseError` with an intake-taxonomy code: ``INPUT_TRUNCATED`` (the text
stops mid-record or mid-element), ``INPUT_MALFORMED`` (unreadable records or XML),
``INPUT_SEMANTIC_INVALID`` (no control record, a short control record, a parent number that names no
segment). Encoding faults are refused code-less so the import pipeline names them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "CONTROL_RECORD_FIELDS",
    "CONTROL_RECORD_LENGTH",
    "DATA_RECORD_HEADER_LENGTH",
    "DATA_RECORD_LENGTH",
    "FORM_FLAT",
    "FORM_XML",
    "IDOC_LAYOUT_ASSUMPTIONS",
    "SDATA_LENGTH",
    "FieldDefinition",
    "Idoc",
    "IdocControlRecord",
    "IdocField",
    "IdocFile",
    "IdocParseError",
    "IdocSegment",
    "SegmentDefinition",
    "SegmentDefinitionSet",
    "is_idoc",
    "is_segment_definition",
    "iter_segments",
    "parse_idoc",
    "parse_segment_definitions",
]

FORM_FLAT = "flat"
FORM_XML = "xml"

#: The ``EDI_DC40`` control record (SAP release 4.0 and later): field name and width, in order.
#: The widths sum to :data:`CONTROL_RECORD_LENGTH`.
CONTROL_RECORD_FIELDS: Tuple[Tuple[str, int], ...] = (
    ("TABNAM", 10),
    ("MANDT", 3),
    ("DOCNUM", 16),
    ("DOCREL", 4),
    ("STATUS", 2),
    ("DIRECT", 1),
    ("OUTMOD", 1),
    ("EXPRSS", 1),
    ("TEST", 1),
    ("IDOCTYP", 30),
    ("CIMTYP", 30),
    ("MESTYP", 30),
    ("MESCOD", 3),
    ("MESFCT", 3),
    ("STD", 1),
    ("STDVRS", 6),
    ("STDMES", 6),
    ("SNDPOR", 10),
    ("SNDPRT", 2),
    ("SNDPFC", 2),
    ("SNDPRN", 10),
    ("SNDSAD", 21),
    ("SNDLAD", 70),
    ("RCVPOR", 10),
    ("RCVPRT", 2),
    ("RCVPFC", 2),
    ("RCVPRN", 10),
    ("RCVSAD", 21),
    ("RCVLAD", 70),
    ("CREDAT", 8),
    ("CRETIM", 6),
    ("REFINT", 14),
    ("REFGRP", 14),
    ("REFMES", 14),
    ("ARCKEY", 70),
    ("SERIAL", 20),
)
CONTROL_RECORD_LENGTH = sum(width for _, width in CONTROL_RECORD_FIELDS)

#: The ``EDI_DD40`` data-record header: segment name, client, IDoc number, segment number, parent
#: segment number, hierarchy level. ``SDATA`` follows.
DATA_RECORD_HEADER: Tuple[Tuple[str, int], ...] = (
    ("SEGNAM", 30),
    ("MANDT", 3),
    ("DOCNUM", 16),
    ("SEGNUM", 6),
    ("PSGNUM", 6),
    ("HLEVEL", 2),
)
DATA_RECORD_HEADER_LENGTH = sum(width for _, width in DATA_RECORD_HEADER)
SDATA_LENGTH = 1000
DATA_RECORD_LENGTH = DATA_RECORD_HEADER_LENGTH + SDATA_LENGTH

#: What every flat offset and value in this module assumes. Published by the analysis beside the
#: offsets it computes, mirroring the copybook analyzer's layout-assumption contract: none of these
#: is stated by the file itself, so an offset is only true where they hold.
IDOC_LAYOUT_ASSUMPTIONS: Tuple[str, ...] = (
    "One character per byte position — a single-byte code page. A multi-byte character in a "
    "value shifts every offset after it.",
    "The control record is the 524-character EDI_DC40 layout and each data record the "
    "1063-character EDI_DD40 layout (a 63-character header and 1000 characters of SDATA) of SAP "
    "release 4.0 and later; the release 2.x EDI_DC/EDI_DD layouts are not read.",
    "Trailing blanks are padding and are removed from values; leading blanks are kept.",
    "A data record shorter than its layout lost trailing blanks only, so its SDATA is padded "
    "back with blanks — a record truncated in the middle of a value cannot be told apart.",
    "Segment-definition offsets are 0-based within SDATA, as the definition file states them.",
)

#: Markers that betray a payload decoded with the wrong encoding.
_ENCODING_FAULT_MARKERS = ("\x00", "�")

_FLAT_MARKER = "EDI_DC40"
_XML_IDOC_RE = re.compile(r"<IDOC[\s>/]")
_XML_CONTROL_RE = re.compile(r"<EDI_DC40[\s>/]")
_DEFINITION_RE = re.compile(r"<IDocSegments[\s>/]")

#: Expat's words for an XML document that simply stops.
_TRUNCATION_MESSAGES = ("no element found", "unclosed token")


class IdocParseError(ValueError):
    """Raised when IDoc text cannot be parsed.

    Attributes:
        code: Stable intake-taxonomy code, or ``None`` to let the pipeline classify the fault.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


# ===========================================================================
# AST
# ===========================================================================


@dataclass(frozen=True)
class IdocField:
    """One field value of a segment.

    Attributes:
        name: Field name (``CURCY``), or ``SDATA`` for an opaque flat payload.
        value: The value — trailing padding removed in the flat form, exact in the XML form.
        offset: 0-based offset within ``SDATA`` (flat form only).
        length: Declared length (flat form only).
        sap_type: Declared ABAP data type (``CHAR``, ``CUKY``…), when a definition supplied one.
        description: Declared field description, when a definition supplied one.
    """

    name: str
    value: str
    offset: Optional[int] = None
    length: Optional[int] = None
    sap_type: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class IdocSegment:
    """One data segment and the segments nested under it.

    Attributes:
        name: Segment name (``E1EDK01``).
        number: Segment number — ``SEGNUM`` in the flat form, document order in the XML form.
        parent_number: The parent's segment number; ``0`` at the top level.
        level: The hierarchy level the record declared (``HLEVEL``), or ``None`` when it did not.
        depth: The depth the numbers give (1 at the top level).
        fields: The segment's fields, in order.
        children: Nested segments, in segment-number order.
        defined: Whether a segment definition supplied the field layout (always ``True`` in the
            XML form, where element names are the field names).
        line: 1-based source line (flat form only).
        offset: 0-based character offset of the record (flat form only).
        length: Record length in characters, line terminator excluded (flat form only).
    """

    name: str
    number: int
    parent_number: int
    level: Optional[int]
    depth: int
    fields: Tuple[IdocField, ...]
    children: Tuple["IdocSegment", ...]
    defined: bool
    line: Optional[int] = None
    offset: Optional[int] = None
    length: Optional[int] = None

    def field_value(self, name: str) -> Optional[str]:
        """Return a field's value by name, or ``None`` when the segment has no such field."""
        for item in self.fields:
            if item.name == name:
                return item.value
        return None


@dataclass(frozen=True)
class IdocControlRecord:
    """The ``EDI_DC40`` control record.

    Attributes:
        fields: Every field the record carried, ``(name, value)``, in layout order. In the flat form
            that is all 36; in the XML form, the elements present.
        line: 1-based source line (flat form only).
        offset: 0-based character offset (flat form only).
        length: Record length in characters (flat form only).
    """

    fields: Tuple[Tuple[str, str], ...]
    line: Optional[int] = None
    offset: Optional[int] = None
    length: Optional[int] = None

    def get(self, name: str) -> str:
        """Return one field's value, or ``""`` when the record does not carry it."""
        for key, value in self.fields:
            if key == name:
                return value
        return ""

    @property
    def basic_type(self) -> str:
        """``IDOCTYP`` — the basic type (``ORDERS05``)."""
        return self.get("IDOCTYP")

    @property
    def message_type(self) -> str:
        """``MESTYP`` — the logical message type (``ORDERS``)."""
        return self.get("MESTYP")

    @property
    def extension(self) -> str:
        """``CIMTYP`` — the customer extension type, or ``""``."""
        return self.get("CIMTYP")

    @property
    def document_number(self) -> str:
        """``DOCNUM`` — the IDoc number."""
        return self.get("DOCNUM")

    def non_empty(self) -> Dict[str, str]:
        """Every field that carried a value, in the canonical layout order.

        The flat form writes all 36 fields and the XML form only the ones present, so comparing the
        two needs one normal form: non-empty fields, ordered as :data:`CONTROL_RECORD_FIELDS`, with
        any name the layout does not know appended in source order.
        """
        known = [name for name, _ in CONTROL_RECORD_FIELDS]
        values = {key: value for key, value in self.fields if value != ""}
        ordered = {name: values[name] for name in known if name in values}
        for key, value in self.fields:
            if value != "" and key not in ordered:
                ordered[key] = value
        return ordered


@dataclass(frozen=True)
class Idoc:
    """One IDoc: its control record and its top-level segments.

    Attributes:
        control: The control record.
        segments: Top-level segments, in segment-number order.
        segment_count: Every data segment in the IDoc, nested ones included.
        level_disagreements: Segment numbers whose declared ``HLEVEL`` disagrees with the depth the
            parent numbers give.
    """

    control: IdocControlRecord
    segments: Tuple[IdocSegment, ...]
    segment_count: int
    level_disagreements: Tuple[int, ...] = ()


@dataclass(frozen=True)
class FieldDefinition:
    """One field of a segment definition."""

    name: str
    offset: int
    length: int
    sap_type: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class SegmentDefinition:
    """One segment of a definition export.

    Attributes:
        name: Segment name.
        fields: Its fields, in offset order.
        description: The segment's description.
        min_occurs: Declared minimum occurrences, when stated.
        max_occurs: Declared maximum occurrences, when stated.
        parent: Declared parent segment, when stated.
    """

    name: str
    fields: Tuple[FieldDefinition, ...]
    description: Optional[str] = None
    min_occurs: Optional[int] = None
    max_occurs: Optional[int] = None
    parent: Optional[str] = None


@dataclass(frozen=True)
class SegmentDefinitionSet:
    """A segment-definition export (WE60-style ``<IDocSegments>``).

    Attributes:
        basic_type: The basic type the export describes.
        release: The release it was exported from.
        segments: Definitions by segment name.
        sources: The file names the definitions were read from.
    """

    basic_type: str
    release: str
    segments: Dict[str, SegmentDefinition]
    sources: Tuple[str, ...] = ()


@dataclass(frozen=True)
class IdocFile:
    """A parsed IDoc file: one or more IDocs in one form.

    Attributes:
        form: :data:`FORM_FLAT` or :data:`FORM_XML`.
        idocs: The IDocs, in source order.
        raw: The source text.
        definitions: The segment definitions applied, when any were supplied.
        root_element: The XML root element name (the basic type, by convention); ``None`` for flat.
    """

    form: str
    idocs: Tuple[Idoc, ...]
    raw: str
    definitions: Optional[SegmentDefinitionSet] = None
    root_element: Optional[str] = None


def iter_segments(segments: Sequence[IdocSegment]) -> Iterator[IdocSegment]:
    """Yield every segment depth-first, in segment-number order."""
    for segment in segments:
        yield segment
        yield from iter_segments(segment.children)


# ===========================================================================
# Detection
# ===========================================================================


def _first_content(text: str) -> str:
    """The text after leading whitespace."""
    return text.lstrip()


def is_idoc(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an IDoc in either form.

    Flat: the first non-blank line starts with ``EDI_DC40``. XML: an ``<IDOC>`` element is present
    (with or without its control record, so a document that lost its ``EDI_DC40`` is still claimed
    and refused for the right reason). A segment-definition export is not an IDoc.

    Args:
        content: Candidate text.

    Returns:
        Whether the text is IDoc-shaped.
    """
    if not content or not isinstance(content, str):
        return False
    head = content[:8192]
    if any(marker in head for marker in _ENCODING_FAULT_MARKERS):
        return False
    if _first_content(content).startswith(_FLAT_MARKER):
        return True
    stripped = _first_content(content)
    return stripped.startswith("<") and _XML_IDOC_RE.search(head) is not None


def has_xml_control_record(content: str) -> bool:
    """Whether an XML IDoc carries an ``<EDI_DC40>`` element."""
    return _XML_CONTROL_RE.search(content[:65536]) is not None


def is_segment_definition(content: str) -> bool:
    """Return whether ``content`` is a WE60-style segment-definition export."""
    return bool(content) and _DEFINITION_RE.search(content[:8192]) is not None


# ===========================================================================
# Segment definitions
# ===========================================================================


def _local(tag: str) -> str:
    """An element tag without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _int_attribute(element: ET.Element, name: str) -> Optional[int]:
    value = (element.get(name) or "").strip()
    return int(value) if value.isdigit() else None


def parse_segment_definitions(
    content: str, *, source_label: Optional[str] = None
) -> SegmentDefinitionSet:
    """Read a WE60-style ``<IDocSegments>`` export.

    Args:
        content: The definition file's text.
        source_label: Its name, for messages and provenance.

    Returns:
        The definition set.

    Raises:
        IdocParseError: ``INPUT_MALFORMED`` when the file is not a readable definition, or a field
            declares no usable offset/length.
    """
    try:
        root = parse_xml(content, source_label=source_label)
    except SecureXmlError as exc:
        raise IdocParseError(str(exc), code=exc.code or "INPUT_MALFORMED") from exc
    if _local(root.tag) != "IDocSegments":
        raise IdocParseError(
            f"Segment definition{_label(source_label)} must have an <IDocSegments> root.",
            code="INPUT_MALFORMED",
        )
    segments: Dict[str, SegmentDefinition] = {}
    for element in root:
        if _local(element.tag) != "Segment":
            continue
        name = (element.get("name") or "").strip()
        if not name:
            raise IdocParseError(
                f"Segment definition{_label(source_label)} has a <Segment> with no name.",
                code="INPUT_MALFORMED",
            )
        fields: List[FieldDefinition] = []
        for child in element:
            if _local(child.tag) != "Field":
                continue
            offset = _int_attribute(child, "offset")
            length = _int_attribute(child, "length")
            field_name = (child.get("name") or "").strip()
            if not field_name or offset is None or not length:
                raise IdocParseError(
                    f"Segment definition {name}{_label(source_label)} declares a field without a "
                    "name, a non-negative offset and a positive length.",
                    code="INPUT_MALFORMED",
                )
            if offset + length > SDATA_LENGTH:
                raise IdocParseError(
                    f"Segment definition field {name}.{field_name}{_label(source_label)} ends at "
                    f"{offset + length}, past the {SDATA_LENGTH}-character SDATA.",
                    code="INPUT_MALFORMED",
                )
            fields.append(
                FieldDefinition(
                    name=field_name,
                    offset=offset,
                    length=length,
                    sap_type=(child.get("type") or None),
                    description=(child.get("description") or None),
                )
            )
        segments[name] = SegmentDefinition(
            name=name,
            fields=tuple(sorted(fields, key=lambda item: item.offset)),
            description=element.get("description") or None,
            min_occurs=_int_attribute(element, "minOccurs"),
            max_occurs=_int_attribute(element, "maxOccurs"),
            parent=element.get("parent") or None,
        )
    return SegmentDefinitionSet(
        basic_type=(root.get("basicType") or "").strip(),
        release=(root.get("release") or "").strip(),
        segments=segments,
        sources=(source_label,) if source_label else (),
    )


def merge_definitions(sets: Sequence[SegmentDefinitionSet]) -> Optional[SegmentDefinitionSet]:
    """Combine several definition exports into one; the first export wins a repeated segment."""
    if not sets:
        return None
    segments: Dict[str, SegmentDefinition] = {}
    sources: List[str] = []
    for item in sets:
        for name, definition in item.segments.items():
            segments.setdefault(name, definition)
        sources.extend(item.sources)
    first = sets[0]
    return SegmentDefinitionSet(
        basic_type=first.basic_type,
        release=first.release,
        segments=segments,
        sources=tuple(sources),
    )


# ===========================================================================
# Building the hierarchy (shared by both forms)
# ===========================================================================


@dataclass
class _Node:
    """A segment while its children are still being collected."""

    name: str
    number: int
    parent_number: int
    level: Optional[int]
    fields: Tuple[IdocField, ...]
    defined: bool
    line: Optional[int] = None
    offset: Optional[int] = None
    length: Optional[int] = None
    children: List["_Node"] = field(default_factory=list)


def _freeze(node: _Node, depth: int, disagreements: List[int]) -> IdocSegment:
    """Turn a collected node into an immutable segment, recording ``HLEVEL`` disagreements."""
    if node.level is not None and node.level != depth:
        disagreements.append(node.number)
    return IdocSegment(
        name=node.name,
        number=node.number,
        parent_number=node.parent_number,
        level=node.level,
        depth=depth,
        fields=node.fields,
        children=tuple(_freeze(child, depth + 1, disagreements) for child in node.children),
        defined=node.defined,
        line=node.line,
        offset=node.offset,
        length=node.length,
    )


def _assemble(control: IdocControlRecord, nodes: Sequence[_Node]) -> Idoc:
    """Nest segments by parent number.

    Raises:
        IdocParseError: ``INPUT_SEMANTIC_INVALID`` for a repeated segment number, a parent number
            that names no earlier segment, or an IDoc with no segment at all.
    """
    docnum = control.document_number or "(no DOCNUM)"
    if not nodes:
        raise IdocParseError(
            f"IDoc {docnum} carries a control record and no data segment.",
            code="INPUT_SEMANTIC_INVALID",
        )
    by_number: Dict[int, _Node] = {}
    top: List[_Node] = []
    for node in nodes:
        if node.number in by_number:
            raise IdocParseError(
                f"IDoc {docnum} repeats segment number {node.number:06d} ({node.name}).",
                code="INPUT_SEMANTIC_INVALID",
            )
        if node.parent_number == 0:
            top.append(node)
        else:
            parent = by_number.get(node.parent_number)
            if parent is None:
                raise IdocParseError(
                    f"IDoc {docnum} segment {node.name} ({node.number:06d}) names parent segment "
                    f"{node.parent_number:06d}, which does not precede it.",
                    code="INPUT_SEMANTIC_INVALID",
                )
            parent.children.append(node)
        by_number[node.number] = node
    disagreements: List[int] = []
    segments = tuple(_freeze(node, 1, disagreements) for node in top)
    return Idoc(
        control=control,
        segments=segments,
        segment_count=len(nodes),
        level_disagreements=tuple(disagreements),
    )


# ===========================================================================
# Flat form
# ===========================================================================


def _label(source_label: Optional[str]) -> str:
    return f" ({source_label})" if source_label else ""


def _lines(text: str) -> List[Tuple[int, int, str]]:
    """``(1-based line, offset, text without terminator)`` for every line."""
    out: List[Tuple[int, int, str]] = []
    offset = 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        body = line.rstrip("\r\n")
        out.append((number, offset, body))
        offset += len(line)
    return out


def _cut(record: str, layout: Sequence[Tuple[str, int]]) -> List[Tuple[str, str]]:
    """Cut a fixed-width record by ``layout``, removing trailing padding from each value."""
    values: List[Tuple[str, str]] = []
    position = 0
    for name, width in layout:
        values.append((name, record[position : position + width].rstrip(" ")))
        position += width
    return values


def _number(value: str, what: str, line: int) -> int:
    text = value.strip()
    if not text.isdigit():
        raise IdocParseError(
            f"IDoc data record on line {line} has a non-numeric {what} ({value!r}).",
            code="INPUT_MALFORMED",
        )
    return int(text)


def _flat_fields(
    sdata: str, definition: Optional[SegmentDefinition]
) -> Tuple[Tuple[IdocField, ...], bool]:
    """Cut ``SDATA`` by the segment's definition, or keep it whole when there is none."""
    if definition is None:
        return (
            (IdocField(name="SDATA", value=sdata.rstrip(" "), offset=0, length=SDATA_LENGTH),),
            False,
        )
    padded = sdata.ljust(SDATA_LENGTH)
    return (
        tuple(
            IdocField(
                name=item.name,
                value=padded[item.offset : item.offset + item.length].rstrip(" "),
                offset=item.offset,
                length=item.length,
                sap_type=item.sap_type,
                description=item.description,
            )
            for item in definition.fields
        ),
        True,
    )


def _parse_flat(
    text: str, definitions: Optional[SegmentDefinitionSet], source_label: Optional[str]
) -> IdocFile:
    """Read the flat form."""
    lines = [entry for entry in _lines(text) if entry[2].strip()]
    last_line = lines[-1][0] if lines else 0
    idocs: List[Idoc] = []
    control: Optional[IdocControlRecord] = None
    nodes: List[_Node] = []

    for number, offset, record in lines:
        if record.startswith(_FLAT_MARKER):
            if control is not None:
                idocs.append(_assemble(control, nodes))
            if len(record) < CONTROL_RECORD_LENGTH:
                raise IdocParseError(
                    f"IDoc control record on line {number}{_label(source_label)} is "
                    f"{len(record)} characters; an EDI_DC40 record is {CONTROL_RECORD_LENGTH}, so "
                    "IDOCTYP and MESTYP cannot be read at their declared offsets.",
                    code="INPUT_SEMANTIC_INVALID",
                )
            if len(record) > CONTROL_RECORD_LENGTH:
                raise IdocParseError(
                    f"IDoc control record on line {number} is {len(record)} characters; an "
                    f"EDI_DC40 record is {CONTROL_RECORD_LENGTH}.",
                    code="INPUT_MALFORMED",
                )
            control = IdocControlRecord(
                fields=tuple(_cut(record, CONTROL_RECORD_FIELDS)),
                line=number,
                offset=offset,
                length=len(record),
            )
            if not control.basic_type:
                raise IdocParseError(
                    f"IDoc control record on line {number} names no basic type (IDOCTYP).",
                    code="INPUT_SEMANTIC_INVALID",
                )
            nodes = []
            continue

        if control is None:
            raise IdocParseError(
                f"IDoc data record on line {number}{_label(source_label)} precedes any EDI_DC40 "
                "control record, so nothing identifies the IDoc it belongs to.",
                code="INPUT_SEMANTIC_INVALID",
            )
        if len(record) < DATA_RECORD_HEADER_LENGTH:
            raise IdocParseError(
                f"IDoc data record on line {number} is {len(record)} characters, shorter than the "
                f"{DATA_RECORD_HEADER_LENGTH}-character EDI_DD40 header."
                + (" The file was truncated." if number == last_line else ""),
                code="INPUT_TRUNCATED" if number == last_line else "INPUT_MALFORMED",
            )
        if len(record) > DATA_RECORD_LENGTH:
            raise IdocParseError(
                f"IDoc data record on line {number} is {len(record)} characters; an EDI_DD40 "
                f"record is at most {DATA_RECORD_LENGTH}.",
                code="INPUT_MALFORMED",
            )
        header = dict(_cut(record, DATA_RECORD_HEADER))
        name = header["SEGNAM"].strip()
        if not name:
            raise IdocParseError(
                f"IDoc data record on line {number} names no segment (SEGNAM).",
                code="INPUT_MALFORMED",
            )
        if header["DOCNUM"].strip() and header["DOCNUM"].strip() != control.document_number:
            raise IdocParseError(
                f"IDoc data record {name} on line {number} belongs to IDoc "
                f"{header['DOCNUM'].strip()}, but the control record before it is IDoc "
                f"{control.document_number}.",
                code="INPUT_SEMANTIC_INVALID",
            )
        level_text = header["HLEVEL"].strip()
        definition = definitions.segments.get(name) if definitions else None
        fields, defined = _flat_fields(record[DATA_RECORD_HEADER_LENGTH:], definition)
        nodes.append(
            _Node(
                name=name,
                number=_number(header["SEGNUM"], "SEGNUM", number),
                parent_number=_number(header["PSGNUM"] or "0", "PSGNUM", number),
                level=int(level_text) if level_text.isdigit() else None,
                fields=fields,
                defined=defined,
                line=number,
                offset=offset,
                length=len(record),
            )
        )

    if control is None:
        raise IdocParseError(
            f"IDoc file{_label(source_label)} carries no EDI_DC40 control record.",
            code="INPUT_SEMANTIC_INVALID",
        )
    idocs.append(_assemble(control, nodes))
    return IdocFile(form=FORM_FLAT, idocs=tuple(idocs), raw=text, definitions=definitions)


# ===========================================================================
# XML form
# ===========================================================================


def _is_segment(element: ET.Element) -> bool:
    """An element is a segment when it says so (``SEGMENT``) or holds elements of its own."""
    return element.get("SEGMENT") is not None or len(element) > 0


def _xml_fields(
    element: ET.Element, definition: Optional[SegmentDefinition]
) -> Tuple[IdocField, ...]:
    """A segment's field elements, described from its definition where one is supplied."""
    declared = {item.name: item for item in definition.fields} if definition else {}
    fields: List[IdocField] = []
    for child in element:
        if _is_segment(child):
            continue
        name = _local(child.tag)
        spec = declared.get(name)
        fields.append(
            IdocField(
                name=name,
                value=child.text or "",
                sap_type=spec.sap_type if spec else None,
                description=spec.description if spec else None,
            )
        )
    return tuple(fields)


def _xml_nodes(
    element: ET.Element,
    parent_number: int,
    counter: List[int],
    out: List[_Node],
    definitions: Optional[SegmentDefinitionSet],
) -> None:
    """Number an XML IDoc's segments in document order, parents before children."""
    for child in element:
        if not _is_segment(child):
            continue
        counter[0] += 1
        number = counter[0]
        name = _local(child.tag)
        definition = definitions.segments.get(name) if definitions else None
        out.append(
            _Node(
                name=name,
                number=number,
                parent_number=parent_number,
                level=None,
                fields=_xml_fields(child, definition),
                defined=True,
            )
        )
        _xml_nodes(child, number, counter, out, definitions)


def _parse_xml_form(
    text: str, definitions: Optional[SegmentDefinitionSet], source_label: Optional[str]
) -> IdocFile:
    """Read the XML form."""
    try:
        root = parse_xml(text, source_label=source_label)
    except SecureXmlError as exc:
        message = str(exc)
        if exc.code not in (None, "INPUT_MALFORMED"):
            # A guard fired (DTD, entity, size, depth): its own code is the precise one.
            raise IdocParseError(message, code=exc.code) from exc
        truncated = any(marker in message for marker in _TRUNCATION_MESSAGES)
        raise IdocParseError(
            message + (" The document was truncated." if truncated else ""),
            code="INPUT_TRUNCATED" if truncated else "INPUT_MALFORMED",
        ) from exc

    containers = [root] if _local(root.tag) == "IDOC" else [
        child for child in root if _local(child.tag) == "IDOC"
    ]
    if not containers:
        raise IdocParseError(
            f"IDoc XML{_label(source_label)} has no <IDOC> element under its <{_local(root.tag)}> root.",
            code="INPUT_SEMANTIC_INVALID",
        )
    idocs: List[Idoc] = []
    for index, container in enumerate(containers, start=1):
        control_elements = [child for child in container if _local(child.tag) == "EDI_DC40"]
        if not control_elements:
            raise IdocParseError(
                f"IDoc {index}{_label(source_label)} has no <EDI_DC40> control record, so nothing "
                "states its basic type, message type or partners.",
                code="INPUT_SEMANTIC_INVALID",
            )
        control = IdocControlRecord(
            fields=tuple(
                (_local(child.tag), child.text or "") for child in control_elements[0]
            )
        )
        if not control.basic_type:
            raise IdocParseError(
                f"IDoc {index} control record names no basic type (IDOCTYP).",
                code="INPUT_SEMANTIC_INVALID",
            )
        nodes: List[_Node] = []
        _xml_nodes(
            _without(container, control_elements[0]), 0, [0], nodes, definitions
        )
        idocs.append(_assemble(control, nodes))
    return IdocFile(
        form=FORM_XML,
        idocs=tuple(idocs),
        raw=text,
        definitions=definitions,
        root_element=_local(root.tag),
    )


def _without(container: ET.Element, control: ET.Element) -> ET.Element:
    """A shallow view of ``container`` without its control record."""
    view = ET.Element(container.tag)
    view.extend(child for child in container if child is not control)
    return view


# ===========================================================================
# Entry point
# ===========================================================================


def parse_idoc(
    content: str,
    *,
    source_label: Optional[str] = None,
    definitions: Optional[SegmentDefinitionSet] = None,
) -> IdocFile:
    """Parse IDoc text in either form.

    Args:
        content: The IDoc text.
        source_label: Its name, for messages.
        definitions: Segment definitions to cut flat ``SDATA`` by (and describe XML fields with).

    Returns:
        The parsed file.

    Raises:
        IdocParseError: When the text is not a readable IDoc; see the module docstring.
    """
    label = _label(source_label)
    if not content or not content.strip():
        raise IdocParseError(f"Invalid or empty IDoc document{label}", code="INPUT_EMPTY")
    if content.startswith("﻿") or any(marker in content for marker in _ENCODING_FAULT_MARKERS):
        # Code-less on purpose: the pipeline's encoding rule names this fault precisely.
        raise IdocParseError(f"IDoc document{label} is not valid text in its declared encoding")
    if not is_idoc(content):
        raise IdocParseError(
            f"Content does not appear to be an SAP IDoc{label}: a flat IDoc begins with an "
            "EDI_DC40 control record, and an IDoc XML document holds an <IDOC> element."
        )
    if _first_content(content).startswith(_FLAT_MARKER):
        return _parse_flat(content, definitions, source_label)
    return _parse_xml_form(content, definitions, source_label)
