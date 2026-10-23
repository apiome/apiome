"""PL/I structure storage layout — FMT-11.1 (#5480).

The PL/I counterpart of :mod:`app.cobolcopybook_layout`: it takes the :class:`~app.pli_parser.PliItem`
tree the reader produced and returns one :class:`ItemLayout` per item — where it starts, how many
bytes it occupies, and whether either is knowable. It does no parsing and no I/O.

.. code-block:: text

    DCL 1 TRANSACTION_REC,                    offset 1    len 130
          2 TXN_HEADER,                       offset 1    len 16
            3 TXN_TYPE      CHAR(2),          offset 1    len 2
            3 TXN_SEQUENCE  FIXED BIN(31),    offset 5    len 4    (2 bytes padding — fullword)
            3 TXN_STAMP     FIXED DEC(14,0),  offset 9    len 8
          2 TXN_BODY UNION,                   offset 17   len 114
            3 DEBIT_VIEW,                     offset 17   len 105
            3 CREDIT_VIEW,                    offset 17   len 105  ← same storage as DEBIT_VIEW
            3 RAW_VIEW      CHAR(114);        offset 17   len 114  ← same storage as DEBIT_VIEW

Differences from a copybook
---------------------------
* **Alignment is part of the language.** Arithmetic and locator items are ``ALIGNED`` by default and
  sit on their natural boundary (a ``FIXED BIN(31)`` on a fullword), so padding appears between items
  where a copybook would have none. ``ALIGNED`` / ``UNALIGNED`` on a structure is inherited by its
  members. Every padding gap is recorded on the item after it.
* **Bits are packed.** An ``UNALIGNED`` bit string starts at the next free *bit*, so offsets are
  tracked in bits and an item may start part-way into a byte (:attr:`ItemLayout.bit_offset`).
* **UNION** members all start where the union starts and the union is as long as its longest member —
  the same storage presented the way a copybook ``REDEFINES`` is: each later member records the first
  as the storage it shares (:attr:`ItemLayout.redefines`).
* **Self-defining extents.** ``REFER`` and ``*`` extents are runtime values: the item has no length
  and everything after it has no single offset (``offset_variable``), never a guessed one.

What it refuses to do
---------------------
Exactly what the copybook calculator refuses: an item whose size cannot be known (an unread picture,
an ``ENTRY`` or ``FILE`` constant, an ``%INCLUDE`` that was not supplied) has no length, and neither
does any structure containing it, and nothing after it has an offset. The reason is stated.

Assumptions, declared rather than asserted
------------------------------------------
:data:`LAYOUT_ASSUMPTIONS` names everything a byte count here rests on that the declaration does not
state. It is published with every record, as the copybook analyzer publishes its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .pli_parser import PliData, PliItem

__all__ = [
    "LAYOUT_ASSUMPTIONS",
    "ItemLayout",
    "PictureInfo",
    "compute_layout",
    "picture_info",
]

#: What every byte count of this module assumes. The declaration states none of it.
LAYOUT_ASSUMPTIONS: Tuple[str, ...] = (
    "One byte per CHARACTER position (a single-byte EBCDIC or ASCII code page); GRAPHIC and WIDECHAR "
    "take two bytes per position.",
    "A VARYING string carries a 2-byte length prefix before its data and a VARYINGZ string a 1-byte "
    "terminator after it (2 bytes for GRAPHIC / WIDECHAR).",
    "FIXED DECIMAL(p,q) is packed, (p div 2) + 1 bytes; FIXED BINARY takes 1, 2, 4 or 8 bytes by "
    "precision (7 / 15 / 31 / 63 bits signed, 8 / 16 / 32 / 64 unsigned); FLOAT takes 4, 8 or 16 "
    "bytes by precision (hexadecimal or IEEE alike); COMPLEX doubles each.",
    "POINTER, OFFSET and HANDLE take 4 bytes (31-bit addressing); AREA(n) takes n bytes plus a "
    "16-byte control block, and an AREA without a size is 1000 bytes (the language default).",
    "Arithmetic and locator items default to ALIGNED, strings and pictures to UNALIGNED, and an "
    "ALIGNED item starts on its natural boundary (halfword, fullword or doubleword) counted from "
    "the start of its major structure, which is assumed to begin on a doubleword. The compiler's "
    "structure-mapping algorithm can shift a structure's start to save padding; this calculation "
    "pads forward only.",
    "An UNALIGNED bit string starts at the next free bit; any other item starts on a byte boundary.",
    "An array element of an ALIGNED structure is padded to a multiple of the structure's alignment "
    "so every element keeps its boundary.",
    "An element with no data attributes takes the language defaults (FIXED BIN(15) for a name "
    "starting I–N, else FLOAT DEC(6)), as under RULES(IBM).",
)

#: How each size was derived.
BASIS_CHARACTER = "character"
BASIS_BIT = "bit"
BASIS_PACKED = "packed"
BASIS_BINARY = "binary"
BASIS_FLOAT = "float"
BASIS_PICTURE = "picture"
BASIS_LOCATOR = "locator"
BASIS_AREA = "area"

#: Data kinds that default to UNALIGNED.
_UNALIGNED_BY_DEFAULT = frozenset({"character", "bit", "graphic", "widechar", "picture"})
#: Kinds whose storage this module does not size.
_UNSIZED_KINDS = frozenset({"entry", "file", "label", "format", "event", "task", "ordinal", "type"})
#: Picture characters that occupy one position each.
_POSITION_CHARS = frozenset("9XAZ*YTIRS+-$.,/BE")
#: Picture characters that are digit positions.
_DIGIT_CHARS = frozenset("9Z*YTIR")
#: Picture characters that edit a numeric picture for display.
_EDIT_CHARS = frozenset("Z*$.,/B+-E")


@dataclass(frozen=True)
class PictureInfo:
    """What a PL/I picture says.

    Attributes:
        positions: Character positions (= bytes), or ``None`` when the picture cannot be read.
        character: True for a character picture (``A`` / ``X``), false for a numeric one.
        digits: Digit positions of a numeric picture.
        decimals: Digit positions after the assumed decimal point (``V``).
        signed: True when the picture carries a sign position or an overpunch (``S``, ``T``, ``I``,
            ``R``, ``+``, ``-``).
        edited: True for a numeric picture with editing characters — display text, not a number.
    """

    positions: Optional[int]
    character: bool = False
    digits: int = 0
    decimals: int = 0
    signed: bool = False
    edited: bool = False


def _expand_picture(picture: str, *, prefix: bool) -> Optional[List[str]]:
    """Expand repetition factors into one symbol per entry, or ``None`` when the form does not fit.

    PL/I writes a factor before its character (``(5)9V(2)9``); pictures written COBOL-style
    (``S9(7)V99``) put it after. ``prefix`` picks the reading.
    """
    text = picture.upper().replace(" ", "")
    symbols: List[str] = []
    index = 0
    pending: Optional[int] = None
    while index < len(text):
        factor = re.match(r"\((\d+)\)", text[index:])
        if factor:
            count = int(factor.group(1))
            index += factor.end()
            if prefix:
                if pending is not None:
                    return None
                pending = count
            else:
                if not symbols or symbols[-1] in {"V", "K"}:
                    return None
                symbols.extend([symbols[-1]] * (count - 1))
            continue
        if text.startswith(("CR", "DB"), index):
            symbol = text[index : index + 2]
            index += 2
        elif text[index] == "F" and re.match(r"F\([+-]?\d+\)", text[index:]):
            # Scaling factor F(n): no position.
            index += re.match(r"F\([+-]?\d+\)", text[index:]).end()  # type: ignore[union-attr]
            continue
        else:
            symbol = text[index]
            index += 1
        repeat = pending if pending is not None else 1
        pending = None
        if repeat != 1 and symbol in {"V", "K"}:
            return None
        symbols.extend([symbol] * repeat)
    if pending is not None:
        return None
    return symbols


def picture_info(picture: Optional[str]) -> PictureInfo:
    """Read a PL/I picture: its positions, category, digits and editing.

    Args:
        picture: The picture string without quotes.

    Returns:
        The :class:`PictureInfo`; ``positions`` is ``None`` for a picture this module cannot read.
    """
    if not picture:
        return PictureInfo(positions=None)
    symbols = _expand_picture(picture, prefix=True)
    if symbols is None or any(s not in _POSITION_CHARS | {"V", "K", "CR", "DB"} for s in symbols):
        symbols = _expand_picture(picture, prefix=False)
    if symbols is None or any(s not in _POSITION_CHARS | {"V", "K", "CR", "DB"} for s in symbols):
        return PictureInfo(positions=None)
    positions = sum(2 if s in {"CR", "DB"} else 0 if s in {"V", "K"} else 1 for s in symbols)
    if any(s in {"A", "X"} for s in symbols):
        return PictureInfo(positions=positions, character=True)
    digits = decimals = 0
    after_point = False
    for symbol in symbols:
        if symbol == "V":
            after_point = True
        elif symbol in _DIGIT_CHARS:
            digits += 1
            decimals += 1 if after_point else 0
    signed = any(s in {"S", "T", "I", "R", "+", "-", "CR", "DB"} for s in symbols)
    edited = any(s in _EDIT_CHARS or s in {"CR", "DB"} for s in symbols) and not all(
        s in {"9", "V", "S", "+", "-", "T", "I", "R"} for s in symbols
    )
    return PictureInfo(positions=positions, digits=digits, decimals=decimals, signed=signed, edited=edited)


@dataclass(frozen=True)
class ItemLayout:
    """Where one item sits and how much room it takes.

    Attributes:
        offset: 1-based byte offset of the item (its first element) within the major structure, or
            ``None`` when it cannot be known (see ``offset_variable``).
        bit_offset: The bit (0–7) within that byte an UNALIGNED bit string starts at.
        length: Bytes of one element (a bit string rounded up), or ``None`` when unknown.
        bits: Bits of one element of an UNALIGNED bit string; ``None`` for anything else.
        total_length: Bytes of every element, or ``None`` when unknown.
        occurrences: Number of elements (1 for a non-array), or ``None`` when an extent is runtime.
        alignment: The boundary the item is placed on, in bytes (0 for an UNALIGNED bit string).
        aligned: Whether the item is ALIGNED (as declared, inherited or by default).
        padding_bits: Slack inserted before the item to reach its boundary.
        offset_variable: True when an earlier item's extent is a runtime value.
        variable: True when this item (or something inside it) has a runtime extent.
        basis: How the size was derived (``character``, ``packed``, ``binary`` …); ``None`` for a
            structure or an unsized item.
        union: The UNION whose storage the item shares, for a direct member of one.
        redefines: For the second and later members of a UNION, the first member — the storage the
            item describes a second way, as a copybook ``REDEFINES`` does.
        reason: Why the length is unknown, when it is.
    """

    offset: Optional[int]
    bit_offset: int
    length: Optional[int]
    bits: Optional[int]
    total_length: Optional[int]
    occurrences: Optional[int]
    alignment: int
    aligned: bool
    padding_bits: int
    offset_variable: bool
    variable: bool
    basis: Optional[str]
    union: Optional[str] = None
    redefines: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class _Size:
    """An elementary item's storage: bits of one element, boundary in bytes, basis, reason."""

    bits: Optional[int]
    boundary: int
    aligned: bool
    basis: Optional[str]
    variable: bool = False
    reason: Optional[str] = None


