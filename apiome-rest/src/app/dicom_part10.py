"""DICOM Part 10 reader — the metadata layer only — FMT-6.7 (#5451).

Reads a DICOM file (PS3.10) element by element: the 128-byte preamble and ``DICM`` magic, the file
meta group (``0002,xxxx``, always explicit VR little endian), then the dataset in the transfer
syntax the meta group names — implicit or explicit VR, little or big endian, or a deflate stream.
Sequences nest to any depth (defined or undefined length, with item and sequence delimiters), and a
``UN`` element of undefined length is read as the implicit-VR sequence PS3.5 §6.2.2 says it holds.

The pixel-data boundary is enforced here, in one place
-------------------------------------------------------
Pixel Data, Float Pixel Data, Double Float Pixel Data and Overlay Data values
(:func:`app.dicom_dictionary.is_pixel_data_tag`) are **stepped over by their declared length** —
or, for an encapsulated value, by the lengths in its item headers — and nothing else.
:func:`_skip_pixel_value` compares offsets and reads item headers; it never slices, decodes,
copies or hashes a byte of the value. What is recorded is a :class:`~app.dicom_model.PixelDataSkip`:
the tag, VR, length and fragment count, so the skip is stated rather than implied.

Refusals carry the intake taxonomy code: a file that stops inside an element is
``INPUT_TRUNCATED``; bytes that cannot be an element (an unknown VR, an item where none may be, a
value that overruns its sequence item) are ``INPUT_MALFORMED``; a file without the ``DICM`` magic or
without a transfer syntax is ``INPUT_SEMANTIC_INVALID``.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .dicom_dictionary import (
    LONG_HEADER_VRS,
    VR_SPECS,
    implicit_vr,
    is_pixel_data_tag,
    tag_text,
    transfer_syntax,
)
from .dicom_model import (
    FORM_PART10,
    VALUE_BINARY,
    VALUE_EMPTY,
    VALUE_INLINE,
    VALUE_PIXEL_SKIPPED,
    VALUE_SEQUENCE,
    DicomDataset,
    DicomElement,
    DicomItem,
    DicomParseError,
    PixelDataSkip,
)

__all__ = [
    "DICOM_MAGIC",
    "MAX_INFLATED_BYTES",
    "MAX_PART10_ELEMENTS",
    "MAX_SEQUENCE_DEPTH",
    "PART10_SUFFIXES",
    "PREAMBLE_LENGTH",
    "parse_part10",
    "sniff_part10",
]

#: The magic every Part 10 file carries after its preamble.
DICOM_MAGIC = b"DICM"
#: Length of the preamble before the magic (PS3.10 §7.1).
PREAMBLE_LENGTH = 128
#: Filename suffixes that claim an upload as Part 10 even when its bytes are broken (IXH-7.5 rule).
PART10_SUFFIXES: Tuple[str, ...] = (".dcm", ".dicom", ".dic")
#: Deepest sequence nesting read before the file is refused as too deep.
MAX_SEQUENCE_DEPTH = 32
#: Most elements one file may carry (every nesting level counted).
MAX_PART10_ELEMENTS = 200_000
#: Largest inflated dataset a deflated transfer syntax may expand to.
MAX_INFLATED_BYTES = 64 * 1024 * 1024

_ITEM = 0xFFFEE000
_ITEM_DELIMITER = 0xFFFEE00D
_SEQUENCE_DELIMITER = 0xFFFEE0DD
_UNDEFINED = 0xFFFFFFFF
_META_GROUP = 0x0002
_SPECIFIC_CHARACTER_SET = 0x00080005
_TRANSFER_SYNTAX_UID = 0x00020010

#: VRs whose bytes are never decoded into values (their length is recorded instead).
_OPAQUE_VRS = frozenset({"OB", "OD", "OF", "OL", "OV", "OW", "UN"})
#: Text VRs that hold one value, so a backslash is text rather than a separator.
_SINGLE_VALUE_TEXT_VRS = frozenset({"LT", "ST", "UT", "UR"})


def sniff_part10(data: Optional[bytes]) -> bool:
    """Whether ``data`` carries the Part 10 magic at offset 128. Cheap; never raises."""
    return bool(data) and len(data) >= PREAMBLE_LENGTH + 4 and data[PREAMBLE_LENGTH:PREAMBLE_LENGTH + 4] == DICOM_MAGIC


@dataclass
class _Context:
    """Read state shared by one stream's recursive descent."""

    data: bytes
    little: bool
    explicit: bool
    encoding: str = "latin-1"
    elements: int = 0
    pixel: List[PixelDataSkip] = field(default_factory=list)

    @property
    def endian(self) -> str:
        return "<" if self.little else ">"

    def implicit_child(self) -> "_Context":
        """A view of the same bytes read as implicit VR little endian (a ``UN`` sequence's body)."""
        child = _Context(self.data, little=True, explicit=False, encoding=self.encoding)
        child.elements = self.elements
        child.pixel = self.pixel
        return child


