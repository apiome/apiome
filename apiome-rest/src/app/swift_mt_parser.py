"""SWIFT MT message parser — FMT-6.3 (#5447).

Reads SWIFT FIN (MT) messages into a typed :class:`SwiftMtFile` AST:

.. code-block:: text

    {1:F01BANKBEBBAXXX0000000000}            basic header       application, service, LT address,
                                                                session and sequence numbers
    {2:I103BANKDEFFXXXXN}                    application header input/output, message type,
                                                                receiver or MIR, priority
    {3:{108:MUR}{121:UETR}{119:COV}}         user header        tagged sub-blocks
    {4:                                      text               :nn[a]: tag fields, read into
    :20:REF…                                                    components by the field catalogue
    -}
    {5:{CHK:…}}                              trailer            tagged sub-blocks

Several messages may follow one another in a file; each ``{1:`` opens the next.

Errors are :class:`SwiftMtParseError` with an intake-taxonomy code:

* ``INPUT_TRUNCATED`` — the text stops inside a header block, or inside a field of a text block that
  never terminates (the last field is incomplete for its documented shape);
* ``INPUT_MALFORMED`` — an unterminated text block whose last field is complete (the ``-}`` is simply
  missing), an unreadable header, a block id outside 1–5, text before the first field;
* ``INPUT_SEMANTIC_INVALID`` — no basic or application header, no text block, a message type this
  adapter does not model, a message with no field 20.

Encoding faults are refused code-less so the import pipeline names them.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from .swift_mt_fields import SUPPORTED_MESSAGE_TYPES, FieldReading, read_field

__all__ = [
    "SwiftHeaderBlock",
    "SwiftMtField",
    "SwiftMtFile",
    "SwiftMtMessage",
    "SwiftMtParseError",
    "SwiftMtSequence",
    "is_swift_mt",
    "parse_swift_mt",
]

_ENCODING_FAULT_MARKERS = ("\x00", "�")
_FIELD_RE = re.compile(r"^:(?P<tag>\d{2})(?P<option>[A-Z])?:(?P<content>.*)$")
_BASIC_RE = re.compile(
    r"^(?P<applicationId>[FAL])(?P<serviceId>\d{2})(?P<ltAddress>[A-Z0-9]+?)"
    r"(?P<sessionNumber>\d{4})(?P<sequenceNumber>\d{6})$"
)
_INPUT_RE = re.compile(
    r"^I(?P<messageType>\d{3})(?P<receiver>[A-Z0-9]+?)(?P<priority>[SNU])?"
    r"(?P<deliveryMonitoring>[123])?(?P<obsolescencePeriod>\d{3})?$"
)
_OUTPUT_RE = re.compile(
    r"^O(?P<messageType>\d{3})(?P<inputTime>\d{4})(?P<mirDate>\d{6})(?P<mirLtAddress>[A-Z0-9]+?)"
    r"(?P<mirSession>\d{4})(?P<mirSequence>\d{6})(?P<outputDate>\d{6})(?P<outputTime>\d{4})"
    r"(?P<priority>[SNU])?$"
)
_SUBBLOCK_RE = re.compile(r"\{(?P<tag>[A-Z0-9]{3}):(?P<value>[^{}]*)\}")


class SwiftMtParseError(ValueError):
    """Raised when SWIFT MT text cannot be parsed.

    Attributes:
        code: Stable intake-taxonomy code, or ``None`` to let the pipeline classify the fault.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SwiftHeaderBlock:
    """One header or trailer block (1, 2, 3 or 5), with where it sits.

    Attributes:
        block_id: ``"1"``, ``"2"``, ``"3"`` or ``"5"``.
        content: The block's content as written, braces excluded.
        values: Its parsed values: named header components for blocks 1 and 2, ``(tag, value)``
            sub-blocks for 3 and 5.
        offset: 0-based offset of the opening brace.
        length: Characters the block occupies, braces included.
        line: 1-based line of the opening brace.
    """

    block_id: str
    content: str
    values: Tuple[Tuple[str, str], ...]
    offset: int
    length: int
    line: int

    def get(self, name: str) -> str:
        """One value by name, or ``""``."""
        for key, value in self.values:
            if key == name:
                return value
        return ""


