"""NACHA ACH file parser — FMT-6.6 (#5450).

Reads a NACHA ACH file into a typed :class:`NachaFile` AST:

.. code-block:: text

    1  file header
    5  batch header          ┐
    6  entry detail          │ one batch, repeated
    7  addenda (0..n)        │ addenda attach to the entry before them
    8  batch control         ┘
    9  file control
    9999…9999  block padding to a multiple of ten records

Records are one per line (``\\n`` or ``\\r\\n``). A file written without line breaks — one long line
whose length is a multiple of 94 — is cut into 94-character records.

Errors are :class:`NachaParseError` with an intake-taxonomy code:

* ``FORMAT_MISMATCH`` — the first line is not an ACH file header (a SEPA XML file, for one);
* ``INPUT_TRUNCATED`` — the text stops inside a record (a short last record before any file
  control), inside a batch, or before the file control record;
* ``INPUT_MALFORMED`` — a record that is not 94 characters anywhere else, or a record type code
  outside ``1 5 6 7 8 9``;
* ``INPUT_SEMANTIC_INVALID`` — records out of order: no file header first, a batch with no entries,
  an addenda record with no entry before it, a batch opened inside another, an entry outside a
  batch, a file with no batches, block padding before the file control, content after it;
* ``INPUT_EMPTY`` — nothing to read.

Encoding faults are refused code-less so the import pipeline names them. Control totals are **not**
checked here: a file that disagrees with its own batch or file control is still readable, and the
analysis states both figures (:mod:`app.nacha_analysis`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from .nacha_records import FILLER_RECORD, RECORD_LENGTH, RECORD_NAMES, RECORD_SIZE, layout_for

__all__ = [
    "NachaBatch",
    "NachaEntry",
    "NachaFile",
    "NachaParseError",
    "NachaRecord",
    "is_nacha",
    "parse_nacha",
]

_ENCODING_FAULT_MARKERS = ("\x00", "�")
_RECORD_TYPES = frozenset("156789")


class NachaParseError(ValueError):
    """Raised when text cannot be read as an ACH file.

    Attributes:
        code: The intake-taxonomy code, or ``None`` for an encoding fault the pipeline names.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NachaRecord:
    """One 94-character record and where it sits in the file.

    Attributes:
        text: The record's characters, exactly as written.
        line: 1-based line number.
        column: 1-based column (1, except for records cut from an unbroken line).
        offset: 0-based character offset of the first character.
        length: Characters the record occupies (always 94 on a parsed record).
        ordinal: 0-based position among the file's records, padding excluded.
    """

    text: str
    line: int
    column: int
    offset: int
    length: int
    ordinal: int

    @property
    def record_type(self) -> str:
        """The record type code (position 1)."""
        return self.text[:1]

    @property
    def addenda_type(self) -> str:
        """Positions 2-3 of an addenda record; empty for any other record type."""
        return self.text[1:3] if self.record_type == "7" else ""

    def field(self, name: str) -> str:
        """Return the named field's characters, as written.

        Args:
            name: A field name from the record's layout (:mod:`app.nacha_records`).

        Raises:
            KeyError: When the record's layout has no such field.
        """
        for spec in layout_for(self.text):
            if spec.name == name:
                return spec.slice(self.text)
        raise KeyError(f"{RECORD_NAMES.get(self.record_type, 'record')} has no field {name!r}")


@dataclass(frozen=True)
class NachaEntry:
    """An entry detail record with the addenda records that follow it."""

    record: NachaRecord
    addenda: Tuple[NachaRecord, ...]

    @property
    def transaction_code(self) -> str:
        return self.record.field("transactionCode")

    @property
    def trace_number(self) -> str:
        return self.record.field("traceNumber")


@dataclass(frozen=True)
class NachaBatch:
    """A batch: its header, entries and control record."""

    header: NachaRecord
    entries: Tuple[NachaEntry, ...]
    control: NachaRecord

    @property
    def batch_number(self) -> str:
        return self.header.field("batchNumber")

    @property
    def sec_code(self) -> str:
        return self.header.field("standardEntryClassCode").strip()

    @property
    def addenda_count(self) -> int:
        return sum(len(entry.addenda) for entry in self.entries)