def _need(ctx: _Context, end: int, limit: int, what: str) -> None:
    """Refuse a read that would pass ``limit``.

    Running past the end of the file is truncation; running past the end of the enclosing item or
    sequence (which itself fits in the file) means the lengths disagree — malformed.
    """
    if end <= limit:
        return
    if end > len(ctx.data) and limit >= len(ctx.data):
        raise DicomParseError(
            f"The DICOM file ends inside {what}: {end - len(ctx.data)} more byte(s) were declared "
            "than the file holds.",
            code="INPUT_TRUNCATED",
        )
    raise DicomParseError(
        f"{what[:1].upper()}{what[1:]} runs past the end of the item or sequence that holds it.",
        code="INPUT_MALFORMED",
    )


def _tag_at(ctx: _Context, pos: int) -> int:
    group, element = struct.unpack_from(ctx.endian + "HH", ctx.data, pos)
    return (group << 16) | element


def _length_at(ctx: _Context, pos: int) -> int:
    return struct.unpack_from(ctx.endian + "L", ctx.data, pos)[0]


def _decode_values(ctx: _Context, vr: str, raw: bytes, path: str) -> Tuple[str, ...]:
    """Decode a non-opaque value into text values (payload — the analysis keeps or drops them)."""
    if not raw or vr in _OPAQUE_VRS:
        return ()
    spec = VR_SPECS[vr]
    if spec.struct_code is not None:
        code = "HH" if vr == "AT" else spec.struct_code
        size = struct.calcsize("<" + code)
        if len(raw) % size:
            raise DicomParseError(
                f"{path} ({vr}) has a {len(raw)}-byte value, which is not a whole number of "
                f"{size}-byte values.",
                code="INPUT_MALFORMED",
            )
        values = []
        for offset in range(0, len(raw), size):
            unpacked = struct.unpack_from(ctx.endian + code, raw, offset)
            if vr == "AT":
                values.append(tag_text((unpacked[0] << 16) | unpacked[1]))
            else:
                values.append(repr(unpacked[0]) if isinstance(unpacked[0], float) else str(unpacked[0]))
        return tuple(values)
    text = raw.decode(ctx.encoding, errors="replace").rstrip("\x00 ")
    if vr in _SINGLE_VALUE_TEXT_VRS:
        return (text,)
    return tuple(part.strip() for part in text.split("\\"))


def _skip_pixel_value(
    ctx: _Context, *, tag: int, vr: str, path: str, start: int, value_start: int, length: int, limit: int
) -> Tuple[DicomElement, int]:
    """Step over a pixel-data value without reading it.

    A defined-length value is passed by its length. An encapsulated (undefined-length) value is
    passed item by item using only each item's 8-byte header, up to the sequence delimiter. The value
    bytes themselves are never sliced, decoded or copied.
    """
    fragments: Optional[int] = None
    if length != _UNDEFINED:
        end = value_start + length
        _need(ctx, end, limit, f"the {tag_text(tag)} pixel data value")
        declared: Optional[int] = length
    else:
        declared = None
        pos, items = value_start, 0
        while True:
            _need(ctx, pos + 8, limit, f"the encapsulated {tag_text(tag)} pixel data")
            item_tag, item_length = _tag_at(ctx, pos), _length_at(ctx, pos + 4)
            if item_tag == _SEQUENCE_DELIMITER:
                end = pos + 8
                break
            if item_tag != _ITEM or item_length == _UNDEFINED:
                raise DicomParseError(
                    f"The encapsulated {tag_text(tag)} pixel data holds {tag_text(item_tag)} where "
                    "a fragment item was expected.",
                    code="INPUT_MALFORMED",
                )
            _need(ctx, pos + 8 + item_length, limit, f"a {tag_text(tag)} pixel data fragment")
            pos, items = pos + 8 + item_length, items + 1
        # The first item is the Basic Offset Table; the rest are compressed fragments.
        fragments = max(items - 1, 0)
    skip = PixelDataSkip(
        tag=tag,
        vr=vr,
        path=path,
        declared_length=declared,
        fragments=fragments,
        offset=start,
        value_span=(value_start, end),
    )
    ctx.pixel.append(skip)
    element = DicomElement(
        tag=tag,
        vr=vr,
        path=path,
        value_form=VALUE_PIXEL_SKIPPED,
        value_length=declared,
        offset=start,
        header_length=value_start - start,
        pixel=skip,
        vr_explicit=ctx.explicit,
    )
    return element, end