@dataclass(frozen=True)
class SwiftMtField:
    """One ``:nn[a]:`` field of a text block.

    Attributes:
        tag: The two-digit tag (``50``).
        option: The option letter (``K``), or ``None``.
        lines: The content lines as written.
        reading: The field catalogue's reading of those lines.
        line: 1-based line of the ``:tag:``.
        offset: 0-based offset of the ``:tag:``.
        length: Characters the field occupies, line breaks inside it included.
    """

    tag: str
    option: Optional[str]
    lines: Tuple[str, ...]
    reading: FieldReading
    line: int
    offset: int
    length: int

    @property
    def label(self) -> str:
        """The tag as written: ``50K``, ``20``."""
        return self.tag + (self.option or "")


@dataclass(frozen=True)
class SwiftMtSequence:
    """A sequence of fields: ``A`` (general information), ``B`` (underlying customer transfer)…"""

    name: str
    fields: Tuple[SwiftMtField, ...]


@dataclass(frozen=True)
class SwiftMtMessage:
    """One MT message.

    Attributes:
        basic: Block 1.
        application: Block 2.
        user: Block 3, when present.
        trailer: Block 5, when present.
        sequences: The text's field sequences, in order.
        text_offset: 0-based offset of the first text block.
        text_line: 1-based line of the first text block.
    """

    basic: SwiftHeaderBlock
    application: SwiftHeaderBlock
    user: Optional[SwiftHeaderBlock]
    trailer: Optional[SwiftHeaderBlock]
    sequences: Tuple[SwiftMtSequence, ...]
    text_offset: int
    text_line: int

    @property
    def message_type(self) -> str:
        """The three-digit message type (``103``)."""
        return self.application.get("messageType")

    @property
    def direction(self) -> str:
        """``input`` (sent to SWIFT) or ``output`` (delivered by SWIFT)."""
        return "input" if self.application.content.startswith("I") else "output"

    @property
    def variant(self) -> str:
        """The validation flag (block 3 field 119: ``COV``, ``STP``, ``REMIT``), or ``""``."""
        return self.user.get("119") if self.user else ""

    @property
    def name(self) -> str:
        """``MT103``, ``MT202COV`` — the message type with its cover variant."""
        cover = "COV" if self.message_type == "202" and self.variant == "COV" else ""
        return f"MT{self.message_type}{cover}"

    def fields(self) -> Iterator[SwiftMtField]:
        """Every field of every sequence, in order."""
        for sequence in self.sequences:
            yield from sequence.fields

    def field(self, label: str) -> Optional[SwiftMtField]:
        """The first field written as ``label`` (``20``, ``32A``), or ``None``."""
        return next((item for item in self.fields() if item.label == label), None)


@dataclass(frozen=True)
class SwiftMtFile:
    """A parsed file of one or more MT messages, and the exact text it was read from."""

    messages: Tuple[SwiftMtMessage, ...]
    raw: str


# ===========================================================================
# Detection
# ===========================================================================


def is_swift_mt(content: str) -> bool:
    """Return whether ``content`` opens like a SWIFT MT message (``{1:`` then ``{2:``/``{4:``).

    Args:
        content: Candidate text.

    Returns:
        Whether the text begins with a basic header block and carries a text block.
    """
    if not content or not isinstance(content, str):
        return False
    head = content[:8192]
    if any(marker in head for marker in _ENCODING_FAULT_MARKERS):
        return False
    return content.lstrip().startswith("{1:") and "{4:" in head


# ===========================================================================
# Reading
# ===========================================================================


class _Reader:
    """Cuts the text into blocks, tracking offsets and lines."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._starts = [0] + [match.end() for match in re.finditer(r"\r\n|\r|\n", text)]

    def line(self, offset: int) -> int:
        """1-based line of ``offset``."""
        return bisect.bisect_right(self._starts, offset)

    def braced(self, start: int) -> int:
        """End offset (exclusive) of the brace group opening at ``start``.

        Raises:
            SwiftMtParseError: ``INPUT_TRUNCATED`` when the text ends before the group closes.
        """
        depth = 0
        for index in range(start, len(self.text)):
            char = self.text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
        raise SwiftMtParseError(
            f"SWIFT MT block opened on line {self.line(start)} never closes: the message was "
            "truncated.",
            code="INPUT_TRUNCATED",
        )


def _header(block_id: str, content: str, offset: int, length: int, line: int) -> SwiftHeaderBlock:
    """Parse a header or trailer block's content."""
    if block_id in ("3", "5"):
        values = tuple((m["tag"], m["value"]) for m in _SUBBLOCK_RE.finditer(content))
        if _SUBBLOCK_RE.sub("", content).strip():
            raise SwiftMtParseError(
                f"SWIFT MT block {block_id} on line {line} holds text outside its {{tag:value}} "
                "sub-blocks.",
                code="INPUT_MALFORMED",
            )
        return SwiftHeaderBlock(block_id, content, values, offset, length, line)
    pattern = _BASIC_RE if block_id == "1" else (_INPUT_RE if content.startswith("I") else _OUTPUT_RE)
    match = pattern.match(content)
    if match is None:
        kind = "basic header" if block_id == "1" else "application header"
        raise SwiftMtParseError(
            f"SWIFT MT {kind} (block {block_id}) on line {line} is not readable: {content!r}.",
            code="INPUT_MALFORMED",
        )
    values = tuple((name, value) for name, value in match.groupdict().items() if value is not None)
    return SwiftHeaderBlock(block_id, content, values, offset, length, line)


