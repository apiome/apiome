"""UN/EDIFACT interchange parser — FMT-6.1 (#5445).

Parses a UN/EDIFACT batch interchange (ISO 9735) into a typed :class:`EdifactDocument` AST:

.. code-block:: text

    UNA                    service string advice — optional, declares the six service characters
    UNB … UNZ              interchange
      UNG … UNE            functional group — optional; all messages are grouped, or none are
        UNH … UNT          message
          BGM, NAD, LIN …  segments → data elements → components (→ repetitions, syntax 4)

Why a hand-written parser
-------------------------
The syntax is small and fixed — six service characters, a release character, three envelopes — and
the analysis needs facts a value-oriented library does not keep: where every segment's bytes sit,
which element positions were written and left empty, and how a repeated element divides. Reading
the text once, here, means the parse *is* the source scan, so every segment carries a checked byte
range by construction rather than by a second alignment pass (which is what X12 needs, because
``pyx12`` exposes no positions).

Delimiters
----------
A ``UNA`` segment declares the service characters in a fixed order — component separator, element
separator, decimal mark, release character, repetition separator (reserved before syntax version 4),
segment terminator — and they are honoured exactly. Without ``UNA`` the ISO 9735 defaults apply
(``:`` ``+`` ``.`` ``?`` and ``'``; ``*`` as the repetition separator at syntax version 4), or the
level-B control-character defaults (IS1/IS3/IS4) when the interchange header is written with them.

Errors
------
Every refusal is an :class:`EdifactParseError` carrying a stable intake-taxonomy code, so the
import pipeline reports *what kind* of fault it was:

* ``INPUT_TRUNCATED`` — the text ends mid-segment, inside a message, or before ``UNZ``;
* ``INPUT_MALFORMED`` — a segment terminator is missing, a tag is unreadable, ``UNA`` is short;
* ``INPUT_SEMANTIC_INVALID`` — the envelopes do not nest (``UNH`` without ``UNT``, a segment outside
  any message, groups mixed with ungrouped messages) or the interchange carries no message.

An encoding fault (NULs, replacement characters, a byte-order mark) is refused **without** a code, so
the pipeline's own encoding rule names it.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

__all__ = [
    "DEFAULT_DELIMITERS",
    "EdifactDelimiters",
    "EdifactDocument",
    "EdifactElement",
    "EdifactFunctionalGroup",
    "EdifactInterchange",
    "EdifactMessage",
    "EdifactParseError",
    "EdifactSegment",
    "is_edifact",
    "parse_edifact",
]

#: Service segments that open or close an envelope. Everything else is a message body segment.
_ENVELOPE_TAGS = frozenset({"UNA", "UNB", "UNG", "UNH", "UNT", "UNE", "UNZ"})

#: A segment tag: three upper-case alphanumerics (ISO 9735 §7).
_TAG_RE = re.compile(r"^[A-Z0-9]{3}$")

#: What an unescaped line break inside a segment looks like when the terminator before it was
#: dropped: the break, then the next segment's tag and an element separator.
_LINE_BREAK_THEN_TAG = "(?:\r\n|\r|\n)[A-Z][A-Z0-9]{2}"

#: Text that betrays a payload decoded with the wrong encoding (UTF-16 read as UTF-8, or invalid
#: byte sequences replaced under a permissive decode).
_ENCODING_FAULT_MARKERS = ("\x00", "�")


class EdifactParseError(ValueError):
    """Raised when UN/EDIFACT text cannot be parsed.

    Attributes:
        code: Stable intake-taxonomy code (:mod:`app.intake_error_taxonomy`), or ``None`` when the
            pipeline should classify the fault itself (an encoding fault).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EdifactDelimiters:
    """The service characters an interchange is written with.

    Attributes:
        component: Component data element separator (default ``:``).
        element: Data element separator (default ``+``).
        decimal: Decimal mark (default ``.``). Recorded, never applied: values are not read as
            numbers.
        release: Release (escape) character (default ``?``), or ``None`` when ``UNA`` declares none.
        repetition: Repetition separator, or ``None`` when the syntax version has none (before
            version 4 that ``UNA`` position is reserved and must not split anything).
        segment: Segment terminator (default ``'``).
        declared: True when a ``UNA`` segment declared these characters; False when they are
            defaults.
    """

    component: str = ":"
    element: str = "+"
    decimal: str = "."
    release: Optional[str] = "?"
    repetition: Optional[str] = None
    segment: str = "'"
    declared: bool = False


