"""WSDL live fetch — MFI-13.3 (#3790).

A running SOAP service publishes its description at its endpoint URL with a query: ``?wsdl``
(every stack) and, on WCF, ``?singleWsdl`` — the same description with every ``wsdl:import`` and
``xs:import`` already flattened into one document. A ``?wsdl`` description often is *not* one
document: it names others by URL (``<wsdl:import location="…?wsdl=wsdl0">``,
``<xs:import schemaLocation="…?xsd=xsd0">``), and without them its messages and types are
missing.

:func:`fetch_wsdl_service`:

1. picks the description URL — ``?singleWsdl`` first, then ``?wsdl`` — unless the caller already
   named one (a ``…?wsdl`` URL still tries ``?singleWsdl`` first, since it inlines the graph);
2. follows every ``wsdl:import`` ``location`` and ``xs:import`` / ``xs:include``
   ``schemaLocation`` of the description and of each document it pulls in, transitively, resolving
   relative locations against the document that names them;
3. returns the description and the documents it references, keyed by the location *as written*,
   which is exactly what :func:`app.wsdl_parser.parse_wsdl` resolves ``members`` by.

Every request goes through the SSRF-guarded client (:mod:`app.live_fetch`). The graph is bounded:
at most :data:`MAX_REFERENCED_DOCUMENTS` referenced documents and :data:`MAX_TOTAL_BYTES` in all.
A referenced document that cannot be fetched is noted and skipped — the description still imports,
with those types unresolved, as an unresolved fileset member would.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from .import_source import ImportSourceError
from .live_fetch import auth_headers, check_public_url, guarded_client, guarded_get
from .secure_xml import SecureXmlError, parse_xml
from .wsdl_parser import is_wsdl

__all__ = [
    "MAX_DOCUMENT_BYTES",
    "MAX_REFERENCED_DOCUMENTS",
    "MAX_TOTAL_BYTES",
    "WsdlFetch",
    "candidate_urls",
    "fetch_wsdl_service",
    "referenced_locations",
]

#: Largest single document read.
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
#: Most documents a description may pull in (imports and includes, transitively).
MAX_REFERENCED_DOCUMENTS = 50
#: Most bytes read for one description and everything it references.
MAX_TOTAL_BYTES = 32 * 1024 * 1024

_ACCEPT = "text/xml, application/xml, application/wsdl+xml;q=0.9, */*;q=0.1"
_WSDL_QUERY_KEYS = ("wsdl", "singlewsdl")


@dataclass(frozen=True)
class WsdlFetch:
    """A fetched WSDL description and the documents it references.

    Attributes:
        url: The description URL that answered.
        single_wsdl: Whether that was ``?singleWsdl`` (the graph arrived already inlined).
        wsdl: The description text.
        members: Referenced documents, keyed by the location as written in the referencing
            document.
        fetched: ``(location as written, absolute URL)`` for every referenced document read.
        notes: Referenced documents that were skipped, and why.
    """

    url: str
    single_wsdl: bool
    wsdl: str
    members: Dict[str, str] = field(default_factory=dict)
    fetched: Tuple[Tuple[str, str], ...] = ()
    notes: Tuple[str, ...] = ()


def _with_query(url: str, key: str) -> str:
    """``url`` with its WSDL query (``wsdl`` / ``singleWsdl``) replaced by ``key``."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _WSDL_QUERY_KEYS]
    query = "&".join(filter(None, [urlencode(kept), key]))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def candidate_urls(url: str) -> List[str]:
    """The description URLs to try for a service URL, best first.

    Args:
        url: A service endpoint (``https://host/Service.svc``), its ``?wsdl`` / ``?singleWsdl``
            URL, or a ``.wsdl`` file URL.

    Returns:
        ``[…?singleWsdl, …?wsdl]`` for an endpoint or ``?wsdl`` URL; the URL alone for a
        ``?singleWsdl`` or ``.wsdl`` URL (or any other URL that already carries a query).

    Raises:
        ImportSourceError: When the URL is not http(s).
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ImportSourceError(f"WSDL fetch needs an http(s) URL, not {url!r}")
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    keys = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    if "singlewsdl" in keys or parts.path.lower().endswith((".wsdl", ".xml")):
        return [cleaned]
    if "wsdl" in keys or not parts.query:
        return [_with_query(cleaned, "singleWsdl"), _with_query(cleaned, "wsdl")]
    return [cleaned]


def referenced_locations(text: str, *, source_label: Optional[str] = None) -> List[str]:
    """The locations a WSDL or XSD document names: ``wsdl:import location``, ``xs:import`` /
    ``xs:include`` ``schemaLocation`` (as written, in document order, without duplicates)."""
    try:
        root = parse_xml(text, source_label=source_label)
    except SecureXmlError:
        return []
    found: List[str] = []
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""
        location = None
        if local == "import" and element.get("location"):
            location = element.get("location")
        elif local in ("import", "include") and element.get("schemaLocation"):
            location = element.get("schemaLocation")
        if location and location.strip() and location.strip() not in found:
            found.append(location.strip())
    return found


def _fetch_description(
    client: httpx.Client, url: str, headers: Mapping[str, str]
) -> Tuple[str, str, bool]:
    """Fetch the first candidate URL that answers with a WSDL document.

    Returns:
        ``(url, text, single_wsdl)``.

    Raises:
        ImportSourceError: The last candidate's error, or ``FORMAT_MISMATCH`` when every
            candidate answered with something that is not WSDL.
    """
    last_error: Optional[ImportSourceError] = None
    for candidate in candidate_urls(url):
        try:
            text = guarded_get(
                client,
                candidate,
                accept=_ACCEPT,
                headers=headers,
                what="WSDL description",
                max_bytes=MAX_DOCUMENT_BYTES,
            )
        except ImportSourceError as exc:
            last_error = exc
            continue
        if is_wsdl(text):
            return candidate, text, "singlewsdl" in candidate.lower()
        last_error = ImportSourceError(
            f"{candidate} did not return a WSDL description.", code="FORMAT_MISMATCH"
        )
    assert last_error is not None
    raise last_error


def fetch_wsdl_service(
    url: str,
    *,
    auth_type: Optional[str] = None,
    auth_payload: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.Client] = None,
) -> WsdlFetch:
    """Fetch a live SOAP service's WSDL description and every document it references.

    Args:
        url: The service endpoint, or its ``?wsdl`` / ``?singleWsdl`` / ``.wsdl`` URL.
        auth_type: Credential-vault auth type.
        auth_payload: The decrypted credential for ``auth_type``.
        headers: Extra request headers.
        client: An httpx client to inject (tests); production uses the SSRF-guarded client.

    Returns:
        The description and its referenced documents.

    Raises:
        ImportSourceError: When the URL is unsafe or not http(s), the credential is malformed, the
            description cannot be fetched (see :func:`app.live_fetch.guarded_get`), or no
            candidate URL returned WSDL (``FORMAT_MISMATCH``).
    """
    first = candidate_urls(url)[0]
    check_public_url(first, what="WSDL")
    request_headers = {**auth_headers(auth_type, auth_payload), **dict(headers or {})}

    owns_client = client is None
    http = client if client is not None else guarded_client()
    try:
        description_url, wsdl, single = _fetch_description(http, url, request_headers)
        members: Dict[str, str] = {}
        fetched: List[Tuple[str, str]] = []
        notes: List[str] = []
        seen_urls = {description_url}
        total = len(wsdl.encode("utf-8"))
        queue: List[Tuple[str, str]] = [(description_url, wsdl)]
        while queue:
            base_url, text = queue.pop(0)
            for location in referenced_locations(text, source_label=base_url):
                absolute = urljoin(base_url, location)
                if location in members or absolute in seen_urls:
                    continue
                if urlsplit(absolute).scheme.lower() not in ("http", "https"):
                    notes.append(f"{location}: not an http(s) location, not fetched")
                    continue
                if len(fetched) >= MAX_REFERENCED_DOCUMENTS:
                    notes.append(f"{location}: more than {MAX_REFERENCED_DOCUMENTS} referenced documents, not fetched")
                    continue
                seen_urls.add(absolute)
                try:
                    check_public_url(absolute, what="referenced document")
                    body = guarded_get(
                        http,
                        absolute,
                        accept=_ACCEPT,
                        headers=request_headers,
                        what="referenced document",
                        max_bytes=MAX_DOCUMENT_BYTES,
                    )
                except ImportSourceError as exc:
                    notes.append(f"{location}: {exc}")
                    continue
                total += len(body.encode("utf-8"))
                if total > MAX_TOTAL_BYTES:
                    raise ImportSourceError(
                        f"The WSDL description and the documents it references exceed {MAX_TOTAL_BYTES} bytes.",
                        code="INPUT_TOO_LARGE",
                    )
                members[location] = body
                fetched.append((location, absolute))
                queue.append((absolute, body))
    finally:
        if owns_client:
            http.close()
    return WsdlFetch(
        url=description_url,
        single_wsdl=single,
        wsdl=wsdl,
        members=members,
        fetched=tuple(fetched),
        notes=tuple(notes),
    )

