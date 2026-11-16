"""Read a HAR file into ``apiome.usage.event/v1`` events — RDG-1.4 (#5762).

``apiome usage upload file.har`` turns a browser devtools or proxy recording into usage events
**on the developer's machine**, so a body never leaves it:

1. :func:`iter_har_entries` streams ``log.entries`` one entry at a time (a HAR from a long session
   can be hundreds of megabytes; it is never loaded whole).
2. :func:`observation_from_entry` reads an entry into a :class:`HarObservation`, which carries the
   same fields as the server's ``app.inferred_spec.HttpObservation`` (the MFI-32.1 engine) plus
   what a usage event needs from a HAR: when it started, how long it took and the body sizes.
3. :func:`event_from_observation` builds the event: method, path (query **values** dropped here,
   names kept), status, latency, sizes, scheme and host, ``auth_present`` (whether a credential
   header was present — never its value), the raw user agent (the server scrubs and truncates it)
   and ``fields`` — the JSON Pointers present in the request and response bodies. The bodies are
   then discarded; only an explicit ``--sample-bodies`` against a source whose body window is open
   adds a ``sample`` (the server reduces and re-scans it, and refuses it otherwise).
4. :func:`batches` groups events into ingest batches of at most 5,000 events and 2 MiB — the
   RDG-1.2 door's limits — so an upload is ledgered as one ``usage_ingest_batch`` per 5,000 entries.

Path templating, scrubbing and matching stay the server's (the ingest pipeline templates raw paths
with ``app.inferred_spec``'s tokenizer), so a HAR upload and an OTLP span land on the same
operation the same way. This module is pure: no network I/O.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import parse_qsl, urlencode, urlsplit

__all__ = [
    "CREDENTIAL_HEADERS",
    "MAX_BATCH_BYTES",
    "MAX_EVENTS_PER_BATCH",
    "MAX_FIELD_POINTERS",
    "MAX_SAMPLE_BYTES",
    "SKIP_REASONS",
    "HarObservation",
    "HarParseError",
    "SkippedEntry",
    "batches",
    "event_from_observation",
    "field_pointers",
    "iter_har_entries",
    "observation_from_entry",
    "read_har",
]

#: The ingest door's per-batch event limit (``app.usage_ingest.MAX_EVENTS_PER_BATCH``).
MAX_EVENTS_PER_BATCH = 5000

#: The ingest door's per-batch size limit in bytes, before and after gzip.
MAX_BATCH_BYTES = 2 * 1024 * 1024

#: The most field pointers an event may carry per direction (``app.usage_events``).
MAX_FIELD_POINTERS = 512

#: The largest opt-in sample the server stores (``app.usage_ingest.MAX_SAMPLE_BYTES``).
MAX_SAMPLE_BYTES = 16384

#: Request headers whose presence means the call carried a credential — the headers
#: ``app.inferred_spec.auth_scheme_from_headers`` reads, plus ``Proxy-Authorization``.
CREDENTIAL_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "cookie"}
)

#: Why an entry produced no event. Counted and reported, never silently dropped.
SKIP_REASONS = ("no-response", "unsupported-url", "invalid-entry")

_METHOD = re.compile(r"^[A-Z]{1,16}$")
_HOST = re.compile(
    r"^[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?$|^\[[0-9A-Fa-f:.]{2,45}\](:[0-9]{1,5})?$"
)
_POINTER = re.compile(r"^(/([^~\s]|~[01])*)+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_POINTER_LENGTH = 512
_MAX_PATH_LENGTH = 2048
_MAX_LATENCY_MS = 2**31 - 1
_MAX_USER_AGENT_SENT = 1024
_READ_CHUNK = 1 << 20
_TRUNCATED = "the HAR file is truncated or is not valid JSON"
# A batch's envelope: ``{"source_id":"<36>","events":[]}`` plus slack.
_BATCH_OVERHEAD = 128


class HarParseError(ValueError):
    """The file is not a HAR archive (or is truncated or malformed JSON)."""


@dataclass(frozen=True)
class HarObservation:
    """One HAR entry, in the shape of ``app.inferred_spec.HttpObservation``.

    The first fields mirror the server's engine one for one; the last four are the HAR facts a
    usage event needs that an inferred-spec observation does not.

    Attributes:
        method: HTTP verb, upper-cased.
        url: The absolute request URL.
        headers: Request headers as ``(name, value)`` pairs.
        query: Query pairs from the HAR's ``queryString`` (values are dropped before an event).
        request_body: Raw request body text, if any.
        response_status: Response status code, if any (``None`` for an aborted request).
        response_body: Raw response body text (decoded from base64 when the HAR says so).
        source_location: ``entry <n>`` — the entry's index in ``log.entries``.
        source_label: The file name.
        source_file: Always ``None`` (a HAR is one file).
        started_at: When the request started (``startedDateTime``), timezone-aware.
        time_ms: Total time of the request in milliseconds (``time``).
        request_bytes: Request body size, when known.
        response_bytes: Response body size, when known.
        request_media_type: The request body's MIME type, when given.
        response_media_type: The response body's MIME type, when given.
        response_headers: Response headers as ``(name, value)`` pairs (for an opt-in sample only).
        cookies_present: Whether the HAR lists request cookies (a credential, like ``Cookie``).
    """

    method: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()
    query: tuple[tuple[str, str], ...] = ()
    request_body: str | None = None
    response_status: int | None = None
    response_body: str | None = None
    source_location: str | None = None
    source_label: str | None = None
    source_file: str | None = None
    started_at: datetime | None = None
    time_ms: float | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    request_media_type: str | None = None
    response_media_type: str | None = None
    response_headers: tuple[tuple[str, str], ...] = ()
    cookies_present: bool = False


@dataclass(frozen=True)
class SkippedEntry:
    """An entry that produced no event.

    Attributes:
        index: The entry's position in ``log.entries`` (0-based).
        reason: One of :data:`SKIP_REASONS`.
    """

    index: int
    reason: str


# ---------------------------------------------------------------------------------------------
# Streaming reader
# ---------------------------------------------------------------------------------------------


class _Stream:
    """A minimal incremental JSON reader over a binary file.

    It only knows how to walk object keys and decode one complete value at a time, which is all
    reaching ``log.entries`` and yielding its items needs. Text is buffered in chunks of
    ``_READ_CHUNK``; a value that does not fit yet is retried after reading more.
    """

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self._buffer = ""
        self._pos = 0
        self._eof = False
        self._decoder = json.JSONDecoder()
        self._pending = b""

    def _fill(self) -> bool:
        """Read another chunk; return ``False`` at end of file."""
        if self._eof:
            return False
        chunk = self._handle.read(_READ_CHUNK)
        if not chunk:
            self._eof = True
            if self._pending:
                raise HarParseError("the file is not valid UTF-8")
            return False
        data = self._pending + chunk
        try:
            text = data.decode("utf-8")
            self._pending = b""
        except UnicodeDecodeError as exc:
            # A multi-byte character may straddle the chunk boundary; keep its first bytes.
            if exc.start < len(data) - 3:
                raise HarParseError("the file is not valid UTF-8") from exc
            text = data[: exc.start].decode("utf-8")
            self._pending = data[exc.start :]
        if not self._buffer and text.startswith("﻿"):
            text = text[1:]
        self._buffer = self._buffer[self._pos :] + text
        self._pos = 0
        return True

    def peek(self) -> str:
        """The next non-whitespace character ("" at end of file), without consuming it."""
        while True:
            while (
                self._pos < len(self._buffer) and self._buffer[self._pos] in " \t\r\n"
            ):
                self._pos += 1
            if self._pos < len(self._buffer):
                return self._buffer[self._pos]
            if not self._fill():
                return ""

    def expect(self, char: str) -> None:
        """Consume ``char`` or raise :class:`HarParseError`."""
        nxt = self.peek()
        if nxt == "":
            raise HarParseError(_TRUNCATED)
        if nxt != char:
            raise HarParseError(f"expected '{char}' in the HAR file")
        self._pos += 1

    def value(self) -> Any:
        """Decode and consume one complete JSON value."""
        self.peek()
        while True:
            try:
                value, end = self._decoder.raw_decode(self._buffer, self._pos)
            except json.JSONDecodeError as exc:
                if not self._fill():
                    raise HarParseError(_TRUNCATED) from exc
                continue
            # A number at the very end of the buffer may continue in the next chunk.
            if end == len(self._buffer) and not self._eof and self._fill():
                continue
            self._pos = end
            return value

    def keys(self) -> Iterator[str]:
        """Walk the keys of the object at the cursor; the caller consumes each value."""
        self.expect("{")
        if self.peek() == "}":
            self._pos += 1
            return
        while True:
            key = self.value()
            if not isinstance(key, str):
                raise HarParseError(
                    "the HAR file is not valid JSON (an object key is not a string)"
                )
            self.expect(":")
            yield key
            nxt = self.peek()
            if nxt == "":
                raise HarParseError(_TRUNCATED)
            self._pos += 1
            if nxt == "}":
                return
            if nxt != ",":
                raise HarParseError(
                    "the HAR file is not valid JSON (expected ',' or '}')"
                )


def iter_har_entries(handle: BinaryIO) -> Iterator[dict[str, Any]]:
    """Stream the entries of a HAR archive.

    Args:
        handle: The archive, opened in binary mode.

    Yields:
        Each item of ``log.entries`` as a dict (a non-object item is yielded as-is, and the caller
        counts it as an invalid entry).

    Raises:
        HarParseError: When the file is not JSON, has no ``log`` object or no ``log.entries`` array,
            or is truncated.
    """
    stream = _Stream(handle)
    if stream.peek() != "{":
        raise HarParseError("not a HAR file: expected a JSON object with a 'log' key")
    found_log = found_entries = False
    for key in stream.keys():
        if key != "log" or found_log:
            stream.value()
            continue
        found_log = True
        if stream.peek() != "{":
            raise HarParseError("not a HAR file: 'log' is not an object")
        for log_key in stream.keys():
            if log_key != "entries" or found_entries:
                stream.value()
                continue
            found_entries = True
            stream.expect("[")
            if stream.peek() == "]":
                stream.expect("]")
                continue
            while True:
                yield stream.value()
                if stream.peek() == "]":
                    stream.expect("]")
                    break
                stream.expect(",")
    if stream.peek() != "":
        raise HarParseError("the HAR file has content after its top-level object")
    if not found_log:
        raise HarParseError("not a HAR file: no 'log' object")
    if not found_entries:
        raise HarParseError("not a HAR file: 'log' has no 'entries' array")


# ---------------------------------------------------------------------------------------------
# Entry → observation → event
# ---------------------------------------------------------------------------------------------


def _pairs(items: Any) -> tuple[tuple[str, str], ...]:
    """HAR ``[{name, value}]`` lists as ``(name, value)`` pairs; anything else is ignored."""
    if not isinstance(items, list):
        return ()
    pairs = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            value = item.get("value")
            pairs.append((item["name"], value if isinstance(value, str) else ""))
    return tuple(pairs)


def _size(value: Any) -> int | None:
    """A HAR size (``-1`` means unknown)."""
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _started_at(value: Any) -> datetime | None:
    """Parse ``startedDateTime``; ``None`` when missing, unparseable or without a time zone."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def observation_from_entry(
    entry: Any, *, index: int, label: str | None = None
) -> HarObservation | None:
    """Read one HAR entry.

    Args:
        entry: An item of ``log.entries``.
        index: Its position, recorded as ``source_location``.
        label: The file name, recorded as ``source_label``.

    Returns:
        The observation, or ``None`` when the entry has no ``request`` object with a method and URL.
    """
    if not isinstance(entry, dict):
        return None
    request = entry.get("request")
    response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
    if not isinstance(request, dict):
        return None
    method, url = request.get("method"), request.get("url")
    if not isinstance(method, str) or not isinstance(url, str):
        return None
    post = request.get("postData") if isinstance(request.get("postData"), dict) else {}
    content = (
        response.get("content") if isinstance(response.get("content"), dict) else {}
    )
    request_body = post.get("text") if isinstance(post.get("text"), str) else None
    response_body = (
        content.get("text") if isinstance(content.get("text"), str) else None
    )
    if response_body is not None and content.get("encoding") == "base64":
        try:
            response_body = base64.b64decode(response_body, validate=True).decode(
                "utf-8"
            )
        except (ValueError, UnicodeDecodeError):
            response_body = None  # a binary body has no fields
    status = response.get("status")
    status = (
        status if isinstance(status, int) and not isinstance(status, bool) else None
    )
    time_ms = entry.get("time")
    time_ms = (
        float(time_ms)
        if isinstance(time_ms, (int, float)) and not isinstance(time_ms, bool)
        else None
    )
    request_bytes = _size(request.get("bodySize"))
    if request_bytes is None and request_body is not None:
        request_bytes = len(request_body.encode("utf-8"))
    response_bytes = _size(content.get("size"))
    if response_bytes is None:
        response_bytes = _size(response.get("bodySize"))
    return HarObservation(
        method=method.strip().upper(),
        url=url.strip(),
        headers=_pairs(request.get("headers")),
        query=_pairs(request.get("queryString")),
        request_body=request_body,
        response_status=status,
        response_body=response_body,
        source_location=f"entry {index}",
        source_label=label,
        started_at=_started_at(entry.get("startedDateTime")),
        time_ms=time_ms,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        request_media_type=post.get("mimeType")
        if isinstance(post.get("mimeType"), str)
        else None,
        response_media_type=content.get("mimeType")
        if isinstance(content.get("mimeType"), str)
        else None,
        response_headers=_pairs(response.get("headers")),
        cookies_present=bool(_pairs(request.get("cookies"))),
    )