#: The ISO 9735 defaults for levels A and C, used when no ``UNA`` is present.
DEFAULT_DELIMITERS = EdifactDelimiters()

#: The level-B defaults: IS1 (segment), IS3 (element) and IS4 (component) control characters.
_LEVEL_B_DELIMITERS = EdifactDelimiters(
    component="\x1f", element="\x1d", decimal=".", release=None, segment="\x1c"
)


@dataclass(frozen=True)
class EdifactElement:
    """One data element position in a segment.

    Attributes:
        position: 1-based position after the segment tag.
        repetitions: The element's occurrences, each a tuple of its components, release characters
            resolved. A simple element is one occurrence of one component; a position the source
            wrote and left empty is one occurrence of one empty component.
    """

    position: int
    repetitions: Tuple[Tuple[str, ...], ...]

    @property
    def components(self) -> Tuple[str, ...]:
        """The first occurrence's components."""
        return self.repetitions[0]

    @property
    def is_repeated(self) -> bool:
        """Whether a repetition separator divided this element."""
        return len(self.repetitions) > 1

    @property
    def is_composite(self) -> bool:
        """Whether the first occurrence has more than one component."""
        return len(self.components) > 1

    @property
    def value(self) -> str:
        """The first occurrence's first component — the whole value of a simple element."""
        return self.components[0]


@dataclass(frozen=True)
class EdifactSegment:
    """One segment, with the exact bytes it was read from.

    Attributes:
        tag: The segment tag (``BGM``, ``NAD``).
        elements: Data elements after the tag, in position order.
        raw: The segment's text, terminator excluded, exactly as written.
        offset: 0-based character offset of the tag's first character.
        length: Characters the segment occupies, terminator included.
        line: 1-based line of the tag.
        column: 1-based column of the tag.
    """

    tag: str
    elements: Tuple[EdifactElement, ...]
    raw: str
    offset: int
    length: int
    line: int
    column: int

    def component(self, position: int, index: int = 1) -> str:
        """Return one component's text, or ``""`` when the segment did not write it.

        Args:
            position: 1-based element position.
            index: 1-based component index within the element's first occurrence.

        Returns:
            The component text, release characters resolved.
        """
        if not 0 < position <= len(self.elements):
            return ""
        components = self.elements[position - 1].components
        return components[index - 1] if 0 < index <= len(components) else ""


@dataclass(frozen=True)
class EdifactMessage:
    """One ``UNH`` … ``UNT`` message.

    Attributes:
        reference: Message reference number (``UNH`` 0062).
        message_type: Message type (``ORDERS``, ``INVOIC``).
        version: Message version number (``D``).
        release: Message release number (``96A``).
        agency: Controlling agency (``UN``).
        association: Association assigned code (``EAN008``), or ``""``.
        header: The ``UNH`` segment.
        trailer: The ``UNT`` segment.
        segments: Body segments between them, in source order.
    """

    reference: str
    message_type: str
    version: str
    release: str
    agency: str
    association: str
    header: EdifactSegment
    trailer: EdifactSegment
    segments: Tuple[EdifactSegment, ...]

    @property
    def directory(self) -> str:
        """The directory the message claims (``D:96A``), or ``""`` when it names none."""
        if not self.version and not self.release:
            return ""
        return f"{self.version}:{self.release}"


@dataclass(frozen=True)
class EdifactFunctionalGroup:
    """One ``UNG`` … ``UNE`` functional group.

    Attributes:
        group_id: Message group identification (``UNG`` 0038).
        sender: Application sender identification.
        recipient: Application recipient identification.
        reference: Group reference number (``UNG`` 0048).
        agency: Controlling agency.
        header: The ``UNG`` segment.
        trailer: The ``UNE`` segment.
        messages: Its messages, in source order.
    """

    group_id: str
    sender: str
    recipient: str
    reference: str
    agency: str
    header: EdifactSegment
    trailer: EdifactSegment
    messages: Tuple[EdifactMessage, ...]


