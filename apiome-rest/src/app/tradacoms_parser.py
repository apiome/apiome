"""TRADACOMS transmission parser — FMT-6.5 (#5449).

Parses a TRADACOMS transmission — the UK retail EDI standard — into a typed
:class:`TradacomsDocument` AST:

.. code-block:: text

    STX … END              transmission — sender, recipient, date, references; END counts messages
      file                 a header message (ORDHDR, INVFIL, DELHDR …), detail and trailer messages
        MHD … MTR          message — MHD numbers it and names its type; MTR counts its segments
          CLO, ORD, OLD …  segments → data elements → components

A document may carry several transmissions back to back; each is its own ``STX`` … ``END``.

A profile on the EDIFACT engine, with its own envelope
------------------------------------------------------
TRADACOMS writes EDIFACT's segments with EDIFACT's service characters (``+`` between elements,
``:`` between components, ``'`` after each segment, ``?`` as the release character) — but with an
``=`` after every segment tag and an envelope that is entirely its own. So this parser reads the
segments with the EDIFACT lexical layer (:mod:`app.edifact_parser`: the same segment cutting, the
same release handling, the same :class:`~app.edifact_parser.EdifactSegment` records with checked
byte positions) and builds the ``STX`` / file / ``MHD`` structure itself. An EDIFACT interchange is
never read here: a document that opens with ``UNB`` is not TRADACOMS, and the import pipeline names
the misroute ``FORMAT_MISMATCH``.

Files
-----
TRADACOMS groups the messages of one transmission into *files*: a header message, which carries the
file's transaction type in a ``TYP`` segment (``TYP=0430+ORDERS``), then its detail messages, then
its trailer messages. A file therefore starts at each message whose first segment is ``TYP``; the
messages before the first such header (a transmission that has none) form one file without a header.

Errors
------
Every refusal is a :class:`TradacomsParseError` carrying a stable intake-taxonomy code:

* ``INPUT_TRUNCATED`` — the text ends mid-segment, or inside a message before its ``MTR``;
* ``INPUT_MALFORMED`` — a segment tag is not followed by ``=``, or a segment terminator is missing;
* ``INPUT_SEMANTIC_INVALID`` — the envelopes do not nest (``MHD`` without ``MTR``, a segment outside
  any message, content after ``END`` that is not another ``STX``), a transmission has no ``END`` or
  no message, or the ``MHD`` message references do not count 1, 2, 3 … through the transmission.

An encoding fault, and text that is not TRADACOMS at all, are refused **without** a code, so the
pipeline's own rules name them (``INPUT_ENCODING_INVALID``, ``FORMAT_MISMATCH``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

from .edi_analysis_base import int_or_none
from .edifact_parser import (
    ENCODING_FAULT_MARKERS,
    EdifactDelimiters,
    EdifactElement,
    EdifactParseError,
    EdifactSegment,
    SourcePositions,
    split_raw_segments,
    split_released,
    unescape_released,
)

__all__ = [
    "TRADACOMS_DELIMITERS",
    "TradacomsDocument",
    "TradacomsFile",
    "TradacomsMessage",
    "TradacomsParseError",
    "TradacomsTransmission",
    "carries_message_header",
    "is_tradacoms",
    "parse_tradacoms",
]

#: TRADACOMS' fixed service characters. There is no ``UNA`` equivalent and no repetition separator.
TRADACOMS_DELIMITERS = EdifactDelimiters(
    component=":", element="+", decimal=".", release="?", repetition=None, segment="'"
)

#: What separates a segment tag from its first data element.
TAG_SEPARATOR = "="

#: A segment tag: three upper-case alphanumerics.
_TAG_RE = re.compile(r"^[A-Z0-9]{3}$")

#: The envelope segments. Everything else is a message body segment.
_ENVELOPE_TAGS = frozenset({"STX", "MHD", "MTR", "END"})


class TradacomsParseError(EdifactParseError):
    """Raised when TRADACOMS text cannot be parsed.

    A subclass of :class:`~app.edifact_parser.EdifactParseError` because the lexical layer that
    raises half of these is EDIFACT's.

    Attributes:
        code: Stable intake-taxonomy code, or ``None`` when the pipeline should classify the fault.
    """


@dataclass(frozen=True)
class TradacomsMessage:
    """One ``MHD`` … ``MTR`` message.

    Attributes:
        reference: Message reference (``MHD`` MSRF) — its sequence number in the transmission.
        message_type: Message type (``ORDHDR``, ``ORDERS``, ``VATTLR``).
        version: Message version (``9``).
        header: The ``MHD`` segment.
        trailer: The ``MTR`` segment.
        segments: Body segments between them, in source order.
    """

    reference: str
    message_type: str
    version: str
    header: EdifactSegment
    trailer: EdifactSegment
    segments: Tuple[EdifactSegment, ...]

    @property
    def is_file_header(self) -> bool:
        """Whether this message opens a file — its first segment is the ``TYP`` transaction type."""
        return bool(self.segments) and self.segments[0].tag == "TYP"

    def first(self, tag: str) -> Optional[EdifactSegment]:
        """Return the message's first ``tag`` segment, or ``None``."""
        return next((segment for segment in self.segments if segment.tag == tag), None)