def _read_sequence(
    ctx: _Context, *, value_start: int, length: int, limit: int, depth: int, path: str
) -> Tuple[Tuple[DicomItem, ...], int]:
    """Read a sequence's items (defined or undefined length)."""
    if depth >= MAX_SEQUENCE_DEPTH:
        raise DicomParseError(
            f"Sequences nest more than {MAX_SEQUENCE_DEPTH} levels deep at {path}.",
            code="INPUT_DEPTH_LIMIT",
        )
    delimited = length == _UNDEFINED
    end = limit if delimited else value_start + length
    if not delimited:
        _need(ctx, end, limit, f"the {path} sequence")
    items: List[DicomItem] = []
    pos = value_start
    while True:
        if not delimited and pos >= end:
            return tuple(items), end
        _need(ctx, pos + 8, end, f"the {path} sequence")
        item_tag, item_length = _tag_at(ctx, pos), _length_at(ctx, pos + 4)
        if delimited and item_tag == _SEQUENCE_DELIMITER:
            return tuple(items), pos + 8
        if item_tag != _ITEM:
            raise DicomParseError(
                f"The {path} sequence holds {tag_text(item_tag)} where an item was expected.",
                code="INPUT_MALFORMED",
            )
        item_path = f"{path}[{len(items)}]"
        if item_length == _UNDEFINED:
            elements, after = _read_elements(
                ctx, pos=pos + 8, limit=end, depth=depth + 1, path=item_path, delimited=True
            )
            items.append(DicomItem(elements=elements, path=item_path, offset=pos))
        else:
            item_end = pos + 8 + item_length
            _need(ctx, item_end, end, f"item {item_path}")
            elements, after = _read_elements(
                ctx, pos=pos + 8, limit=item_end, depth=depth + 1, path=item_path, delimited=False
            )
            items.append(DicomItem(elements=elements, path=item_path, offset=pos, length=item_length))
        pos = after


