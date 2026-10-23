"""PL/I ``DECLARE`` structure reader — FMT-11.1 (#5480).

PL/I structures sit beside COBOL copybooks in the same estates and describe the same records with a
different declaration syntax. This module reads the declarations a PL/I include member (or a
program's declare section) carries and returns a :class:`PliDocument` of structures; storage
arithmetic is :mod:`app.pli_layout`'s, normalization :mod:`app.pli_normalizer`'s.

What is read
------------
.. code-block:: text

    DCL 1 ORDER_REC BASED(P),            major structure (level 1), storage class kept
          2 ORDER_ID   CHAR(10),         elementary item: CHAR / GRAPHIC / WIDECHAR / BIT [VARYING]
          2 TOTAL      FIXED DEC(15,2),  FIXED / FLOAT, DEC / BIN, precision, SIGNED / UNSIGNED
          2 SHIP_TO    LIKE ADDR_BLOCK,  structure clone — expanded after every declaration is read
          2 LINES(20),                   dimensions: (n), (l:u), (n,m), (*), (e REFER(x))
            3 SKU      PIC'(8)X',        picture
          2 BODY UNION,                  shared storage — members overlay one another
            ...
     %INCLUDE ADDRBLK;                   textual inclusion, resolved against the fileset

* **Levels.** A structure starts at level 1; a deeper level number opens a member of the item
  before it. Level numbers need not be consecutive (``2`` then ``4`` is a child), as in PL/I.
* **Attributes.** The data attributes above, alignment (``ALIGNED`` / ``UNALIGNED``, inherited by a
  structure's members), storage class (``BASED``, ``STATIC``, ``CONTROLLED`` …), ``DEFINED`` and
  ``POSITION``. Attributes with no bearing on the record (``INITIAL``, ``BYADDR``, ``NONASSIGNABLE``
  …) are skipped with their arguments; an attribute this reader does not know is kept as *unread*
  and reported by the normalizer as a declared limit.
* **Defaults.** An elementary item with no data attributes takes PL/I's language defaults —
  ``FIXED BIN(15)`` for a name starting I–N, else ``FLOAT DEC(6)`` — and partial attributes are
  completed the same way (``FIXED`` → ``FIXED DEC(5,0)``, ``BIN`` → ``FLOAT BIN(21)``).
* **Scalars.** A declaration without a level number (``DCL P POINTER;``) is kept as a scalar; it is
  not a record.

``%INCLUDE``
------------
``%INCLUDE name;``, ``%INCLUDE ddname(member);`` and ``%INCLUDE 'path';`` are resolved against the
fileset by member name (case-insensitive, any suffix) and the member's text is spliced in place,
exactly as the preprocessor would. An include that cannot be resolved is handled by what it leaves
missing:

* a ``LIKE`` (or ``DEFINED``) naming a declaration nothing in the upload supplies → the import is
  refused with ``INPUT_REFERENCE_UNRESOLVED``, naming the missing members — a clone of an unknown
  block has no layout at all;
* an include **inside** a structure (its lines would have been members) → the structure keeps an
  :attr:`PliItem.include` placeholder at that point, so its layout stops being a number there and
  the record is reported ``partial`` with the member named — never a silently short layout;
* an include between declarations that nothing references → the import goes ahead and the
  document records it in :attr:`PliDocument.includes` as unresolved.

Errors
------
Every failure is a :class:`~app.mainframe_misc_common.MainframeParseError` carrying an intake code:

==============================  ==================================================================
``INPUT_EMPTY``                 nothing but blanks and comments
``INPUT_ENCODING_INVALID``      a UTF-16 / binary upload (NULs, U+FFFD, a byte-order mark)
``FORMAT_MISMATCH``             no ``DCL`` / ``DECLARE`` / ``%INCLUDE`` anywhere (a COBOL copybook)
``INPUT_TRUNCATED``             the text ends inside a comment, a string, parentheses or a statement
``INPUT_MALFORMED``             a statement that does not parse (a missing ``;`` before ``DCL``)
``INPUT_SEMANTIC_INVALID``      levels that do not form a tree, a member under an item with data
                                attributes, ``LIKE`` of a non-structure, a ``LIKE`` / include cycle,
                                duplicate structure names, no structure at all
``INPUT_REFERENCE_UNRESOLVED``  a ``LIKE`` / ``DEFINED`` target nothing in the upload declares
==============================  ==================================================================
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from .fileset import IntakeFileset
from .mainframe_misc_common import MainframeParseError, check_encoding, where

__all__ = [
    "FORMAT_KEY",
    "SOURCE_SUFFIXES",
    "PliData",
    "PliDimension",
    "PliDocument",
    "PliInclude",
    "PliItem",
    "PliStatement",
    "has_pli_declarations",
    "parse_pli_fileset",
    "parse_pli_text",
]

#: Adapter / normalizer key.
FORMAT_KEY = "pli"

#: File suffixes read as PL/I source when they sit in a fileset.
SOURCE_SUFFIXES = (".pli", ".pl1", ".inc", ".cpy", ".copy", ".txt")

#: How deep ``%INCLUDE`` may nest before the reader stops (a cycle is reported separately).
MAX_INCLUDE_DEPTH = 16

# ---------------------------------------------------------------------------
# Attribute vocabulary
# ---------------------------------------------------------------------------

#: Synonyms → the attribute name this module uses.
_SYNONYMS: Dict[str, str] = {
    "DECLARE": "DCL",
    "CHARACTER": "CHAR",
    "G": "GRAPHIC",
    "WCHAR": "WIDECHAR",
    "DECIMAL": "DEC",
    "BINARY": "BIN",
    "CPLX": "COMPLEX",
    "PICTURE": "PIC",
    "VAR": "VARYING",
    "VARZ": "VARYINGZ",
    "NONVAR": "NONVARYING",
    "PTR": "POINTER",
    "AUTO": "AUTOMATIC",
    "CTL": "CONTROLLED",
    "EXT": "EXTERNAL",
    "INT": "INTERNAL",
    "DEF": "DEFINED",
    "POS": "POSITION",
    "INIT": "INITIAL",
    "DIM": "DIMENSION",
    "PARM": "PARAMETER",
    "CONN": "CONNECTED",
    "NONCONN": "NONCONNECTED",
    "ASGN": "ASSIGNABLE",
    "NONASGN": "NONASSIGNABLE",
    "CELL": "UNION",
}

#: String-like data attributes, which take a length.
_STRING_KINDS = {"CHAR": "character", "BIT": "bit", "GRAPHIC": "graphic", "WIDECHAR": "widechar"}
#: Locator / program-control data attributes. Their argument (if any) is a name, not a size.
_LOCATOR_KINDS = {
    "POINTER": "pointer",
    "OFFSET": "offset",
    "HANDLE": "handle",
    "AREA": "area",
    "ENTRY": "entry",
    "FILE": "file",
    "LABEL": "label",
    "FORMAT": "format",
    "EVENT": "event",
    "TASK": "task",
    "ORDINAL": "ordinal",
    "TYPE": "type",
}
#: Arithmetic attribute words; a parenthesised list after one of them is the precision.
_ARITHMETIC = {"FIXED", "FLOAT", "DEC", "BIN", "REAL", "COMPLEX", "SIGNED", "UNSIGNED"}
#: Storage classes, kept as declared metadata.
_STORAGE_CLASSES = {"AUTOMATIC", "STATIC", "BASED", "CONTROLLED", "PARAMETER", "DEFINED"}
#: Scope attributes, kept as declared metadata.
_SCOPES = {"EXTERNAL", "INTERNAL"}
#: Attributes that change nothing about a record's shape; skipped with any argument.
_SKIPPED = {
    "INITIAL",
    "VALUE",
    "BYADDR",
    "BYVALUE",
    "CONNECTED",
    "NONCONNECTED",
    "ASSIGNABLE",
    "NONASSIGNABLE",
    "NORMAL",
    "ABNORMAL",
    "OPTIONAL",
    "BIGENDIAN",
    "LITTLEENDIAN",
    "NATIVE",
    "NONNATIVE",
    "HEXADEC",
    "IEEE",
    "DATE",
    "BUILTIN",
    "RESERVED",
    "NONVARYING",
    "VARIABLE",
    "CONSTANT",
    "LIST",
    "SUPPRESS",
}
#: Statement keywords that may never appear inside a declaration — seeing one means the ``;`` that
#: should have ended the declaration before it is missing.
_STATEMENT_KEYWORDS = {"DCL", "PROC", "PROCEDURE", "BEGIN", "END", "CALL", "DO", "IF"}
#: Listing-control directives dropped without trace.
_LISTING_DIRECTIVES = {"PAGE", "SKIP", "PRINT", "NOPRINT", "PROCESS", "NOTE", "LINE", "PUSH", "POP"}

#: Language-default precisions (Enterprise PL/I, RULES(IBM)).
_DEFAULT_PRECISION = {("FIXED", "DEC"): 5, ("FIXED", "BIN"): 15, ("FLOAT", "DEC"): 6, ("FLOAT", "BIN"): 21}

_DECLARATION_MARKER = re.compile(r"(?:^|;)\s*(?:[A-Z_@#$][\w@#$]*\s*:\s*)*(?:DCL|DECLARE)\b", re.I | re.M)
_INCLUDE_MARKER = re.compile(r"%\s*X?INCLUDE\b", re.I)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_SEQUENCE_TAIL = re.compile(r"[A-Z0-9 ]{1,8}")


# ---------------------------------------------------------------------------
# Parsed shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PliDimension:
    """One bound pair of an array dimension.

    Attributes:
        lower: The lower bound, when it is a constant (``1`` when omitted).
        upper: The upper bound, when it is a constant.
        text: The bound pair as written (``1:12``, ``*``, ``N REFER(COUNT)``).
        refer: The member named by ``REFER``, when the extent is self-defining.
    """

    lower: Optional[int]
    upper: Optional[int]
    text: str
    refer: Optional[str] = None

    @property
    def count(self) -> Optional[int]:
        """The number of elements, or ``None`` when a bound is not a constant."""
        if self.lower is None or self.upper is None:
            return None
        return max(self.upper - self.lower + 1, 0)


@dataclass
class PliData:
    """An elementary item's data description, completed with PL/I's defaults.

    Attributes:
        kind: ``character``, ``bit``, ``graphic``, ``widechar``, ``fixed-decimal``,
            ``fixed-binary``, ``float-decimal``, ``float-binary``, ``picture``, or a locator /
            program-control kind (``pointer``, ``offset``, ``area``, ``handle``, ``entry`` …).
        length: A string's length or an area's size, when it is a constant.
        length_text: The length as written, when it is not a constant (``*``, ``N REFER(L)``).
        refer: The member named by ``REFER`` in the length, when there is one.
        varying: ``VARYING`` or ``VARYINGZ`` for a varying string.
        precision: Arithmetic precision (digits or bits).
        scale: Arithmetic scale factor (digits after the decimal point).
        unsigned: True for ``UNSIGNED`` binary.
        complex: True for ``COMPLEX`` arithmetic.
        picture: The picture string, without quotes.
        target: The argument of ``OFFSET(area)`` / ``HANDLE(type)`` / ``ORDINAL name`` / ``TYPE name``.
        defaulted: The attributes the language defaults supplied (``scale``, ``base``,
            ``precision``, ``all``), so a reader can tell declared from assumed.
    """

    kind: str
    length: Optional[int] = None
    length_text: Optional[str] = None
    refer: Optional[str] = None
    varying: Optional[str] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    unsigned: bool = False
    complex: bool = False
    picture: Optional[str] = None
    target: Optional[str] = None
    defaulted: Tuple[str, ...] = ()


@dataclass
class PliItem:
    """One declared item: a structure, a member, a scalar, or an unresolved-include placeholder.

    Attributes:
        level: The level number as written (``None`` for a scalar declared without one).
        name: The item's name (``*`` for an unnamed filler member).
        file: The file the item was declared in.
        line: The 1-based line it was declared on.
        dimensions: Its array dimensions, outermost first.
        data: The data description of an elementary item; ``None`` for a structure.
        like: The structure named by ``LIKE``; the item's members are a copy of its members.
        union: True for a ``UNION`` / ``CELL`` structure, whose members share storage.
        alignment: ``ALIGNED`` / ``UNALIGNED`` as written on this item.
        storage_class: ``BASED`` / ``STATIC`` / ``CONTROLLED`` … as written.
        locator: The argument of ``BASED(…)``.
        defined: The base of ``DEFINED`` (an overlay of other storage).
        position: The ``POSITION(n)`` of a ``DEFINED`` overlay.
        scope: ``EXTERNAL`` / ``INTERNAL`` as written.
        unread: Attributes this reader does not know, as written.
        children: The item's members.
        include: For a placeholder only — the ``%INCLUDE`` member that could not be resolved where
            a member list continued; the item has no name, data or size.
        cloned_from: Set on members copied in by ``LIKE`` — the structure they were copied from.
    """

    level: Optional[int]
    name: str
    file: str
    line: int
    dimensions: List[PliDimension] = field(default_factory=list)
    data: Optional[PliData] = None
    like: Optional[str] = None
    union: bool = False
    alignment: Optional[str] = None
    storage_class: Optional[str] = None
    locator: Optional[str] = None
    defined: Optional[str] = None
    position: Optional[int] = None
    scope: Optional[str] = None
    unread: List[str] = field(default_factory=list)
    children: List["PliItem"] = field(default_factory=list)
    include: Optional[str] = None
    cloned_from: Optional[str] = None

    @property
    def is_structure(self) -> bool:
        """True for an item with members (or a ``LIKE`` clone, which has its target's)."""
        return bool(self.children) or self.like is not None

    def walk(self) -> Iterator["PliItem"]:
        """Yield this item and every item under it, in declaration order."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class PliInclude:
    """One ``%INCLUDE`` directive.

    Attributes:
        member: The member name it asks for (``ADDRBLK``; ``SYSLIB(ADDRBLK)`` → ``ADDRBLK``).
        file: The file the directive sits in.
        line: Its 1-based line.
        resolved: The fileset path it resolved to, or ``None`` when no member matched.
        inside: The structure the directive sits inside, when it is within a declaration.
    """

    member: str
    file: str
    line: int
    resolved: Optional[str]
    inside: Optional[str] = None


@dataclass(frozen=True)
class PliStatement:
    """A statement that is not a declaration (``PROC``, an assignment, a preprocessor ``%DCL`` …).

    Attributes:
        keyword: Its first word.
        file: The file it is in.
        line: Its 1-based line.
    """

    keyword: str
    file: str
    line: int


@dataclass
class PliDocument:
    """Every structure a PL/I source (or fileset) declares.

    Attributes:
        label: The upload's label.
        is_fileset: True when read from a set of members.
        sources: ``path → text`` of every file read (the root and the members it included).
        structures: Major structures (level-1 items with members), in declaration order.
        scalars: Items declared without a level number (``DCL P POINTER;``).
        includes: Every ``%INCLUDE`` directive met, resolved or not.
        statements: Statements that are not declarations, which are not read.
        unreferenced: Fileset members no ``%INCLUDE`` reached.
    """

    label: Optional[str]
    is_fileset: bool = False
    sources: Dict[str, str] = field(default_factory=dict)
    structures: List[PliItem] = field(default_factory=list)
    scalars: List[PliItem] = field(default_factory=list)
    includes: List[PliInclude] = field(default_factory=list)
    statements: List[PliStatement] = field(default_factory=list)
    unreferenced: List[str] = field(default_factory=list)

    @property
    def unresolved_includes(self) -> List[PliInclude]:
        """The ``%INCLUDE`` directives no member satisfied."""
        return [include for include in self.includes if include.resolved is None]


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    """One lexical token.

    ``kind`` is ``word`` (an identifier or keyword, upper-cased), ``number``, ``string`` (``text``
    holds the content without quotes), ``punct``, or ``include`` (an unresolved ``%INCLUDE``
    placeholder whose ``text`` is the member name).
    """

    kind: str
    text: str
    file: str
    line: int


_WORD_START = re.compile(r"[A-Za-z_@#$]")
_WORD = re.compile(r"[A-Za-z0-9_@#$]+")
_NUMBER = re.compile(r"\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?")


def _strip_margins(text: str) -> str:
    """Drop sequence numbers in columns 73–80 when the source carries them.

    Fixed-format PL/I keeps statements in columns 2–72 and a sequence number in 73–80. The columns
    are cut only when every line longer than 72 characters has a short alphanumeric tail there, so a
    free-format file with a long comment line is left alone.
    """
    lines = text.split("\n")
    long_lines = [line.rstrip("\r") for line in lines if len(line.rstrip("\r")) > 72]
    if not long_lines or any(len(line) > 80 or not _SEQUENCE_TAIL.fullmatch(line[72:].upper()) for line in long_lines):
        return text
    return "\n".join(line.rstrip("\r")[:72] for line in lines)


def _tokenize(text: str, path: str) -> List[_Token]:
    """Split PL/I source into tokens, dropping comments.

    Raises:
        MainframeParseError: ``INPUT_TRUNCATED`` for a comment or string still open at the end.
    """
    text = _strip_margins(text)
    tokens: List[_Token] = []
    index = 0
    line = 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
            continue
        if char.isspace():
            index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise MainframeParseError(
                    f"A comment opened on line {line}{where(path)} is never closed — the source is cut off",
                    code="INPUT_TRUNCATED",
                )
            line += text.count("\n", index, end)
            index = end + 2
            continue
        if char in "'\"":
            start_line = line
            cursor = index + 1
            parts: List[str] = []
            while True:
                end = text.find(char, cursor)
                if end < 0:
                    raise MainframeParseError(
                        f"A string opened on line {start_line}{where(path)} is never closed — the source is cut off",
                        code="INPUT_TRUNCATED",
                    )
                parts.append(text[cursor:end])
                if text.startswith(char * 2, end):
                    parts.append(char)
                    cursor = end + 2
                    continue
                break
            line += text.count("\n", index, end)
            index = end + 1
            # A string may carry a type suffix ('101'B, 'C1'X, 'abc'G); it is part of the constant.
            suffix = _WORD.match(text, index)
            if suffix and suffix.group(0).upper() in {
                "B",
                "B1",
                "B3",
                "B4",
                "BX",
                "X",
                "XN",
                "XU",
                "G",
                "GX",
                "M",
                "A",
                "E",
                "W",
                "WX",
                "U",
            }:
                index = suffix.end()
            tokens.append(_Token("string", "".join(parts), path, start_line))
            continue
        if _WORD_START.match(char):
            match = _WORD.match(text, index)
            assert match is not None
            tokens.append(_Token("word", match.group(0).upper(), path, line))
            index = match.end()
            continue
        if char.isdigit():
            match = _NUMBER.match(text, index)
            assert match is not None
            tokens.append(_Token("number", match.group(0), path, line))
            index = match.end()
            continue
        tokens.append(_Token("punct", char, path, line))
        index += 1
    return tokens


def _drop_process_lines(text: str) -> str:
    """Blank ``*PROCESS`` compiler-option lines, keeping line numbers."""
    return "\n".join("" if line.lstrip().upper().startswith("*PROCESS") else line for line in text.split("\n"))


# ---------------------------------------------------------------------------
# %INCLUDE
# ---------------------------------------------------------------------------


def _member_key(name: str) -> str:
    """Normalise a member name or fileset path to the key includes are matched on."""
    return PurePosixPath(name.replace("\\", "/")).stem.upper()


class _Expander:
    """Tokenizes the root file, splicing ``%INCLUDE`` members in place."""

    def __init__(self, members: Dict[str, str], document: PliDocument) -> None:
        self._members = members
        self._by_key: Dict[str, str] = {}
        for path in sorted(members):
            self._by_key.setdefault(_member_key(path), path)
        self._document = document
        self.reached: Set[str] = set()

    def expand(self, path: str, stack: Tuple[str, ...] = ()) -> List[_Token]:
        """Return ``path``'s tokens with every include spliced in.

        Raises:
            MainframeParseError: For an encoding fault, a truncated directive or an include cycle.
        """
        if path in stack:
            chain = " → ".join([*stack, path])
            raise MainframeParseError(
                f"%INCLUDE members include one another in a cycle: {chain}", code="INPUT_SEMANTIC_INVALID"
            )
        if len(stack) >= MAX_INCLUDE_DEPTH:
            raise MainframeParseError(
                f"%INCLUDE nests more than {MAX_INCLUDE_DEPTH} levels deep at {path}", code="INPUT_SEMANTIC_INVALID"
            )
        text = self._members[path]
        check_encoding(text, path, what="PL/I source")
        self.reached.add(path)
        self._document.sources[path] = text
        raw = _tokenize(_drop_process_lines(text), path)
        out: List[_Token] = []
        index = 0
        while index < len(raw):
            token = raw[index]
            if token.kind == "punct" and token.text == "%" and index + 1 < len(raw) and raw[index + 1].kind == "word":
                directive = raw[index + 1].text
                end = _directive_end(raw, index, path)
                if directive in {"INCLUDE", "XINCLUDE"}:
                    for member in _include_members(raw[index + 2 : end], token, path):
                        out.extend(self._include(member, token, (*stack, path)))
                elif directive not in _LISTING_DIRECTIVES:
                    self._document.statements.append(PliStatement(f"%{directive}", path, token.line))
                index = end + 1
                continue
            out.append(token)
            index += 1
        return out

    def _include(self, member: str, at: _Token, stack: Tuple[str, ...]) -> List[_Token]:
        """Resolve one member: its expanded tokens, or a placeholder token when it is missing."""
        resolved = self._by_key.get(_member_key(member))
        self._document.includes.append(PliInclude(member=member, file=at.file, line=at.line, resolved=resolved))
        if resolved is None:
            return [_Token("include", member, at.file, at.line)]
        return self.expand(resolved, stack)


def _directive_end(tokens: Sequence[_Token], start: int, path: str) -> int:
    """Index of the ``;`` ending the preprocessor directive at ``start``.

    Raises:
        MainframeParseError: ``INPUT_TRUNCATED`` when the file ends first.
    """
    for index in range(start, len(tokens)):
        if tokens[index].kind == "punct" and tokens[index].text == ";":
            return index
    raise MainframeParseError(
        f"The %{tokens[start + 1].text} directive on line {tokens[start].line}{where(path)} has no closing ';' — "
        "the source is cut off",
        code="INPUT_TRUNCATED",
    )


def _include_members(tokens: Sequence[_Token], at: _Token, path: str) -> List[str]:
    """Member names of one ``%INCLUDE`` directive (``A``, ``DD(A)``, ``'a.inc'``, ``A, B``).

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a directive naming nothing.
    """
    members: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "string":
            members.append(token.text)
        elif token.kind == "word":
            name = token.text
            if (
                index + 2 < len(tokens)
                and tokens[index + 1].text == "("
                and tokens[index + 2].kind in {"word", "string"}
            ):
                # ddname(member) — the member is what is looked up.
                name = tokens[index + 2].text
                index += 3
            members.append(name)
        index += 1
    if not members:
        raise MainframeParseError(f"%INCLUDE on line {at.line}{where(path)} names no member", code="INPUT_MALFORMED")
    return members


# ---------------------------------------------------------------------------
# Statements and declarations
# ---------------------------------------------------------------------------


def _split_statements(tokens: Sequence[_Token], path: str) -> List[List[_Token]]:
    """Split tokens at top-level ``;``.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for unbalanced parentheses inside a statement;
            ``INPUT_TRUNCATED`` when the last statement has no ``;``.
    """
    statements: List[List[_Token]] = []
    current: List[_Token] = []
    depth = 0
    for token in tokens:
        if token.kind == "punct" and token.text == "(":
            depth += 1
        elif token.kind == "punct" and token.text == ")":
            depth -= 1
            if depth < 0:
                raise MainframeParseError(
                    f"Unbalanced ')' on line {token.line}{where(token.file)}", code="INPUT_MALFORMED"
                )
        if token.kind == "punct" and token.text == ";":
            if depth:
                raise MainframeParseError(
                    f"The statement ending on line {token.line}{where(token.file)} leaves a parenthesis open",
                    code="INPUT_MALFORMED",
                )
            statements.append(current)
            current = []
            continue
        current.append(token)
    pending = [token for token in current if token.kind != "include"]
    if pending:
        first = pending[0]
        raise MainframeParseError(
            f"The statement starting on line {first.line}{where(first.file)} never ends — the source is cut off "
            f"(no closing ';'{', and a parenthesis is still open' if depth else ''})",
            code="INPUT_TRUNCATED",
        )
    if current:
        statements.append(current)
    return statements


def _split_top_level(tokens: Sequence[_Token], separator: str = ",") -> List[List[_Token]]:
    """Split a token run at ``separator`` outside parentheses; placeholders stand on their own."""
    parts: List[List[_Token]] = []
    current: List[_Token] = []
    depth = 0
    for token in tokens:
        if token.kind == "punct" and token.text == "(":
            depth += 1
        elif token.kind == "punct" and token.text == ")":
            depth -= 1
        if depth == 0 and token.kind == "punct" and token.text == separator:
            parts.append(current)
            current = []
            continue
        if depth == 0 and token.kind == "include":
            # An unresolved include inside a declaration ends the item before it, like a comma.
            if current:
                parts.append(current)
            parts.append([token])
            current = []
            continue
        current.append(token)
    parts.append(current)
    return parts


def _group(tokens: Sequence[_Token], start: int) -> Tuple[List[_Token], int]:
    """Return the tokens inside the parentheses opening at ``start`` and the index after them."""
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].text == "(" and tokens[index].kind == "punct":
            depth += 1
        elif tokens[index].text == ")" and tokens[index].kind == "punct":
            depth -= 1
            if depth == 0:
                return list(tokens[start + 1 : index]), index + 1
    return list(tokens[start + 1 :]), len(tokens)


def _render(tokens: Sequence[_Token]) -> str:
    """Re-render a token run compactly (``1:12``, ``N REFER(COUNT)``)."""
    out = ""
    for token in tokens:
        text = f"'{token.text}'" if token.kind == "string" else token.text
        if (
            out
            and token.kind in {"word", "number"}
            and out[-1] not in "(:,-+ "
            and (out[-1].isalnum() or out[-1] in "_@#$')")
        ):
            out += " "
        out += text
    return out


def _constant(tokens: Sequence[_Token]) -> Optional[int]:
    """The integer an expression is, when it is a (possibly signed) integer constant."""
    if len(tokens) == 1 and tokens[0].kind == "number" and tokens[0].text.isdigit():
        return int(tokens[0].text)
    if len(tokens) == 2 and tokens[0].text in {"-", "+"} and tokens[1].kind == "number" and tokens[1].text.isdigit():
        value = int(tokens[1].text)
        return -value if tokens[0].text == "-" else value
    return None


def _refer(tokens: Sequence[_Token]) -> Optional[str]:
    """The member a ``REFER(name)`` in an extent names."""
    for index, token in enumerate(tokens):
        if token.kind == "word" and token.text == "REFER" and index + 2 < len(tokens) and tokens[index + 1].text == "(":
            return tokens[index + 2].text
    return None


def _dimensions(tokens: Sequence[_Token]) -> List[PliDimension]:
    """Read a dimension list ``(n)``, ``(l:u)``, ``(n,m)``, ``(*)``, ``(e REFER(x))``."""
    dimensions: List[PliDimension] = []
    for bound in _split_top_level(tokens):
        refer = _refer(bound)
        halves = _split_top_level(bound, ":")
        if len(halves) == 2:
            lower, upper = _constant(halves[0]), _constant(halves[1])
        else:
            lower, upper = 1, _constant(bound)
        dimensions.append(PliDimension(lower=lower, upper=upper, text=_render(bound), refer=refer))
    return dimensions


def _malformed(message: str, token: _Token) -> MainframeParseError:
    return MainframeParseError(f"{message} on line {token.line}{where(token.file)}", code="INPUT_MALFORMED")


@dataclass
class _Attributes:
    """Attributes collected from one declaration item, before defaults are applied."""

    words: List[str] = field(default_factory=list)
    string_kind: Optional[str] = None
    length: Optional[int] = None
    length_text: Optional[str] = None
    refer: Optional[str] = None
    varying: Optional[str] = None
    scale: Optional[str] = None
    base: Optional[str] = None
    precision: Optional[int] = None
    fraction: Optional[int] = None
    unsigned: bool = False
    complex: bool = False
    picture: Optional[str] = None
    locator: Optional[str] = None
    locator_arg: Optional[str] = None
    like: Optional[str] = None
    union: bool = False
    alignment: Optional[str] = None
    storage_class: Optional[str] = None
    based_on: Optional[str] = None
    defined: Optional[str] = None
    position: Optional[int] = None
    scope: Optional[str] = None
    dimensions: List[PliDimension] = field(default_factory=list)
    unread: List[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        """Whether any data attribute was written (a structure may carry none)."""
        return bool(
            self.string_kind
            or self.picture is not None
            or self.locator
            or self.scale
            or self.base
            or self.precision is not None
            or self.unsigned
            or self.complex
        )


def _read_attributes(tokens: Sequence[_Token], start: int, name_token: _Token) -> _Attributes:
    """Read the attributes after an item's name (and dimensions).

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a token that is not an attribute.
    """
    attrs = _Attributes()
    index = start
    last_arithmetic = False
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "punct" and token.text == "(":
            group, index = _group(tokens, index)
            if last_arithmetic:
                parts = _split_top_level(group)
                attrs.precision = _constant(parts[0])
                attrs.fraction = _constant(parts[1]) if len(parts) > 1 else None
                if attrs.precision is None:
                    raise _malformed(f"The precision of {name_token.text} is not a number", token)
            else:
                raise _malformed(f"Unexpected '(' after the attributes of {name_token.text}", token)
            last_arithmetic = False
            continue
        last_arithmetic = False
        if token.kind != "word":
            raise _malformed(
                f"Unexpected {token.text!r} in the declaration of {name_token.text} — a ',' or ';' is missing", token
            )
        word = _SYNONYMS.get(token.text, token.text)
        has_group = index + 1 < len(tokens) and tokens[index + 1].kind == "punct" and tokens[index + 1].text == "("
        argument: List[_Token] = []
        after = index + 1
        if has_group:
            argument, after = _group(tokens, index + 1)
        if word in _STATEMENT_KEYWORDS:
            raise _malformed(
                f"{token.text} appears inside the declaration of {name_token.text} — the ';' before it is missing",
                token,
            )
        attrs.words.append(word)
        if word in _STRING_KINDS:
            attrs.string_kind = word
            if has_group:
                attrs.length = _constant(argument)
                attrs.length_text = None if attrs.length is not None else _render(argument)
                attrs.refer = _refer(argument)
            index = after
            continue
        if word in {"VARYING", "VARYINGZ"}:
            attrs.varying = word
        elif word in {"FIXED", "FLOAT"}:
            attrs.scale = word
            last_arithmetic = True
        elif word in {"DEC", "BIN"}:
            attrs.base = word
            last_arithmetic = True
        elif word in {"REAL", "SIGNED"}:
            last_arithmetic = True
        elif word == "UNSIGNED":
            attrs.unsigned = True
            last_arithmetic = True
        elif word == "COMPLEX":
            attrs.complex = True
            last_arithmetic = True
        elif word == "PIC":
            if index + 1 >= len(tokens) or tokens[index + 1].kind != "string":
                raise _malformed(f"PICTURE of {name_token.text} is not followed by a quoted picture", token)
            attrs.picture = tokens[index + 1].text
            index += 2
            continue
        elif word in _LOCATOR_KINDS:
            attrs.locator = word
            if (
                word in {"ORDINAL", "TYPE"}
                and not has_group
                and index + 1 < len(tokens)
                and tokens[index + 1].kind == "word"
            ):
                attrs.locator_arg = tokens[index + 1].text
                index += 2
                continue
            if has_group:
                attrs.locator_arg = _render(argument)
                if word == "AREA":
                    attrs.length = _constant(argument)
                    attrs.length_text = None if attrs.length is not None else _render(argument)
                    attrs.refer = _refer(argument)
            index = after
            continue
        elif word == "LIKE":
            if index + 1 >= len(tokens) or tokens[index + 1].kind != "word":
                raise _malformed(f"LIKE in the declaration of {name_token.text} names no structure", token)
            qualified = [tokens[index + 1].text]
            index += 2
            while index + 1 < len(tokens) and tokens[index].text == "." and tokens[index + 1].kind == "word":
                qualified.append(tokens[index + 1].text)
                index += 2
            attrs.like = ".".join(qualified)
            continue
        elif word == "UNION":
            attrs.union = True
        elif word in {"ALIGNED", "UNALIGNED"}:
            attrs.alignment = word
        elif word == "DIMENSION":
            attrs.dimensions = _dimensions(argument)
            index = after
            continue
        elif word in _STORAGE_CLASSES:
            attrs.storage_class = word if word != "DEFINED" else attrs.storage_class
            if word == "BASED" and has_group:
                attrs.based_on = _render(argument)
            if word == "DEFINED":
                if has_group:
                    attrs.defined = _render(argument)
                elif index + 1 < len(tokens) and tokens[index + 1].kind == "word":
                    attrs.defined = tokens[index + 1].text
                    index += 2
                    continue
            index = after
            continue
        elif word == "POSITION":
            attrs.position = _constant(argument)
            index = after
            continue
        elif word in _SCOPES:
            attrs.scope = word
            index = after
            continue
        elif word in _SKIPPED:
            # INITIAL CALL f(...) / INITIAL TO(...) carry a second word before the list.
            if (
                word == "INITIAL"
                and not has_group
                and index + 1 < len(tokens)
                and tokens[index + 1].text in {"CALL", "TO"}
            ):
                index += 2
                while index < len(tokens) and tokens[index].kind == "word":
                    index += 1
                if index < len(tokens) and tokens[index].text == "(":
                    _, index = _group(tokens, index)
                continue
            index = after
            continue
        else:
            attrs.unread.append(token.text + (f"({_render(argument)})" if has_group else ""))
            attrs.words.pop()
            index = after
            continue
        index += 1
    return attrs


def _complete_data(name: str, attrs: _Attributes) -> PliData:
    """Build an elementary item's data description, applying the language defaults."""
    if attrs.string_kind:
        length = attrs.length if attrs.length is not None or attrs.length_text else 1
        return PliData(
            kind=_STRING_KINDS[attrs.string_kind],
            length=length,
            length_text=attrs.length_text,
            refer=attrs.refer,
            varying=attrs.varying,
            defaulted=() if attrs.length is not None or attrs.length_text else ("length",),
        )
    if attrs.picture is not None:
        return PliData(kind="picture", picture=attrs.picture)
    if attrs.locator:
        return PliData(
            kind=_LOCATOR_KINDS[attrs.locator],
            length=attrs.length,
            length_text=attrs.length_text,
            refer=attrs.refer,
            target=None if attrs.locator == "AREA" else attrs.locator_arg,
        )
    defaulted: List[str] = []
    scale, base = attrs.scale, attrs.base
    if scale is None and base is None and attrs.precision is None and not attrs.complex and not attrs.unsigned:
        # No data attributes at all: PL/I's implicit rule by the name's first letter.
        if name[:1] in "IJKLMN":
            scale, base = "FIXED", "BIN"
        else:
            scale, base = "FLOAT", "DEC"
        defaulted.append("all")
    if scale is None:
        scale = "FLOAT"
        defaulted.append("scale")
    if base is None:
        base = "DEC"
        defaulted.append("base")
    precision = attrs.precision
    if precision is None:
        precision = _DEFAULT_PRECISION[(scale, base)]
        if "all" not in defaulted:
            defaulted.append("precision")
    return PliData(
        kind=f"{'fixed' if scale == 'FIXED' else 'float'}-{'decimal' if base == 'DEC' else 'binary'}",
        precision=precision,
        scale=attrs.fraction if scale == "FIXED" else None,
        unsigned=attrs.unsigned,
        complex=attrs.complex,
        defaulted=tuple(defaulted),
    )


def _read_item(tokens: Sequence[_Token], statement_start: _Token) -> List[PliItem]:
    """Read one comma-separated declaration item (several when its names are factored).

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` when the item has no name or a stray token.
    """
    if not tokens:
        raise _malformed("An empty item (two commas in a row) in a declaration", statement_start)
    index = 0
    level: Optional[int] = None
    if tokens[0].kind == "number":
        if not tokens[0].text.isdigit():
            raise _malformed(f"{tokens[0].text} is not a level number", tokens[0])
        level = int(tokens[0].text)
        index = 1
    if index >= len(tokens):
        raise _malformed("A level number with no name after it", tokens[0])
    names: List[_Token] = []
    if tokens[index].kind == "punct" and tokens[index].text == "(":
        group, index = _group(tokens, index)
        for part in _split_top_level(group):
            if len(part) != 1 or part[0].kind != "word":
                raise _malformed("A factored declaration lists something other than names", tokens[0])
            names.append(part[0])
    elif tokens[index].kind == "word" or (tokens[index].kind == "punct" and tokens[index].text == "*"):
        names.append(tokens[index])
        index += 1
    else:
        raise _malformed(f"Expected a name, found {tokens[index].text!r}", tokens[index])
    dimensions: List[PliDimension] = []
    if index < len(tokens) and tokens[index].kind == "punct" and tokens[index].text == "(":
        group, index = _group(tokens, index)
        dimensions = _dimensions(group)
    attrs = _read_attributes(tokens, index, names[0])
    if attrs.dimensions:
        dimensions = attrs.dimensions
    items: List[PliItem] = []
    for name_token in names:
        item = PliItem(
            level=level,
            name=name_token.text,
            file=name_token.file,
            line=name_token.line,
            dimensions=list(dimensions),
            like=attrs.like,
            union=attrs.union,
            alignment=attrs.alignment,
            storage_class=attrs.storage_class,
            locator=attrs.based_on,
            defined=attrs.defined,
            position=attrs.position,
            scope=attrs.scope,
            unread=list(attrs.unread),
        )
        # Data is completed once the item is known to be elementary (see _build_tree).
        item.data = _complete_data(item.name, attrs) if attrs.has_data else None
        setattr(item, "_attrs", attrs)
        items.append(item)
    return items


def _semantic(message: str, item: PliItem) -> MainframeParseError:
    return MainframeParseError(f"{message} (line {item.line}{where(item.file)})", code="INPUT_SEMANTIC_INVALID")


def _build_tree(items: Sequence[PliItem], document: PliDocument) -> None:
    """Arrange one declaration's items into structures by level number.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` when the levels do not form a tree or a
            member sits under an item with data attributes.
    """
    stack: List[PliItem] = []
    for item in items:
        if item.include is not None:
            if not stack:
                continue
            # The member list continued in a file nobody supplied: hang the gap on the structure
            # still being built — the item before it when that one can open a structure (no data
            # attributes, no LIKE), else that item's parent.
            last = stack[-1]
            opens = last.data is None and last.like is None
            owner = last if opens or len(stack) == 1 else stack[-2]
            placeholder = PliItem(
                level=None, name=f"%INCLUDE {item.include}", file=item.file, line=item.line, include=item.include
            )
            owner.children.append(placeholder)
            continue
        if item.level is None:
            # A name without a level number ends the structure before it and declares a scalar.
            stack.clear()
            document.scalars.append(_finish_elementary(item))
            continue
        while stack and stack[-1].level is not None and item.level is not None and stack[-1].level >= item.level:
            stack.pop()
        if not stack:
            if item.level != 1:
                raise _semantic(
                    f"{item.name} is declared at level {item.level} with no level-1 structure above it — the levels "
                    "do not form a tree",
                    item,
                )
            document.structures.append(item)
        else:
            parent = stack[-1]
            if parent.data is not None or parent.like is not None:
                what = "LIKE" if parent.like is not None else "data attributes"
                raise _semantic(
                    f"{item.name} is declared as a member of {parent.name}, which has {what} — it cannot have members",
                    item,
                )
            parent.children.append(item)
        stack.append(item)
    for structure in list(document.structures):
        _finalize(structure)
    # A level-1 item without members is a scalar written with a level number.
    for structure in [s for s in document.structures if not s.is_structure]:
        document.structures.remove(structure)
        document.scalars.append(structure)


def _finish_elementary(item: PliItem) -> PliItem:
    """Give an item that turned out to be elementary its (defaulted) data description."""
    if item.data is None and item.like is None and item.include is None:
        attrs: _Attributes = getattr(item, "_attrs", _Attributes())
        item.data = _complete_data(item.name, attrs)
    return item


def _finalize(item: PliItem) -> None:
    """Complete data descriptions under a structure and drop the scratch attributes."""
    if not item.children:
        _finish_elementary(item)
    else:
        if item.data is not None:
            item.data = None
    for child in item.children:
        _finalize(child)
    if hasattr(item, "_attrs"):
        delattr(item, "_attrs")


def _read_declaration(keyword: _Token, tokens: Sequence[_Token], document: PliDocument) -> None:
    """Read one ``DCL`` statement (``tokens`` excludes the keyword).

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a declaration of nothing or a bad item.
    """
    if not [token for token in tokens if token.kind != "include"]:
        raise _malformed(f"{keyword.text} declares nothing", keyword)
    items: List[PliItem] = []
    for part in _split_top_level(tokens):
        if len(part) == 1 and part[0].kind == "include":
            items.append(PliItem(level=None, name="", file=part[0].file, line=part[0].line, include=part[0].text))
            continue
        items.extend(_read_item(part, keyword))
    _build_tree(items, document)


# ---------------------------------------------------------------------------
# LIKE, references and checks
# ---------------------------------------------------------------------------


def _structure_index(document: PliDocument) -> Dict[str, List[PliItem]]:
    """``name → items`` for every structure (major or minor) declared, majors first."""
    index: Dict[str, List[PliItem]] = {}
    for structure in document.structures:
        index.setdefault(structure.name, []).append(structure)
    for structure in document.structures:
        for item in list(structure.walk())[1:]:
            if item.children or item.like:
                index.setdefault(item.name, []).append(item)
    return index


def _missing_reference(what: str, item: PliItem, document: PliDocument) -> MainframeParseError:
    """The error for a reference nothing in the upload declares, naming unresolved includes."""
    unresolved = sorted({include.member for include in document.unresolved_includes})
    if unresolved:
        hint = (
            f"; %INCLUDE {', '.join(unresolved)} {'was' if len(unresolved) == 1 else 'were'} not supplied and may "
            "declare it — upload the members together as a fileset"
        )
    else:
        hint = ""
    return MainframeParseError(
        f"{what} in {item.name} (line {item.line}{where(item.file)}) names nothing the upload declares{hint}",
        code="INPUT_REFERENCE_UNRESOLVED",
    )


def _lookup(name: str, index: Dict[str, List[PliItem]], document: PliDocument) -> Optional[PliItem]:
    """Find a structure by (optionally qualified) name: a major structure first, else a unique minor."""
    parts = name.split(".")
    candidates = index.get(parts[-1], [])
    if len(parts) > 1:
        candidates = [
            c for c in candidates if any(parts[0] == s.name and c in list(s.walk()) for s in document.structures)
        ]
    majors = [c for c in candidates if c in document.structures]
    if majors:
        return majors[0]
    return candidates[0] if len(candidates) == 1 else None


def _relevel(items: Sequence[PliItem], delta: int, origin: str) -> List[PliItem]:
    """Deep-copy LIKE members, shifting their level numbers and marking where they came from."""
    copies: List[PliItem] = []
    for item in items:
        clone = copy.copy(item)
        clone.level = None if item.level is None else item.level + delta
        clone.dimensions = list(item.dimensions)
        clone.unread = list(item.unread)
        clone.cloned_from = item.cloned_from or origin
        clone.children = _relevel(item.children, delta, origin)
        copies.append(clone)
    return copies


def _expand_likes(document: PliDocument) -> None:
    """Replace every ``LIKE`` with a copy of its target's members.

    Raises:
        MainframeParseError: ``INPUT_REFERENCE_UNRESOLVED`` for a target nothing declares;
            ``INPUT_SEMANTIC_INVALID`` for a target that is not a structure, or a LIKE cycle.
    """
    index = _structure_index(document)
    scalars = {scalar.name for scalar in document.scalars}
    done: Set[int] = set()

    def expand(item: PliItem, active: Tuple[str, ...]) -> None:
        for member in list(item.walk()):
            if member.like is None or id(member) in done or member.children:
                continue
            if member.like in active:
                chain = " → ".join([*active, member.like])
                raise _semantic(f"LIKE structures clone one another in a cycle: {chain}", member)
            target = _lookup(member.like, index, document)
            if target is None:
                if member.like.split(".")[-1] in scalars or any(
                    member.like.split(".")[-1] == i.name
                    for s in document.structures
                    for i in s.walk()
                    if i.data is not None
                ):
                    raise _semantic(
                        f"LIKE {member.like} in {member.name} names an item that is not a structure", member
                    )
                raise _missing_reference(f"LIKE {member.like}", member, document)
            expand(target, (*active, member.like))
            if not target.children:
                raise _semantic(f"LIKE {member.like} in {member.name} names an item that is not a structure", member)
            base_level = member.level if member.level is not None else 1
            target_level = target.level if target.level is not None else 1
            member.children = _relevel(target.children, base_level - target_level, target.name)
            if target.union and not member.union:
                member.union = True
            done.add(id(member))

    for structure in document.structures:
        expand(structure, (structure.name,))


def _check_document(document: PliDocument) -> None:
    """Whole-document checks: something to import, unique structure names, resolvable DEFINED.

    Raises:
        MainframeParseError: See the module docstring.
    """
    if not document.structures:
        if document.unresolved_includes and not document.scalars:
            members = ", ".join(sorted({i.member for i in document.unresolved_includes}))
            raise MainframeParseError(
                f"The upload declares nothing itself; its declarations are in %INCLUDE {members}, which "
                "was not supplied — upload the members together as a fileset",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        raise MainframeParseError(
            "The source declares no structure (a level-1 item with members); scalar declarations alone "
            "describe no record",
            code="INPUT_SEMANTIC_INVALID",
        )
    seen: Dict[str, PliItem] = {}
    for structure in document.structures:
        if structure.name in seen:
            first = seen[structure.name]
            raise _semantic(
                f"The structure {structure.name} is declared twice (first on line {first.line}{where(first.file)})",
                structure,
            )
        seen[structure.name] = structure
    declared = {item.name for s in document.structures for item in s.walk()} | {s.name for s in document.scalars}
    for structure in document.structures:
        for item in structure.walk():
            base = (item.defined or "").split("(")[0].split(".")[0].strip()
            if base and base not in declared:
                raise _missing_reference(f"DEFINED {item.defined}", item, document)
    for structure in document.structures:
        _annotate_includes(structure, document)


def _annotate_includes(structure: PliItem, document: PliDocument) -> None:
    """Record which structure each unresolved in-declaration include sits inside."""
    for item in structure.walk():
        if item.include is None:
            continue
        for position, include in enumerate(document.includes):
            if (
                include.resolved is None
                and include.inside is None
                and include.member == item.include
                and include.line == item.line
                and include.file == item.file
            ):
                document.includes[position] = PliInclude(
                    member=include.member, file=include.file, line=include.line, resolved=None, inside=structure.name
                )
                break


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def has_pli_declarations(text: str) -> bool:
    """Whether ``text`` holds a ``DCL`` / ``DECLARE`` statement or a ``%INCLUDE`` directive.

    Comments and quoted strings are ignored, so a COBOL copybook that mentions ``DCL`` in a comment
    is not mistaken for PL/I.
    """
    stripped = _QUOTED.sub("''", _BLOCK_COMMENT.sub(" ", text))
    return bool(_DECLARATION_MARKER.search(stripped) or _INCLUDE_MARKER.search(stripped))


def _read(document: PliDocument, members: Dict[str, str], root: str) -> PliDocument:
    """Read ``root`` (splicing includes from ``members``) into ``document``."""
    text = members[root]
    if not text.strip():
        raise MainframeParseError(f"The PL/I source{where(root)} is empty", code="INPUT_EMPTY")
    check_encoding(text, root, what="PL/I source")
    if not has_pli_declarations(text):
        if not _BLOCK_COMMENT.sub("", text).strip():
            raise MainframeParseError(f"The PL/I source{where(root)} holds only comments", code="INPUT_EMPTY")
        raise MainframeParseError(
            f"No DCL / DECLARE statement or %INCLUDE directive{where(root)} — this is not a PL/I structure "
            "declaration (a COBOL copybook is imported with the COBOL copybook importer)",
            code="FORMAT_MISMATCH",
        )
    expander = _Expander(members, document)
    tokens = expander.expand(root)
    for statement in _split_statements(tokens, root):
        # An unresolved include between statements leaves its placeholder at the head of the next
        # one; it sits outside any declaration and is already listed in document.includes. Labels
        # (``L1: DCL …``) are skipped too.
        start = 0
        while start < len(statement) and statement[start].kind == "include":
            start += 1
        while start + 1 < len(statement) and statement[start].kind == "word" and statement[start + 1].text == ":":
            start += 2
        if start >= len(statement):
            continue
        head = statement[start]
        if _SYNONYMS.get(head.text, head.text) == "DCL" and head.kind == "word":
            _read_declaration(head, statement[start + 1 :], document)
        else:
            document.statements.append(PliStatement(head.text, head.file, head.line))
    document.unreferenced = sorted(path for path in members if path not in expander.reached and path != root)
    _expand_likes(document)
    _check_document(document)
    return document


def parse_pli_text(text: str, *, label: Optional[str] = None) -> PliDocument:
    """Parse one PL/I source file; any ``%INCLUDE`` is unresolved.

    Args:
        text: The source text.
        label: The upload's label, used as the file's path in messages.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    path = label or "source.pli"
    return _read(PliDocument(label=label), {path: text}, path)


def parse_pli_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> PliDocument:
    """Parse a fileset's root, resolving ``%INCLUDE`` against its members.

    Members are matched by name without suffix, case-insensitively (``%INCLUDE ADDRBLK`` finds
    ``ADDRBLK.inc``). Members nothing includes are listed in :attr:`PliDocument.unreferenced`.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    members = {
        path: text
        for path, text in fileset.members.items()
        if path == fileset.root or PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES
    }
    return _read(PliDocument(label=label or fileset.root, is_fileset=True), members, fileset.root)