def _binary_width(precision: int, unsigned: bool) -> Optional[int]:
    for ceiling, width in ((8, 1), (16, 2), (32, 4), (64, 8)) if unsigned else ((7, 1), (15, 2), (31, 4), (63, 8)):
        if precision <= ceiling:
            return width
    return None


def _float_width(precision: int, binary: bool) -> Optional[int]:
    for ceiling, width in ((21, 4), (53, 8), (109, 16)) if binary else ((6, 4), (16, 8), (33, 16)):
        if precision <= ceiling:
            return width
    return None


def _elementary_size(data: PliData, aligned: bool) -> _Size:
    """Size one elementary item.

    Args:
        data: Its data description.
        aligned: Whether it is ALIGNED.

    Returns:
        The size; ``bits=None`` with a reason when it cannot be computed.
    """
    kind = data.kind
    if kind in _UNSIZED_KINDS:
        return _Size(
            None, 1, aligned, None, reason=f"A {kind.upper()} item's storage is not described by the declaration."
        )
    if data.length is None and data.length_text is not None:
        return _Size(
            None,
            1,
            aligned,
            None,
            variable=True,
            reason=f"The length {data.length_text} is a runtime value, so the item has no fixed size.",
        )
    if kind == "character":
        size = data.length or 0
        boundary = 2 if data.varying == "VARYING" and aligned else 1
        prefix = 2 if data.varying == "VARYING" else 1 if data.varying == "VARYINGZ" else 0
        return _Size((size + prefix) * 8, boundary, aligned, BASIS_CHARACTER)
    if kind in {"graphic", "widechar"}:
        size = 2 * (data.length or 0)
        prefix = 2 if data.varying else 0
        boundary = 2 if aligned and (data.varying or kind == "widechar") else 1
        return _Size((size + prefix) * 8, boundary, aligned, BASIS_CHARACTER)
    if kind == "bit":
        size = data.length or 0
        if data.varying:
            return _Size((2 + (size + 7) // 8) * 8, 2 if aligned else 1, aligned, BASIS_BIT)
        if aligned:
            return _Size(((size + 7) // 8) * 8, 1, aligned, BASIS_BIT)
        return _Size(size, 0, aligned, BASIS_BIT)
    multiplier = 2 if data.complex else 1
    if kind == "fixed-decimal":
        return _Size(((data.precision or 5) // 2 + 1) * 8 * multiplier, 1, aligned, BASIS_PACKED)
    if kind == "fixed-binary":
        width = _binary_width(data.precision or 15, data.unsigned)
        if width is None:
            return _Size(
                None, 1, aligned, None, reason=f"FIXED BINARY({data.precision}) is wider than any binary item."
            )
        return _Size(width * 8 * multiplier, width if aligned else 1, aligned, BASIS_BINARY)
    if kind in {"float-binary", "float-decimal"}:
        width = _float_width(data.precision or 6, kind == "float-binary")
        if width is None:
            return _Size(
                None, 1, aligned, None, reason=f"FLOAT precision {data.precision} is wider than any float item."
            )
        return _Size(width * 8 * multiplier, min(width, 8) if aligned else 1, aligned, BASIS_FLOAT)
    if kind == "picture":
        info = picture_info(data.picture)
        if info.positions is None:
            return _Size(
                None,
                1,
                aligned,
                None,
                reason=f"The picture {data.picture!r} uses a form this calculation does not read.",
            )
        return _Size(info.positions * 8, 1, aligned, BASIS_PICTURE)
    if kind in {"pointer", "offset", "handle"}:
        return _Size(32, 4 if aligned else 1, aligned, BASIS_LOCATOR)
    if kind == "area":
        size = data.length if data.length is not None else 1000
        return _Size((size + 16) * 8, 8 if aligned else 1, aligned, BASIS_AREA)
    return _Size(None, 1, aligned, None, reason=f"No size is defined for a {kind} item.")


def _is_aligned(item: PliItem, inherited: Optional[str]) -> bool:
    """Whether an elementary item is ALIGNED: declared, else inherited, else the language default."""
    declared = item.alignment or inherited
    if declared:
        return declared == "ALIGNED"
    return item.data is not None and item.data.kind not in _UNALIGNED_BY_DEFAULT


def _boundary(item: PliItem, inherited: Optional[str]) -> int:
    """The boundary (bytes; 0 for a packed bit string) an item must start on."""
    if item.include is not None:
        return 1
    if item.children:
        own = item.alignment or inherited
        return max([1, *(_boundary(child, own) for child in item.children)])
    if item.data is None:
        return 1
    aligned = _is_aligned(item, inherited)
    return _elementary_size(item.data, aligned).boundary


def _occurrences(item: PliItem) -> Tuple[Optional[int], bool]:
    """``(element count, variable)`` from the item's dimensions."""
    count = 1
    for dimension in item.dimensions:
        if dimension.count is None:
            return None, True
        count *= dimension.count
    return count, False


def _round_up(value: int, multiple: int) -> int:
    return value if multiple <= 1 else -(-value // multiple) * multiple


def compute_layout(structure: PliItem) -> Dict[int, ItemLayout]:
    """Lay out one major structure.

    Args:
        structure: The level-1 item (with LIKE already expanded by the reader).

    Returns:
        ``id(item) → ItemLayout`` for every item in the tree, the structure included. Keyed by
        identity because names repeat (``*`` fillers, and every LIKE copy of a block).
    """
    layouts: Dict[int, ItemLayout] = {}

    def place(
        item: PliItem,
        start: Optional[int],
        *,
        offset_variable: bool,
        inherited: Optional[str],
        padding: int,
        union: Optional[str] = None,
        redefines: Optional[str] = None,
    ) -> Tuple[Optional[int], bool]:
        """Lay out ``item`` at bit ``start``; return ``(total bits, variable)``."""
        occurrences, dims_variable = _occurrences(item)
        own = item.alignment or inherited
        if item.include is not None:
            layouts[id(item)] = ItemLayout(
                offset=None if start is None else start // 8 + 1,
                bit_offset=0,
                length=None,
                bits=None,
                total_length=None,
                occurrences=1,
                alignment=1,
                aligned=False,
                padding_bits=padding,
                offset_variable=offset_variable,
                variable=False,
                basis=None,
                union=union,
                redefines=redefines,
                reason=f"%INCLUDE {item.include} was not supplied; the members it declares are missing here.",
            )
            return None, False
        if item.children:
            single, variable, reason = lay_children(item, start, offset_variable=offset_variable, inherited=own)
            boundary = _boundary(item, inherited)
            aligned = boundary > 1
            bits_single: Optional[int] = None if single is None else _round_up(single, 8)
            basis: Optional[str] = None
            bit_length: Optional[int] = None
        else:
            aligned = _is_aligned(item, inherited)
            size = (
                _elementary_size(item.data, aligned)
                if item.data is not None
                else _Size(None, 1, aligned, None, reason="The item has no data description.")
            )
            boundary = size.boundary
            bits_single = size.bits
            variable = size.variable
            reason = size.reason
            basis = size.basis
            bit_length = size.bits if boundary == 0 else None
        stride: Optional[int] = None
        if bits_single is not None:
            stride = bits_single if boundary == 0 else _round_up(bits_single, 8 * max(boundary, 1))
            if occurrences == 1:
                stride = bits_single
        total: Optional[int] = None
        if stride is not None and occurrences is not None:
            total = stride * occurrences
        variable = variable or dims_variable
        if dims_variable and reason is None:
            texts = ", ".join(d.text for d in item.dimensions if d.count is None)
            reason = f"The extent ({texts}) is a runtime value, so the item has no fixed size."
        layouts[id(item)] = ItemLayout(
            offset=None if start is None else start // 8 + 1,
            bit_offset=0 if start is None else start % 8,
            length=None if bits_single is None else -(-bits_single // 8),
            bits=bit_length,
            total_length=None if total is None else -(-total // 8),
            occurrences=occurrences,
            alignment=boundary,
            aligned=aligned,
            padding_bits=padding,
            offset_variable=offset_variable,
            variable=variable,
            basis=basis,
            union=union,
            redefines=redefines,
            reason=reason,
        )
        return total, variable

    def lay_children(
        item: PliItem, start: Optional[int], *, offset_variable: bool, inherited: Optional[str]
    ) -> Tuple[Optional[int], bool, Optional[str]]:
        """Lay out a structure's members from bit ``start``; return ``(bits, variable, reason)``."""
        cursor = 0
        known = True
        cursor_variable = offset_variable
        variable = False
        reason: Optional[str] = None
        longest = 0
        first_member: Optional[str] = None
        for child in item.children:
            boundary = _boundary(child, inherited)
            step = 8 * boundary if boundary else 1
            member_start = 0 if item.union else cursor
            aligned_start = _round_up(member_start, step) if not item.union else 0
            # Slack is only knowable while every earlier member's size is.
            padding = aligned_start - member_start if known else 0
            absolute = None if start is None or not known else start + aligned_start
            if item.union and start is not None:
                absolute = start
            child_bits, child_variable = place(
                child,
                absolute,
                offset_variable=offset_variable if item.union else cursor_variable,
                inherited=inherited,
                padding=padding,
                union=item.name if item.union else None,
                redefines=first_member if item.union else None,
            )
            if item.union and first_member is None and child.include is None:
                first_member = child.name
            child_layout = layouts[id(child)]
            if child_layout.reason is not None and reason is None:
                reason = child_layout.reason
            variable = variable or child_variable
            if child_bits is None:
                known = False
                if child_variable:
                    cursor_variable = True
                continue
            if item.union:
                longest = max(longest, child_bits)
            else:
                cursor = aligned_start + child_bits
        if not known:
            return None, variable, reason or "A member's storage length is unknown, so this structure's is too."
        return (longest if item.union else cursor), variable, reason

    place(structure, 0, offset_variable=False, inherited=None, padding=0)
    return layouts