def _read_element(
    ctx: _Context, *, pos: int, limit: int, depth: int, parent: str
) -> Tuple[DicomElement, int]:
    """Read one element at ``pos`` (its tag is already known not to be a delimiter)."""
    tag = _tag_at(ctx, pos)
    label = tag_text(tag)
    path = f"{parent}/{label}" if parent else label
    if ctx.explicit:
        _need(ctx, pos + 8, limit, f"the {label} element header")
        vr = ctx.data[pos + 4:pos + 6].decode("ascii", errors="replace")
        if vr not in VR_SPECS:
            raise DicomParseError(
                f"Element {path} declares VR {vr!r}, which is not a DICOM value representation.",
                code="INPUT_MALFORMED",
            )
        if vr in LONG_HEADER_VRS:
            _need(ctx, pos + 12, limit, f"the {label} element header")
            length, header = _length_at(ctx, pos + 8), 12
        else:
            length, header = struct.unpack_from(ctx.endian + "H", ctx.data, pos + 6)[0], 8
    else:
        _need(ctx, pos + 8, limit, f"the {label} element header")
        vr, length, header = implicit_vr(tag), _length_at(ctx, pos + 4), 8
    value_start = pos + header

    ctx.elements += 1
    if ctx.elements > MAX_PART10_ELEMENTS:
        raise DicomParseError(
            f"The DICOM file carries more than {MAX_PART10_ELEMENTS} elements.", code="INPUT_TOO_LARGE"
        )

    if is_pixel_data_tag(tag):
        return _skip_pixel_value(
            ctx, tag=tag, vr=vr, path=path, start=pos, value_start=value_start, length=length, limit=limit
        )

    if vr == "SQ" or (vr == "UN" and length == _UNDEFINED):
        reader = ctx.implicit_child() if vr == "UN" else ctx
        items, after = _read_sequence(
            reader, value_start=value_start, length=length, limit=limit, depth=depth, path=path
        )
        ctx.elements = reader.elements
        element = DicomElement(
            tag=tag,
            vr=vr,
            path=path,
            value_form=VALUE_SEQUENCE,
            value_length=None if length == _UNDEFINED else length,
            offset=pos,
            header_length=header,
            items=items,
            vr_explicit=ctx.explicit,
        )
        return element, after

    if length == _UNDEFINED:
        raise DicomParseError(
            f"Element {path} ({vr}) has an undefined length, which only a sequence, an unknown-VR "
            "sequence or pixel data may have.",
            code="INPUT_MALFORMED",
        )
    value_end = value_start + length
    _need(ctx, value_end, limit, f"the {label} element value")
    raw = ctx.data[value_start:value_end]
    values = _decode_values(ctx, vr, raw, path)
    if depth == 0 and tag == _SPECIFIC_CHARACTER_SET and values:
        ctx.encoding = "utf-8" if "ISO_IR 192" in values else "latin-1"
    if length == 0:
        form = VALUE_EMPTY
    elif vr in _OPAQUE_VRS:
        form = VALUE_BINARY
    else:
        form = VALUE_INLINE
    element = DicomElement(
        tag=tag,
        vr=vr,
        path=path,
        value_form=form,
        values=values,
        value_length=length,
        offset=pos,
        header_length=header,
        vr_explicit=ctx.explicit,
    )
    return element, value_end


def _read_elements(
    ctx: _Context, *, pos: int, limit: int, depth: int, path: str, delimited: bool
) -> Tuple[Tuple[DicomElement, ...], int]:
    """Read elements up to ``limit`` (a defined-length item) or an item delimiter (``delimited``)."""
    elements: List[DicomElement] = []
    while True:
        if not delimited and pos >= limit:
            return tuple(elements), pos
        _need(ctx, pos + 4, limit, f"item {path}" if path else "the dataset")
        tag = _tag_at(ctx, pos)
        if tag == _ITEM_DELIMITER:
            if not delimited:
                raise DicomParseError(
                    f"An item delimiter appears inside the defined-length item {path or 'dataset'}.",
                    code="INPUT_MALFORMED",
                )
            _need(ctx, pos + 8, limit, f"item {path}")
            return tuple(elements), pos + 8
        if tag >> 16 == 0xFFFE:
            raise DicomParseError(
                f"{tag_text(tag)} appears where an element was expected in {path or 'the dataset'}.",
                code="INPUT_MALFORMED",
            )
        element, pos = _read_element(ctx, pos=pos, limit=limit, depth=depth, parent=path)
        elements.append(element)


