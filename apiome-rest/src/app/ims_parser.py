"""IMS DBD and PSB reader — FMT-11.2 (#5482).

Reads the two macro sources that describe an IMS hierarchical database and a program's view of it:

* **DBD** (Database Description) — ``DBD NAME=…,ACCESS=(…)`` opens it, ``DATASET`` / ``AREA`` name
  its data sets, ``SEGM NAME=…,PARENT=…,BYTES=…`` declares a segment type, and ``FIELD
  NAME=(f,SEQ,U|M),BYTES=…,START=…,TYPE=…`` a field of the segment declared before it. ``LCHILD``
  pairs a segment with an index or a logical child; the ``XDFLD`` after an ``LCHILD`` defines the
  search field of a secondary index. ``DBDGEN`` closes it. A ``ACCESS=LOGICAL`` DBD builds its
  segments from physical ones named by ``SOURCE=``.
* **PSB** (Program Specification Block) — ``PCB TYPE=DB,DBDNAME=…,PROCOPT=…`` opens a database
  view, ``SENSEG NAME=…,PARENT=…,PROCOPT=…`` names a segment the program is sensitive to, and
  ``SENFLD NAME=…,START=…`` a field of it. ``PCB TYPE=TP`` is a message destination and ``PCB
  TYPE=GSAM`` a sequential file. ``PSBGEN PSBNAME=…`` closes it.

Both are assembler statements: an optional label in column 1, the operation, then comma-separated
``KEYWORD=value`` operands ending at the first blank. A statement is continued by a non-blank
character after its operands in **column 72**, and the continuation's operands resume in column 16.
Columns 73–80 are the sequence field, so a mark that lands one column late (``…,  X`` ending in
column 73) is still read as a continuation mark when it stands apart from the operands; an operand
that itself runs into column 72 is an over-long line, not a continued one. ``*`` in column 1 starts
a comment line.

The **hierarchy** is rebuilt from ``PARENT=``, not from the file order: ``PARENT=0`` (or no
``PARENT``) is the root, and any other value names the segment's physical parent.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_EMPTY`` — nothing to read;
* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark;
* ``FORMAT_MISMATCH`` — no ``DBD`` and no ``PCB`` statement;
* ``INPUT_MALFORMED`` — an operation that is not a DBD / PSB macro (a continuation line written
  without the column-72 mark reads as one), a continuation line that does not start in column 16,
  an operand list ending in a comma with more statements after it, unbalanced parentheses, a
  statement outside the block it belongs to (``FIELD`` before any ``SEGM``, ``SENSEG`` outside a
  ``PCB``), a missing ``NAME``, or a non-numeric ``BYTES`` / ``START``;
* ``INPUT_TRUNCATED`` — the source ends on a continuation mark, or before the ``DBDGEN`` /
  ``PSBGEN`` that closes it;
* ``INPUT_SEMANTIC_INVALID`` — a DBD with no segment, no root or more than one root, a ``PARENT``
  cycle, a name used twice, a field that runs past its segment, a ``SENSEG`` whose ``PARENT``
  contradicts the DBD, or an unknown ``FIELD`` ``TYPE``;
* ``INPUT_REFERENCE_UNRESOLVED`` — a ``PARENT`` naming no segment of the DBD, an ``XDFLD`` naming a
  segment or field that does not exist, or (when the PSB's DBD is in the upload) a ``SENSEG`` /
  ``SENFLD`` the DBD does not define.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterator, List, Optional, Tuple, Union

from .fileset import IntakeFileset
from .mainframe_misc_common import MainframeParseError, check_encoding, where

__all__ = [
    "FORMAT_KEY",
    "FIELD_TYPES",
    "PROCOPT_CODES",
    "SOURCE_SUFFIXES",
    "ImsDbd",
    "ImsDocument",
    "ImsField",
    "ImsLChild",
    "ImsPcb",
    "ImsPsb",
    "ImsSegment",
    "ImsSenfld",
    "ImsSenseg",
    "ImsSourceSegment",
    "ImsXdfld",
    "OperandValue",
    "decode_procopt",
    "has_ims_statements",
    "parse_ims_fileset",
    "parse_ims_text",
]

#: The adapter / canonical format key.
FORMAT_KEY = "ims"

#: Suffixes of the files a fileset import reads besides its root.
SOURCE_SUFFIXES = (".dbd", ".psb", ".asm", ".mac", ".txt")

#: ``FIELD TYPE=`` codes → what the bytes hold.
FIELD_TYPES: Dict[str, str] = {
    "C": "character",
    "X": "hexadecimal",
    "P": "packed-decimal",
    "Z": "zoned-decimal",
    "H": "halfword-binary",
    "F": "fullword-binary",
}

#: ``PROCOPT`` letters → the access intent they declare. ``A`` is all of get, insert, replace and
#: delete.
PROCOPT_CODES: Dict[str, str] = {
    "G": "get",
    "I": "insert",
    "R": "replace",
    "D": "delete",
    "A": "all",
    "P": "path",
    "K": "key-sensitive",
    "O": "read-without-integrity",
    "N": "no-abend-on-invalid-data",
    "T": "retry-on-invalid-data",
    "E": "exclusive",
    "L": "load",
    "S": "sequential",
    "H": "high-speed-sequential",
    "M": "multiple-positioning",
}

_DBD_OPERATIONS = frozenset({"DBD", "DATASET", "AREA", "SEGM", "FIELD", "LCHILD", "XDFLD", "DBDGEN"})
_PSB_OPERATIONS = frozenset({"PCB", "SENSEG", "SENFLD", "PSBGEN"})
#: Statements that are assembler housekeeping, not part of the description.
_ASSEMBLER_DIRECTIVES = frozenset({"PRINT", "TITLE", "SPACE", "EJECT", "PUNCH", "ISEQ", "ICTL", "FINISH"})

_DBD_RE = re.compile(r"^(?:\S{1,8})?\s+DBD\s+\S*NAME=", re.MULTILINE)
_PCB_RE = re.compile(r"^(?:\S{1,8})?\s+PCB\s+\S*TYPE=", re.MULTILINE)
_SEGMENT_RE = re.compile(r"^(?:\S{1,8})?\s+(?:SEGM|SENSEG)\s+\S*NAME=", re.MULTILINE)

#: How deep operand parentheses may nest before the statement is refused (IMS needs three).
_MAX_OPERAND_DEPTH = 8

OperandValue = Union[str, Tuple["OperandValue", ...]]


# ===========================================================================
# The parsed document
# ===========================================================================


@dataclass
class ImsField:
    """One ``FIELD``.

    Attributes:
        name: The field name (``/SX`` / ``/CK`` names a system-related field).
        start: 1-based byte position in the segment; ``None`` when not declared.
        length: ``BYTES``; ``None`` when not declared.
        type_code: The ``TYPE`` letter (``C`` when not declared).
        sequence: Whether the field is the segment's sequence (key) field.
        unique: For a sequence field, whether it is unique (``U``) or not (``M``).
        operands: Every other operand, as written.
        line: The source line the statement starts on.
    """

    name: str
    start: Optional[int]
    length: Optional[int]
    type_code: str = "C"
    sequence: bool = False
    unique: Optional[bool] = None
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0

    @property
    def system_related(self) -> bool:
        """Whether this is a ``/SX`` / ``/CK`` system-related field rather than segment data."""
        return self.name.startswith("/")


@dataclass
class ImsLChild:
    """One ``LCHILD``: an index pointer or a logical child of the segment it follows.

    Attributes:
        segment: The paired segment's name.
        dbd: The database that defines it.
        pointer: ``POINTER=`` (``INDX`` for an index, ``SNGL`` / ``DBLE`` / ``NONE`` otherwise).
        operands: Every other operand, as written.
        line: The source line.
    """

    segment: str
    dbd: Optional[str]
    pointer: Optional[str]
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0

    @property
    def is_index(self) -> bool:
        """Whether the pairing is with an index database (``POINTER=INDX``)."""
        return self.pointer == "INDX"


@dataclass
class ImsXdfld:
    """One ``XDFLD``: the search field of the secondary index named by the ``LCHILD`` before it.

    Attributes:
        name: The search field's name (used in a program's SSA).
        index: The ``LCHILD`` it belongs to.
        source_segment: ``SEGMENT=`` — the index source segment (the target segment when omitted).
        search: ``SRCH`` — the source fields the key is built from, in order.
        subsequence: ``SUBSEQ`` — fields appended to make the key unique.
        duplicate_data: ``DDATA`` — fields copied into the index entry.
        null_value: ``NULLVAL`` — the value that suppresses an index entry.
        operands: Every other operand, as written.
        line: The source line.
    """

    name: str
    index: ImsLChild
    source_segment: str
    search: Tuple[str, ...]
    subsequence: Tuple[str, ...] = ()
    duplicate_data: Tuple[str, ...] = ()
    null_value: Optional[str] = None
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0


@dataclass
class ImsSourceSegment:
    """One ``SOURCE=`` entry of a logical DBD's segment: ``(segment, DATA|KEY, dbd)``."""

    segment: str
    mode: str
    dbd: str


