"""Natural / ADABAS DDM listing reader — FMT-11.4 (#5486).

A **DDM** (Data Definition Module) is Natural's description of an ADABAS file. Its listing has a
header and one line per field::

    DDM Name ...... CUSTOMER-FILE
    DB ............ 001
    File .......... 010
    Default Sequence AA

    T L DB Name                             F Leng  S D Remark
    - - -- -------------------------------- - ----  - - ------------------------------
      1 AA CUSTOMER-NUMBER                  A    10     U Unique descriptor
    M 1 AH PHONE-NUMBER                     A    20     N Multiple-value field
    P 1 AI CONTACT                                        Periodic group
      2 AJ CONTACT-TYPE                     A     2     N
    S 1 S1 SUPER-NAME-STATUS                A    41     D AB(1-40),AC(1-1)

A field line reads, left to right: an optional **type** in column 1 (``M`` multiple-value field,
``P`` periodic group, ``G`` group, ``R`` redefinition of the field with the same short name, ``S``
super-, ``Q`` sub-, ``H`` hyper-, ``C`` collation and ``N`` phonetic descriptor), the **level**, the
two-character ADABAS **short name**, the long **name**, then — for a data field — the **format**
(``A N P B F G L U D T I W``), the **length** (``n`` or ``n.d``), the optional **suppression** flag
(``N`` null suppression, ``F`` fixed storage) and the **descriptor** flag (``D`` descriptor, ``U``
unique, ``N`` none), and a free-text **remark**. A group or periodic-group header has no format.
Lines are read by token rather than by exact column, so a listing that drifts by a column still
reads. A remark starting ``NU`` or ``FI`` also marks null suppression or fixed storage; a
super / sub descriptor's remark lists its sources as ``AB(1-40),AC(1-1)``.

A **fileset** may carry Natural source beside the DDM (``.nsp`` / ``.nsl`` / ``.nsa`` / ``.nsg`` /
``.nat``): each ``DEFINE DATA`` ``VIEW OF <ddm>`` names the fields a program reads and the
occurrence bounds ``(1:n)`` it handles, which the DDM itself does not state.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_EMPTY`` — nothing to read;
* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark;
* ``FORMAT_MISMATCH`` — no ``DDM Name`` header;
* ``INPUT_MALFORMED`` — no column banner, a field line that does not read (an unknown type or
  format, a missing level, short name or length, a short name that is not two characters);
* ``INPUT_TRUNCATED`` — the last field line stops after its length while every other field line
  carries its descriptor column;
* ``INPUT_SEMANTIC_INVALID`` — no field lines, a level that skips or sits under a field that is not
  a group, a periodic group inside a periodic group, a name or short name used twice, a group with
  no members, redefinitions longer than their field, or a descriptor whose length differs from its
  sources;
* ``INPUT_REFERENCE_UNRESOLVED`` — a descriptor source, a redefinition or the default sequence
  naming a short name the DDM does not define, or a view naming a field the DDM lacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterator, List, Optional, Tuple

from .fileset import IntakeFileset
from .mainframe_misc_common import MainframeParseError, check_encoding, where

__all__ = [
    "DERIVED_DESCRIPTOR_TYPES",
    "DdmDescriptor",
    "DdmDocument",
    "DdmField",
    "DdmFile",
    "DdmView",
    "DdmViewField",
    "FORMATS",
    "FORMAT_KEY",
    "NATURAL_SOURCE_SUFFIXES",
    "SOURCE_SUFFIXES",
    "has_ddm_header",
    "parse_ddm_fileset",
    "parse_ddm_text",
]

#: The adapter / canonical format key.
FORMAT_KEY = "natural-ddm"

#: Natural source suffixes a fileset may carry beside its DDMs (read for ``DEFINE DATA`` views).
NATURAL_SOURCE_SUFFIXES = (".nsp", ".nsl", ".nsa", ".nsg", ".nsn", ".nat")
#: Suffixes of the files a fileset import reads besides its root.
SOURCE_SUFFIXES = (".ddm", ".txt", ".lst") + NATURAL_SOURCE_SUFFIXES

#: Format letters → what the field holds.
FORMATS: Dict[str, str] = {
    "A": "alphanumeric",
    "N": "unpacked-numeric",
    "P": "packed-numeric",
    "B": "binary",
    "F": "floating-point",
    "G": "floating-point",
    "L": "logical",
    "U": "unicode",
    "W": "wide-alphanumeric",
    "D": "date",
    "T": "time",
    "I": "integer",
}

#: Type prefixes of lines that describe a derived key rather than a stored field.
DERIVED_DESCRIPTOR_TYPES: Dict[str, str] = {
    "S": "superdescriptor",
    "Q": "subdescriptor",
    "H": "hyperdescriptor",
    "C": "collation-descriptor",
    "N": "phonetic-descriptor",
}
_FIELD_TYPES = frozenset({"", "M", "P", "G", "R"}) | frozenset(DERIVED_DESCRIPTOR_TYPES)

_HEADER_RE = re.compile(r"^\s*DDM\s+Name\s*\.{2,}\s*(\S+)", re.MULTILINE | re.IGNORECASE)
_BANNER_RE = re.compile(r"^\s*T\s+L\s+DB\s+Name\s+F\s+Leng\b", re.IGNORECASE)
_RULE_RE = re.compile(r"^[-\s]+$")
_SHORT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]$")
_NAME_RE = re.compile(r"^[A-Z#@$&][A-Z0-9#@$&_-]*$")
_LENGTH_RE = re.compile(r"^(\d+)(?:[.,](\d+))?$")
_SOURCE_RE = re.compile(r"^([A-Z][A-Z0-9])\((\d+)-(\d+)\)$")
_OCCURRENCE_REMARK_RE = re.compile(r"\bUp\s+to\s+(\d+)\s+occurrences?\b", re.IGNORECASE)
_VIEW_RE = re.compile(r"^\s*1\s+([A-Z#@$&][\w#@$&-]*)\s+VIEW\s+(?:OF\s+)?([A-Z#@$&][\w#@$&-]*)", re.IGNORECASE)
_VIEW_FIELD_RE = re.compile(r"^\s*(\d+)\s+([A-Z#@$&][\w#@$&-]*)\s*(?:\(\s*(\d+)\s*:\s*(\d+)\s*\))?\s*$", re.IGNORECASE)


# ===========================================================================
# The parsed document
# ===========================================================================


@dataclass
class DdmField:
    """One field line (a data field, a group, a periodic group or a redefinition).

    Attributes:
        name: The long name.
        short_name: The two-character ADABAS name.
        level: The level number.
        type_code: The type prefix (``""``, ``M``, ``P``, ``G`` or ``R``).
        format_code: The format letter; ``None`` for a group header.
        length: The ``Leng`` integer part (characters, digits or bytes by format).
        decimals: The digits after the decimal point of an ``N`` / ``P`` length.
        suppression: ``N`` (null suppression), ``F`` (fixed storage) or ``None``.
        descriptor: ``D`` (descriptor), ``U`` (unique descriptor) or ``None``.
        remark: The remark text.
        children: The members of a group, periodic group or redefined field.
        max_occurrences: The occurrence bound of an MU field or a periodic group, when one is stated.
        occurrence_source: Where the bound came from (``remark`` or ``view <name>``).
        line: The source line.
    """

    name: str
    short_name: str
    level: int
    type_code: str = ""
    format_code: Optional[str] = None
    length: Optional[int] = None
    decimals: Optional[int] = None
    suppression: Optional[str] = None
    descriptor: Optional[str] = None
    remark: str = ""
    children: List["DdmField"] = field(default_factory=list)
    max_occurrences: Optional[int] = None
    occurrence_source: Optional[str] = None
    line: int = 0

    @property
    def is_group(self) -> bool:
        """Whether the line is a group or periodic-group header (members, no format)."""
        return self.format_code is None

    @property
    def multiple_value(self) -> bool:
        """Whether the field is a multiple-value (MU) field."""
        return self.type_code == "M"

    @property
    def periodic(self) -> bool:
        """Whether the line is a periodic-group (PE) header."""
        return self.type_code == "P"

    @property
    def null_suppressed(self) -> bool:
        """Whether empty values are suppressed (``N`` in the S column or ``NU`` in the remark)."""
        return self.suppression == "N" or self.remark.upper().startswith("NU ") or self.remark.upper() == "NU"

    @property
    def fixed_storage(self) -> bool:
        """Whether the field is stored at fixed length (``F`` in the S column or ``FI`` in the remark)."""
        return self.suppression == "F" or self.remark.upper().startswith("FI ") or self.remark.upper() == "FI"

    def walk(self) -> Iterator["DdmField"]:
        """This field and every member below it, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class DdmDescriptor:
    """One derived key: a super-, sub-, hyper-, collation or phonetic descriptor.

    Attributes:
        kind: ``superdescriptor``, ``subdescriptor`` … (see :data:`DERIVED_DESCRIPTOR_TYPES`).
        name: The long name.
        short_name: The two-character ADABAS name.
        format_code: The format of the derived value.
        length: Its length.
        unique: Whether it is a unique descriptor.
        sources: ``(short name, from byte, to byte)`` of each source field, in order.
        remark: The remark text.
        line: The source line.
    """

    kind: str
    name: str
    short_name: str
    format_code: Optional[str]
    length: Optional[int]
    unique: bool
    sources: List[Tuple[str, int, int]] = field(default_factory=list)
    remark: str = ""
    line: int = 0


