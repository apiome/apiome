"""CICS BMS map reader — FMT-11.3 (#5484).

Reads the two texts that describe a 3270 screen of a CICS transaction:

* **BMS macro source** — assembler statements: a label in column 1, the operation (``DFHMSD``,
  ``DFHMDI``, ``DFHMDF``), then comma-separated ``KEYWORD=value`` operands. A statement is continued
  by any non-blank character in **column 72**, and the continuation's operands resume on the next
  line (from column 16). ``*`` in column 1 starts a comment line. A **mapset** (``DFHMSD``) holds
  **maps** (``DFHMDI``, one screen each, ``SIZE=(rows,cols)``), and a map holds **fields**
  (``DFHMDF``, ``POS=(row,col)``, ``LENGTH``, ``ATTRB``, ``PICIN`` / ``PICOUT`` …). A ``DFHMDF``
  without a label is a screen **literal** — chrome, not data. ``DFHMSD TYPE=FINAL`` closes the
  mapset.
* **Symbolic-map copybooks** — the COBOL copybook BMS generates from a mapset: per map an input
  record ``<map>I`` and an output record ``<map>O REDEFINES <map>I``, and per named field an
  ``L`` (length), ``F`` / ``A`` (flag / attribute), ``I`` (input data) and ``O`` (output data) entry.
  It gives the record the program uses, but no screen positions. Read beside its mapset in a
  fileset, it names each field's symbolic entries; read alone, it is the only layout there is.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark;
* ``FORMAT_MISMATCH`` — no ``DFHMSD`` / ``DFHMDI`` / ``DFHMDF`` macro and not a symbolic map;
* ``INPUT_MALFORMED`` — a statement whose operation is not a BMS macro (a continuation line written
  without the column-72 mark reads as one), an operand list ending in a comma with no
  continuation, an unterminated quote before the end, unbalanced parentheses, a map outside a
  mapset or a field outside a map, a missing label, or a non-numeric ``POS`` / ``LENGTH`` /
  ``SIZE`` / ``OCCURS``;
* ``INPUT_TRUNCATED`` — the source ends on a continuation mark, inside a quoted value, or before
  ``DFHMSD TYPE=FINAL``;
* ``INPUT_SEMANTIC_INVALID`` — a map with no named field, a mapset with no map, a named field
  without a position or length, a name used twice, or fields that overlap or fall outside their
  map.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .fileset import IntakeFileset
from .mainframe_misc_common import MainframeParseError, check_encoding, where

__all__ = [
    "BmsField",
    "BmsDocument",
    "BmsMap",
    "BmsMapset",
    "FORMAT_KEY",
    "SOURCE_SUFFIXES",
    "SymbolicField",
    "SymbolicMap",
    "has_bms_macros",
    "is_symbolic_map",
    "parse_bms_fileset",
    "parse_bms_text",
]

#: The adapter / canonical format key of this sub-format.
FORMAT_KEY = "cics-bms"

#: Suffixes of the files a BMS import reads: macro source and symbolic-map copybooks.
SOURCE_SUFFIXES = (".bms", ".cpy", ".cbl", ".copy")

#: The 3270 Model 2 screen BMS assumes when a map declares no ``SIZE``.
DEFAULT_SIZE = (24, 80)

#: Statements that are assembler housekeeping, not part of the map.
_ASSEMBLER_DIRECTIVES = frozenset({"PRINT", "TITLE", "SPACE", "EJECT", "COPY", "PUNCH", "ISEQ", "ICTL"})
_BMS_MACROS = frozenset({"DFHMSD", "DFHMDI", "DFHMDF"})

_MACRO_RE = re.compile(r"^(?:\S{1,8})?\s+DFHM(?:SD|DI|DF)\b", re.MULTILINE)
#: A copybook entry: level, name and its clauses up to the terminating period.
_ENTRY_RE = re.compile(r"^(\d{2})\s+([A-Za-z0-9][\w-]*)\s*(.*?)\s*\.?$", re.DOTALL)
_PIC_RE = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+?)\.?(?=\s|$)", re.IGNORECASE)
_REDEFINES_RE = re.compile(r"\bREDEFINES\s+([\w-]+)", re.IGNORECASE)
_OCCURS_RE = re.compile(r"\bOCCURS\s+(\d+)", re.IGNORECASE)
_USAGE_RE = re.compile(r"\b(COMP(?:-\d)?|BINARY|COMPUTATIONAL(?:-\d)?)\b", re.IGNORECASE)
#: Symbolic-map entry suffixes besides the data entries ``I`` / ``O``: length, flag, attribute,
#: and the extended attributes (colour, highlight, programmed symbol, validation, outline …).
_SYMBOLIC_SUFFIXES = ("L", "F", "A", "C", "H", "P", "V", "U", "M", "T", "B", "E")

OperandValue = Union[str, Tuple[str, ...]]


# ===========================================================================
# The parsed document
# ===========================================================================


@dataclass
class BmsField:
    """One ``DFHMDF``.

    Attributes:
        name: The label; ``None`` for a literal.
        row: 1-based row within the map.
        column: 1-based column within the map (the attribute byte's column).
        length: Data length in characters (the attribute byte is not counted).
        attributes: The ``ATTRB`` values as written (``PROT``, ``NUM``, ``BRT`` …).
        attributes_declared: Whether ``ATTRB`` was written (BMS defaults to ``(ASKIP,NORM)``).
        picin: The input picture, when declared.
        picout: The output picture, when declared.
        initial: The ``INITIAL`` value, when declared.
        occurs: ``OCCURS=n``, when declared.
        group: ``GRPNAME``, when declared.
        operands: Every other operand (``COLOR``, ``HILIGHT``, ``VALIDN``, ``JUSTIFY`` …).
        line: The source line the statement starts on.
    """

    name: Optional[str]
    row: int
    column: int
    length: int
    attributes: Tuple[str, ...] = ()
    attributes_declared: bool = False
    picin: Optional[str] = None
    picout: Optional[str] = None
    initial: Optional[str] = None
    occurs: Optional[int] = None
    group: Optional[str] = None
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    line: int = 0


@dataclass
class SymbolicField:
    """One named field of a symbolic map: its entries and pictures.

    Attributes:
        name: The field's base name (the BMS label).
        entries: Suffix → entry name (``{"L": "CUSTIDL", "F": "CUSTIDF", "I": "CUSTIDI", "O": "CUSTIDO"}``).
        input_picture: The ``I`` entry's picture.
        output_picture: The ``O`` entry's picture.
        occurs: The ``OCCURS`` count of the group that repeats the field, when any.
    """

    name: str
    entries: Dict[str, str] = field(default_factory=dict)
    input_picture: Optional[str] = None
    output_picture: Optional[str] = None
    occurs: Optional[int] = None


@dataclass
class SymbolicMap:
    """One map of a symbolic-map copybook: ``<map>I`` and ``<map>O REDEFINES <map>I``."""

    name: str
    input_record: str
    output_record: Optional[str]
    fields: List[SymbolicField] = field(default_factory=list)
    path: Optional[str] = None

    def field(self, name: str) -> Optional[SymbolicField]:
        """The symbolic field named ``name``, or ``None``."""
        return next((f for f in self.fields if f.name == name), None)


@dataclass
class BmsMap:
    """One ``DFHMDI``: a screen.

    Attributes:
        name: The label.
        rows: Map height.
        columns: Map width.
        size_declared: Whether ``SIZE`` was written (otherwise :data:`DEFAULT_SIZE`).
        operands: Every other operand (``LINE``, ``COLUMN``, ``CTRL``, ``JUSTIFY``, ``COLOR`` …).
        fields: The fields, named and literal, in source order.
        symbolic: The symbolic map read beside the mapset for this map, when any.
        line: The source line the statement starts on.
    """

    name: str
    rows: int
    columns: int
    size_declared: bool = True
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    fields: List[BmsField] = field(default_factory=list)
    symbolic: Optional[SymbolicMap] = None
    line: int = 0

    @property
    def named_fields(self) -> List[BmsField]:
        """The data fields (the labelled ``DFHMDF``s), in source order."""
        return [f for f in self.fields if f.name]


@dataclass
class BmsMapset:
    """One ``DFHMSD``: the mapset and its maps."""

    name: str
    operands: Dict[str, OperandValue] = field(default_factory=dict)
    maps: List[BmsMap] = field(default_factory=list)
    path: Optional[str] = None


@dataclass
class BmsDocument:
    """Everything one import read.

    Attributes:
        mapsets: The mapsets, in source order.
        symbolic_maps: Symbolic maps that matched no map of a mapset (a copybook read alone, or one
            whose mapset was not in the upload).
        sources: Every file's text, keyed by path (or label).
        is_fileset: Whether the import was a fileset.
        label: The upload's label.
    """

    mapsets: List[BmsMapset] = field(default_factory=list)
    symbolic_maps: List[SymbolicMap] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)
    is_fileset: bool = False
    label: Optional[str] = None


# ===========================================================================
# Sniffing
# ===========================================================================


def has_bms_macros(text: str) -> bool:
    """Whether ``text`` holds a ``DFHMSD`` / ``DFHMDI`` / ``DFHMDF`` statement."""
    return bool(_MACRO_RE.search(text))


def is_symbolic_map(text: str) -> bool:
    """Whether ``text`` is a BMS-generated symbolic map.

    That is a ``01 <map>I`` record, a ``01 <map>O REDEFINES <map>I`` record, and at least one field
    entry pair ``<name>L`` (``COMP``) / ``<name>I``. An ordinary copybook has none of that shape.
    """
    upper = text.upper()
    for match in re.finditer(r"\b01\s+([A-Z0-9][A-Z0-9-]*)I\s*\.", upper):
        name = re.escape(match.group(1))
        if re.search(rf"\b01\s+{name}O\s+REDEFINES\s+{name}I\b", upper) and re.search(
            r"\b02\s+[A-Z0-9-]+L\s+(?:COMP|BINARY)", upper
        ):
            return True
    return False


# ===========================================================================
# Assembler statements
# ===========================================================================


@dataclass
class _Statement:
    label: Optional[str]
    operation: str
    operands: str
    line: int


def _read_operand_chunk(text: str, start: int, in_quote: bool) -> Tuple[str, int, bool]:
    """Read operand characters from ``text[start:]`` up to the first unquoted blank.

    Returns:
        ``(chunk, end, in_quote)`` — the characters read, where reading stopped, and whether a
        quoted value is still open at the end of ``text``.
    """
    out: List[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if in_quote:
            out.append(char)
            if char == "'":
                if text[index + 1 : index + 2] == "'":
                    out.append("'")
                    index += 2
                    continue
                in_quote = False
            index += 1
            continue
        if char == " ":
            break
        if char == "'":
            in_quote = True
        out.append(char)
        index += 1
    return "".join(out), index, in_quote


def _statements(text: str, path: Optional[str]) -> List[_Statement]:
    """Read assembler statements, joining column-72 continuations.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` or ``INPUT_TRUNCATED`` (see the module docstring).
    """
    lines = text.splitlines()
    statements: List[_Statement] = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        number = index + 1
        index += 1
        if not raw.strip() or raw.startswith("*") or raw.startswith(".*"):
            continue
        body = raw[:71]
        continued = len(raw) >= 72 and raw[71] != " "
        label: Optional[str] = None
        position = 0
        if body[:1] != " ":
            label = body.split()[0]
            position = len(label)
        rest = body[position:]
        stripped = rest.lstrip()
        operation = stripped.split()[0] if stripped.split() else ""
        position += len(rest) - len(stripped) + len(operation)
        while position < len(body) and body[position] == " ":
            position += 1
        chunk, _, in_quote = _read_operand_chunk(body, position, False)
        whole, whole_end, whole_open = _read_operand_chunk(raw, position, False)
        if not whole_open and whole_end > 71:
            # An over-long line: the operand itself runs into column 72 and ends there, complete
            # (``…,INITIAL='QUANTITY'`` with the closing quote in column 72). Read as one line — a
            # continuation mark stands after the operand, never inside it.
            chunk, in_quote, continued = whole, False, False
        operands = [chunk]
        while continued or in_quote:
            if in_quote and not continued:
                if any(line.strip() and not line.startswith("*") for line in lines[index:]):
                    raise MainframeParseError(
                        f"The quoted value of the statement at line {number}{where(path)} is never closed",
                        code="INPUT_MALFORMED",
                    )
                raise MainframeParseError(
                    f"The BMS source{where(path)} ends inside the quoted value of the statement at line {number}",
                    code="INPUT_TRUNCATED",
                )
            if index >= len(lines):
                raise MainframeParseError(
                    f"The BMS source{where(path)} ends on the continuation mark of the statement at line {number}",
                    code="INPUT_TRUNCATED",
                )
            follow = lines[index]
            index += 1
            follow_body = follow[:71]
            if follow_body[:15].strip():
                raise MainframeParseError(
                    f"Line {index}{where(path)} continues the statement at line {number} but does not "
                    "start in column 16",
                    code="INPUT_MALFORMED",
                )
            continued = len(follow) >= 72 and follow[71] != " "
            start = 15 if in_quote else len(follow_body) - len(follow_body[15:].lstrip())
            chunk, _, in_quote = _read_operand_chunk(follow_body, start, in_quote)
            operands.append(chunk)
        text_operands = "".join(operands)
        if text_operands.endswith(","):
            raise MainframeParseError(
                f"The operands of the statement at line {number}{where(path)} end with a comma, but "
                "the line has no continuation mark in column 72",
                code="INPUT_MALFORMED",
            )
        statements.append(_Statement(label=label, operation=operation.upper(), operands=text_operands, line=number))
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
    return [part for part in parts if part]


def _operand_value(raw: str, *, at: str) -> OperandValue:
    """``(A,B)`` → ``("A", "B")``; ``'TEXT'`` → ``TEXT`` (``''`` → ``'``); anything else as written."""
    if raw.startswith("(") and raw.endswith(")"):
        return tuple(_operand_value(part, at=at) for part in _split_top_level(raw[1:-1], at=at))  # type: ignore[misc]
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def _operands(statement: _Statement, path: Optional[str]) -> Dict[str, OperandValue]:
    """The statement's ``KEYWORD=value`` operands."""
    at = f" of the statement at line {statement.line}{where(path)}"
    result: Dict[str, OperandValue] = {}
    for part in _split_top_level(statement.operands, at=at):
        keyword, sep, value = part.partition("=")
        if not sep:
            result[keyword.upper()] = ""
            continue
        result[keyword.upper()] = _operand_value(value, at=at)
    return result


def _as_tuple(value: Optional[OperandValue]) -> Tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, tuple):
        return tuple(str(v).upper() for v in value)
    return (str(value).upper(),)


def _as_int(value: Optional[OperandValue], name: str, *, at: str) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        raise MainframeParseError(f"{name}={value}{at} is not a whole number", code="INPUT_MALFORMED")
    return int(value)


def _pair(value: Optional[OperandValue], name: str, *, at: str) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    if not isinstance(value, tuple) or len(value) != 2 or not all(str(v).isdigit() for v in value):
        raise MainframeParseError(f"{name}={value}{at} must be (number,number)", code="INPUT_MALFORMED")
    return int(value[0]), int(value[1])


def _string(value: Optional[OperandValue]) -> Optional[str]:
    if value is None:
        return None
    return ",".join(value) if isinstance(value, tuple) else value


# ===========================================================================
# Mapsets
# ===========================================================================


def _field(statement: _Statement, operands: Dict[str, OperandValue], bms_map: BmsMap, path: Optional[str]) -> BmsField:
    """Build one ``DFHMDF``."""
    at = f" (field {statement.label or 'literal'} at line {statement.line}{where(path)})"
    pos = operands.pop("POS", None)
    if pos is None:
        raise MainframeParseError(
            f"A field{at} has no POS, so it cannot be placed on the screen", code="INPUT_SEMANTIC_INVALID"
        )
    if isinstance(pos, tuple):
        row, column = _pair(pos, "POS", at=at) or (0, 0)
    else:
        offset = _as_int(pos, "POS", at=at) or 0
        row, column = offset // bms_map.columns + 1, offset % bms_map.columns + 1
    initial = _string(operands.pop("INITIAL", None))
    length = _as_int(operands.pop("LENGTH", None), "LENGTH", at=at)
    if length is None:
        if initial is None:
            raise MainframeParseError(
                f"A field{at} has neither LENGTH nor INITIAL, so its length is unknown",
                code="INPUT_SEMANTIC_INVALID",
            )
        length = len(initial)
    attrb = operands.pop("ATTRB", None)
    return BmsField(
        name=statement.label,
        row=row,
        column=column,
        length=length,
        attributes=_as_tuple(attrb),
        attributes_declared=attrb is not None,
        picin=_string(operands.pop("PICIN", None)),
        picout=_string(operands.pop("PICOUT", None)),
        initial=initial,
        occurs=_as_int(operands.pop("OCCURS", None), "OCCURS", at=at),
        group=_string(operands.pop("GRPNAME", None)),
        operands=operands,
        line=statement.line,
    )


def _check_map(bms_map: BmsMap, path: Optional[str]) -> None:
    """Refuse a map that cannot be laid out.

    A field occupies its attribute byte at ``POS`` and ``LENGTH`` characters after it. Only the
    first occurrence of an ``OCCURS`` field is placed: the later ones follow it, and their layout
    is not modelled.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID``.
    """
    at = f"Map {bms_map.name}{where(path)}"
    if not bms_map.named_fields:
        raise MainframeParseError(
            f"{at} declares no named DFHMDF field, so the screen has no data to model",
            code="INPUT_SEMANTIC_INVALID",
        )
    problems: List[str] = []
    seen: Dict[str, int] = {}
    spans: List[Tuple[int, int, str]] = []
    last = bms_map.rows * bms_map.columns - 1
    for item in bms_map.fields:
        label = item.name or f"the literal at line {item.line}"
        if item.name:
            if item.name in seen:
                problems.append(f"{item.name} is defined twice (lines {seen[item.name]} and {item.line})")
            seen[item.name] = item.line
        if not (1 <= item.row <= bms_map.rows and 1 <= item.column <= bms_map.columns):
            problems.append(
                f"{label} is at ({item.row},{item.column}), outside the {bms_map.rows}×{bms_map.columns} map"
            )
            continue
        start = (item.row - 1) * bms_map.columns + item.column - 1
        end = start + item.length
        if end > last:
            problems.append(f"{label} runs past the end of the {bms_map.rows}×{bms_map.columns} map")
        for other_start, other_end, other in spans:
            if start <= other_end and other_start <= end:
                problems.append(f"{label} overlaps {other}")
        spans.append((start, end, label))
    if problems:
        raise MainframeParseError(f"{at} cannot be laid out: " + "; ".join(problems), code="INPUT_SEMANTIC_INVALID")


def _read_mapsets(text: str, path: Optional[str]) -> List[BmsMapset]:
    """Read every mapset of one macro source file."""
    mapsets: List[BmsMapset] = []
    current_set: Optional[BmsMapset] = None
    current_map: Optional[BmsMap] = None
    closed = False
    for statement in _statements(text, path):
        at = f" at line {statement.line}{where(path)}"
        if statement.operation in _ASSEMBLER_DIRECTIVES:
            continue
        if statement.operation == "END":
            break
        if statement.operation not in _BMS_MACROS:
            raise MainframeParseError(
                f"{statement.operation or statement.label}{at} is not a BMS macro (DFHMSD, DFHMDI, "
                "DFHMDF); a continuation line written without the column-72 mark reads this way",
                code="INPUT_MALFORMED",
            )
        operands = _operands(statement, path)
        if statement.operation == "DFHMSD":
            if _string(operands.get("TYPE")) == "FINAL":
                if current_set is None:
                    raise MainframeParseError(f"DFHMSD TYPE=FINAL{at} closes no mapset", code="INPUT_MALFORMED")
                if current_map is not None:
                    _check_map(current_map, path)
                if not current_set.maps:
                    raise MainframeParseError(
                        f"Mapset {current_set.name}{where(path)} defines no map", code="INPUT_SEMANTIC_INVALID"
                    )
                mapsets.append(current_set)
                current_set, current_map, closed = None, None, True
                continue
            if not statement.label:
                raise MainframeParseError(f"The DFHMSD{at} has no label (the mapset name)", code="INPUT_MALFORMED")
            if current_set is not None:
                raise MainframeParseError(
                    f"DFHMSD {statement.label}{at} opens a mapset before {current_set.name} is closed",
                    code="INPUT_MALFORMED",
                )
            current_set = BmsMapset(name=statement.label, operands=operands, path=path)
            closed = False
        elif statement.operation == "DFHMDI":
            if current_set is None:
                raise MainframeParseError(
                    f"The map{at} is outside a mapset (no DFHMSD before it)", code="INPUT_MALFORMED"
                )
            if not statement.label:
                raise MainframeParseError(f"The DFHMDI{at} has no label (the map name)", code="INPUT_MALFORMED")
            if current_map is not None:
                _check_map(current_map, path)
            size = _pair(operands.pop("SIZE", None), "SIZE", at=at)
            current_map = BmsMap(
                name=statement.label,
                rows=(size or DEFAULT_SIZE)[0],
                columns=(size or DEFAULT_SIZE)[1],
                size_declared=size is not None,
                operands=operands,
                line=statement.line,
            )
            if any(m.name == current_map.name for m in current_set.maps):
                raise MainframeParseError(
                    f"Map {current_map.name} is defined twice in mapset {current_set.name}",
                    code="INPUT_SEMANTIC_INVALID",
                )
            current_set.maps.append(current_map)
        else:
            if current_map is None:
                raise MainframeParseError(
                    f"The field{at} is outside a map (no DFHMDI before it)", code="INPUT_MALFORMED"
                )
            current_map.fields.append(_field(statement, operands, current_map, path))
    if current_set is not None or not closed:
        raise MainframeParseError(
            f"The BMS source{where(path)} ends before DFHMSD TYPE=FINAL closes the mapset",
            code="INPUT_TRUNCATED",
        )
    return mapsets


# ===========================================================================
# Symbolic-map copybooks
# ===========================================================================


@dataclass
class _Entry:
    level: int
    name: str
    clauses: str


def _copybook_entries(text: str) -> List[_Entry]:
    """The data entries of a fixed-format COBOL copybook (sequence area and comments dropped)."""
    code: List[str] = []
    for line in text.splitlines():
        if len(line) > 6 and line[6] in "*/":
            continue
        code.append(line[7:72] if len(line) > 7 else "")
    entries: List[_Entry] = []
    for sentence in " ".join(code).split(". "):
        sentence = " ".join(sentence.split()).rstrip(".")
        match = _ENTRY_RE.match(sentence)
        if match:
            entries.append(_Entry(level=int(match.group(1)), name=match.group(2).upper(), clauses=match.group(3)))
    return entries


def _read_symbolic_maps(text: str, path: Optional[str]) -> List[SymbolicMap]:
    """Read the maps of a symbolic-map copybook.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` when an input record has no field entries.
    """
    entries = _copybook_entries(text)
    records: List[Tuple[_Entry, List[_Entry]]] = []
    for entry in entries:
        if entry.level == 1:
            records.append((entry, []))
        elif records:
            records[-1][1].append(entry)
    outputs = {
        (_REDEFINES_RE.search(record.clauses).group(1).upper()): (record, members)  # type: ignore[union-attr]
        for record, members in records
        if _REDEFINES_RE.search(record.clauses)
    }
    maps: List[SymbolicMap] = []
    for record, members in records:
        if _REDEFINES_RE.search(record.clauses) or not record.name.endswith("I"):
            continue
        name = record.name[:-1]
        output = outputs.get(record.name)
        symbolic = SymbolicMap(
            name=name, input_record=record.name, output_record=output[0].name if output else None, path=path
        )
        _symbolic_fields(symbolic, members, output[1] if output else [])
        if not symbolic.fields:
            raise MainframeParseError(
                f"The symbolic map {record.name}{where(path)} has no <field>L / <field>I entries",
                code="INPUT_SEMANTIC_INVALID",
            )
        maps.append(symbolic)
    return maps


def _symbolic_fields(symbolic: SymbolicMap, inputs: Sequence[_Entry], outputs: Sequence[_Entry]) -> None:
    """Group a symbolic map's entries into fields, keyed by their data (``I``) entries."""
    occurs_by_entry: Dict[str, int] = {}
    group_occurs: Optional[Tuple[int, int]] = None
    for entry in list(inputs) + list(outputs):
        occurs = _OCCURS_RE.search(entry.clauses)
        if occurs and not _PIC_RE.search(entry.clauses):
            group_occurs = (entry.level, int(occurs.group(1)))
            continue
        if group_occurs and entry.level <= group_occurs[0]:
            group_occurs = None
        count = int(occurs.group(1)) if occurs else (group_occurs[1] if group_occurs else None)
        if count:
            occurs_by_entry[entry.name] = count
    pictures = {e.name: _PIC_RE.search(e.clauses) for e in list(inputs) + list(outputs)}
    names = {e.name for e in list(inputs) + list(outputs) if e.name != "FILLER"}
    for entry in inputs:
        if entry.name == "FILLER" or not entry.name.endswith("I") or not pictures.get(entry.name):
            continue
        base = entry.name[:-1]
        if f"{base}L" not in names:
            continue
        item = SymbolicField(name=base, occurs=occurs_by_entry.get(entry.name))
        for suffix in _SYMBOLIC_SUFFIXES + ("I", "O"):
            if f"{base}{suffix}" in names:
                item.entries[suffix] = f"{base}{suffix}"
        input_picture = pictures[entry.name]
        output_picture = pictures.get(f"{base}O")
        item.input_picture = input_picture.group(1) if input_picture else None
        item.output_picture = output_picture.group(1) if output_picture else None
        symbolic.fields.append(item)


# ===========================================================================
# Entry points
# ===========================================================================


def _read_file(text: str, path: Optional[str], document: BmsDocument, *, require: bool) -> bool:
    """Read one file into ``document``.

    Args:
        require: Refuse a file that is neither macro source nor a symbolic map
            (``FORMAT_MISMATCH``) instead of skipping it.

    Returns:
        Whether the file was read.
    """
    check_encoding(text, path, what="BMS source")
    if has_bms_macros(text):
        document.mapsets.extend(_read_mapsets(text, path))
    elif is_symbolic_map(text):
        document.symbolic_maps.extend(_read_symbolic_maps(text, path))
    elif require:
        raise MainframeParseError(
            f"No DFHMSD / DFHMDI / DFHMDF macro{where(path)} and no BMS symbolic map was found; "
            "this is not CICS BMS source",
            code="FORMAT_MISMATCH",
        )
    else:
        return False
    document.sources[path or "input.bms"] = text
    return True


def _attach_symbolic_maps(document: BmsDocument) -> None:
    """Pair each symbolic map with the map of the same name; keep the unpaired ones."""
    unpaired: List[SymbolicMap] = []
    for symbolic in document.symbolic_maps:
        target = next((m for s in document.mapsets for m in s.maps if m.name == symbolic.name), None)
        if target is None:
            unpaired.append(symbolic)
        else:
            target.symbolic = symbolic
    document.symbolic_maps = unpaired


def _check_names(document: BmsDocument) -> None:
    seen: Dict[str, str] = {}
    for mapset in document.mapsets:
        if mapset.name in seen:
            raise MainframeParseError(
                f"Mapset {mapset.name} is defined twice ({seen[mapset.name]} and {mapset.path or 'the input'})",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[mapset.name] = mapset.path or "the input"


def parse_bms_text(text: str, *, label: Optional[str] = None) -> BmsDocument:
    """Parse one uploaded BMS macro source file or symbolic-map copybook.

    Args:
        text: The file text.
        label: The upload's file name, for messages.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    if text is None or not text.strip():
        raise MainframeParseError("The BMS source is empty", code="INPUT_EMPTY")
    document = BmsDocument(label=label)
    _read_file(text, label, document, require=True)
    _check_names(document)
    return document


def parse_bms_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> BmsDocument:
    """Parse a mapset with its symbolic-map copybooks (or several of each).

    Members with a :data:`SOURCE_SUFFIXES` suffix are read; a symbolic map is paired with the map
    of the same name. A member that is neither macro source nor a symbolic map is ignored unless it
    is the root.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    document = BmsDocument(label=label or fileset.root, is_fileset=True)
    for path in sorted(fileset.members):
        text = fileset.members[path]
        if PurePosixPath(path).suffix.lower() not in SOURCE_SUFFIXES and path != fileset.root:
            continue
        if not text.strip():
            continue
        _read_file(text, path, document, require=path == fileset.root)
    if not document.sources:
        raise MainframeParseError("The upload holds no BMS macro source and no symbolic map", code="FORMAT_MISMATCH")
    _attach_symbolic_maps(document)
    _check_names(document)
    return document
