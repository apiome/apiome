"""ASN.1 (ITU-T X.680) notation helpers for the ASN.1 emitter — MFX-27.1 (#4163).

The lexical rules a written module must follow so that ``asn1tools`` (and any X.680 compiler)
accepts it, kept apart from :mod:`app.asn1_emitter` so the writer reads as a mapping:

* **names** — a *typereference* or *modulereference* starts with an upper-case letter, an
  *identifier* (a component, alternative or enumeration item) with a lower-case one; both are
  letters, digits and single hyphens, and neither ends with a hyphen (``--`` opens a comment).
  :class:`Namer` turns any source name into one, keeps it clear of the reserved words and unique in
  its scope;
* **literals** — :func:`number_literal`, :func:`cstring_literal`;
* **subtype notation** — :func:`value_range` (``(0..255)``, ``(1..MAX)``, ``(5)``) and
  :func:`size_constraint` (``(SIZE (1..20))``);
* **module identifiers** — :func:`module_oid` (``1.3.6.1.4.1.99999`` → ``{ 1 3 6 1 4 1 99999 }``);
* **permitted alphabets** — :func:`pattern_alphabet` turns an anchored one-class pattern
  (``^[A-Z0-9_]{3,8}$``) into ``(FROM (…))`` and a size (MFX-27.2).
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Dict, List, Optional, Set, Union

__all__ = [
    "RESERVED_WORDS",
    "Namer",
    "cstring_literal",
    "identifier",
    "integer_bounds",
    "module_oid",
    "number_literal",
    "pattern_alphabet",
    "size_constraint",
    "type_reference",
    "value_range",
]

Number = Union[int, float]

#: X.680 §12.38 reserved words. All are upper case, so only a typereference can collide with one.
RESERVED_WORDS = frozenset("""
ABSENT ABSTRACT-SYNTAX ALL APPLICATION AUTOMATIC BEGIN BIT BMPString BOOLEAN BY CHARACTER CHOICE CLASS
COMPONENT COMPONENTS CONSTRAINED CONTAINING DATE DATE-TIME DEFAULT DEFINITIONS DURATION EMBEDDED ENCODED
ENCODING-CONTROL END ENUMERATED EXCEPT EXPLICIT EXPORTS EXTENSIBILITY EXTERNAL FALSE FROM GeneralizedTime
GeneralString GraphicString IA5String IDENTIFIER IMPLICIT IMPLIED IMPORTS INCLUDES INSTANCE INSTRUCTIONS
INTEGER INTERSECTION ISO646String MAX MIN MINUS-INFINITY NOT-A-NUMBER NULL NumericString OBJECT
ObjectDescriptor OCTET OF OID-IRI OPTIONAL PATTERN PDV PLUS-INFINITY PRESENT PrintableString PRIVATE REAL
RELATIVE-OID RELATIVE-OID-IRI SEQUENCE SET SETTINGS SIZE STRING SYNTAX T61String TAGS TeletexString TIME
TIME-OF-DAY TRUE TYPE-IDENTIFIER UNION UNIQUE UNIVERSAL UniversalString UTCTime UTF8String
VideotexString VisibleString WITH
""".split())

_NOT_NAME = re.compile(r"[^A-Za-z0-9]+")
#: A module OID in dotted form (``1.3.6.1``) or as a brace list of arcs (``{ iso(1) 3 6 }``).
_DOTTED_OID = re.compile(r"^[0-2](\.(0|[1-9][0-9]*))+$")
_BRACE_OID = re.compile(r"^\{\s*(([a-z][A-Za-z0-9-]*(\(\d+\))?|\d+)\s+)*([a-z][A-Za-z0-9-]*(\(\d+\))?|\d+)\s*\}$")


def _words(name: str) -> str:
    """``name`` as letters and digits joined by single hyphens (``order_id`` → ``order-id``)."""
    return "-".join(part for part in _NOT_NAME.split(name or "") if part)


def type_reference(name: str, *, fallback: str = "Type") -> str:
    """A typereference / modulereference spelling of ``name`` (not checked for uniqueness).

    ``order_line`` → ``Order-line``, ``2fa`` → ``T-2fa``, ``END`` → ``END-Type`` (a reserved word).
    """
    word = _words(name) or fallback
    if not word[0].isalpha():
        word = f"T-{word}"
    word = word[0].upper() + word[1:]
    return f"{word}-Type" if word in RESERVED_WORDS else word


def identifier(name: str, *, fallback: str = "value") -> str:
    """An identifier spelling of ``name``: a lower-case first letter (``OPEN`` → ``open``, ``Id`` → ``id``)."""
    word = _words(name) or fallback
    if not word[0].isalpha():
        word = f"x-{word}"
    if word.upper() == word:
        return word.lower()
    return word[0].lower() + word[1:]


class Namer:
    """Hands out names that are unique in one scope (``Name``, ``Name-2`` …).

    Args:
        spell: :func:`type_reference` or :func:`identifier`.
    """

    def __init__(self, spell) -> None:
        self._spell = spell
        self._used: Set[str] = set()
        self._given: Dict[str, str] = {}

    def name(self, source: str, *, key: Optional[str] = None) -> str:
        """The unique name for ``source`` (the same one again for the same ``key``)."""
        if key is not None and key in self._given:
            return self._given[key]
        base = self._spell(source)
        candidate, suffix = base, 2
        # X.680 names are case-sensitive, but a module with `Order` and `ORDER` reads as a mistake.
        while candidate.lower() in self._used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        self._used.add(candidate.lower())
        if key is not None:
            self._given[key] = candidate
        return candidate


def number_literal(value: Number) -> str:
    """An ASN.1 number: an integer as is, a real in plain decimal notation (``1.5``, ``-0.25``)."""
    if isinstance(value, bool):
        raise ValueError("a boolean is not a number")
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    text = repr(float(value))
    # `1e-07` is not ASN.1 value notation: write the same value in plain decimals.
    return format(Decimal(text), "f") if "e" in text else text


def cstring_literal(value: str) -> Optional[str]:
    """``value`` as an ASN.1 character string, or ``None`` when ``asn1tools`` cannot read it back.

    X.680 writes a quote inside a cstring as two quotes, but the ``asn1tools`` parser rejects
    that, and a line break would change the value: such strings are not written.
    """
    if '"' in value or "\n" in value or "\r" in value:
        return None
    return f'"{value}"'


def value_range(low: Optional[Number], high: Optional[Number]) -> str:
    """A value-range subtype: ``(0..255)``, ``(1..MAX)``, ``(MIN..10)``, ``(5)``; ``""`` when unbounded."""
    if low is None and high is None:
        return ""
    if low is not None and high is not None and low == high:
        return f"({number_literal(low)})"
    lo = "MIN" if low is None else number_literal(low)
    hi = "MAX" if high is None else number_literal(high)
    return f"({lo}..{hi})"


def size_constraint(low: Optional[int], high: Optional[int]) -> str:
    """A size subtype: ``(SIZE (1..20))``, ``(SIZE (0..10))``; ``""`` when unbounded."""
    if low is None and high is None:
        return ""
    return f"(SIZE {value_range(low if low is not None else 0, high)})"


def module_oid(value: str) -> str:
    """A module's object identifier as written after its name.

    Args:
        value: Dotted decimal (``1.3.6.1.4.1.99999.1``, first arc 0–2) or a brace list of arcs
            (``{ iso(1) identified-organization(3) 6 }``).

    Returns:
        The brace form (``{ 1 3 6 1 4 1 99999 1 }``).

    Raises:
        ValueError: ``value`` is neither form.
    """
    text = " ".join((value or "").split())
    if _DOTTED_OID.match(text):
        return "{ " + " ".join(text.split(".")) + " }"
    if _BRACE_OID.match(text):
        inner = text.strip("{} ")
        return "{ " + inner + " }"
    raise ValueError(
        "oid must be dotted decimal such as 1.3.6.1.4.1.99999.1, or arcs in braces such as "
        "{ iso(1) identified-organization(3) 6 }"
    )


def integer_bounds(
    minimum: Optional[Number],
    maximum: Optional[Number],
    exclusive_minimum: Optional[Number],
    exclusive_maximum: Optional[Number],
) -> tuple[Optional[int], Optional[int]]:
    """The inclusive integer bounds equal to (possibly exclusive, possibly fractional) numeric bounds.

    For integers this is exact: ``> 0`` is ``>= 1`` and ``<= 9.5`` is ``<= 9``.
    """
    lows = [math.ceil(minimum)] if minimum is not None else []
    if exclusive_minimum is not None:
        lows.append(math.floor(exclusive_minimum) + 1)
    highs = [math.floor(maximum)] if maximum is not None else []
    if exclusive_maximum is not None:
        highs.append(math.ceil(exclusive_maximum) - 1)
    return (max(lows) if lows else None), (min(highs) if highs else None)


#: ``^`` one character class (``[…]``, ``\d`` or ``\w``) one quantifier ``$`` — the patterns that say only
#: "every character is one of these" (and how many there are).
_SIMPLE_PATTERN = re.compile(r"^\^(\[(?!\^)(?P<cls>(?:\\.|[^\]\\])+)\]|\\(?P<esc>[dw]))"
                             r"(?P<q>[*+?]|\{(?P<n>\d+)(?P<comma>,(?P<m>\d*))?\})\$$")
#: The characters a class shorthand stands for.
_SHORTHANDS = {"d": ["0-9"], "w": ["A-Z", "a-z", "0-9", "_"]}


def pattern_alphabet(pattern: str) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    r"""A permitted-alphabet constraint equal to a simple pattern, or ``None`` when it is not simple.

    Simple is anchored at both ends, one character class with no negation (``[A-Z0-9_-]``, ``\d``,
    ``\w``) and one quantifier (``*``, ``+``, ``?``, ``{n}``, ``{n,}``, ``{n,m}``). An unanchored pattern
    only asks for a match *somewhere*, so it says nothing about the whole value's alphabet.

    Args:
        pattern: An ECMAScript (JSON Schema) regular expression.

    Returns:
        ``('(FROM ("A".."Z" | "_"))', min_length, max_length)`` — the lengths the quantifier allows
        (``None`` when unbounded) — or ``None``.
    """
    match = _SIMPLE_PATTERN.match(pattern or "")
    if match is None:
        return None
    pieces = _class_pieces(match.group("cls")) if match.group("cls") else _SHORTHANDS[match.group("esc")]
    if not pieces:
        return None
    alternatives: List[str] = []
    for piece in pieces:
        if piece in _SHORTHANDS:
            piece_list = _SHORTHANDS[piece]
        else:
            piece_list = [piece]
        for item in piece_list:
            low, _, high = item.partition("-") if len(item) == 3 and item[1] == "-" else (item, "", "")
            for char in (low, high):
                if char and (cstring_literal(char) is None or not char.isprintable()):
                    return None
            alternatives.append(f'"{low}".."{high}"' if high else f'"{low}"')
    quantifier = match.group("q")
    if quantifier == "*":
        size: tuple[Optional[int], Optional[int]] = (0, None)
    elif quantifier == "+":
        size = (1, None)
    elif quantifier == "?":
        size = (0, 1)
    else:
        n = int(match.group("n"))
        if match.group("comma") is None:
            size = (n, n)
        else:
            size = (n, int(match.group("m")) if match.group("m") else None)
    return "(FROM (" + " | ".join(dict.fromkeys(alternatives)) + "))", size[0], size[1]


def _class_pieces(body: str) -> Optional[List[str]]:
    r"""The members of a character class body: ``a-z`` ranges, single characters, ``d`` / ``w`` shorthands.

    Returns ``None`` for what an alphabet cannot state (``\s``, ``\b``, other escapes of letters).
    """
    tokens: List[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\":
            if index + 1 >= len(body):
                return None
            escaped = body[index + 1]
            if escaped in _SHORTHANDS:
                tokens.append(escaped)
                index += 2
                continue
            if escaped.isalnum():
                return None
            tokens.append(escaped)
            index += 2
            continue
        tokens.append(char)
        index += 1
    pieces: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        is_range = (index + 2 < len(tokens) and tokens[index + 1] == "-" and token not in _SHORTHANDS
                    and tokens[index + 2] not in _SHORTHANDS)
        if is_range:
            if ord(token) > ord(tokens[index + 2]):
                return None
            pieces.append(f"{token}-{tokens[index + 2]}")
            index += 3
        else:
            pieces.append(token)
            index += 1
    return pieces