@dataclass
class ImsSegment:
    """One ``SEGM``.

    Attributes:
        name: The segment name.
        parent: The physical parent's name; ``None`` for the root.
        parent_pointer: The pointer type given with the parent (``SNGL`` / ``DBLE``), when any.
        logical_parent: ``(segment, PHYSICAL|VIRTUAL, dbd)`` of a logical child's logical parent.
        max_bytes: ``BYTES`` (or the first of ``BYTES=(max,min)``); ``None`` for a logical segment.
        min_bytes: The minimum of a variable-length segment.
        fields: The fields, in source order.
        lchildren: The ``LCHILD`` statements that follow it.
        xdflds: The ``XDFLD`` statements that follow it.
        sources: ``SOURCE=`` of a logical DBD's segment.
        operands: Every other operand, as written.
        line: The source line.
    """

    name: str
    parent: Optional[str]
    parent_pointer: Optional[str] = None
    logical_parent: Optional[Tuple[str, str, Optional[str]]] = None
    max_bytes: Optional[int] = None
    min_bytes: Optional[int] = None
    fields: List[ImsField] = field(default_factory=list)
    lchildren: List[ImsLChild] = field(default_factory=list)
    xdflds: List[ImsXdfld] = field(default_factory=list)
    sources: List[ImsSourceSegment] = field(default_factory=list)
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0

    @property
    def variable_length(self) -> bool:
        """Whether the segment is variable length (``BYTES=(max,min)``)."""
        return self.min_bytes is not None

    def field(self, name: str) -> Optional[ImsField]:
        """The field named ``name``, or ``None``."""
        return next((f for f in self.fields if f.name == name), None)


@dataclass
class ImsDbd:
    """One database description.

    Attributes:
        name: ``DBD NAME=``.
        access: ``ACCESS=`` as written (``("HDAM", "OSAM")``, ``("LOGICAL",)``).
        operands: Every other ``DBD`` operand (``RMNAME``, ``PASSWD`` …), as written.
        datasets: The ``DATASET`` / ``AREA`` statements' operands, in order.
        segments: The segments, in source order.
        path: The file it was read from.
    """

    name: str
    access: Tuple[str, ...]
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    datasets: List[Dict[str, OperandValue]] = field(default_factory=list)
    segments: List[ImsSegment] = field(default_factory=list)
    path: Optional[str] = None

    @property
    def logical(self) -> bool:
        """Whether this is a ``ACCESS=LOGICAL`` database built from physical ones."""
        return bool(self.access) and self.access[0] == "LOGICAL"

    @property
    def root(self) -> ImsSegment:
        """The root segment (validated to exist by the reader)."""
        return next(s for s in self.segments if s.parent is None)

    def segment(self, name: str) -> Optional[ImsSegment]:
        """The segment named ``name``, or ``None``."""
        return next((s for s in self.segments if s.name == name), None)

    def children(self, name: str) -> List[ImsSegment]:
        """The segments whose physical parent is ``name``, in source order."""
        return [s for s in self.segments if s.parent == name]


@dataclass
class ImsSenfld:
    """One ``SENFLD``: a field the program is sensitive to.

    Attributes:
        name: The DBD field's name.
        start: 1-based position of the field in the program's I/O area.
        replace: ``REPL=`` — whether the program may replace it (``YES`` when not declared).
        line: The source line.
    """

    name: str
    start: Optional[int]
    replace: bool = True
    line: int = 0