@dataclass(frozen=True)
class EdifactInterchange:
    """One ``UNB`` … ``UNZ`` interchange.

    ISO 9735 lets an interchange carry functional groups *or* messages directly, never both, so
    exactly one of :attr:`functional_groups` and :attr:`messages` is non-empty.

    Attributes:
        syntax_identifier: Syntax identifier — the character repertoire (``UNOC``).
        syntax_version: Syntax version number (``3``, ``4``).
        sender_id: Interchange sender identification.
        sender_qualifier: Its identification code qualifier (``14``, ``ZZZ``), or ``""``.
        recipient_id: Interchange recipient identification.
        recipient_qualifier: Its qualifier, or ``""``.
        date: Date of preparation.
        time: Time of preparation.
        control_reference: Interchange control reference (``UNB`` 0020).
        application_reference: Application reference (``UNB`` 0026), or ``""``.
        test_indicator: Test indicator (``UNB`` 0035), or ``""``.
        delimiters: The service characters the interchange was read with.
        service_string_advice: The ``UNA`` segment, when one was present.
        header: The ``UNB`` segment.
        trailer: The ``UNZ`` segment.
        functional_groups: Functional groups, when the interchange uses them.
        messages: Messages carried directly, when it does not.
    """

    syntax_identifier: str
    syntax_version: str
    sender_id: str
    sender_qualifier: str
    recipient_id: str
    recipient_qualifier: str
    date: str
    time: str
    control_reference: str
    application_reference: str
    test_indicator: str
    delimiters: EdifactDelimiters
    service_string_advice: Optional[EdifactSegment]
    header: EdifactSegment
    trailer: EdifactSegment
    functional_groups: Tuple[EdifactFunctionalGroup, ...]
    messages: Tuple[EdifactMessage, ...]

    def all_messages(self) -> Iterator[EdifactMessage]:
        """Yield every message in source order, grouped or not."""
        for group in self.functional_groups:
            yield from group.messages
        yield from self.messages


@dataclass(frozen=True)
class EdifactDocument:
    """A parsed interchange and the exact text it was read from.

    Attributes:
        interchange: The interchange.
        raw: The source text.
    """

    interchange: EdifactInterchange
    raw: str


# ===========================================================================
# Detection
# ===========================================================================


def _leading_offset(content: str) -> int:
    """Return the offset of the first non-whitespace character."""
    return len(content) - len(content.lstrip())


def is_edifact(content: str) -> bool:
    """Return ``True`` when ``content`` opens like a UN/EDIFACT interchange.

    The marker is positional, not a substring: the document must *begin* with ``UNB`` (or with a
    nine-character ``UNA`` advice followed by ``UNB``) and the character after ``UNB`` must be an
    element separator. An X12 interchange, a prose file that mentions ``UNB``, or a payload decoded
    with the wrong encoding is never claimed.

    Args:
        content: Candidate text.

    Returns:
        Whether the text opens with an interchange header.
    """
    if not content or not isinstance(content, str):
        return False
    if any(marker in content[:4096] for marker in _ENCODING_FAULT_MARKERS):
        return False
    start = _leading_offset(content)
    head = content[start : start + 64]
    if head.startswith("UNA"):
        if len(head) < 9:
            return False
        delimiters = _una_delimiters(head[:9])
        rest = head[9:].lstrip("\r\n")
        return rest.startswith("UNB") and rest[3:4] == delimiters.element
    if head.startswith("UNB"):
        return head[3:4] in (DEFAULT_DELIMITERS.element, _LEVEL_B_DELIMITERS.element)
    return False


def carries_message_header(content: str) -> bool:
    """Return whether an interchange-shaped text also carries a ``UNH`` message header.

    The header is looked for after a segment terminator, using the characters a ``UNA`` declares
    when there is one, so an interchange written with ``~`` or a newline as its terminator is
    recognised as readily as one written with the default ``'``.

    Args:
        content: Text :func:`is_edifact` already claimed.

    Returns:
        Whether a ``UNH`` segment opens somewhere after a terminator.
    """
    start = _leading_offset(content)
    if content.startswith("UNA", start) and len(content) >= start + 9:
        delimiters = _una_delimiters(content[start : start + 9])
    else:
        delimiters = DEFAULT_DELIMITERS
    terminators = re.escape(delimiters.segment) + "\x1c\r\n"
    separators = re.escape(delimiters.element) + "\x1d"
    return re.search(f"(?:^|[{terminators}])\\s*UNH[{separators}]", content) is not None


# ===========================================================================
# Lexical layer: service characters, segments, elements
# ===========================================================================