def _fields(reader: _Reader, start: int, end: int) -> List[SwiftMtField]:
    """Read the fields of a text block whose content spans ``start``–``end``.

    Raises:
        SwiftMtParseError: ``INPUT_MALFORMED`` for text before the first field.
    """
    fields: List[Dict] = []
    offset = start
    for raw_line in reader.text[start:end].splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        match = _FIELD_RE.match(line)
        if match:
            fields.append(
                {
                    "tag": match["tag"],
                    "option": match["option"],
                    "lines": [match["content"]],
                    "offset": offset,
                    "end": offset + len(line),
                }
            )
        elif fields:
            fields[-1]["lines"].append(line)
            fields[-1]["end"] = offset + len(line)
        elif line.strip():
            raise SwiftMtParseError(
                f"SWIFT MT text block holds {line[:20]!r} on line {reader.line(offset)} before its "
                "first :tag: field.",
                code="INPUT_MALFORMED",
            )
        offset += len(raw_line)
    return [
        SwiftMtField(
            tag=item["tag"],
            option=item["option"],
            lines=tuple(item["lines"]),
            reading=read_field(item["tag"], item["option"], list(item["lines"])),
            line=reader.line(item["offset"]),
            offset=item["offset"],
            length=item["end"] - item["offset"],
        )
        for item in fields
    ]


def _unterminated_text(reader: _Reader, start: int) -> SwiftMtParseError:
    """Classify a text block that never reaches ``-}``.

    An incomplete last field is the mark of a message cut off mid-field (truncated); a complete one
    means only the terminator is missing (malformed).
    """
    fields = _fields(reader, start, len(reader.text))
    line = reader.line(start)
    if fields and not fields[-1].reading.well_formed:
        last = fields[-1]
        return SwiftMtParseError(
            f"SWIFT MT text block opened on line {line} ends inside field :{last.label}: (line "
            f"{last.line}), which is incomplete: the message was truncated.",
            code="INPUT_TRUNCATED",
        )
    return SwiftMtParseError(
        f"SWIFT MT text block opened on line {line} is not terminated by `-}}`.",
        code="INPUT_MALFORMED",
    )


def _sequences(blocks: List[List[SwiftMtField]], cover: bool) -> Tuple[SwiftMtSequence, ...]:
    """Name the text's sequences.

    Several text blocks are several sequences (A, B, …). A single text block of an MT202 COV is
    split where its sequence B — the underlying customer credit transfer — opens, at the first
    field 50.
    """
    if len(blocks) == 1 and cover:
        fields = blocks[0]
        split = next((index for index, item in enumerate(fields) if item.tag == "50"), None)
        if split:
            blocks = [fields[:split], fields[split:]]
    return tuple(
        SwiftMtSequence(name=chr(ord("A") + index), fields=tuple(fields))
        for index, fields in enumerate(blocks)
    )