def _escape(segment: str) -> str:
    """RFC 6901-escape one pointer segment."""
    return segment.replace("~", "~0").replace("/", "~1")


def field_pointers(body: str | None) -> list[str]:
    """The JSON Pointers present in a JSON body — names only, never values.

    Every object member is a pointer (``/user`` and ``/user/name``). Array items are folded into
    index ``0`` (``/items/0/id``), so a field counts as present when any item carries it. A pointer
    the usage contract cannot hold (whitespace in a name, more than 512 characters) is left out, and
    at most :data:`MAX_FIELD_POINTERS` are kept (the first in sorted order).

    Args:
        body: Raw body text. Anything that is not a JSON object or array has no pointers.

    Returns:
        Sorted, distinct pointers.
    """
    if not body:
        return []
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        return []
    if not isinstance(document, (dict, list)):
        return []
    found: set[str] = set()

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                pointer = f"{prefix}/{_escape(str(key))}"
                if len(pointer) > _MAX_POINTER_LENGTH or not _POINTER.match(pointer):
                    continue
                found.add(pointer)
                walk(value, pointer)
        elif isinstance(node, list):
            pointer = f"{prefix}/0"
            if len(pointer) > _MAX_POINTER_LENGTH:
                return
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item, pointer)

    try:
        walk(document, "")
    except RecursionError:
        return []
    return sorted(found)[:MAX_FIELD_POINTERS]