@dataclass(frozen=True)
class TradacomsFile:
    """One file: a header message and the detail and trailer messages after it.

    Attributes:
        messages: Every message of the file, the header first when it has one.
        header: The header message (the one carrying ``TYP``), or ``None``.
    """

    messages: Tuple[TradacomsMessage, ...]
    header: Optional[TradacomsMessage]

    def _header_component(self, tag: str, position: int) -> str:
        """A component of the header message's first ``tag`` segment, or ``""``."""
        if self.header is None:
            return ""
        segment = self.header.first(tag)
        return segment.component(position) if segment is not None else ""

    @property
    def transaction_code(self) -> str:
        """``TYP`` TCDE — the file's transaction code (``0430``), or ``""``."""
        return self._header_component("TYP", 1)

    @property
    def transaction_name(self) -> str:
        """``TYP`` TTYP — the transaction's name (``ORDERS``), or ``""``."""
        return self._header_component("TYP", 2)

    @property
    def generation(self) -> str:
        """``FIL`` FLGN — the file generation number, or ``""``."""
        return self._header_component("FIL", 1)

    @property
    def file_version(self) -> str:
        """``FIL`` FLVN — the file version number, or ``""``."""
        return self._header_component("FIL", 2)

    @property
    def header_type(self) -> str:
        """The header message's type (``ORDHDR``), or ``""`` for a file without one."""
        return self.header.message_type if self.header is not None else ""


@dataclass(frozen=True)
class TradacomsTransmission:
    """One ``STX`` … ``END`` transmission.

    Attributes:
        syntax_identifier: ``STX`` STDS-1 (``ANAA``).
        syntax_version: ``STX`` STDS-2 (``1``).
        sender_code: ``STX`` FROM-1 — the sender's code (often a GLN).
        recipient_code: ``STX`` UNTO-1.
        date: ``STX`` TRDT-1 (``YYMMDD``).
        time: ``STX`` TRDT-2 (``HHMM``).
        sender_reference: ``STX`` SNRF — the sender's transmission reference.
        application_reference: ``STX`` APRF, or ``""``.
        header: The ``STX`` segment.
        trailer: The ``END`` segment.
        files: The transmission's files, in source order.
    """

    syntax_identifier: str
    syntax_version: str
    sender_code: str
    recipient_code: str
    date: str
    time: str
    sender_reference: str
    application_reference: str
    header: EdifactSegment
    trailer: EdifactSegment
    files: Tuple[TradacomsFile, ...]

    def all_messages(self) -> Iterator[TradacomsMessage]:
        """Yield every message in source order."""
        for file in self.files:
            yield from file.messages


@dataclass(frozen=True)
class TradacomsDocument:
    """Parsed transmissions and the exact text they were read from.

    Attributes:
        transmissions: Every transmission, in source order (at least one).
        raw: The source text.
    """

    transmissions: Tuple[TradacomsTransmission, ...]
    raw: str

    def all_messages(self) -> Iterator[TradacomsMessage]:
        """Yield every message of every transmission, in source order."""
        for transmission in self.transmissions:
            yield from transmission.all_messages()


# ===========================================================================
# Detection
# ===========================================================================


def is_tradacoms(content: str) -> bool:
    """Return ``True`` when ``content`` opens like a TRADACOMS transmission.

    The marker is positional: the document must *begin* with ``STX=``. An EDIFACT interchange
    (``UNB``), an X12 one (``ISA``), prose that mentions ``STX`` or text decoded with the wrong
    encoding is never claimed.

    Args:
        content: Candidate text.

    Returns:
        Whether the text opens with a transmission header.
    """
    if not content or not isinstance(content, str):
        return False
    if any(marker in content[:4096] for marker in ENCODING_FAULT_MARKERS):
        return False
    return content.lstrip().startswith("STX" + TAG_SEPARATOR)


