"""Reader for HAR (HTTP Archive) captures — MFI-32.2 (#4404).

A HAR file is what a browser's devtools (Network → *Save all as HAR*), a debugging proxy (Charles,
Fiddler, mitmproxy) or a test runner writes when it records traffic: one JSON object whose
``log.entries`` list holds every request the page made, each with its ``response``. HAR 1.2 is the
version every current tool writes; 1.1 differs only in fields this reader does not use, so both are
read the same way.

This module turns one capture (or several, uploaded as a fileset) into a :class:`HarDocument`: the
:class:`~app.inferred_spec.HttpObservation` samples the shared inferred-spec engine clusters into
operations, plus what the engine has no slot for — each request's body media type and auth scheme,
the hosts the capture called, and the entries the import left out and why.

**Noise.** Every entry first goes through :func:`app.har_filters.classify_entry`: page assets,
analytics beacons, CORS preflights and non-HTTP URLs are left out (and counted), tunable with the
``har_*`` import options (:class:`~app.har_filters.HarOptions`). Of what is left, **one host** is
imported — the one with the most API calls, or the hosts named in ``har_hosts`` — so a capture of a
page that talks to three APIs becomes one catalog item per host, one import each.

**Credentials never leave this module.** A capture carries live session cookies, bearer tokens and
API keys. The ``cookies`` arrays are never read. An ``Authorization`` value keeps only its scheme
word (``Bearer``); every other header, parameter, URL and body value passes the shared secret-scrub
gate, and a header or parameter whose *name* says it holds a secret is redacted outright. Headers
the browser sets by itself (``User-Agent``, ``sec-*``, HTTP/2 pseudo-headers …) are dropped, so they
do not become operation parameters.

Error codes (the import taxonomy):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark.
* ``INPUT_TRUNCATED`` — the JSON ends while a value is still open (a capture cut off mid-write).
* ``INPUT_MALFORMED`` — any other JSON syntax error, or a ``log`` whose ``entries`` / ``request``
  structure is wrong.
* ``FORMAT_MISMATCH`` — valid JSON that is not a HAR capture (no ``log`` object).
* ``INPUT_SEMANTIC_INVALID`` — a capture with no entries, one where every entry was filtered as
  noise, a ``har_hosts`` host the capture never called, or an option with the wrong shape.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit

from .client_collection import load_client_json, scrub_named, scrub_value
from .har_filters import (
    EXCLUDED_BY_PATTERN,
    NON_HTTP,
    UNSELECTED_HOST,
    HarOptions,
    classify_entry,
    is_browser_header,
)
from .inferred_spec import HttpObservation, auth_scheme_from_headers
from .intake_secret_scrub import REDACTION_MARKER

__all__ = [
    "FORMAT_KEY",
    "HarAuth",
    "HarDocument",
    "HarEntry",
    "HarHost",
    "HarParseError",
    "MEMBER_SUFFIXES",
    "is_har",
    "parse_har_fileset",
    "parse_har_text",
]

#: The registry key of the format.
FORMAT_KEY = "har"

#: Fileset members read as captures; any other member (a README) is ignored.
MEMBER_SUFFIXES = (".har", ".json")

#: Never matches: HAR has no variable syntax, so no value is "a reference rather than a secret".
_NO_REFERENCE = re.compile(r"(?!)")


class HarParseError(ValueError):
    """Raised when a HAR upload cannot be read.

    Attributes:
        code: The import taxonomy code the pipeline reports.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HarAuth:
    """The auth scheme a captured request carried — the scheme only, never the credential.

    Attributes:
        scheme: The canonical scheme identifier (``bearer``, ``basic``, ``apiKey``, ``cookie`` …).
    """

    scheme: str

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the operation's ``extras`` record."""
        return {"scheme": self.scheme}


@dataclass(frozen=True)
class HarEntry:
    """One captured API call that reached the engine.

    Attributes:
        method: The upper-cased request method.
        url: The scrubbed URL the observation carries (no fragment, no user-info).
        host: The lower-cased ``host[:port]``.
        folder: Always empty — a capture has no folders (kept for the shared annotation helper).
        auth: The auth scheme the request carried, if any.
        content_type: The request body's media type, if it had a body.
        location: Where the entry sits (``log.entries[3]``).
        source_file: The fileset member it came from, if any.
        carries_cookies: Whether the request sent cookies (a ``Cookie`` header or ``cookies`` list).
        carries_credential: Whether its ``Authorization`` credential was withheld.
    """

    method: str
    url: str
    host: str
    folder: Tuple[str, ...] = ()
    auth: Optional[HarAuth] = None
    content_type: Optional[str] = None
    location: str = ""
    source_file: Optional[str] = None
    carries_cookies: bool = False
    carries_credential: bool = False