@dataclass
class ImsSenseg:
    """One ``SENSEG``: a segment the program is sensitive to.

    Attributes:
        name: The DBD segment's name.
        parent: The sensitive parent's name; ``None`` for the root.
        procopt: The segment's ``PROCOPT``; ``None`` to inherit the PCB's.
        fields: The ``SENFLD``s that follow it (empty: every field is sensitive).
        operands: Every other operand, as written.
        line: The source line.
    """

    name: str
    parent: Optional[str]
    procopt: Optional[str] = None
    fields: List[ImsSenfld] = field(default_factory=list)
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0


@dataclass
class ImsPcb:
    """One ``PCB``.

    Attributes:
        name: The label, ``PCBNAME=``, or ``PCB<n>`` by position.
        pcb_type: ``DB``, ``TP`` or ``GSAM``.
        dbd_name: ``DBDNAME=`` of a database PCB.
        procopt: The PCB's ``PROCOPT`` (``G`` when not declared on a database PCB).
        key_length: ``KEYLEN=``.
        processing_sequence: ``PROCSEQ=`` — the secondary index the program reads through.
        sensegs: The sensitive segments, in source order.
        operands: Every other operand, as written.
        line: The source line.
    """

    name: str
    pcb_type: str
    dbd_name: Optional[str] = None
    procopt: Optional[str] = None
    key_length: Optional[int] = None
    processing_sequence: Optional[str] = None
    sensegs: List[ImsSenseg] = field(default_factory=list)
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0

    def senseg(self, name: str) -> Optional[ImsSenseg]:
        """The sensitive segment named ``name``, or ``None``."""
        return next((s for s in self.sensegs if s.name == name), None)


@dataclass
class ImsPsb:
    """One program specification block.

    Attributes:
        name: ``PSBGEN PSBNAME=`` (the file's stem when not declared).
        language: ``LANG=``.
        pcbs: The PCBs, in source order.
        operands: Every other ``PSBGEN`` operand, as written.
        path: The file it was read from.
    """

    name: str
    language: Optional[str] = None
    pcbs: List[ImsPcb] = field(default_factory=list)
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    path: Optional[str] = None


@dataclass
class ImsDocument:
    """Everything one import read.

    Attributes:
        dbds: The database descriptions, in reading order.
        psbs: The program specification blocks, in reading order.
        sources: Every file's text, keyed by path (or label).
        is_fileset: Whether the import was a fileset.
        label: The upload's label.
    """

    dbds: List[ImsDbd] = field(default_factory=list)
    psbs: List[ImsPsb] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)
    is_fileset: bool = False
    label: Optional[str] = None

    def dbd(self, name: Optional[str]) -> Optional[ImsDbd]:
        """The DBD named ``name`` read in this upload, or ``None``."""
        return next((d for d in self.dbds if d.name == name), None)


# ===========================================================================
# Sniffing
# ===========================================================================


def has_ims_statements(text: str) -> Tuple[bool, bool]:
    """Whether ``text`` holds a ``DBD`` / ``PCB`` statement, and whether it also declares segments.

    Returns:
        ``(opens, segments)`` — a ``DBD NAME=`` or ``PCB TYPE=`` statement is present; a ``SEGM`` or
        ``SENSEG`` statement is present too.
    """
    opens = bool(_DBD_RE.search(text) or _PCB_RE.search(text))
    return opens, opens and bool(_SEGMENT_RE.search(text))


def decode_procopt(procopt: str) -> Dict[str, object]:
    """Decode a ``PROCOPT`` into its declared access intent.

    Args:
        procopt: The value as written (``G``, ``AP``, ``GIRD``, ``LS`` …).

    Returns:
        ``{"code", "intents", "get", "insert", "replace", "delete", "path"}`` plus ``"unrecognised"``
        when a letter is outside :data:`PROCOPT_CODES`. ``A`` grants all four of get, insert,
        replace and delete; ``L`` (load) grants insert.
    """
    letters = procopt.upper()
    allows_all = "A" in letters
    unrecognised = [c for c in letters if c not in PROCOPT_CODES]
    return {
        "code": letters,
        "intents": [PROCOPT_CODES[c] for c in letters if c in PROCOPT_CODES],
        "get": allows_all or "G" in letters,
        "insert": allows_all or "I" in letters or "L" in letters,
        "replace": allows_all or "R" in letters,
        "delete": allows_all or "D" in letters,
        "path": "P" in letters,
        **({"unrecognised": unrecognised} if unrecognised else {}),
    }


# ===========================================================================
# Assembler statements
# ===========================================================================


@dataclass
class _Statement:
    label: Optional[str]
    operation: str
    operands: str
    line: int


def _read_operand_field(text: str, start: int) -> Tuple[str, int, bool]:
    """Read the operand field of ``text`` from ``start`` up to the first blank outside quotes.

    Returns:
        ``(operands, end, in_quote)`` — what was read, the index reading stopped at, and whether a
        quoted value is still open at the end of ``text``.
    """
    out: List[str] = []
    index = start
    in_quote = False
    while index < len(text):
        char = text[index]
        if char == "'":
            in_quote = not in_quote
        elif char == " " and not in_quote:
            break
        out.append(char)
        index += 1
    return "".join(out), index, in_quote


def _operand_line(raw: str, start: int) -> Tuple[str, bool]:
    """Read one line's operand field and whether a continuation mark follows it.

    The operand field ends at the first blank (outside quotes) at or before column 71, and the
    mark belongs in column 72. Two departures from the strict rule are accepted:

    * an operand that itself runs into column 72 and beyond is an **over-long line**, read whole and
      not continued — unless it ends exactly in column 72 right after a comma, which is a mark
      written flush against a full operand field;
    * a mark that lands one column late (column 72 blank, a lone character in column 73 and
      nothing after it) is still a mark: a real sequence field in columns 73–80 is never one
      character.

    Args:
        raw: The line.
        start: Where its operands start.

    Returns:
        ``(operands, continued)``.
    """
    chunk, _, _ = _read_operand_field(raw[:71], start)
    whole, whole_end, _ = _read_operand_field(raw, start)
    if whole_end > 71:
        if whole_end == 72 and chunk.endswith(","):
            return chunk, True
        return whole, False
    tail = raw[71:].rstrip()
    late_mark = len(tail) == 2 and tail[0] == " "
    return chunk, bool(raw[71:72].strip()) or late_mark


