"""SOAP service discovery for ``apiome import wsdl --discover`` (MFI-13.3, #3790).

A SOAP service publishes its description at its endpoint with a query: ``?wsdl`` on every stack,
and on WCF also ``?singleWsdl`` — the same description with every ``wsdl:import`` and
``xs:import`` already inlined. :func:`discover_wsdl_url` tries ``?singleWsdl`` first, then
``?wsdl`` (the rules of the REST adapter's live fetch, ``app.wsdl_fetch.candidate_urls``), and
returns the first that answers with a WSDL document; it is then imported through the ordinary
registry-dispatch import.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

_WSDL_KEYS = ("wsdl", "singlewsdl")
_WSDL_ROOTS = ("<wsdl:definitions", "<definitions", "<wsdl:description", "<description")


def _with_query(url: str, key: str) -> str:
    """``url`` with its WSDL query (``wsdl`` / ``singleWsdl``) replaced by ``key``."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _WSDL_KEYS]
    query = "&".join(filter(None, [urlencode(kept), key]))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def wsdl_candidate_urls(service_url: str) -> list[str]:
    """The description URLs to try for a service URL, best first.

    Args:
        service_url: A service endpoint, its ``?wsdl`` / ``?singleWsdl`` URL, or a ``.wsdl`` URL.

    Returns:
        ``[…?singleWsdl, …?wsdl]`` for an endpoint or ``?wsdl`` URL; the URL alone otherwise.

    Raises:
        ValueError: When the URL is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (service_url or "").strip()
    if not cleaned:
        raise ValueError("SOAP service URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("SOAP service URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("SOAP service URL has no host")
    base = urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, ""))
    keys = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    if "singlewsdl" in keys or parts.path.lower().endswith((".wsdl", ".xml")):
        return [base]
    if "wsdl" in keys or not parts.query:
        return [_with_query(base, "singleWsdl"), _with_query(base, "wsdl")]
    return [base]


def _is_wsdl(text: str) -> bool:
    """Whether a response body is a WSDL document (1.1 or 2.0)."""
    head = text[:4096]
    return any(root in head for root in _WSDL_ROOTS)


def discover_wsdl_url(
    service_url: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
    client: httpx.Client | None = None,
) -> str:
    """Find the URL a SOAP service serves its WSDL description from.

    Args:
        service_url: The service endpoint or a description URL.
        timeout: HTTP timeout per request, in seconds.
        verify: Whether to verify TLS certificates.
        client: Optional httpx client (tests); one is created and closed otherwise.

    Returns:
        The first candidate URL that answers with a WSDL document.

    Raises:
        ValueError: When ``service_url`` is unusable.
        OSError: On a network failure, or when no candidate serves a WSDL document.
    """
    candidates = wsdl_candidate_urls(service_url)
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, verify=verify, follow_redirects=True)
    try:
        for url in candidates:
            try:
                response = http.get(url)
            except httpx.RequestError as exc:
                raise OSError(f"Failed to fetch {url!r}: {exc}") from exc
            if response.status_code < 400 and _is_wsdl(response.text):
                return url
    finally:
        if owns_client:
            http.close()
    raise OSError("No WSDL description found; tried " + ", ".join(candidates))