def _header(headers: Iterable[tuple[str, str]], name: str) -> str | None:
    """The first value of header ``name`` (case-insensitive)."""
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _parsed_body(text: str | None) -> Any:
    """A body for an opt-in sample: parsed JSON when it parses, the raw text otherwise."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _sample(observation: HarObservation) -> dict[str, Any] | None:
    """The opt-in exchange for ``--sample-bodies``, or ``None`` when it exceeds 16 KiB."""
    sample = {
        "request": {
            "headers": dict(observation.headers),
            "body": _parsed_body(observation.request_body),
            "mediaType": observation.request_media_type,
        },
        "response": {
            "headers": dict(observation.response_headers),
            "body": _parsed_body(observation.response_body),
            "mediaType": observation.response_media_type,
        },
    }
    if (
        len(json.dumps(sample, separators=(",", ":")).encode("utf-8"))
        > MAX_SAMPLE_BYTES
    ):
        return None
    return sample


def event_from_observation(
    observation: HarObservation, *, environment: str, sample_bodies: bool = False
) -> tuple[dict[str, Any] | None, str | None]:
    """Build one ``apiome.usage.event/v1`` event from an observation; the bodies are discarded.

    Args:
        observation: The entry.
        environment: The environment to file it under.
        sample_bodies: Attach the opt-in ``sample`` (only when the source's body window is open —
            the caller checks).

    Returns:
        ``(event, None)``, or ``(None, reason)`` with a reason from :data:`SKIP_REASONS`.
    """
    status = observation.response_status
    if status is None or not 100 <= status <= 599:
        return None, "no-response"  # aborted, blocked or cached-without-status
    if not _METHOD.match(observation.method) or observation.started_at is None:
        return None, "invalid-entry"
    try:
        parts = urlsplit(observation.url)
        port = parts.port
    except ValueError:
        return None, "unsupported-url"
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None, "unsupported-url"  # data:, blob:, chrome-extension:, ws: ...
    path = parts.path or "/"
    if (
        not path.startswith("/")
        or _CONTROL.search(path)
        or any(ch.isspace() for ch in path)
    ):
        return None, "unsupported-url"
    # Query values never leave the machine: only the names are sent.
    names = list(
        dict.fromkeys(
            name for name, _ in parse_qsl(parts.query, keep_blank_values=True)
        )
    )
    if names:
        path = f"{path}?{urlencode([(name, '') for name in names])}"
    if len(path) > _MAX_PATH_LENGTH:
        return None, "unsupported-url"

    event: dict[str, Any] = {
        "observed_at": observation.started_at.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "environment": environment,
        "method": observation.method,
        "path": path,
        "status": status,
        "latency_ms": min(_MAX_LATENCY_MS, max(0, round(observation.time_ms or 0))),
        "scheme": scheme,
        "auth_present": "true"
        if observation.cookies_present
        or any(name.lower() in CREDENTIAL_HEADERS for name, _ in observation.headers)
        else "false",
    }
    host = parts.hostname
    if host:
        host = f"[{host}]" if ":" in host else host
        host = f"{host}:{port}" if port is not None else host
        if _HOST.match(host):
            event["host"] = host.lower()
    if observation.request_bytes is not None:
        event["request_bytes"] = observation.request_bytes
    if observation.response_bytes is not None:
        event["response_bytes"] = observation.response_bytes
    user_agent = _header(observation.headers, "user-agent")
    if user_agent and not _CONTROL.search(user_agent):
        # The server scrubs it, then truncates it to 256; the generous local cap only bounds size.
        event["user_agent"] = user_agent[:_MAX_USER_AGENT_SENT]
    request_fields = field_pointers(observation.request_body)
    response_fields = field_pointers(observation.response_body)
    if request_fields or response_fields:
        event["fields"] = {"request": request_fields, "response": response_fields}
    if sample_bodies:
        sample = _sample(observation)
        if sample is not None:
            event["sample"] = sample
    return event, None


# ---------------------------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------------------------


@dataclass
class _Batch:
    events: list[dict[str, Any]] = field(default_factory=list)
    size: int = _BATCH_OVERHEAD


def batches(
    events: Iterable[dict[str, Any]],
    *,
    max_events: int = MAX_EVENTS_PER_BATCH,
    max_bytes: int = MAX_BATCH_BYTES,
) -> Iterator[list[dict[str, Any]]]:
    """Group events into ingest batches.

    A batch closes at ``max_events`` events, or earlier when the next event would take its JSON
    past ``max_bytes`` (the door's limit applies before and after gzip). An event that alone is
    larger than the limit is sent without its opt-in ``sample``. Without one, an event is always far
    below the limit (512 pointers per side, a 2,048-character path, a 1,024-character user agent).

    Args:
        events: The events, in file order.
        max_events: Events per batch.
        max_bytes: Bytes per batch.

    Yields:
        Lists of events, in order.
    """
    current = _Batch()
    for event in events:
        size = (
            len(
                json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
            )
            + 1
        )
        if size + _BATCH_OVERHEAD > max_bytes and "sample" in event:
            event = {key: value for key, value in event.items() if key != "sample"}
            size = (
                len(
                    json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode(
                        "utf-8"
                    )
                )
                + 1
            )
        if current.events and (
            len(current.events) >= max_events or current.size + size > max_bytes
        ):
            yield current.events
            current = _Batch()
        current.events.append(event)
        current.size += size
    if current.events:
        yield current.events


def read_har(path: Path) -> Iterator[tuple[int, Any]]:
    """Stream ``(index, entry)`` pairs from a HAR file on disk.

    Args:
        path: The file.

    Yields:
        Each entry with its 0-based index.

    Raises:
        HarParseError: See :func:`iter_har_entries`.
        OSError: When the file cannot be read.
    """
    with path.open("rb") as handle:
        yield from enumerate(iter_har_entries(handle))