def _significant(line: str) -> bool:
    return bool(line.strip()) and not line.startswith("*") and not line.startswith(".*")


def _statements(text: str, path: Optional[str], what: str) -> List[_Statement]:
    """Read assembler statements, joining continuations.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` or ``INPUT_TRUNCATED`` (see the module docstring).
    """
    lines = text.splitlines()
    statements: List[_Statement] = []
    index = 0
    while index < len(lines):
        raw = lines[index].rstrip("\r")
        number = index + 1
        index += 1
        if not _significant(raw):
            continue
        label: Optional[str] = None
        position = 0
        if raw[:1] != " ":
            label = raw.split()[0]
            position = len(label)
        rest = raw[position:]
        stripped = rest.lstrip()
        operation = stripped.split()[0] if stripped.split() else ""
        position += len(rest) - len(stripped) + len(operation)
        while position < len(raw) and raw[position] == " ":
            position += 1
        chunk, continued = _operand_line(raw, position)
        operands = [chunk]
        while continued:
            if index >= len(lines) or not any(_significant(line) for line in lines[index:]):
                raise MainframeParseError(
                    f"The {what}{where(path)} ends on the continuation mark of the statement at line {number}",
                    code="INPUT_TRUNCATED",
                )
            follow = lines[index].rstrip("\r")
            index += 1
            if follow[:15].strip():
                raise MainframeParseError(
                    f"Line {index}{where(path)} should continue the statement at line {number} (it carries a "
                    "continuation mark in column 72) but does not start in column 16 — the continuation "
                    "leads nowhere",
                    code="INPUT_MALFORMED",
                )
            start = len(follow) - len(follow.lstrip()) if follow.strip() else len(follow)
            chunk, continued = _operand_line(follow, start)
            operands.append(chunk)
        joined = "".join(operands)
        if joined.endswith(","):
            if not any(_significant(line) for line in lines[index:]):
                raise MainframeParseError(
                    f"The {what}{where(path)} ends inside the operands of the statement at line {number}",
                    code="INPUT_TRUNCATED",
                )
            raise MainframeParseError(
                f"The operands of the statement at line {number}{where(path)} end with a comma, but the line "
                "has no continuation mark in column 72",
                code="INPUT_MALFORMED",
            )
        statements.append(_Statement(label=label, operation=operation.upper(), operands=joined, line=number))
    return statements


def _split_top_level(text: str, *, at: str) -> List[str]:
    """Split ``text`` on commas outside parentheses and quotes.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for unbalanced parentheses.
    """
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    in_quote = False
    for char in text:
        if char == "'":
            in_quote = not in_quote
        elif not in_quote and char == "(":
            depth += 1
        elif not in_quote and char == ")":
            depth -= 1
            if depth < 0:
                break
        if char == "," and depth == 0 and not in_quote:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if depth != 0:
        raise MainframeParseError(f"The operands{at} have unbalanced parentheses", code="INPUT_MALFORMED")
    parts.append("".join(current))
    return parts


def _operand_value(raw: str, *, at: str, depth: int = 0) -> OperandValue:
    """``(A,B)`` → ``("A", "B")`` (nested groups nest); ``'TEXT'`` → ``TEXT``; anything else upper-cased.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for groups nested deeper than
            :data:`_MAX_OPERAND_DEPTH` (no IMS operand nests more than three deep).
    """
    if raw.startswith("(") and raw.endswith(")"):
        if depth >= _MAX_OPERAND_DEPTH:
            raise MainframeParseError(
                f"The operands{at} nest parentheses more than {_MAX_OPERAND_DEPTH} deep", code="INPUT_MALFORMED"
            )
        return tuple(_operand_value(part, at=at, depth=depth + 1) for part in _split_top_level(raw[1:-1], at=at))
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw.upper()


def _operands(statement: _Statement, path: Optional[str]) -> Dict[str, OperandValue]:
    """The statement's ``KEYWORD=value`` operands.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for an operand without ``=`` or written twice.
    """
    at = f" of the {statement.operation} statement at line {statement.line}{where(path)}"
    result: Dict[str, OperandValue] = {}
    if not statement.operands:
        return result
    for part in _split_top_level(statement.operands, at=at):
        keyword, sep, value = part.partition("=")
        keyword = keyword.upper()
        if not sep or not keyword or not value:
            raise MainframeParseError(
                f"The operand {part or '(empty)'!r}{at} is not KEYWORD=value", code="INPUT_MALFORMED"
            )
        if keyword in result:
            raise MainframeParseError(f"{keyword}{at} is written twice", code="INPUT_MALFORMED")
        result[keyword] = _operand_value(value, at=at)
    return result


def _flat(value: Optional[OperandValue]) -> Tuple[str, ...]:
    """A value as a flat tuple of strings (``A`` → ``("A",)``; ``(A,(B,C))`` → ``("A", "B", "C")``)."""
    if value is None or value == "":
        return ()
    if isinstance(value, tuple):
        return tuple(item for part in value for item in _flat(part))
    return (value,)


def _text(value: Optional[OperandValue], name: str, *, at: str) -> Optional[str]:
    """A single-valued operand (``A`` or ``(A)``).

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` when the value is a list of several.
    """
    if value is None:
        return None
    flat = _flat(value)
    if len(flat) != 1:
        raise MainframeParseError(f"{name}={_render(value)}{at} must be a single value", code="INPUT_MALFORMED")
    return flat[0]


def _number(value: Optional[OperandValue], name: str, *, at: str) -> Optional[int]:
    """A whole-number operand.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` when it is not a whole number.
    """
    text = _text(value, name, at=at)
    if text is None:
        return None
    if not text.isdigit():
        raise MainframeParseError(f"{name}={text}{at} is not a whole number", code="INPUT_MALFORMED")
    return int(text)


def _render(value: OperandValue) -> str:
    """Write a value back the way the source does (``("A", ("B", "C"))`` → ``(A,(B,C))``)."""
    if isinstance(value, tuple):
        return "(" + ",".join(_render(part) for part in value) + ")"
    return value


# ===========================================================================
# DBD
# ===========================================================================