@dataclass
class DdmViewField:
    """One field of a ``DEFINE DATA`` view: its name, level and occurrence bounds."""

    name: str
    level: int
    lower: Optional[int] = None
    upper: Optional[int] = None
    line: int = 0


@dataclass
class DdmView:
    """One ``1 <name> VIEW OF <ddm>`` of a Natural program.

    Attributes:
        name: The view's name.
        ddm: The DDM it is a view of.
        fields: Its fields, in order.
        path: The file it was read from.
        line: The line the view starts on.
    """

    name: str
    ddm: str
    fields: List[DdmViewField] = field(default_factory=list)
    path: Optional[str] = None
    line: int = 0


@dataclass
class DdmFile:
    """One DDM listing.

    Attributes:
        name: ``DDM Name``.
        database: ``DB`` number.
        file_number: ``File`` number.
        default_sequence: The ``Default Sequence`` short name, when declared.
        fields: The level-1 fields and groups, in order (members nest).
        descriptors: The derived keys, in order.
        path: The file it was read from.
    """

    name: str
    database: Optional[str] = None
    file_number: Optional[str] = None
    default_sequence: Optional[str] = None
    fields: List[DdmField] = field(default_factory=list)
    descriptors: List[DdmDescriptor] = field(default_factory=list)
    path: Optional[str] = None

    def walk(self) -> Iterator[DdmField]:
        """Every field, group and member, depth first."""
        for item in self.fields:
            yield from item.walk()

    def by_short_name(self, short_name: str) -> Optional[DdmField]:
        """The field (not a redefinition) with ``short_name``, or ``None``."""
        return next((f for f in self.walk() if f.short_name == short_name and f.type_code != "R"), None)

    def by_name(self, name: str) -> Optional[DdmField]:
        """The field, group or redefinition with long ``name``, or ``None``."""
        return next((f for f in self.walk() if f.name == name), None)