@dataclass(frozen=True)
class HarHost:
    """One host the capture made API calls to.

    Attributes:
        host: The lower-cased ``host[:port]``.
        api_calls: How many entries to it survived the noise filter.
        selected: Whether this import kept it.
    """

    host: str
    api_calls: int
    selected: bool

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the model's ``extras`` record."""
        return {"host": self.host, "api_calls": self.api_calls, "selected": self.selected}


@dataclass
class HarDocument:
    """A parsed HAR upload, ready for the inferred-spec engine.

    Attributes:
        title: The artifact title (the selected host or hosts).
        versions: Every ``log.version`` read, sorted.
        creators: Every ``log.creator`` (``name version``) read, sorted.
        observations: The engine's input — one per kept entry.
        requests: The per-entry facts the engine has no slot for, aligned with ``observations``.
        hosts: Every host API calls went to, with whether it was selected.
        exclusions: Exclusion reason → one ``host/path`` location per entry left out.
        total_entries: Every entry read, kept or not.
        cookie_entries: Kept entries that carried cookies (never read).
        credential_entries: Kept entries whose ``Authorization`` credential was withheld.
        options: The import options that shaped the read.
    """

    title: str
    versions: List[str]
    creators: List[str]
    observations: List[HttpObservation]
    requests: List[HarEntry]
    hosts: List[HarHost]
    exclusions: Dict[str, List[str]]
    total_entries: int
    cookie_entries: int
    credential_entries: int
    options: HarOptions = field(default_factory=HarOptions)


def _error(message: str, code: str) -> HarParseError:
    return HarParseError(message, code=code)


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def is_har(document: Any) -> bool:
    """True when ``document`` has a HAR's shape: a ``log`` object holding an ``entries`` list."""
    if not isinstance(document, Mapping):
        return False
    log = document.get("log")
    return isinstance(log, Mapping) and isinstance(log.get("entries"), list)


def _media_type(value: Any) -> Optional[str]:
    """The bare, lower-cased media type of a ``mimeType`` value, or ``None``."""
    if not isinstance(value, str):
        return None
    bare = value.split(";", 1)[0].strip().lower()
    return bare or None


def _pairs(value: Any) -> List[Tuple[str, str]]:
    """Read a HAR ``[{name, value}]`` list, skipping malformed members."""
    if not isinstance(value, list):
        return []
    pairs: List[Tuple[str, str]] = []
    for item in value:
        if isinstance(item, Mapping) and isinstance(item.get("name"), str):
            raw = item.get("value")
            pairs.append((item["name"], raw if isinstance(raw, str) else ("" if raw is None else str(raw))))
    return pairs


def _host_of(parts: Any) -> str:
    """``host[:port]`` of a split URL, lower-cased, without user-info."""
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return netloc.lower()


def _header_value(name: str, value: str) -> str:
    """A header value safe to keep: an ``Authorization`` keeps its scheme word only."""
    if name.strip().lower() == "authorization" and value.strip():
        scheme = value.strip().split(None, 1)[0]
        return f"{scheme} {REDACTION_MARKER}" if scheme.isalpha() else REDACTION_MARKER
    return scrub_named(name, value, reference=_NO_REFERENCE)


def _response_body(content: Mapping[str, Any]) -> Optional[str]:
    """The response body text, decoding a base64 body; ``None`` when there is none or it is binary."""
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return None
    if str(content.get("encoding") or "").lower() == "base64":
        try:
            return base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            return None
    return text