def _parent(
    segment_name: str, value: Optional[OperandValue], *, at: str
) -> Tuple[Optional[str], Optional[str], Optional[Tuple[str, str, Optional[str]]]]:
    """Decode ``PARENT=``: ``0`` / ``P`` / ``(P,SNGL)`` / ``((P,SNGL),(LP,PHYSICAL,DBD))``.

    Returns:
        ``(parent, pointer, logical_parent)`` — the physical parent (``None`` for the root), the
        pointer type written with it, and a logical child's ``(segment, PHYSICAL|VIRTUAL, dbd)``.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a shape that is none of those.
    """
    if value is None:
        return None, None, None
    if isinstance(value, str):
        return (None if value == "0" else value), None, None
    groups = [value] if all(isinstance(part, str) for part in value) else list(value)
    physical = _flat(groups[0])
    if len(groups) > 2 or not physical:
        raise MainframeParseError(
            f"PARENT={_render(value)} of segment {segment_name}{at} must be (parent[,pointer]) optionally "
            "followed by (logical parent,PHYSICAL|VIRTUAL,dbd)",
            code="INPUT_MALFORMED",
        )
    logical: Optional[Tuple[str, str, Optional[str]]] = None
    if len(groups) == 2:
        flat = _flat(groups[1])
        if not flat:
            raise MainframeParseError(
                f"PARENT of segment {segment_name}{at} has an empty logical parent", code="INPUT_MALFORMED"
            )
        logical = (flat[0], flat[1] if len(flat) > 1 else "VIRTUAL", flat[2] if len(flat) > 2 else None)
    parent = None if physical[0] == "0" else physical[0]
    return parent, (physical[1] if len(physical) > 1 else None), logical


def _segment(statement: _Statement, operands: Dict[str, OperandValue], path: Optional[str]) -> ImsSegment:
    """Build one ``SEGM``."""
    at = f" at line {statement.line}{where(path)}"
    name = _text(operands.pop("NAME", None), "NAME", at=at)
    if not name:
        raise MainframeParseError(f"The SEGM{at} has no NAME", code="INPUT_MALFORMED")
    parent, pointer, logical = _parent(name, operands.pop("PARENT", None), at=at)
    max_bytes: Optional[int] = None
    min_bytes: Optional[int] = None
    size = operands.pop("BYTES", None)
    if isinstance(size, tuple):
        flat = _flat(size)
        if len(flat) != 2 or not all(part.isdigit() for part in flat):
            raise MainframeParseError(
                f"BYTES={_render(size)} of segment {name}{at} must be (max,min)", code="INPUT_MALFORMED"
            )
        max_bytes, min_bytes = int(flat[0]), int(flat[1])
    else:
        max_bytes = _number(size, "BYTES", at=at)
    sources: List[ImsSourceSegment] = []
    source = operands.pop("SOURCE", None)
    if source is not None:
        single = isinstance(source, str) or all(isinstance(part, str) for part in source)
        groups: List[OperandValue] = [source] if single else list(source)
        for group in groups:
            flat = _flat(group)
            if len(flat) != 3:
                raise MainframeParseError(
                    f"SOURCE of segment {name}{at} must list (segment,DATA|KEY,dbd) entries", code="INPUT_MALFORMED"
                )
            sources.append(ImsSourceSegment(segment=flat[0], mode=flat[1], dbd=flat[2]))
    return ImsSegment(
        name=name,
        parent=parent,
        parent_pointer=pointer,
        logical_parent=logical,
        max_bytes=max_bytes,
        min_bytes=min_bytes,
        sources=sources,
        operands=operands,
        line=statement.line,
    )


def _field(
    statement: _Statement, operands: Dict[str, OperandValue], segment: ImsSegment, path: Optional[str]
) -> ImsField:
    """Build one ``FIELD``."""
    at = f" (field at line {statement.line} of segment {segment.name}{where(path)})"
    name_value = operands.pop("NAME", None)
    flat = _flat(name_value)
    if not flat:
        raise MainframeParseError(f"A FIELD{at} has no NAME", code="INPUT_MALFORMED")
    sequence = len(flat) > 1 and flat[1] == "SEQ"
    if len(flat) > 1 and not sequence:
        raise MainframeParseError(
            f"NAME={_render(name_value or '')}{at} must be (name,SEQ,U|M)", code="INPUT_MALFORMED"
        )
    unique: Optional[bool] = None
    if sequence:
        flag = flat[2] if len(flat) > 2 else "U"
        if flag not in ("U", "M"):
            raise MainframeParseError(f"The sequence flag {flag}{at} must be U or M", code="INPUT_MALFORMED")
        unique = flag == "U"
    type_code = _text(operands.pop("TYPE", None), "TYPE", at=at) or "C"
    if type_code not in FIELD_TYPES:
        raise MainframeParseError(
            f"TYPE={type_code}{at} is not a field type IMS knows ({', '.join(FIELD_TYPES)})",
            code="INPUT_SEMANTIC_INVALID",
        )
    return ImsField(
        name=flat[0],
        start=_number(operands.pop("START", None), "START", at=at),
        length=_number(operands.pop("BYTES", None), "BYTES", at=at),
        type_code=type_code,
        sequence=sequence,
        unique=unique,
        operands=operands,
        line=statement.line,
    )


def _lchild(statement: _Statement, operands: Dict[str, OperandValue], path: Optional[str]) -> ImsLChild:
    at = f" at line {statement.line}{where(path)}"
    flat = _flat(operands.pop("NAME", None))
    if not flat:
        raise MainframeParseError(f"The LCHILD{at} has no NAME", code="INPUT_MALFORMED")
    return ImsLChild(
        segment=flat[0],
        dbd=flat[1] if len(flat) > 1 else None,
        pointer=_text(operands.pop("POINTER", None), "POINTER", at=at),
        operands=operands,
        line=statement.line,
    )