def _read_file_meta(data: bytes) -> Tuple[Tuple[DicomElement, ...], int]:
    """Read the file meta group that follows the magic; return it and where the dataset starts."""
    ctx = _Context(data, little=True, explicit=True)
    pos = PREAMBLE_LENGTH + 4
    elements: List[DicomElement] = []
    while pos + 2 <= len(data) and struct.unpack_from("<H", data, pos)[0] == _META_GROUP:
        _need(ctx, pos + 4, len(data), "the file meta information")
        element, pos = _read_element(ctx, pos=pos, limit=len(data), depth=0, parent="")
        elements.append(element)
    if not elements:
        if pos >= len(data) - 1:
            raise DicomParseError(
                "The DICOM file ends after its magic, before the file meta information.",
                code="INPUT_TRUNCATED",
            )
        raise DicomParseError(
            "The DICOM file has no file meta information group (0002,xxxx) after its magic.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return tuple(elements), pos


def _inflate(data: bytes) -> bytes:
    """Inflate a deflated dataset (raw deflate, PS3.5 §A.5), refusing a runaway expansion."""
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    try:
        inflated = inflater.decompress(data, MAX_INFLATED_BYTES)
    except zlib.error as exc:
        raise DicomParseError(
            f"The deflated dataset is not a valid deflate stream ({exc}).", code="INPUT_MALFORMED"
        ) from exc
    if inflater.unconsumed_tail:
        raise DicomParseError(
            f"The deflated dataset expands past {MAX_INFLATED_BYTES} bytes.", code="INPUT_EXPANSION_LIMIT"
        )
    return inflated


def _excise(data: bytes, spans: List[Tuple[int, int]]) -> bytes:
    """``data`` without the pixel-data value byte ranges."""
    pieces, cursor = [], 0
    for start, end in sorted(spans):
        pieces.append(data[cursor:start])
        cursor = end
    pieces.append(data[cursor:])
    return b"".join(pieces)


def parse_part10(data: bytes, *, label: Optional[str] = None) -> Tuple[DicomDataset, bytes]:
    """Read a Part 10 file's metadata layer.

    Args:
        data: The file's bytes.
        label: The upload's name, recorded on the dataset.

    Returns:
        ``(dataset, analysed)`` — the dataset, and the bytes the analysis may hash: the file with
        every pixel-data value excised (for a deflated dataset, the meta group plus the inflated
        dataset, excised the same way).

    Raises:
        DicomParseError: With ``INPUT_TRUNCATED``, ``INPUT_MALFORMED``, ``INPUT_SEMANTIC_INVALID``,
            ``INPUT_DEPTH_LIMIT``, ``INPUT_TOO_LARGE`` or ``INPUT_EXPANSION_LIMIT``.
    """
    if len(data) < PREAMBLE_LENGTH + 4:
        tail = data[PREAMBLE_LENGTH:]
        if len(data) >= PREAMBLE_LENGTH and DICOM_MAGIC.startswith(tail):
            raise DicomParseError("The DICOM file ends inside its magic.", code="INPUT_TRUNCATED")
        raise DicomParseError(
            "This is not a DICOM Part 10 file: it is shorter than the 128-byte preamble and `DICM` "
            "magic every Part 10 file starts with.",
            code="INPUT_SEMANTIC_INVALID",
        )
    if data[PREAMBLE_LENGTH:PREAMBLE_LENGTH + 4] != DICOM_MAGIC:
        raise DicomParseError(
            "This is not a DICOM Part 10 file: the four bytes after the 128-byte preamble are not "
            "`DICM`. (A dataset without the Part 10 header is not read; DICOM JSON is accepted "
            "instead.)",
            code="INPUT_SEMANTIC_INVALID",
        )
    file_meta, dataset_start = _read_file_meta(data)
    ts_element = next((e for e in file_meta if e.tag == _TRANSFER_SYNTAX_UID), None)
    ts_uid = ts_element.values[0] if ts_element is not None and ts_element.values else None
    if not ts_uid:
        raise DicomParseError(
            "The file meta information has no Transfer Syntax UID (0002,0010), so the dataset "
            "cannot be read.",
            code="INPUT_SEMANTIC_INVALID",
        )
    syntax = transfer_syntax(ts_uid)

    if syntax.deflated:
        stream = _inflate(data[dataset_start:])
        prefix, base = data[:dataset_start], 0
    else:
        stream, prefix, base = data, b"", dataset_start
    ctx = _Context(stream, little=syntax.little_endian, explicit=syntax.explicit_vr)
    elements, _ = _read_elements(ctx, pos=base, limit=len(stream), depth=0, path="", delimited=False)
    if not elements:
        raise DicomParseError(
            "The DICOM file holds file meta information but no dataset.", code="INPUT_SEMANTIC_INVALID"
        )
    dataset = DicomDataset(
        elements=elements,
        path="",
        offset=base,
        form=FORM_PART10,
        label=label,
        file_meta=file_meta,
        transfer_syntax=syntax.uid,
        transfer_syntax_name=syntax.name,
        deflated=syntax.deflated,
        pixel_data=tuple(ctx.pixel),
    )
    spans = [skip.value_span for skip in ctx.pixel if skip.value_span is not None]
    return dataset, prefix + _excise(stream, spans)
