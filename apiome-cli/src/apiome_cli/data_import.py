"""Rules for ``apiome data import`` (CLI 10.7, #3259): read, map, check and send records in bulk.

:mod:`apiome_cli.commands.data` resolves the class and drives the loop; this module holds the
parts that can be tested without a terminal:

* :func:`detect_format` — ``--ndjson`` / ``--csv`` / ``--json``, else the file extension;
* :func:`iter_ndjson` / :func:`iter_json_array` / :func:`iter_csv` — streaming readers that yield
  one :class:`Row` at a time, so memory stays flat however big the file is;
* :func:`parse_mapping` / :func:`map_csv_row` — ``--mapping 'first_name,email_addr=email'`` and the
  schema-driven typing of CSV cells (``"19.99"`` → ``19.99`` for a ``number`` field);
* :func:`batches` — groups rows into ``--batch`` sized lists;
* :func:`post_with_retry` — one ``POST /v1/data/{tenant}/records``, retried on 429 and 5xx;
* :class:`ReportWriter` — the ``--report`` file, written row by row.

The server has no bulk-create endpoint, so a batch is sent as one POST per row; the command runs
up to ``--concurrency`` batches at once.
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Callable, Iterable, Iterator, Mapping, Optional, Sequence

from apiome_cli.client.errors import format_api_error
from apiome_cli.data_record import DataInputError

#: Input formats, as named by the ``--ndjson`` / ``--csv`` / ``--json`` flags.
FORMAT_NDJSON = "ndjson"
FORMAT_CSV = "csv"
FORMAT_JSON = "json"

#: File extensions the format is sniffed from when no format flag is given.
EXTENSION_FORMATS = {
    ".ndjson": FORMAT_NDJSON,
    ".jsonl": FORMAT_NDJSON,
    ".csv": FORMAT_CSV,
    ".json": FORMAT_JSON,
}

#: The file argument that means "read stdin".
STDIN_PATH = "-"

#: Row statuses in the report. ``created`` / ``valid`` succeeded; ``invalid`` / ``failed`` did not.
STATUS_CREATED = "created"
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_FAILED = "failed"
FAILED_STATUSES = frozenset({STATUS_INVALID, STATUS_FAILED})

#: HTTP statuses worth retrying: rate limited, or the server failed.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: How many times one record is sent before it is reported as failed.
MAX_ATTEMPTS = 4

#: First back-off in seconds; doubled after each retry.
BACKOFF_SECONDS = 0.5

#: The longest ``Retry-After`` the CLI waits for, in seconds.
MAX_RETRY_AFTER = 30.0

#: How many characters the JSON-array reader reads at a time.
CHUNK_SIZE = 64 * 1024


@dataclass
class Row:
    """One input record.

    Attributes:
        number: 1-based position in the input (a CSV's header row is not counted).
        data: The record object, or ``None`` when the row could not be read.
        error: Why the row could not be read or checked; ``None`` for a usable row.
    """

    number: int
    data: Optional[dict[str, Any]]
    error: Optional[str] = None


@dataclass
class RowResult:
    """What happened to one row: one entry of the ``--report`` file."""

    row: int
    status: str
    record_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def failed(self) -> bool:
        """Whether the row counts towards ``failed_count``."""
        return self.status in FAILED_STATUSES

    def to_json(self) -> dict[str, Any]:
        """``{row, status, record_id?, error?}`` — unset keys are left out."""
        entry: dict[str, Any] = {"row": self.row, "status": self.status}
        if self.record_id is not None:
            entry["record_id"] = self.record_id
        if self.error is not None:
            entry["error"] = self.error
        return entry


def detect_format(path: str, *, ndjson: bool, csv_: bool, json_: bool) -> str:
    """The input format: the one flag given, else the file's extension.

    Args:
        path: The file argument (``-`` for stdin).
        ndjson: ``--ndjson`` was given.
        csv_: ``--csv`` was given.
        json_: ``--json`` was given.

    Returns:
        :data:`FORMAT_NDJSON`, :data:`FORMAT_CSV` or :data:`FORMAT_JSON`.

    Raises:
        DataInputError: More than one flag, stdin without a flag, or an extension that does not
            say the format.
    """
    chosen = [name for name, on in ((FORMAT_NDJSON, ndjson), (FORMAT_CSV, csv_), (FORMAT_JSON, json_)) if on]
    if len(chosen) > 1:
        raise DataInputError("Give one of --ndjson, --csv or --json.")
    if chosen:
        return chosen[0]
    if path == STDIN_PATH:
        raise DataInputError("Say what stdin holds with --ndjson, --csv or --json.")
    found = EXTENSION_FORMATS.get(Path(path).suffix.lower())
    if found is None:
        raise DataInputError(
            f"Cannot tell the format of {path} from its extension; add --ndjson, --csv or --json."
        )
    return found


def _object_row(number: int, value: Any) -> Row:
    """A :class:`Row` for a parsed value: usable when it is an object."""
    if isinstance(value, dict):
        return Row(number, value)
    return Row(number, None, "is not a JSON object")


def iter_ndjson(stream: IO[str]) -> Iterator[Row]:
    """Yield one row per non-blank line of NDJSON (JSON Lines).

    A line that is not JSON, or not an object, is yielded with its ``error`` set; reading carries on.
    Blank lines are skipped and not counted.
    """
    number = 0
    for line in stream:
        if not line.strip():
            continue
        number += 1
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            yield Row(number, None, f"is not valid JSON ({exc.msg})")
            continue
        yield _object_row(number, value)


def iter_json_array(stream: IO[str], *, chunk_size: int = CHUNK_SIZE) -> Iterator[Row]:
    """Yield one row per element of a top-level JSON array, reading ``chunk_size`` characters at a time.

    Only the element being decoded is held in memory, never the whole array.

    Raises:
        DataInputError: The input is not a JSON array, or it is cut off or malformed between
            elements (the rows before the problem have already been yielded).
    """
    decoder = json.JSONDecoder()
    buffer = ""
    eof = False

    def fill() -> None:
        nonlocal buffer, eof
        chunk = stream.read(chunk_size)
        if chunk:
            buffer += chunk
        else:
            eof = True

    def skip_space() -> None:
        """Drop leading whitespace, reading on until there is a character or the input ends."""
        nonlocal buffer
        while True:
            buffer = buffer.lstrip()
            if buffer or eof:
                return
            fill()

    skip_space()
    if not buffer.startswith("["):
        raise DataInputError("The input is not a JSON array; use --ndjson for one object per line.")
    buffer = buffer[1:]
    number = 0
    while True:
        skip_space()
        if buffer.startswith("]"):
            return
        if number:
            if not buffer.startswith(","):
                raise DataInputError(f"The JSON array is malformed after element {number} (expected ',' or ']').")
            buffer = buffer[1:]
            skip_space()
        if not buffer:
            raise DataInputError(f"The JSON array ends after element {number} without a closing ']'.")
        while True:
            try:
                value, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError as exc:
                if eof:
                    raise DataInputError(f"Element {number + 1} of the JSON array is not valid JSON ({exc.msg}).") from exc
                fill()
                continue
            if end == len(buffer) and not eof:
                # A number or literal may continue in the next chunk: read on and decode again.
                fill()
                continue
            break
        buffer = buffer[end:]
        number += 1
        yield _object_row(number, value)


def parse_mapping(text: Optional[str]) -> list[tuple[str, str]]:
    """Parse ``--mapping 'first_name,last_name,email_addr=email'`` into ``(column, field)`` pairs.

    A bare name keeps the column under its own name; ``column=field`` renames it.

    Args:
        text: The option value, or ``None`` when it was not given.

    Returns:
        The pairs in order; empty when ``text`` is ``None``.

    Raises:
        DataInputError: An empty entry or side, or two columns mapped to the same field.
    """
    if text is None:
        return []
    pairs: list[tuple[str, str]] = []
    for entry in text.split(","):
        source, sep, target = (part.strip() for part in entry.partition("="))
        target = target if sep else source
        if not source or not target:
            raise DataInputError(f"--mapping entry {entry.strip()!r} must be column or column=field.")
        pairs.append((source, target))
    targets = [target for _, target in pairs]
    repeated = sorted({target for target in targets if targets.count(target) > 1})
    if repeated:
        raise DataInputError(f"--mapping maps several columns to {', '.join(repeated)}.")
    return pairs


def check_mapping(mapping: Sequence[tuple[str, str]], header: Sequence[str]) -> None:
    """Every ``--mapping`` column must be in the CSV header.

    Raises:
        DataInputError: The missing columns, and the header's columns.
    """
    missing = [source for source, _ in mapping if source not in header]
    if missing:
        raise DataInputError(
            f"--mapping names columns the CSV does not have: {', '.join(missing)}. "
            f"Its columns: {', '.join(header)}."
        )


def _types(prop: Any) -> set[str]:
    """The JSON types a schema property allows (``type`` as a string or a list); empty when unstated."""
    if not isinstance(prop, Mapping):
        return set()
    declared = prop.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {item for item in declared if isinstance(item, str)}
    return set()


def coerce_cell(text: str, prop: Any) -> Any:
    """Type one CSV cell from the field's schema, so CSV rows validate like JSON ones.

    The cell stays a string when the field allows strings or its type is not stated, or when it
    does not read as any type the field allows (validation then reports it). Otherwise it becomes
    an integer, number, boolean (``true`` / ``false``, any case), ``null`` (``null``) or, for an
    ``object`` / ``array`` field, the parsed JSON.

    Args:
        text: The cell as read (not empty — empty cells are left out of the record).
        prop: The field's schema (``properties.<field>``), if the class has one.

    Returns:
        The typed value, or ``text``.
    """
    allowed = _types(prop)
    if not allowed or "string" in allowed:
        return text
    stripped = text.strip()
    if "integer" in allowed:
        try:
            return int(stripped)
        except ValueError:
            pass
    if "number" in allowed:
        try:
            number = float(stripped)
        except ValueError:
            pass
        else:
            if not math.isfinite(number):
                return text
            written_as_integer = "." not in stripped and "e" not in stripped.lower()
            return int(number) if number.is_integer() and written_as_integer else number
    if "boolean" in allowed and stripped.lower() in ("true", "false"):
        return stripped.lower() == "true"
    if "null" in allowed and stripped.lower() == "null":
        return None
    if allowed & {"object", "array"}:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return text


def map_csv_row(
    cells: Mapping[str, Optional[str]],
    mapping: Sequence[tuple[str, str]],
    properties: Mapping[str, Any],
) -> dict[str, Any]:
    """The record for one CSV row: the mapped (or all) columns, typed by the class schema.

    Args:
        cells: The row as ``{column: text}`` (``csv.DictReader``).
        mapping: The ``--mapping`` pairs; empty keeps every column under its own name.
        properties: The class schema's ``properties``, used by :func:`coerce_cell`.

    Returns:
        The record; empty cells are left out, so an optional field stays unset and a required one
        is reported missing.
    """
    pairs = mapping or [(column, column) for column in cells if column]
    record: dict[str, Any] = {}
    for source, target in pairs:
        text = cells.get(source)
        if text is None or text == "":
            continue
        record[target] = coerce_cell(text, properties.get(target))
    return record


def iter_csv(
    stream: IO[str],
    mapping: Sequence[tuple[str, str]],
    properties: Mapping[str, Any],
) -> Iterator[Row]:
    """Yield one row per CSV data row (the first row is the header).

    A row with more cells than the header is yielded with its ``error`` set.

    Raises:
        DataInputError: The input has no header row, or ``--mapping`` names a column it lacks
            (raised before the first row is yielded).
    """
    reader = csv.DictReader(stream)
    header = reader.fieldnames
    if not header:
        raise DataInputError("The CSV has no header row.")
    check_mapping(mapping, header)
    for number, cells in enumerate(reader, start=1):
        if None in cells:
            yield Row(number, None, f"has more cells than the header's {len(header)} columns")
            continue
        yield Row(number, map_csv_row(cells, mapping, properties))


def batches(rows: Iterable[Row], size: int) -> Iterator[list[Row]]:
    """Group ``rows`` into lists of at most ``size``, reading only one list ahead.

    When reading fails part-way (a malformed JSON array, text that is not UTF-8), the rows read
    before the problem are yielded first, then the error is raised.
    """
    batch: list[Row] = []
    try:
        for row in rows:
            batch.append(row)
            if len(batch) >= size:
                yield batch
                batch = []
    except (DataInputError, UnicodeDecodeError):
        if batch:
            yield batch
        raise
    if batch:
        yield batch


def _retry_delay(response: Any, attempt: int) -> float:
    """Seconds to wait before attempt ``attempt + 1``: ``Retry-After`` when given, else back-off."""
    header = response.headers.get("Retry-After") if response is not None else None
    if header:
        try:
            return min(max(float(header), 0.0), MAX_RETRY_AFTER)
        except ValueError:
            pass
    return BACKOFF_SECONDS * (2 ** (attempt - 1))


def post_with_retry(
    send: Callable[[], Any],
    *,
    max_attempts: int = MAX_ATTEMPTS,
    sleep: Optional[Callable[[float], None]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Create one record, retrying a 429 or 5xx answer with back-off.

    Args:
        send: Makes the POST and returns the ``httpx.Response`` (a transport error exits the CLI).
        max_attempts: How many times to send before giving up.
        sleep: Waits between attempts (default :func:`time.sleep`; replaced in tests).

    Returns:
        ``(record_id, None)`` when created, else ``(None, error message)``.
    """
    response = None
    for attempt in range(1, max_attempts + 1):
        response = send()
        if response.status_code < 400:
            try:
                answer = response.json()
            except ValueError:
                answer = None
            record_id = answer.get("record_id") if isinstance(answer, dict) else None
            return (str(record_id), None) if record_id else (None, "the server did not return a record_id")
        if response.status_code not in RETRY_STATUSES or attempt == max_attempts:
            break
        (sleep or time.sleep)(_retry_delay(response, attempt))
    return None, format_api_error(response)


@dataclass
class ImportCounts:
    """Running totals for the summary line and the report."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    failures: list[RowResult] = field(default_factory=list)

    def add(self, result: RowResult, *, keep_failures: int) -> None:
        """Count ``result``; keep the first ``keep_failures`` failures to print."""
        self.total += 1
        if result.failed:
            self.failed += 1
            if len(self.failures) < keep_failures:
                self.failures.append(result)
        else:
            self.succeeded += 1


class ReportWriter:
    """Writes the ``--report`` JSON file one row at a time, so it never holds every row in memory.

    The file is one object: ``{"rows": [{row, status, record_id?, error?}, …], "total",
    "created_count", "failed_count", "dry_run", …}``. With no path every call is a no-op.
    """

    def __init__(self, path: Optional[Path]) -> None:
        """Open ``path`` for writing (raises ``OSError`` when it cannot be)."""
        self._file = path.open("w", encoding="utf-8") if path is not None else None
        self._first = True
        if self._file is not None:
            self._file.write('{"rows":[')

    def write(self, result: RowResult) -> None:
        """Append one row's entry."""
        if self._file is None:
            return
        prefix = "\n" if self._first else ",\n"
        self._file.write(prefix + json.dumps(result.to_json(), ensure_ascii=False))
        self._first = False

    def close(self, summary: Mapping[str, Any]) -> None:
        """Finish the rows array, add the ``summary`` keys, and close the file."""
        if self._file is None:
            return
        tail = json.dumps(dict(summary), ensure_ascii=False)[1:-1]
        self._file.write(f"\n]{',' + tail if tail else ''}}}\n")
        self._file.close()
        self._file = None