def _una_delimiters(una: str) -> EdifactDelimiters:
    """Read the six service characters a ``UNA`` segment declares.

    Args:
        una: The nine-character ``UNA`` segment.

    Returns:
        The declared delimiters. A space in the release position means "no release character";
        the repetition position is resolved later, once the syntax version is known.
    """
    component, element, decimal, release, repetition, segment = una[3:9]
    return EdifactDelimiters(
        component=component,
        element=element,
        decimal=decimal,
        release=None if release == " " else release,
        repetition=None if repetition == " " else repetition,
        segment=segment,
        declared=True,
    )


class _Positions:
    """Offset → 1-based line/column, computed once per document."""

    def __init__(self, text: str) -> None:
        self._starts = [0] + [match.end() for match in re.finditer(r"\r\n|\r|\n", text)]

    def line_column(self, offset: int) -> Tuple[int, int]:
        """Return the 1-based line and column of ``offset``."""
        index = bisect.bisect_right(self._starts, offset) - 1
        return index + 1, offset - self._starts[index] + 1


def _split(text: str, separator: Optional[str], release: Optional[str]) -> List[str]:
    """Split ``text`` on ``separator``, leaving released characters (and the release) in place.

    Args:
        text: Raw text.
        separator: The separator, or ``None`` to return the text whole.
        release: The release character, if any.

    Returns:
        The raw parts, still escaped — :func:`_unescape` resolves them once fully split.
    """
    if separator is None:
        return [text]
    parts: List[str] = []
    current: List[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if release is not None and char == release and index + 1 < len(text):
            current.append(text[index : index + 2])
            index += 2
            continue
        if char == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _unescape(text: str, release: Optional[str]) -> str:
    """Resolve release characters: ``?+`` reads as ``+``, ``??`` as ``?``."""
    if release is None or release not in text:
        return text
    out: List[str] = []
    index = 0
    while index < len(text):
        if text[index] == release and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _split_segments(
    text: str, start: int, delimiters: EdifactDelimiters
) -> List[Tuple[str, int, int]]:
    """Cut the text into raw segments on the (unreleased) segment terminator.

    Line breaks *between* segments are formatting and are skipped. A line break *inside* a segment
    that is followed by something shaped like the next segment's tag is a dropped terminator, and is
    refused rather than read as one long segment whose last element swallowed its neighbour.

    Args:
        text: The whole document.
        start: Offset to begin at (after any ``UNA``).
        delimiters: The service characters in force.

    Returns:
        ``(raw text, offset, length including terminator)`` per segment.

    Raises:
        EdifactParseError: ``INPUT_TRUNCATED`` when the text ends inside a segment;
            ``INPUT_MALFORMED`` when a segment terminator is missing.
    """
    terminator = delimiters.segment
    release = delimiters.release
    segments: List[Tuple[str, int, int]] = []
    index = start
    length = len(text)
    while index < length:
        while index < length and text[index] in "\r\n\t ":
            index += 1
        if index >= length:
            break
        begin = index
        while index < length:
            char = text[index]
            if release is not None and char == release:
                index += 2
                continue
            if char == terminator:
                break
            index += 1
        body = text[begin : min(index, length)]
        if terminator == "\n" and body.endswith("\r"):
            # A newline terminator written with CRLF line ends: the CR is line formatting.
            body = body[:-1]
        _refuse_dropped_terminator(body, text, begin)
        if index >= length:
            tag = body[:3] if len(body) >= 3 else body
            raise EdifactParseError(
                f"EDIFACT interchange ends mid-segment: the final `{tag}` segment has no segment "
                f"terminator (`{terminator}`). The interchange was truncated.",
                code="INPUT_TRUNCATED",
            )
        segments.append((body, begin, index + 1 - begin))
        index += 1
    return segments


def _refuse_dropped_terminator(body: str, text: str, begin: int) -> None:
    """Refuse a segment that runs on into the next one across a line break.

    Args:
        body: The raw segment text.
        text: The whole document (for the line number).
        begin: The segment's offset.

    Raises:
        EdifactParseError: ``INPUT_MALFORMED`` naming the line the terminator is missing on.
    """
    match = re.search(_LINE_BREAK_THEN_TAG, body)
    if match is None:
        return
    line = text.count("\n", 0, begin) + 1
    tag = body[:3]
    raise EdifactParseError(
        f"EDIFACT segment `{tag}` on line {line} has no segment terminator: it runs on into the "
        f"next line's `{body[match.end() - 3 : match.end()]}` segment.",
        code="INPUT_MALFORMED",
    )


def _read_segment(
    body: str, offset: int, length: int, delimiters: EdifactDelimiters, positions: _Positions
) -> EdifactSegment:
    """Split one raw segment into its tag and data elements.

    Raises:
        EdifactParseError: ``INPUT_MALFORMED`` when the segment has no readable tag.
    """
    raw_elements = _split(body, delimiters.element, delimiters.release)
    tag_components = _split(raw_elements[0], delimiters.component, delimiters.release)
    tag = _unescape(tag_components[0], delimiters.release)
    line, column = positions.line_column(offset)
    if not _TAG_RE.match(tag):
        raise EdifactParseError(
            f"EDIFACT segment on line {line}, column {column} has no readable segment tag "
            f"(found {tag[:12]!r}).",
            code="INPUT_MALFORMED",
        )
    elements: List[EdifactElement] = []
    for position, raw_element in enumerate(raw_elements[1:], start=1):
        occurrences = _split(raw_element, delimiters.repetition, delimiters.release)
        elements.append(
            EdifactElement(
                position=position,
                repetitions=tuple(
                    tuple(
                        _unescape(component, delimiters.release)
                        for component in _split(
                            occurrence, delimiters.component, delimiters.release
                        )
                    )
                    for occurrence in occurrences
                ),
            )
        )
    return EdifactSegment(
        tag=tag,
        elements=tuple(elements),
        raw=body,
        offset=offset,
        length=length,
        line=line,
        column=column,
    )


def _resolve_delimiters(text: str, start: int) -> Tuple[EdifactDelimiters, Optional[str], int]:
    """Decide the service characters, before any segment is cut.

    Args:
        text: The whole document.
        start: Offset of its first non-whitespace character.

    Returns:
        ``(delimiters, UNA text or None, offset the first real segment starts at)``. The repetition
        separator is still provisional — :func:`_with_syntax_version` settles it.

    Raises:
        EdifactParseError: ``INPUT_MALFORMED`` when a ``UNA`` is too short, or declares the same
            character for two roles.
    """
    if text.startswith("UNA", start):
        una = text[start : start + 9]
        if len(una) < 9:
            raise EdifactParseError(
                "EDIFACT `UNA` service string advice must be nine characters long "
                f"(found {len(una)}).",
                code="INPUT_MALFORMED",
            )
        delimiters = _una_delimiters(una)
        roles = [delimiters.component, delimiters.element, delimiters.segment]
        if delimiters.release is not None:
            roles.append(delimiters.release)
        if len(set(roles)) != len(roles):
            raise EdifactParseError(
                "EDIFACT `UNA` declares the same character for two service roles.",
                code="INPUT_MALFORMED",
            )
        return delimiters, una, start + 9
    if text.startswith("UNB" + _LEVEL_B_DELIMITERS.element, start):
        return _LEVEL_B_DELIMITERS, None, start
    return DEFAULT_DELIMITERS, None, start


def _with_syntax_version(
    delimiters: EdifactDelimiters, una: Optional[str], unb_raw: str
) -> EdifactDelimiters:
    """Settle the repetition separator once ``UNB`` has named the syntax version.

    Only syntax version 4 has a repetition separator. Before it, the fifth ``UNA`` character is
    reserved and must not divide anything, so it is dropped; at version 4 with no ``UNA``, the
    default ``*`` applies.

    Args:
        delimiters: The provisional delimiters.
        una: The ``UNA`` text, when one was present.
        unb_raw: The raw ``UNB`` segment.

    Returns:
        The final delimiters.
    """
    elements = _split(unb_raw, delimiters.element, delimiters.release)
    syntax = _split(elements[1], delimiters.component, delimiters.release) if len(elements) > 1 else []
    version = _unescape(syntax[1], delimiters.release).strip() if len(syntax) > 1 else ""
    version_four = version.isdigit() and int(version) >= 4
    if not version_four:
        repetition = None
    elif una is not None:
        repetition = delimiters.repetition
    else:
        repetition = "*"
    return EdifactDelimiters(
        component=delimiters.component,
        element=delimiters.element,
        decimal=delimiters.decimal,
        release=delimiters.release,
        repetition=repetition,
        segment=delimiters.segment,
        declared=delimiters.declared,
    )


# ===========================================================================
# Structural layer: envelopes
# ===========================================================================


def _semantic(message: str) -> EdifactParseError:
    """An envelope-nesting fault."""
    return EdifactParseError(message, code="INPUT_SEMANTIC_INVALID")


def _where(segment: EdifactSegment) -> str:
    """``line N`` for an error message."""
    return f"line {segment.line}"


class _MessageBuilder:
    """A message whose ``UNH`` has been read and whose ``UNT`` has not."""

    def __init__(self, header: EdifactSegment) -> None:
        self.header = header
        self.body: List[EdifactSegment] = []

    def close(self, trailer: EdifactSegment) -> EdifactMessage:
        """Finish the message with its ``UNT``."""
        header = self.header
        return EdifactMessage(
            reference=header.component(1),
            message_type=header.component(2, 1),
            version=header.component(2, 2),
            release=header.component(2, 3),
            agency=header.component(2, 4),
            association=header.component(2, 5),
            header=header,
            trailer=trailer,
            segments=tuple(self.body),
        )


class _GroupBuilder:
    """A functional group whose ``UNG`` has been read and whose ``UNE`` has not."""

    def __init__(self, header: EdifactSegment) -> None:
        self.header = header
        self.messages: List[EdifactMessage] = []

    def close(self, trailer: EdifactSegment) -> EdifactFunctionalGroup:
        """Finish the group with its ``UNE``."""
        header = self.header
        return EdifactFunctionalGroup(
            group_id=header.component(1),
            sender=header.component(2),
            recipient=header.component(3),
            reference=header.component(5),
            agency=header.component(6),
            header=header,
            trailer=trailer,
            messages=tuple(self.messages),
        )


def _build_interchange(
    segments: Sequence[EdifactSegment],
    delimiters: EdifactDelimiters,
    una: Optional[EdifactSegment],
) -> EdifactInterchange:
    """Nest the segments into interchange → group → message, refusing anything that does not nest.

    Args:
        segments: Every segment after any ``UNA``, in source order; the first is ``UNB``.
        delimiters: The final delimiters.
        una: The ``UNA`` segment, when one was present.

    Returns:
        The interchange.

    Raises:
        EdifactParseError: ``INPUT_SEMANTIC_INVALID`` for envelopes that do not nest or an interchange
            with no message; ``INPUT_TRUNCATED`` when the text stops before an envelope closes.
    """
    header = segments[0]
    groups: List[EdifactFunctionalGroup] = []
    ungrouped: List[EdifactMessage] = []
    group: Optional[_GroupBuilder] = None
    message: Optional[_MessageBuilder] = None
    trailer: Optional[EdifactSegment] = None

    for segment in segments[1:]:
        tag = segment.tag
        if trailer is not None:
            raise _semantic(
                f"EDIFACT interchange carries a `{tag}` segment on {_where(segment)} after its "
                "`UNZ` trailer; one interchange per document is read."
            )
        if message is not None and tag in _ENVELOPE_TAGS and tag != "UNT":
            raise _semantic(
                f"EDIFACT message {message.header.component(1)!r} opened with `UNH` on "
                f"{_where(message.header)} has no `UNT` before the `{tag}` on {_where(segment)}."
            )
        if tag == "UNG":
            if group is not None:
                raise _semantic(
                    f"EDIFACT functional group opened on {_where(group.header)} has no `UNE` "
                    f"before the next `UNG` on {_where(segment)}."
                )
            if ungrouped:
                raise _semantic(
                    "EDIFACT interchange mixes ungrouped messages with functional groups "
                    f"(`UNG` on {_where(segment)}); ISO 9735 allows one or the other."
                )
            group = _GroupBuilder(segment)
        elif tag == "UNE":
            if group is None:
                raise _semantic(f"EDIFACT `UNE` on {_where(segment)} closes no functional group.")
            groups.append(group.close(segment))
            group = None
        elif tag == "UNH":
            if groups and group is None:
                raise _semantic(
                    "EDIFACT interchange mixes ungrouped messages with functional groups "
                    f"(`UNH` on {_where(segment)}); ISO 9735 allows one or the other."
                )
            message = _MessageBuilder(segment)
        elif tag == "UNT":
            if message is None:
                raise _semantic(f"EDIFACT `UNT` on {_where(segment)} closes no message.")
            closed = message.close(segment)
            (group.messages if group is not None else ungrouped).append(closed)
            message = None
        elif tag == "UNZ":
            if group is not None:
                raise _semantic(
                    f"EDIFACT functional group opened on {_where(group.header)} has no `UNE` "
                    f"before `UNZ` on {_where(segment)}."
                )
            trailer = segment
        elif tag in ("UNA", "UNB"):
            raise _semantic(
                f"EDIFACT `{tag}` on {_where(segment)} appears inside an interchange that is "
                "still open."
            )
        elif message is None:
            raise _semantic(
                f"EDIFACT segment `{tag}` on {_where(segment)} is outside any message: every "
                "segment between `UNB` and `UNZ` belongs to a `UNH` … `UNT` message."
            )
        else:
            message.body.append(segment)

    if message is not None:
        raise EdifactParseError(
            f"EDIFACT interchange ends inside message {message.header.component(1)!r} (opened on "
            f"{_where(message.header)}) before its `UNT`. The interchange was truncated.",
            code="INPUT_TRUNCATED",
        )
    if group is not None:
        raise EdifactParseError(
            f"EDIFACT interchange ends inside the functional group opened on "
            f"{_where(group.header)} before its `UNE`. The interchange was truncated.",
            code="INPUT_TRUNCATED",
        )
    if not groups and not ungrouped:
        raise _semantic("EDIFACT interchange carries no `UNH` … `UNT` message.")
    if not any(group.messages for group in groups) and not ungrouped:
        raise _semantic("EDIFACT interchange's functional groups carry no message.")
    if trailer is None:
        raise EdifactParseError(
            "EDIFACT interchange ends before its `UNZ` trailer. The interchange was truncated.",
            code="INPUT_TRUNCATED",
        )

    return EdifactInterchange(
        syntax_identifier=header.component(1, 1),
        syntax_version=header.component(1, 2),
        sender_id=header.component(2, 1),
        sender_qualifier=header.component(2, 2),
        recipient_id=header.component(3, 1),
        recipient_qualifier=header.component(3, 2),
        date=header.component(4, 1),
        time=header.component(4, 2),
        control_reference=header.component(5),
        application_reference=header.component(7),
        test_indicator=header.component(11),
        delimiters=delimiters,
        service_string_advice=una,
        header=header,
        trailer=trailer,
        functional_groups=tuple(groups),
        messages=tuple(ungrouped),
    )


def parse_edifact(content: str, *, source_label: Optional[str] = None) -> EdifactDocument:
    """Parse UN/EDIFACT interchange text into an :class:`EdifactDocument`.

    Args:
        content: The interchange text.
        source_label: Optional label (file name) for error messages.

    Returns:
        The parsed document.

    Raises:
        EdifactParseError: When the text is not a readable interchange; see the module docstring for
            the codes.
    """
    label = f" ({source_label})" if source_label else ""
    if not content or not content.strip():
        raise EdifactParseError(f"Invalid or empty EDIFACT document{label}", code="INPUT_EMPTY")
    if content.startswith("﻿") or any(marker in content for marker in _ENCODING_FAULT_MARKERS):
        # Code-less on purpose: the pipeline's encoding rule names this fault precisely.
        raise EdifactParseError(
            f"EDIFACT document{label} is not valid text in its declared encoding"
        )
    if not is_edifact(content):
        raise EdifactParseError(
            f"Content does not appear to be a UN/EDIFACT interchange{label}: it must begin with "
            "`UNB`, optionally preceded by `UNA` service string advice."
        )

    start = _leading_offset(content)
    delimiters, una_text, body_start = _resolve_delimiters(content, start)
    positions = _Positions(content)
    raw_segments = _split_segments(content, body_start, delimiters)
    if not raw_segments or not raw_segments[0][0].startswith("UNB"):
        raise EdifactParseError(
            f"EDIFACT interchange{label} must begin with a `UNB` segment.", code="INPUT_MALFORMED"
        )
    delimiters = _with_syntax_version(delimiters, una_text, raw_segments[0][0])
    segments = [
        _read_segment(body, offset, length, delimiters, positions)
        for body, offset, length in raw_segments
    ]

    una_segment: Optional[EdifactSegment] = None
    if una_text is not None:
        line, column = positions.line_column(start)
        una_segment = EdifactSegment(
            tag="UNA", elements=(), raw=una_text[:-1], offset=start, length=9, line=line, column=column
        )
    return EdifactDocument(
        interchange=_build_interchange(segments, delimiters, una_segment), raw=content
    )