@dataclass
class DdmDocument:
    """Everything one import read.

    Attributes:
        ddms: The DDM listings, in reading order.
        views: The ``DEFINE DATA`` views read from Natural source in the fileset.
        sources: Every file's text, keyed by path (or label).
        is_fileset: Whether the import was a fileset.
        label: The upload's label.
    """

    ddms: List[DdmFile] = field(default_factory=list)
    views: List[DdmView] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)
    is_fileset: bool = False
    label: Optional[str] = None

    def ddm(self, name: str) -> Optional[DdmFile]:
        """The DDM named ``name`` read in this upload, or ``None``."""
        return next((d for d in self.ddms if d.name == name), None)


# ===========================================================================
# Sniffing
# ===========================================================================


def has_ddm_header(text: str) -> Tuple[bool, bool]:
    """Whether ``text`` carries a ``DDM Name`` header, and whether it also carries the column banner.

    Returns:
        ``(header, banner)``.
    """
    header = bool(_HEADER_RE.search(text))
    return header, header and any(_BANNER_RE.match(line) for line in text.splitlines())


# ===========================================================================
# Field lines
# ===========================================================================


def _malformed(message: str) -> MainframeParseError:
    return MainframeParseError(message, code="INPUT_MALFORMED")


def _read_line(raw: str, number: int, path: Optional[str]) -> Tuple[DdmField, Optional[DdmDescriptor], bool]:
    """Read one field line.

    Returns:
        ``(field, descriptor, has_descriptor_column)`` — ``descriptor`` is set for a derived-key
        line (the ``field`` then only carries its names and level); the flag says whether the line
        reached its descriptor column.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a line that does not read.
    """
    at = f"Line {number}{where(path)}"
    type_code = ""
    body = raw
    if raw[:1] != " ":
        type_code = raw[:1].upper()
        if type_code not in _FIELD_TYPES or raw[1:2] != " ":
            raise _malformed(
                f"{at} starts with {raw.split()[0]!r}, which is not a DDM field type (M, P, G, R, S, Q, H)"
            )
        body = raw[1:]
    tokens = body.split()
    if len(tokens) < 3:
        raise _malformed(f"{at} does not have a level, a short name and a name: {raw.strip()!r}")
    level_text, short_name, name = tokens[0], tokens[1].upper(), tokens[2].upper()
    if not level_text.isdigit() or not 1 <= int(level_text) <= 9:
        raise _malformed(f"{at} has level {level_text!r}; a DDM level is a digit 1–9")
    if not _SHORT_NAME_RE.match(short_name):
        raise _malformed(f"{at} has short name {tokens[1]!r}; an ADABAS short name is two characters")
    if not _NAME_RE.match(name):
        raise _malformed(f"{at} has field name {tokens[2]!r}, which is not a Natural name")
    item = DdmField(name=name, short_name=short_name, level=int(level_text), type_code=type_code, line=number)
    rest = tokens[3:]
    if type_code in ("P", "G") or not rest or rest[0].upper() not in FORMATS or len(rest) < 2:
        if type_code in ("P", "G") or not rest:
            item.remark = " ".join(rest)
            return item, None, False
        raise _malformed(f"{at} ({name}) has no readable format and length: {' '.join(rest)!r}")
    format_code = rest[0].upper()
    length = _LENGTH_RE.match(rest[1])
    if length is None:
        raise _malformed(f"{at} ({name}) has length {rest[1]!r}; a length is n or n.d")
    item.format_code = format_code
    item.length = int(length.group(1))
    item.decimals = int(length.group(2)) if length.group(2) is not None else None
    flags: List[str] = []
    index = 2
    while index < len(rest) and len(flags) < 2 and len(rest[index]) == 1 and rest[index].upper() in "DUNF":
        flags.append(rest[index].upper())
        index += 1
    descriptor_flag: Optional[str] = flags[-1] if flags else None
    if len(flags) == 2:
        item.suppression = flags[0]
    item.descriptor = descriptor_flag if descriptor_flag in ("D", "U") else None
    item.remark = " ".join(rest[index:])
    derived: Optional[DdmDescriptor] = None
    if type_code in DERIVED_DESCRIPTOR_TYPES:
        derived = DdmDescriptor(
            kind=DERIVED_DESCRIPTOR_TYPES[type_code],
            name=name,
            short_name=short_name,
            format_code=format_code,
            length=item.length,
            unique=descriptor_flag == "U",
            sources=_descriptor_sources(rest[index] if index < len(rest) else ""),
            remark=item.remark,
            line=number,
        )
    return item, derived, bool(flags)