@dataclass(frozen=True)
class NachaFile:
    """A parsed ACH file.

    Attributes:
        header: The ``1`` file header record.
        batches: Every batch in source order.
        control: The ``9`` file control record.
        padding_records: How many ``9``-filler records followed the file control.
        raw: The text the positions were read from.
    """

    header: NachaRecord
    batches: Tuple[NachaBatch, ...]
    control: NachaRecord
    padding_records: int
    raw: str

    @property
    def record_count(self) -> int:
        """Records in the file, padding included — the figure the block count is computed from."""
        return (
            2
            + sum(2 + len(batch.entries) + batch.addenda_count for batch in self.batches)
            + (self.padding_records)
        )

    def all_entries(self) -> Iterator[Tuple[NachaBatch, NachaEntry]]:
        """Yield ``(batch, entry)`` for every entry in source order."""
        for batch in self.batches:
            for entry in batch.entries:
                yield batch, entry


def is_nacha(text: Optional[str]) -> bool:
    """Whether ``text`` opens with an ACH file header.

    The marker is the header's own fixed fields: record type ``1`` at position 1, record size
    ``094`` at 35-37 and blocking factor ``10`` at 38-39. Only the first line is inspected, so a
    file truncated or malformed further on is still recognised and the parser can say what is wrong.

    Args:
        text: Candidate text.

    Returns:
        True when the first non-blank line carries the file-header marker.
    """
    if not text:
        return False
    first = text.lstrip("﻿\r\n").split("\n", 1)[0].rstrip("\r")
    return len(first) >= 40 and first[0] == "1" and first[34:37] == RECORD_SIZE and first[37:39] == "10"


def _split_records(text: str) -> List[Tuple[str, int, int, int]]:
    """Cut the text into ``(record, line, column, offset)`` tuples, blank trailing lines dropped.

    A single unbroken line whose length is a multiple of 94 (and more than one record) is cut into
    94-character records on that line.
    """
    pieces: List[Tuple[str, int, int, int]] = []
    offset = 0
    for index, raw_line in enumerate(text.split("\n")):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        pieces.append((line, index + 1, 1, offset))
        offset += len(raw_line) + 1
    while pieces and not pieces[-1][0].strip():
        pieces.pop()
    if len(pieces) == 1:
        line, number, _, start = pieces[0]
        if len(line) > RECORD_LENGTH and len(line) % RECORD_LENGTH == 0:
            return [
                (line[at : at + RECORD_LENGTH], number, at + 1, start + at)
                for at in range(0, len(line), RECORD_LENGTH)
            ]
    return pieces