def _message(
    headers: Dict[str, SwiftHeaderBlock],
    texts: List[List[SwiftMtField]],
    text_offset: Optional[int],
    reader: _Reader,
    ordinal: int,
) -> SwiftMtMessage:
    """Assemble and check one message.

    Raises:
        SwiftMtParseError: ``INPUT_SEMANTIC_INVALID`` for a message that cannot be identified or that
            this adapter does not model.
    """
    where = f"SWIFT MT message {ordinal}"
    if "1" not in headers or "2" not in headers:
        missing = "basic header (block 1)" if "1" not in headers else "application header (block 2)"
        raise SwiftMtParseError(
            f"{where} has no {missing}, so nothing states what it is.", code="INPUT_SEMANTIC_INVALID"
        )
    if not texts or text_offset is None:
        raise SwiftMtParseError(f"{where} has no text block (block 4).", code="INPUT_SEMANTIC_INVALID")
    application = headers["2"]
    message_type = application.get("messageType")
    if message_type not in SUPPORTED_MESSAGE_TYPES:
        supported = ", ".join(f"MT{item}" for item in SUPPORTED_MESSAGE_TYPES)
        raise SwiftMtParseError(
            f"{where} is MT{message_type}, which this adapter does not model (it reads {supported}).",
            code="INPUT_SEMANTIC_INVALID",
        )
    user = headers.get("3")
    cover = message_type == "202" and user is not None and user.get("119") == "COV"
    message = SwiftMtMessage(
        basic=headers["1"],
        application=application,
        user=user,
        trailer=headers.get("5"),
        sequences=_sequences(texts, cover),
        text_offset=text_offset,
        text_line=reader.line(text_offset),
    )
    if not any(item.tag == "20" for item in message.sequences[0].fields):
        raise SwiftMtParseError(
            f"{where} ({message.name}) has no field 20 (Transaction Reference Number).",
            code="INPUT_SEMANTIC_INVALID",
        )
    return message


def parse_swift_mt(content: str, *, source_label: Optional[str] = None) -> SwiftMtFile:
    """Parse SWIFT MT text into a :class:`SwiftMtFile`.

    Args:
        content: The message text (one message, or several in sequence).
        source_label: A name for messages.

    Returns:
        The parsed file.

    Raises:
        SwiftMtParseError: When the text is not a readable MT message; see the module docstring.
    """
    label = f" ({source_label})" if source_label else ""
    if not content or not content.strip():
        raise SwiftMtParseError(f"Invalid or empty SWIFT MT document{label}", code="INPUT_EMPTY")
    if content.startswith("﻿") or any(marker in content for marker in _ENCODING_FAULT_MARKERS):
        # Code-less on purpose: the pipeline's encoding rule names this fault precisely.
        raise SwiftMtParseError(f"SWIFT MT document{label} is not valid text in its declared encoding")
    if not is_swift_mt(content):
        raise SwiftMtParseError(
            f"Content does not appear to be a SWIFT MT message{label}: it must begin with a "
            "`{1:` basic header block and carry a `{4:` text block."
        )

    reader = _Reader(content)
    messages: List[SwiftMtMessage] = []
    headers: Dict[str, SwiftHeaderBlock] = {}
    texts: List[List[SwiftMtField]] = []
    text_offset: Optional[int] = None
    position = 0
    length = len(content)
    while position < length:
        char = content[position]
        if char.isspace() or char == "$":
            position += 1
            continue
        if char != "{":
            raise SwiftMtParseError(
                f"SWIFT MT text on line {reader.line(position)} sits outside any block: "
                f"{content[position:position + 20]!r}.",
                code="INPUT_MALFORMED",
            )
        colon = content.find(":", position)
        block_id = content[position + 1 : colon] if colon != -1 else ""
        if block_id not in ("1", "2", "3", "4", "5"):
            raise SwiftMtParseError(
                f"SWIFT MT block on line {reader.line(position)} has id {block_id[:5]!r}; MT blocks "
                "are numbered 1 to 5.",
                code="INPUT_MALFORMED",
            )
        if block_id == "1" and headers:
            messages.append(_message(headers, texts, text_offset, reader, len(messages) + 1))
            headers, texts, text_offset = {}, [], None
        if block_id == "4":
            start = colon + 1
            terminator = re.compile(r"(?:\r\n|\r|\n)-\}").search(content, start)
            if terminator is None:
                raise _unterminated_text(reader, start)
            texts.append(_fields(reader, start, terminator.start()))
            text_offset = position if text_offset is None else text_offset
            position = terminator.end()
            continue
        end = reader.braced(position)
        if block_id in headers:
            raise SwiftMtParseError(
                f"SWIFT MT message repeats block {block_id} on line {reader.line(position)}.",
                code="INPUT_MALFORMED",
            )
        headers[block_id] = _header(
            block_id, content[colon + 1 : end - 1], position, end - position, reader.line(position)
        )
        position = end
    messages.append(_message(headers, texts, text_offset, reader, len(messages) + 1))
    return SwiftMtFile(messages=tuple(messages), raw=content)