def _xdfld(
    statement: _Statement, operands: Dict[str, OperandValue], segment: ImsSegment, path: Optional[str]
) -> ImsXdfld:
    at = f" at line {statement.line}{where(path)}"
    name = _text(operands.pop("NAME", None), "NAME", at=at)
    if not name:
        raise MainframeParseError(f"The XDFLD{at} has no NAME", code="INPUT_MALFORMED")
    if not segment.lchildren:
        raise MainframeParseError(
            f"The XDFLD {name}{at} follows no LCHILD, so it names no index", code="INPUT_MALFORMED"
        )
    search = _flat(operands.pop("SRCH", None))
    if not search:
        raise MainframeParseError(f"The XDFLD {name}{at} has no SRCH fields", code="INPUT_MALFORMED")
    return ImsXdfld(
        name=name,
        index=segment.lchildren[-1],
        source_segment=_text(operands.pop("SEGMENT", None), "SEGMENT", at=at) or segment.name,
        search=search,
        subsequence=_flat(operands.pop("SUBSEQ", None)),
        duplicate_data=_flat(operands.pop("DDATA", None)),
        null_value=_text(operands.pop("NULLVAL", None), "NULLVAL", at=at),
        operands=operands,
        line=statement.line,
    )


def _check_dbd(dbd: ImsDbd) -> None:
    """Refuse a DBD whose hierarchy or layout cannot be rebuilt.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` or ``INPUT_REFERENCE_UNRESOLVED``.
    """
    at = f"DBD {dbd.name}{where(dbd.path)}"
    if not dbd.segments:
        raise MainframeParseError(
            f"{at} declares no SEGM, so the database describes no records to model", code="INPUT_SEMANTIC_INVALID"
        )
    names: Dict[str, int] = {}
    for segment in dbd.segments:
        if segment.name in names:
            raise MainframeParseError(
                f"{at} defines segment {segment.name} twice (lines {names[segment.name]} and {segment.line})",
                code="INPUT_SEMANTIC_INVALID",
            )
        names[segment.name] = segment.line
    for segment in dbd.segments:
        if segment.parent is not None and segment.parent not in names:
            raise MainframeParseError(
                f"Segment {segment.name} (line {segment.line}) of {at} names PARENT={segment.parent}, and no "
                "SEGM of the DBD defines it — the hierarchy cannot be rebuilt",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
    roots = [s.name for s in dbd.segments if s.parent is None]
    if len(roots) != 1:
        raise MainframeParseError(
            f"{at} has {'no root segment' if not roots else 'more than one root segment (' + ', '.join(roots) + ')'}; "
            "exactly one SEGM must have PARENT=0",
            code="INPUT_SEMANTIC_INVALID",
        )
    for segment in dbd.segments:
        seen = {segment.name}
        current = segment.parent
        while current is not None:
            if current in seen:
                raise MainframeParseError(
                    f"The PARENT chain of segment {segment.name} in {at} loops back on itself",
                    code="INPUT_SEMANTIC_INVALID",
                )
            seen.add(current)
            current = dbd.segment(current).parent  # type: ignore[union-attr]
    for segment in dbd.segments:
        _check_segment(dbd, segment, at)


def _check_segment(dbd: ImsDbd, segment: ImsSegment, at: str) -> None:
    where_segment = f"segment {segment.name} of {at}"
    if not dbd.logical:
        if segment.max_bytes is None:
            raise MainframeParseError(f"The {where_segment} has no BYTES", code="INPUT_SEMANTIC_INVALID")
        if segment.min_bytes is not None and segment.min_bytes > segment.max_bytes:
            raise MainframeParseError(
                f"The {where_segment} has a minimum length above its maximum", code="INPUT_SEMANTIC_INVALID"
            )
    elif not segment.sources:
        raise MainframeParseError(
            f"The {where_segment} is in a LOGICAL database but names no SOURCE segment",
            code="INPUT_SEMANTIC_INVALID",
        )
    seen: Dict[str, int] = {}
    sequence_fields = [f.name for f in segment.fields if f.sequence]
    if len(sequence_fields) > 1:
        raise MainframeParseError(
            f"The {where_segment} declares more than one sequence field ({', '.join(sequence_fields)})",
            code="INPUT_SEMANTIC_INVALID",
        )
    for item in segment.fields:
        if item.name in seen:
            raise MainframeParseError(
                f"Field {item.name} is defined twice in the {where_segment} (lines {seen[item.name]} and {item.line})",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[item.name] = item.line
        if item.system_related:
            continue
        if item.start is None or item.length is None:
            raise MainframeParseError(
                f"Field {item.name} of the {where_segment} has no {'START' if item.start is None else 'BYTES'}",
                code="INPUT_SEMANTIC_INVALID",
            )
        if item.start < 1 or item.length < 1:
            raise MainframeParseError(
                f"Field {item.name} of the {where_segment} has START and BYTES below 1", code="INPUT_SEMANTIC_INVALID"
            )
        if segment.max_bytes is not None and item.start + item.length - 1 > segment.max_bytes:
            raise MainframeParseError(
                f"Field {item.name} of the {where_segment} ends at byte {item.start + item.length - 1}, past the "
                f"segment's {segment.max_bytes} bytes",
                code="INPUT_SEMANTIC_INVALID",
            )
    for xdfld in segment.xdflds:
        source = dbd.segment(xdfld.source_segment)
        if source is None:
            raise MainframeParseError(
                f"XDFLD {xdfld.name} of the {where_segment} names SEGMENT={xdfld.source_segment}, which the DBD "
                "does not define",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        for name in xdfld.search + xdfld.subsequence + xdfld.duplicate_data:
            if source.field(name) is None and not name.startswith("/"):
                raise MainframeParseError(
                    f"XDFLD {xdfld.name} of the {where_segment} uses field {name}, which segment {source.name} "
                    "does not define",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )


# ===========================================================================
# PSB
# ===========================================================================


def _pcb(statement: _Statement, operands: Dict[str, OperandValue], number: int, path: Optional[str]) -> ImsPcb:
    at = f" at line {statement.line}{where(path)}"
    pcb_type = _text(operands.pop("TYPE", None), "TYPE", at=at) or "DB"
    if pcb_type not in ("DB", "TP", "GSAM"):
        raise MainframeParseError(f"PCB TYPE={pcb_type}{at} must be DB, TP or GSAM", code="INPUT_MALFORMED")
    dbd_name = _text(operands.pop("DBDNAME", None), "DBDNAME", at=at)
    if pcb_type != "TP" and not dbd_name:
        raise MainframeParseError(f"The {pcb_type} PCB{at} has no DBDNAME", code="INPUT_MALFORMED")
    name = statement.label or _text(operands.pop("PCBNAME", None), "PCBNAME", at=at) or f"PCB{number}"
    procopt = _text(operands.pop("PROCOPT", None), "PROCOPT", at=at)
    return ImsPcb(
        name=name,
        pcb_type=pcb_type,
        dbd_name=dbd_name,
        procopt=procopt or ("G" if pcb_type == "DB" else None),
        key_length=_number(operands.pop("KEYLEN", None), "KEYLEN", at=at),
        processing_sequence=_text(operands.pop("PROCSEQ", None), "PROCSEQ", at=at),
        operands=operands,
        line=statement.line,
    )


def _senseg(statement: _Statement, operands: Dict[str, OperandValue], path: Optional[str]) -> ImsSenseg:
    at = f" at line {statement.line}{where(path)}"
    name = _text(operands.pop("NAME", None), "NAME", at=at)
    if not name:
        raise MainframeParseError(f"The SENSEG{at} has no NAME", code="INPUT_MALFORMED")
    parent = _text(operands.pop("PARENT", None), "PARENT", at=at)
    return ImsSenseg(
        name=name,
        parent=None if parent in (None, "0") else parent,
        procopt=_text(operands.pop("PROCOPT", None), "PROCOPT", at=at),
        operands=operands,
        line=statement.line,
    )


def _senfld(statement: _Statement, operands: Dict[str, OperandValue], path: Optional[str]) -> ImsSenfld:
    at = f" at line {statement.line}{where(path)}"
    name = _text(operands.pop("NAME", None), "NAME", at=at)
    if not name:
        raise MainframeParseError(f"The SENFLD{at} has no NAME", code="INPUT_MALFORMED")
    replace = _text(operands.pop("REPL", None), "REPL", at=at)
    return ImsSenfld(
        name=name,
        start=_number(operands.pop("START", None), "START", at=at),
        replace=replace != "NO",
        line=statement.line,
    )


def _check_psb(psb: ImsPsb) -> None:
    """Refuse a PSB whose program view is inconsistent in itself.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` or ``INPUT_REFERENCE_UNRESOLVED``.
    """
    at = f"PSB {psb.name}{where(psb.path)}"
    if not psb.pcbs:
        raise MainframeParseError(f"{at} declares no PCB", code="INPUT_SEMANTIC_INVALID")
    for pcb in psb.pcbs:
        if pcb.pcb_type != "DB":
            continue
        if not pcb.sensegs:
            raise MainframeParseError(
                f"Database PCB {pcb.name} of {at} names no SENSEG, so the program sees nothing",
                code="INPUT_SEMANTIC_INVALID",
            )
        names = [s.name for s in pcb.sensegs]
        for senseg in pcb.sensegs:
            if names.count(senseg.name) > 1:
                raise MainframeParseError(
                    f"PCB {pcb.name} of {at} names SENSEG {senseg.name} twice", code="INPUT_SEMANTIC_INVALID"
                )
            if senseg.parent is not None and senseg.parent not in names:
                raise MainframeParseError(
                    f"SENSEG {senseg.name} of PCB {pcb.name} in {at} names PARENT={senseg.parent}, which the PCB "
                    "is not sensitive to",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
        roots = [s.name for s in pcb.sensegs if s.parent is None]
        if len(roots) != 1:
            raise MainframeParseError(
                f"PCB {pcb.name} of {at} must have exactly one root SENSEG (PARENT=0)", code="INPUT_SEMANTIC_INVALID"
            )


def _check_psb_against_dbd(psb: ImsPsb, document: ImsDocument) -> None:
    """Check each database PCB against its DBD, when the DBD is in the upload.

    Raises:
        MainframeParseError: ``INPUT_REFERENCE_UNRESOLVED`` for a segment or field the DBD lacks,
            ``INPUT_SEMANTIC_INVALID`` for a ``SENSEG`` parent that contradicts the hierarchy.
    """
    for pcb in psb.pcbs:
        dbd = document.dbd(pcb.dbd_name) if pcb.pcb_type == "DB" else None
        if dbd is None:
            continue
        at = f"PCB {pcb.name} of PSB {psb.name}{where(psb.path)}"
        for senseg in pcb.sensegs:
            segment = dbd.segment(senseg.name)
            if segment is None:
                raise MainframeParseError(
                    f"{at} is sensitive to segment {senseg.name}, which DBD {dbd.name} does not define",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
            if senseg.parent != segment.parent and not dbd.logical:
                raise MainframeParseError(
                    f"{at} places segment {senseg.name} under {senseg.parent or 'the root'}, but DBD {dbd.name} "
                    f"places it under {segment.parent or 'the root'}",
                    code="INPUT_SEMANTIC_INVALID",
                )
            for senfld in senseg.fields:
                if segment.field(senfld.name) is None:
                    raise MainframeParseError(
                        f"{at} is sensitive to field {senfld.name} of segment {senseg.name}, which DBD {dbd.name} "
                        "does not define",
                        code="INPUT_REFERENCE_UNRESOLVED",
                    )


# ===========================================================================
# Reading a file
# ===========================================================================


def _blocks(statements: List[_Statement], path: Optional[str], what: str) -> Iterator[Tuple[str, List[_Statement]]]:
    """Group statements into ``("DBD", …)`` / ``("PSB", …)`` blocks, each closed by its GEN statement.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a statement outside a block or not an IMS macro,
            ``INPUT_TRUNCATED`` when a block is never closed.
    """
    kind: Optional[str] = None
    block: List[_Statement] = []
    for statement in statements:
        at = f" at line {statement.line}{where(path)}"
        operation = statement.operation
        if operation in _ASSEMBLER_DIRECTIVES:
            continue
        if operation == "END":
            break
        if operation not in _DBD_OPERATIONS and operation not in _PSB_OPERATIONS:
            raise MainframeParseError(
                f"{operation or statement.label}{at} is not a DBD or PSB macro; a continuation line written "
                "without the column-72 mark reads this way",
                code="INPUT_MALFORMED",
            )
        if kind is None:
            if operation == "DBD":
                kind = "DBD"
            elif operation in _PSB_OPERATIONS:
                kind = "PSB"
            else:
                raise MainframeParseError(f"{operation}{at} comes before any DBD statement", code="INPUT_MALFORMED")
        elif (kind == "DBD") != (operation in _DBD_OPERATIONS) or operation == "DBD":
            raise MainframeParseError(
                f"{operation}{at} does not belong inside the {kind} that is still open (no {kind}GEN closed it)",
                code="INPUT_MALFORMED",
            )
        block.append(statement)
        if operation == f"{kind}GEN":
            yield kind, block
            kind, block = None, []
    if kind is not None:
        raise MainframeParseError(
            f"The {what}{where(path)} ends before the {kind}GEN statement that closes the {kind}",
            code="INPUT_TRUNCATED",
        )


def _read_dbd(block: List[_Statement], path: Optional[str]) -> ImsDbd:
    """Build one DBD from its statements (``DBD`` … ``DBDGEN``)."""
    head = block[0]
    operands = _operands(head, path)
    at = f" at line {head.line}{where(path)}"
    name = _text(operands.pop("NAME", None), "NAME", at=at)
    if not name:
        raise MainframeParseError(f"The DBD{at} has no NAME", code="INPUT_MALFORMED")
    dbd = ImsDbd(name=name, access=_flat(operands.pop("ACCESS", None)), operands=operands, path=path)
    current: Optional[ImsSegment] = None
    for statement in block[1:-1]:
        operands = _operands(statement, path)
        at = f" at line {statement.line}{where(path)}"
        if statement.operation in ("DATASET", "AREA"):
            dbd.datasets.append({"STATEMENT": statement.operation, **operands})
        elif statement.operation == "SEGM":
            current = _segment(statement, operands, path)
            dbd.segments.append(current)
        elif current is None:
            raise MainframeParseError(f"The {statement.operation}{at} comes before any SEGM", code="INPUT_MALFORMED")
        elif statement.operation == "FIELD":
            current.fields.append(_field(statement, operands, current, path))
        elif statement.operation == "LCHILD":
            current.lchildren.append(_lchild(statement, operands, path))
        else:
            current.xdflds.append(_xdfld(statement, operands, current, path))
    _check_dbd(dbd)
    return dbd


def _read_psb(block: List[_Statement], path: Optional[str]) -> ImsPsb:
    """Build one PSB from its statements (``PCB`` … ``PSBGEN``)."""
    tail = block[-1]
    operands = _operands(tail, path)
    at = f" at line {tail.line}{where(path)}"
    stem = PurePosixPath(path).stem.upper() if path else "PSB"
    psb = ImsPsb(
        name=_text(operands.pop("PSBNAME", None), "PSBNAME", at=at) or stem,
        language=_text(operands.pop("LANG", None), "LANG", at=at),
        operands=operands,
        path=path,
    )
    current: Optional[ImsPcb] = None
    for statement in block[:-1]:
        operands = _operands(statement, path)
        at = f" at line {statement.line}{where(path)}"
        if statement.operation == "PCB":
            current = _pcb(statement, operands, len(psb.pcbs) + 1, path)
            psb.pcbs.append(current)
        elif current is None or current.pcb_type == "TP":
            raise MainframeParseError(
                f"The {statement.operation}{at} is outside a database PCB", code="INPUT_MALFORMED"
            )
        elif statement.operation == "SENSEG":
            current.sensegs.append(_senseg(statement, operands, path))
        else:
            if not current.sensegs:
                raise MainframeParseError(f"The SENFLD{at} comes before any SENSEG", code="INPUT_MALFORMED")
            current.sensegs[-1].fields.append(_senfld(statement, operands, path))
    _check_psb(psb)
    return psb


def _read_file(text: str, path: Optional[str], document: ImsDocument, *, require: bool) -> bool:
    """Read one file into ``document``.

    Args:
        require: Refuse a file with no DBD / PCB statement (``FORMAT_MISMATCH``) instead of
            skipping it.

    Returns:
        Whether the file was read.
    """
    what = "IMS source"
    check_encoding(text, path, what=what)
    if not has_ims_statements(text)[0]:
        if require:
            raise MainframeParseError(
                f"No DBD NAME= or PCB TYPE= statement{where(path)} was found; this is not an IMS DBD or PSB",
                code="FORMAT_MISMATCH",
            )
        return False
    for kind, block in _blocks(_statements(text, path, what), path, what):
        if kind == "DBD":
            document.dbds.append(_read_dbd(block, path))
        else:
            document.psbs.append(_read_psb(block, path))
    document.sources[path or "input.dbd"] = text
    return True


def _check_document(document: ImsDocument) -> None:
    """Refuse names used twice across the upload, and check every PSB against the DBDs read."""
    for kind, items in (("DBD", document.dbds), ("PSB", document.psbs)):
        seen: Dict[str, str] = {}
        for item in items:
            if item.name in seen:
                raise MainframeParseError(
                    f"{kind} {item.name} is defined twice ({seen[item.name]} and {item.path or 'the input'})",
                    code="INPUT_SEMANTIC_INVALID",
                )
            seen[item.name] = item.path or "the input"
    for psb in document.psbs:
        _check_psb_against_dbd(psb, document)


def parse_ims_text(text: str, *, label: Optional[str] = None) -> ImsDocument:
    """Parse one uploaded DBD or PSB source file.

    Args:
        text: The file text.
        label: The upload's file name, for messages.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    if text is None or not text.strip():
        raise MainframeParseError("The IMS source is empty", code="INPUT_EMPTY")
    document = ImsDocument(label=label)
    _read_file(text, label, document, require=True)
    _check_document(document)
    return document


def parse_ims_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> ImsDocument:
    """Parse DBDs and PSBs uploaded together, resolving each PSB's ``DBDNAME`` against the DBDs.

    Members with a :data:`SOURCE_SUFFIXES` suffix are read; one without DBD or PCB statements is
    ignored unless it is the root.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    document = ImsDocument(label=label or fileset.root, is_fileset=True)
    for path in sorted(fileset.members):
        text = fileset.members[path]
        if PurePosixPath(path).suffix.lower() not in SOURCE_SUFFIXES and path != fileset.root:
            continue
        if not text.strip():
            continue
        _read_file(text, path, document, require=path == fileset.root)
    if not document.sources:
        raise MainframeParseError("The upload holds no IMS DBD or PSB source", code="FORMAT_MISMATCH")
    _check_document(document)
    return document