class _Reader:
    """Reads entries from one or more captures into kept calls and exclusion tallies."""

    def __init__(self, options: HarOptions) -> None:
        self.options = options
        self.versions: set = set()
        self.creators: set = set()
        self.kept: List[Tuple[HttpObservation, HarEntry]] = []
        self.exclusions: Dict[str, List[str]] = {}
        self.total = 0

    def _exclude(self, reason: str, location: str) -> None:
        self.exclusions.setdefault(reason, []).append(location)

    def read_log(self, document: Any, *, label: Optional[str], source_file: Optional[str]) -> None:
        """Read one capture's ``log``.

        Raises:
            HarParseError: ``FORMAT_MISMATCH`` when it is not a HAR, ``INPUT_MALFORMED`` when its
                entries are not shaped as HAR entries.
        """
        if not isinstance(document, Mapping) or not isinstance(document.get("log"), Mapping):
            raise _error(
                f"Not a HAR capture{_where(label)}: a HAR file is a JSON object with a `log` object "
                "(save one from your browser's devtools: Network → Save all as HAR)",
                "FORMAT_MISMATCH",
            )
        log = document["log"]
        entries = log.get("entries")
        if not isinstance(entries, list):
            raise _error(f"`log.entries` must be a list{_where(label)}", "INPUT_MALFORMED")
        version = log.get("version")
        if isinstance(version, str) and version.strip():
            self.versions.add(version.strip())
        creator = log.get("creator")
        if isinstance(creator, Mapping) and isinstance(creator.get("name"), str):
            self.creators.add(f"{creator['name']} {creator.get('version') or ''}".strip())
        for index, entry in enumerate(entries):
            self.read_entry(entry, index=index, label=label, source_file=source_file)

    def read_entry(self, entry: Any, *, index: int, label: Optional[str], source_file: Optional[str]) -> None:
        """Classify one entry and, when it is a kept API call, turn it into an observation."""
        location = f"log.entries[{index}]"
        request = entry.get("request") if isinstance(entry, Mapping) else None
        if not isinstance(request, Mapping) or not isinstance(request.get("url"), str):
            raise _error(f"{location} has no `request.url`{_where(label)}", "INPUT_MALFORMED")
        method = request.get("method")
        if not isinstance(method, str) or not method.strip():
            raise _error(f"{location} has no `request.method`{_where(label)}", "INPUT_MALFORMED")
        self.total += 1
        method = method.strip().upper()
        try:
            parts = urlsplit(request["url"].strip())
        except ValueError as exc:
            raise _error(f"{location} has an unreadable URL{_where(label)}: {exc}", "INPUT_MALFORMED") from exc
        scheme = parts.scheme.lower()
        host = _host_of(parts)
        path = parts.path or "/"
        response = entry.get("response") if isinstance(entry.get("response"), Mapping) else {}
        content = response.get("content") if isinstance(response.get("content"), Mapping) else {}

        reason = self._exclusion_reason(entry, method=method, scheme=scheme, host=host, path=path, content=content)
        if reason is not None:
            # A non-HTTP URL (``data:``…) is its own payload; only its scheme is recorded.
            self._exclude(reason, f"{scheme}:" if reason == NON_HTTP else scrub_value(f"{host}{path}"))
            return
        self.kept.append(
            self._observation(
                request, response, content, method=method, scheme=scheme, host=host, path=path, query=parts.query,
                location=location, label=label, source_file=source_file,
            )
        )

    def _exclusion_reason(
        self, entry: Mapping[str, Any], *, method: str, scheme: str, host: str, path: str, content: Mapping[str, Any]
    ) -> Optional[str]:
        """Why an entry is left out, or ``None`` to keep it (exclude patterns beat include patterns)."""
        builtin = classify_entry(
            method=method,
            scheme=scheme,
            host=host,
            path=path,
            resource_type=entry.get("_resourceType") if isinstance(entry.get("_resourceType"), str) else None,
            response_media_type=content.get("mimeType") if isinstance(content.get("mimeType"), str) else None,
        )
        if builtin == NON_HTTP:
            return NON_HTTP
        if self.options.is_excluded(host, path):
            return EXCLUDED_BY_PATTERN
        if builtin is None or self.options.keep_noise or self.options.is_included(host, path):
            return None
        return builtin

    def _observation(
        self,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        content: Mapping[str, Any],
        *,
        method: str,
        scheme: str,
        host: str,
        path: str,
        query: str,
        location: str,
        label: Optional[str],
        source_file: Optional[str],
    ) -> Tuple[HttpObservation, HarEntry]:
        """Build the scrubbed observation and its per-entry facts."""
        raw_headers = [(name, value) for name, value in _pairs(request.get("headers")) if not is_browser_header(name)]
        headers = tuple((name, _header_value(name, value)) for name, value in raw_headers)
        carries_cookies = bool(_pairs(request.get("cookies"))) or any(
            name.strip().lower() == "cookie" for name, _ in raw_headers
        )
        carries_credential = any(
            name.strip().lower() == "authorization" and value.strip() for name, value in raw_headers
        )

        query_pairs = _pairs(request.get("queryString")) or parse_qsl(query, keep_blank_values=True)
        scrubbed_query = tuple(
            (name, scrub_named(name, value, reference=_NO_REFERENCE)) for name, value in query_pairs
        )
        safe_path = scrub_value(path)
        url = f"{scheme}://{host}{safe_path}"
        if scrubbed_query:
            url += "?" + urlencode(scrubbed_query, safe="[]")

        post = request.get("postData") if isinstance(request.get("postData"), Mapping) else {}
        body_text = post.get("text") if isinstance(post.get("text"), str) and post.get("text") else None
        content_type = _media_type(post.get("mimeType")) if (body_text or post.get("params")) else None

        status = response.get("status")
        response_status = status if isinstance(status, int) and not isinstance(status, bool) and status > 0 else None
        response_text = _response_body(content) if response_status is not None else None

        scheme_name = auth_scheme_from_headers(headers)
        observation = HttpObservation(
            method=method,
            url=url,
            headers=headers,
            query=scrubbed_query,
            request_body=scrub_value(body_text) if body_text else None,
            response_status=response_status,
            response_body=scrub_value(response_text) if response_text else None,
            source_location=location,
            source_label=label,
            source_file=source_file,
        )
        entry = HarEntry(
            method=method,
            url=url,
            host=host,
            auth=HarAuth(scheme_name) if scheme_name else None,
            content_type=content_type,
            location=location,
            source_file=source_file,
            carries_cookies=carries_cookies,
            carries_credential=carries_credential,
        )
        return observation, entry