def carries_message_header(content: str) -> bool:
    """Return whether a transmission-shaped text also carries an ``MHD`` message header.

    Args:
        content: Text :func:`is_tradacoms` already claimed.

    Returns:
        Whether an ``MHD=`` segment opens after a segment terminator.
    """
    return re.search(r"'\s*MHD=", content) is not None


# ===========================================================================
# Segments
# ===========================================================================


def _read_segment(
    body: str, offset: int, length: int, positions: SourcePositions
) -> EdifactSegment:
    """Split one raw segment into its tag and data elements.

    Raises:
        TradacomsParseError: ``INPUT_MALFORMED`` when the tag is unreadable or not followed by ``=``.
    """
    line, column = positions.line_column(offset)
    tag = body[:3]
    if not _TAG_RE.match(tag) or body[3:4] != TAG_SEPARATOR:
        raise TradacomsParseError(
            f"TRADACOMS segment on line {line}, column {column} is not a tag followed by `=` "
            f"(found {body[:12]!r}).",
            code="INPUT_MALFORMED",
        )
    release = TRADACOMS_DELIMITERS.release
    elements = tuple(
        EdifactElement(
            position=position,
            repetitions=(
                tuple(
                    unescape_released(component, release)
                    for component in split_released(
                        raw_element, TRADACOMS_DELIMITERS.component, release
                    )
                ),
            ),
        )
        for position, raw_element in enumerate(
            split_released(body[4:], TRADACOMS_DELIMITERS.element, release), start=1
        )
    )
    return EdifactSegment(
        tag=tag, elements=elements, raw=body, offset=offset, length=length, line=line, column=column
    )


# ===========================================================================
# Structure
# ===========================================================================


def _semantic(message: str) -> TradacomsParseError:
    """An envelope-nesting fault."""
    return TradacomsParseError(message, code="INPUT_SEMANTIC_INVALID")


def _files(messages: Sequence[TradacomsMessage]) -> Tuple[TradacomsFile, ...]:
    """Divide a transmission's messages into files, each opened by a header message."""
    files: List[TradacomsFile] = []
    current: List[TradacomsMessage] = []
    header: Optional[TradacomsMessage] = None
    for message in messages:
        if message.is_file_header and current:
            files.append(TradacomsFile(messages=tuple(current), header=header))
            current = []
        if message.is_file_header:
            header = message
        elif not current:
            header = None
        current.append(message)
    if current:
        files.append(TradacomsFile(messages=tuple(current), header=header))
    return tuple(files)


class _TransmissionBuilder:
    """A transmission whose ``STX`` has been read and whose ``END`` has not."""

    def __init__(self, header: EdifactSegment) -> None:
        self.header = header
        self.messages: List[TradacomsMessage] = []
        self.open_header: Optional[EdifactSegment] = None
        self.body: List[EdifactSegment] = []

    def open_message(self, header: EdifactSegment) -> None:
        """Start a message, refusing a reference out of sequence."""
        expected = len(self.messages) + 1
        reference = header.component(1).strip()
        if int_or_none(reference) != expected:
            raise _semantic(
                f"TRADACOMS `MHD` on line {header.line} numbers its message {reference!r}, but it "
                f"is message {expected} of the transmission opened on line {self.header.line}: "
                "message references count 1, 2, 3 … through a transmission."
            )
        self.open_header = header
        self.body = []

    def close_message(self, trailer: EdifactSegment) -> None:
        """Finish the open message with its ``MTR``."""
        header = self.open_header
        assert header is not None
        self.messages.append(
            TradacomsMessage(
                reference=header.component(1),
                message_type=header.component(2, 1),
                version=header.component(2, 2),
                header=header,
                trailer=trailer,
                segments=tuple(self.body),
            )
        )
        self.open_header = None
        self.body = []

    def close(self, trailer: EdifactSegment) -> TradacomsTransmission:
        """Finish the transmission with its ``END``."""
        header = self.header
        return TradacomsTransmission(
            syntax_identifier=header.component(1, 1),
            syntax_version=header.component(1, 2),
            sender_code=header.component(2, 1),
            recipient_code=header.component(3, 1),
            date=header.component(4, 1),
            time=header.component(4, 2),
            sender_reference=header.component(5),
            application_reference=header.component(7),
            header=header,
            trailer=trailer,
            files=_files(self.messages),
        )