class _Reader:
    """The record-order state machine; one instance per parse."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.header: Optional[NachaRecord] = None
        self.control: Optional[NachaRecord] = None
        self.batches: List[NachaBatch] = []
        self.padding = 0
        self._batch_header: Optional[NachaRecord] = None
        self._entries: List[NachaEntry] = []
        self._entry: Optional[NachaRecord] = None
        self._addenda: List[NachaRecord] = []

    def _fail(self, record: NachaRecord, message: str, code: str = "INPUT_SEMANTIC_INVALID") -> None:
        raise NachaParseError(f"Line {record.line}{self.label}: {message}", code=code)

    def _close_entry(self) -> None:
        if self._entry is not None:
            self._entries.append(NachaEntry(record=self._entry, addenda=tuple(self._addenda)))
        self._entry = None
        self._addenda = []

    def feed(self, record: NachaRecord) -> None:
        """Place one full-length record, or refuse it for being out of order."""
        kind = record.record_type
        if self.control is not None:
            if record.text == FILLER_RECORD:
                self.padding += 1
                return
            self._fail(record, "content follows the file control record (only 9-filler may).")
        if self.header is None:
            if kind != "1":
                self._fail(record, "an ACH file must open with a file header (record type 1).")
            self.header = record
            return
        if kind == "1":
            self._fail(record, "a second file header; one document holds one ACH file.")
        if kind == "5":
            if self._batch_header is not None:
                self._fail(record, "a batch header opens before the previous batch's control record.")
            self._batch_header = record
            return
        if kind in "678" and self._batch_header is None:
            self._fail(record, f"{RECORD_NAMES[kind].lower()} record outside any batch.")
        if kind == "6":
            self._close_entry()
            self._entry = record
            return
        if kind == "7":
            if self._entry is None:
                self._fail(record, "an addenda record with no entry detail record before it.")
            self._addenda.append(record)
            return
        if kind == "8":
            self._close_entry()
            if not self._entries:
                self._fail(
                    record,
                    f"batch {self._batch_header.field('batchNumber')} has no entry detail records.",
                )
            self.batches.append(
                NachaBatch(header=self._batch_header, entries=tuple(self._entries), control=record)
            )
            self._batch_header = None
            self._entries = []
            return
        # kind == "9"
        if record.text == FILLER_RECORD:
            self._fail(record, "block padding (9-filler) before the file control record.")
        if self._batch_header is not None:
            self._fail(record, "the file control record arrives inside an open batch.")
        if not self.batches:
            self._fail(record, "the file carries no batches.")
        self.control = record


def parse_nacha(content: str, *, source_label: Optional[str] = None) -> NachaFile:
    """Parse ACH text into a :class:`NachaFile`.

    Args:
        content: The file's text.
        source_label: Optional name for error messages.

    Returns:
        The parsed file.

    Raises:
        NachaParseError: With the taxonomy code described in the module docstring.
    """
    label = f" ({source_label})" if source_label else ""
    if not content or not content.strip():
        raise NachaParseError(f"Invalid or empty ACH file{label}", code="INPUT_EMPTY")
    if any(marker in content for marker in _ENCODING_FAULT_MARKERS):
        # Code-less on purpose: the pipeline's encoding rule names this fault precisely.
        raise NachaParseError(f"ACH file{label} is not valid text in its declared encoding")
    text = content[1:] if content.startswith("﻿") else content
    if not is_nacha(text):
        raise NachaParseError(
            f"Content{label} does not open with an ACH file header (record type 1, record size 094, "
            "blocking factor 10).",
            code="FORMAT_MISMATCH",
        )

    pieces = _split_records(text)
    reader = _Reader(label)
    for index, (line, number, column, offset) in enumerate(pieces):
        if len(line) != RECORD_LENGTH:
            is_last = index == len(pieces) - 1
            if is_last and reader.control is None and len(line) < RECORD_LENGTH:
                raise NachaParseError(
                    f"Line {number}{label}: the file ends inside a {len(line)}-character record "
                    f"before its file control record.",
                    code="INPUT_TRUNCATED",
                )
            raise NachaParseError(
                f"Line {number}{label}: an ACH record is exactly {RECORD_LENGTH} characters; this "
                f"one has {len(line)}.",
                code="INPUT_MALFORMED",
            )
        if line[0] not in _RECORD_TYPES:
            raise NachaParseError(
                f"Line {number}{label}: record type code {line[0]!r} is not one of 1 5 6 7 8 9.",
                code="INPUT_MALFORMED",
            )
        reader.feed(
            NachaRecord(
                text=line,
                line=number,
                column=column,
                offset=offset,
                length=RECORD_LENGTH,
                ordinal=index,
            )
        )

    if reader.header is None:  # pragma: no cover - pieces is never empty after the strip check
        raise NachaParseError(f"Invalid or empty ACH file{label}", code="INPUT_EMPTY")
    if reader.control is None:
        where = "inside an open batch, " if reader._batch_header is not None else ""
        raise NachaParseError(
            f"ACH file{label} ends {where}before its file control record (record type 9).",
            code="INPUT_TRUNCATED",
        )
    return NachaFile(
        header=reader.header,
        batches=tuple(reader.batches),
        control=reader.control,
        padding_records=reader.padding,
        raw=text,
    )