def _summarize_exclusions(exclusions: Mapping[str, Sequence[str]]) -> str:
    return ", ".join(f"{len(locations)} {reason}" for reason, locations in sorted(exclusions.items()))


def _build(reader: _Reader, *, label: Optional[str]) -> HarDocument:
    """Select the host(s) and assemble the document.

    Raises:
        HarParseError: ``INPUT_SEMANTIC_INVALID`` for an empty capture, one that is all noise, or a
            requested host the capture has no API calls to.
    """
    if reader.total == 0:
        raise _error(f"The capture{_where(label)} has no entries — record some traffic first", "INPUT_SEMANTIC_INVALID")
    if not reader.kept:
        raise _error(
            f"No API calls found{_where(label)}: all {reader.total} entries were left out "
            f"({_summarize_exclusions(reader.exclusions)}). Set the `har_keep_noise` option, or add "
            "`har_include` patterns, to keep them",
            "INPUT_SEMANTIC_INVALID",
        )
    counts = Counter(entry.host for _, entry in reader.kept)
    requested = reader.options.hosts
    if requested:
        missing = [host for host in requested if host not in counts]
        if missing:
            raise _error(
                f"`har_hosts` names {', '.join(missing)}, which the capture has no API calls to. "
                f"Hosts in this capture: {', '.join(sorted(counts))}",
                "INPUT_SEMANTIC_INVALID",
            )
        selected = set(requested)
    else:
        # The host with the most API calls; ties go to the alphabetically first, so the choice is stable.
        selected = {sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]}

    observations: List[HttpObservation] = []
    requests: List[HarEntry] = []
    for observation, entry in reader.kept:
        if entry.host in selected:
            observations.append(observation)
            requests.append(entry)
        else:
            reader._exclude(UNSELECTED_HOST, scrub_value(f"{entry.host}{urlsplit(entry.url).path}"))
    return HarDocument(
        title=", ".join(sorted(selected)),
        versions=sorted(reader.versions),
        creators=sorted(reader.creators),
        observations=observations,
        requests=requests,
        hosts=[HarHost(host=host, api_calls=counts[host], selected=host in selected) for host in sorted(counts)],
        exclusions={reason: list(locations) for reason, locations in sorted(reader.exclusions.items())},
        total_entries=reader.total,
        cookie_entries=sum(1 for entry in requests if entry.carries_cookies),
        credential_entries=sum(1 for entry in requests if entry.carries_credential),
        options=reader.options,
    )


def _load(text: str, label: Optional[str]) -> Any:
    return load_client_json(text, label, product="HAR", error=_error)


def parse_har_text(
    raw: str, *, source_label: Optional[str] = None, options: Optional[HarOptions] = None
) -> HarDocument:
    """Parse one HAR capture.

    Args:
        raw: The decoded upload.
        source_label: The filename, for messages and observation labels.
        options: The import's HAR options (defaults when ``None``).

    Returns:
        The parsed document, one host selected.

    Raises:
        HarParseError: With the taxonomy code (see the module docstring).
    """
    reader = _Reader(options or HarOptions())
    reader.read_log(_load(raw, source_label), label=source_label, source_file=None)
    return _build(reader, label=source_label)


def parse_har_fileset(
    members: Mapping[str, str],
    *,
    root: Optional[str] = None,
    source_label: Optional[str] = None,
    options: Optional[HarOptions] = None,
) -> HarDocument:
    """Parse several captures (one recording session each) into one API.

    Every ``.har`` / ``.json`` member is read as a capture, root first, the rest in path order;
    other members are ignored.

    Args:
        members: Member text keyed by path.
        root: The root member's path.
        source_label: The upload's label, for messages.
        options: The import's HAR options (defaults when ``None``).

    Returns:
        The parsed document, one host selected across every capture.

    Raises:
        HarParseError: When a capture member cannot be read, or none of the members is a capture.
    """
    names = [
        name for name in sorted(members) if PurePosixPath(name).suffix.lower() in MEMBER_SUFFIXES
    ]
    if root in names:
        names.remove(root)
        names.insert(0, root)
    if not names:
        raise _error(
            f"The upload{_where(source_label)} has no `.har` capture among its files", "FORMAT_MISMATCH"
        )
    reader = _Reader(options or HarOptions())
    for name in names:
        reader.read_log(_load(members[name], name), label=name, source_file=name)
    return _build(reader, label=source_label)