def _build_transmissions(segments: Sequence[EdifactSegment]) -> Tuple[TradacomsTransmission, ...]:
    """Nest the segments into transmission → message, refusing anything that does not nest.

    Raises:
        TradacomsParseError: See the module docstring.
    """
    transmissions: List[TradacomsTransmission] = []
    current: Optional[_TransmissionBuilder] = None

    for segment in segments:
        tag = segment.tag
        where = f"line {segment.line}"
        if current is None:
            if tag != "STX":
                raise _semantic(
                    f"TRADACOMS segment `{tag}` on {where} is outside any transmission: after "
                    "`END`, only another `STX` may follow."
                )
            current = _TransmissionBuilder(segment)
            continue
        in_message = current.open_header is not None
        if in_message and tag in _ENVELOPE_TAGS and tag != "MTR":
            raise _semantic(
                f"TRADACOMS message opened with `MHD` on line {current.open_header.line} has no "
                f"`MTR` before the `{tag}` on {where}."
            )
        if tag == "STX":
            raise _semantic(
                f"TRADACOMS `STX` on {where} opens a transmission inside the one opened on line "
                f"{current.header.line}, which has no `END`."
            )
        if tag == "MHD":
            current.open_message(segment)
        elif tag == "MTR":
            if not in_message:
                raise _semantic(f"TRADACOMS `MTR` on {where} closes no message.")
            current.close_message(segment)
        elif tag == "END":
            if not current.messages:
                raise _semantic(
                    f"TRADACOMS transmission opened on line {current.header.line} carries no "
                    "`MHD` … `MTR` message."
                )
            transmissions.append(current.close(segment))
            current = None
        elif not in_message:
            raise _semantic(
                f"TRADACOMS segment `{tag}` on {where} is outside any message: every segment "
                "between `STX` and `END` belongs to an `MHD` … `MTR` message."
            )
        else:
            current.body.append(segment)

    if current is not None:
        if current.open_header is not None:
            raise TradacomsParseError(
                f"TRADACOMS transmission ends inside the message opened on line "
                f"{current.open_header.line} before its `MTR`. The transmission was truncated.",
                code="INPUT_TRUNCATED",
            )
        raise _semantic(
            f"TRADACOMS transmission opened on line {current.header.line} has no `END` segment: "
            "every `STX` is closed by an `END` that counts its messages."
        )
    return tuple(transmissions)


def parse_tradacoms(content: str, *, source_label: Optional[str] = None) -> TradacomsDocument:
    """Parse TRADACOMS text into a :class:`TradacomsDocument`.

    Args:
        content: The transmission text.
        source_label: Optional label (file name) for error messages.

    Returns:
        The parsed document.

    Raises:
        TradacomsParseError: When the text is not a readable transmission; see the module docstring.
    """
    label = f" ({source_label})" if source_label else ""
    if not content or not content.strip():
        raise TradacomsParseError(f"Invalid or empty TRADACOMS document{label}", code="INPUT_EMPTY")
    if content.startswith("﻿") or any(marker in content for marker in ENCODING_FAULT_MARKERS):
        # Code-less on purpose: the pipeline's encoding rule names this fault precisely.
        raise TradacomsParseError(
            f"TRADACOMS document{label} is not valid text in its declared encoding"
        )
    if not is_tradacoms(content):
        # Code-less on purpose: when another adapter claims the text (an EDIFACT `UNB`), the
        # pipeline names the misroute FORMAT_MISMATCH.
        raise TradacomsParseError(
            f"Content does not appear to be a TRADACOMS transmission{label}: it must begin with an "
            "`STX=` transmission header."
        )

    start = len(content) - len(content.lstrip())
    positions = SourcePositions(content)
    try:
        raw_segments = split_raw_segments(
            content, start, TRADACOMS_DELIMITERS, family="TRADACOMS", unit="transmission"
        )
    except EdifactParseError as exc:
        raise TradacomsParseError(str(exc), code=exc.code) from exc
    segments = [
        _read_segment(body, offset, length, positions) for body, offset, length in raw_segments
    ]
    return TradacomsDocument(transmissions=_build_transmissions(segments), raw=content)