def _descriptor_sources(token: str) -> List[Tuple[str, int, int]]:
    """``AB(1-40),AC(1-1)`` → ``[("AB", 1, 40), ("AC", 1, 1)]``; anything else → ``[]``."""
    sources: List[Tuple[str, int, int]] = []
    for part in token.upper().split(","):
        match = _SOURCE_RE.match(part)
        if match is None:
            return []
        sources.append((match.group(1), int(match.group(2)), int(match.group(3))))
    return sources


# ===========================================================================
# A DDM listing
# ===========================================================================


def _header_value(text: str, label: str) -> Optional[str]:
    match = re.search(rf"^\s*{label}\s*\.{{2,}}\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1) if match else None


def _read_ddm(text: str, path: Optional[str]) -> DdmFile:
    """Read one DDM listing into a :class:`DdmFile`.

    Raises:
        MainframeParseError: See the module docstring.
    """
    header = _HEADER_RE.search(text)
    assert header is not None
    ddm = DdmFile(
        name=header.group(1).upper(),
        database=_header_value(text, "DB"),
        file_number=_header_value(text, "File"),
        path=path,
    )
    sequence = re.search(r"^\s*Default\s+Sequence[ \t]*(\S*)[ \t]*$", text, re.MULTILINE | re.IGNORECASE)
    if sequence and sequence.group(1):
        ddm.default_sequence = sequence.group(1).upper()
    lines = text.splitlines()
    banner = next((i for i, line in enumerate(lines) if _BANNER_RE.match(line)), None)
    if banner is None:
        raise _malformed(f"The DDM listing{where(path)} has no 'T L DB Name … F Leng S D Remark' column banner")
    read: List[Tuple[DdmField, Optional[DdmDescriptor], bool]] = []
    for index in range(banner + 1, len(lines)):
        raw = lines[index].rstrip()
        if not raw.strip() or raw.startswith("*") or (index == banner + 1 and _RULE_RE.match(raw)):
            continue
        read.append(_read_line(raw, index + 1, path))
    data = [entry for entry in read if entry[1] is None]
    if not data:
        raise MainframeParseError(
            f"The DDM {ddm.name}{where(path)} has no field lines, so it describes no record to model",
            code="INPUT_SEMANTIC_INVALID",
        )
    formatted = [entry for entry in read if entry[0].format_code is not None]
    last = read[-1]
    if last[0].format_code is not None and not last[2] and all(entry[2] for entry in formatted[:-1]):
        raise MainframeParseError(
            f"The DDM listing{where(path)} ends in the middle of the field line at line {last[0].line} "
            f"({last[0].name}): it stops after the length, before the descriptor column every other line has",
            code="INPUT_TRUNCATED",
        )
    ddm.descriptors = [entry[1] for entry in read if entry[1] is not None]
    ddm.fields = _nest([(entry[0], entry[1] is not None) for entry in read], ddm, path)
    _check_ddm(ddm)
    return ddm


def _nest(items: List[Tuple[DdmField, bool]], ddm: DdmFile, path: Optional[str]) -> List[DdmField]:
    """Build the level tree: members under the group, periodic group or redefined field above them.

    Args:
        items: Every line in order, each flagged when it is a derived-descriptor line. A derived
            descriptor is not a field, but it closes the groups above it like any level-1 line.
        ddm: The DDM being read, for messages.
        path: The file, for messages.

    Returns:
        The level-1 fields and groups, members nested.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` for a level that cannot nest.
    """
    roots: List[DdmField] = []
    stack: List[DdmField] = []
    for item, derived in items:
        at = f"{item.name} (line {item.line}) in DDM {ddm.name}{where(path)}"
        while stack and stack[-1].level >= item.level:
            stack.pop()
        if derived:
            continue
        if item.level == 1:
            if item.type_code == "R":
                raise MainframeParseError(f"The redefinition {at} is at level 1", code="INPUT_SEMANTIC_INVALID")
            roots.append(item)
        else:
            if not stack or stack[-1].level != item.level - 1:
                raise MainframeParseError(
                    f"{at} is at level {item.level} with no level-{item.level - 1} group above it",
                    code="INPUT_SEMANTIC_INVALID",
                )
            parent = stack[-1]
            if item.type_code == "R":
                if parent.short_name != item.short_name or parent.is_group:
                    raise MainframeParseError(
                        f"The redefinition {at} names short name {item.short_name}, but the field above it is "
                        f"{parent.short_name} ({parent.name})",
                        code="INPUT_REFERENCE_UNRESOLVED",
                    )
            elif not parent.is_group:
                raise MainframeParseError(
                    f"{at} sits under {parent.name}, which is a field and not a group", code="INPUT_SEMANTIC_INVALID"
                )
            if item.periodic and any(s.periodic for s in stack):
                raise MainframeParseError(
                    f"The periodic group {at} sits inside another periodic group", code="INPUT_SEMANTIC_INVALID"
                )
            parent.children.append(item)
        stack.append(item)
    return roots


def _check_ddm(ddm: DdmFile) -> None:
    """Refuse a DDM whose names, groups, redefinitions or descriptors do not hold together.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` or ``INPUT_REFERENCE_UNRESOLVED``.
    """
    at = f"DDM {ddm.name}{where(ddm.path)}"
    names: Dict[str, int] = {}
    short_names: Dict[str, int] = {}
    entries = [(f.name, f.short_name, f.line, f.type_code == "R") for f in ddm.walk()] + [
        (d.name, d.short_name, d.line, False) for d in ddm.descriptors
    ]
    for name, short_name, line, redefinition in entries:
        if name in names:
            raise MainframeParseError(
                f"{at} uses the name {name} twice (lines {names[name]} and {line})", code="INPUT_SEMANTIC_INVALID"
            )
        names[name] = line
        if redefinition:
            continue
        if short_name in short_names:
            raise MainframeParseError(
                f"{at} uses the short name {short_name} twice (lines {short_names[short_name]} and {line})",
                code="INPUT_SEMANTIC_INVALID",
            )
        short_names[short_name] = line
    for item in ddm.walk():
        if item.is_group and not item.children:
            raise MainframeParseError(
                f"The group {item.name} (line {item.line}) of {at} has no members", code="INPUT_SEMANTIC_INVALID"
            )
        redefinitions = [c for c in item.children if c.type_code == "R"]
        if redefinitions and item.length is not None:
            total = sum(c.length or 0 for c in redefinitions)
            if total > item.length:
                raise MainframeParseError(
                    f"The redefinitions of {item.name} in {at} take {total} positions, more than its {item.length}",
                    code="INPUT_SEMANTIC_INVALID",
                )
        if remark := _OCCURRENCE_REMARK_RE.search(item.remark):
            if item.multiple_value or item.periodic:
                item.max_occurrences, item.occurrence_source = int(remark.group(1)), "remark"
    if ddm.default_sequence and ddm.by_short_name(ddm.default_sequence) is None:
        raise MainframeParseError(
            f"The default sequence {ddm.default_sequence} of {at} is not a short name the DDM defines",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    for descriptor in ddm.descriptors:
        where_descriptor = f"{descriptor.kind} {descriptor.short_name} ({descriptor.name}) of {at}"
        missing = [s for s, _, _ in descriptor.sources if ddm.by_short_name(s) is None]
        if missing:
            raise MainframeParseError(
                f"The {where_descriptor} is built from {', '.join(missing)}, which the DDM does not define",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        if descriptor.kind in ("superdescriptor", "subdescriptor") and not descriptor.sources:
            raise MainframeParseError(
                f"The {where_descriptor} does not list its source fields (AB(1-40),AC(1-1)) in the remark",
                code="INPUT_SEMANTIC_INVALID",
            )
        if any(start < 1 or end < start for _, start, end in descriptor.sources):
            raise MainframeParseError(f"The {where_descriptor} has an empty byte range", code="INPUT_SEMANTIC_INVALID")
        total = sum(end - start + 1 for _, start, end in descriptor.sources)
        if descriptor.sources and descriptor.length is not None and total != descriptor.length:
            raise MainframeParseError(
                f"The {where_descriptor} is {descriptor.length} long, but its sources give {total}",
                code="INPUT_SEMANTIC_INVALID",
            )


# ===========================================================================
# Natural DEFINE DATA views
# ===========================================================================


def _read_views(text: str, path: Optional[str]) -> List[DdmView]:
    """Read every ``1 <name> VIEW OF <ddm>`` block of a Natural source's ``DEFINE DATA``."""
    views: List[DdmView] = []
    current: Optional[DdmView] = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("/*", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        view = _VIEW_RE.match(line)
        if view:
            current = DdmView(name=view.group(1).upper(), ddm=view.group(2).upper(), path=path, line=number)
            views.append(current)
            continue
        if current is None:
            continue
        member = _VIEW_FIELD_RE.match(line)
        if member is None or int(member.group(1)) < 2:
            current = None
            continue
        current.fields.append(
            DdmViewField(
                name=member.group(2).upper(),
                level=int(member.group(1)),
                lower=int(member.group(3)) if member.group(3) else None,
                upper=int(member.group(4)) if member.group(4) else None,
                line=number,
            )
        )
    return views


def _apply_views(document: DdmDocument) -> None:
    """Check each view against its DDM (when uploaded) and carry its occurrence bounds onto the DDM.

    Raises:
        MainframeParseError: ``INPUT_REFERENCE_UNRESOLVED`` for a view field the DDM lacks.
    """
    for view in document.views:
        ddm = document.ddm(view.ddm)
        if ddm is None:
            continue
        for member in view.fields:
            target = ddm.by_name(member.name)
            if target is None:
                raise MainframeParseError(
                    f"View {view.name}{where(view.path)} (line {member.line}) reads {member.name}, which DDM "
                    f"{ddm.name} does not define",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
            if member.upper is not None and (target.multiple_value or target.periodic):
                if target.max_occurrences is None or member.upper > target.max_occurrences:
                    target.max_occurrences = member.upper
                    target.occurrence_source = f"view {view.name}"


# ===========================================================================
# Entry points
# ===========================================================================


def _read_file(text: str, path: Optional[str], document: DdmDocument, *, require: bool) -> bool:
    """Read one file into ``document``: a DDM listing, or (in a fileset) Natural source with views.

    Args:
        require: Refuse a file that is not a DDM listing (``FORMAT_MISMATCH``) instead of skipping
            it.

    Returns:
        Whether the file was read.
    """
    check_encoding(text, path, what="DDM listing")
    if _HEADER_RE.search(text):
        document.ddms.append(_read_ddm(text, path))
    elif require:
        raise MainframeParseError(
            f"No 'DDM Name ......' header{where(path)} was found; this is not a Natural DDM listing",
            code="FORMAT_MISMATCH",
        )
    elif path and PurePosixPath(path).suffix.lower() in NATURAL_SOURCE_SUFFIXES:
        views = _read_views(text, path)
        if not views:
            return False
        document.views.extend(views)
    else:
        return False
    document.sources[path or "input.ddm"] = text
    return True


def _check_document(document: DdmDocument) -> None:
    seen: Dict[str, str] = {}
    for ddm in document.ddms:
        if ddm.name in seen:
            raise MainframeParseError(
                f"DDM {ddm.name} is defined twice ({seen[ddm.name]} and {ddm.path or 'the input'})",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[ddm.name] = ddm.path or "the input"
    _apply_views(document)


def parse_ddm_text(text: str, *, label: Optional[str] = None) -> DdmDocument:
    """Parse one uploaded DDM listing.

    Args:
        text: The file text.
        label: The upload's file name, for messages.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    if text is None or not text.strip():
        raise MainframeParseError("The DDM listing is empty", code="INPUT_EMPTY")
    document = DdmDocument(label=label)
    _read_file(text, label, document, require=True)
    _check_document(document)
    return document


def parse_ddm_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> DdmDocument:
    """Parse DDM listings uploaded together, with the Natural views over them.

    Members with a :data:`SOURCE_SUFFIXES` suffix are read; a member that is neither a DDM listing
    nor Natural source with a view is ignored unless it is the root.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    document = DdmDocument(label=label or fileset.root, is_fileset=True)
    for path in sorted(fileset.members):
        text = fileset.members[path]
        if PurePosixPath(path).suffix.lower() not in SOURCE_SUFFIXES and path != fileset.root:
            continue
        if not text.strip():
            continue
        _read_file(text, path, document, require=path == fileset.root)
    if not document.ddms:
        raise MainframeParseError("The upload holds no Natural DDM listing", code="FORMAT_MISMATCH")
    _check_document(document)
    return document
