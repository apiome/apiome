"""OData live discovery — MFI-11.3 (#3778).

A running OData service describes itself at two well-known addresses below its **service root**:

* ``<root>/$metadata`` — the CSDL (XML for every version; v4 services may also offer CSDL JSON),
  the full model the import catalogs;
* ``<root>/`` — the **service document**, which lists what the service actually exposes at its top
  level: entity sets, singletons and function imports, each with the URL it is reached at. It comes
  as JSON in v4 (``{"value": [{"name", "kind", "url"}]}``), as ``{"d": {"EntitySets": [...]}}`` in
  v2 JSON, or as an AtomPub ``<app:service>`` document in v2/v3.

:func:`discover_odata_service` fetches both over the SSRF-guarded HTTP client
(:func:`app.ssrf_guard.build_guarded_client`, every redirect hop re-validated), with an optional
credential from the credential vault. The ``$metadata`` document is required; the service
document is best effort — a service that hides it still imports, with a note. The adapter
(:meth:`app.odata_import_source.ODataImportSource.discover`) parses the metadata and records the
service document on the catalog item.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

from .import_source import ImportSourceError
from .mcp_auth import AUTH_TYPE_NONE, CredentialPayloadError, build_auth_headers
from .secure_xml import SecureXmlError, parse_xml
from .ssrf_guard import SSRFError, build_guarded_client, validate_url

__all__ = [
    "MAX_DISCOVERY_BYTES",
    "ODataDiscovery",
    "ODataServiceEntry",
    "discover_odata_service",
    "parse_service_document",
    "service_urls",
]

#: Largest ``$metadata`` or service document read (bytes).
MAX_DISCOVERY_BYTES = 16 * 1024 * 1024

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_UA = "apiome-odata-discovery/1.0"
_METADATA_SEGMENT = "$metadata"


@dataclass(frozen=True)
class ODataServiceEntry:
    """One top-level resource a service document lists.

    Attributes:
        name: The resource's name (``Products``).
        kind: ``EntitySet``, ``Singleton``, ``FunctionImport`` or ``ServiceDocument`` (v4); v2/v3
            service documents list only entity sets.
        url: The URL it is reached at, relative to the service root as the document gives it.
    """

    name: str
    kind: str
    url: str

    def as_dict(self) -> Dict[str, str]:
        """The entry as ``{"name", "kind", "url"}``."""
        return {"name": self.name, "kind": self.kind, "url": self.url}


@dataclass(frozen=True)
class ODataDiscovery:
    """What a live OData service gave back.

    Attributes:
        service_url: The service root (no trailing slash).
        metadata_url: The ``$metadata`` URL fetched.
        metadata: The ``$metadata`` document text.
        service_document: The resources the service document lists, in its order; empty when it
            could not be read.
        service_document_format: ``json``, ``atom`` or ``None`` when it could not be read.
        notes: Why the service document is missing, when it is.
    """

    service_url: str
    metadata_url: str
    metadata: str
    service_document: Tuple[ODataServiceEntry, ...] = ()
    service_document_format: Optional[str] = None
    notes: Tuple[str, ...] = ()


def service_urls(url: str) -> Tuple[str, str]:
    """The service root and ``$metadata`` URL for a service root or ``$metadata`` URL.

    Args:
        url: ``https://host/svc``, ``https://host/svc/`` or ``https://host/svc/$metadata``
            (a query string, e.g. ``sap-client=100``, is kept on both).

    Returns:
        ``(service_root, metadata_url)``.

    Raises:
        ImportSourceError: When the URL is not http(s).
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ImportSourceError(f"OData discovery needs an http(s) service URL, not {url!r}")
    path = parts.path.rstrip("/")
    if path.endswith("/" + _METADATA_SEGMENT) or path == _METADATA_SEGMENT:
        path = path[: -len(_METADATA_SEGMENT)].rstrip("/")
    root = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
    metadata = urlunsplit((parts.scheme, parts.netloc, f"{path}/{_METADATA_SEGMENT}", parts.query, ""))
    return root, metadata


# ===========================================================================
# Service documents
# ===========================================================================


def _json_entries(document: Any) -> Optional[List[ODataServiceEntry]]:
    """Entries of a v4 (``value``) or v2 (``d.EntitySets``) JSON service document."""
    if not isinstance(document, Mapping):
        return None
    if isinstance(document.get("value"), list):
        entries = []
        for item in document["value"]:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                entries.append(
                    ODataServiceEntry(
                        name=item["name"],
                        kind=str(item.get("kind") or "EntitySet"),
                        url=str(item.get("url") or item["name"]),
                    )
                )
        return entries
    data = document.get("d")
    if isinstance(data, Mapping) and isinstance(data.get("EntitySets"), list):
        return [
            ODataServiceEntry(name=name, kind="EntitySet", url=name)
            for name in data["EntitySets"]
            if isinstance(name, str)
        ]
    return None


def _atom_entries(text: str) -> Optional[List[ODataServiceEntry]]:
    """Entries of an AtomPub ``<app:service>`` document (v2/v3)."""
    try:
        root = parse_xml(text, source_label="OData service document")
    except SecureXmlError:
        return None
    if root.tag.rsplit("}", 1)[-1] != "service":
        return None
    entries = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "collection" or not element.get("href"):
            continue
        title = next((child.text for child in element if child.tag.rsplit("}", 1)[-1] == "title"), None)
        href = element.get("href") or ""
        entries.append(ODataServiceEntry(name=(title or href).strip(), kind="EntitySet", url=href))
    return entries


def parse_service_document(text: str) -> Tuple[Tuple[ODataServiceEntry, ...], Optional[str]]:
    """Read an OData service document in any of its three spellings.

    Args:
        text: The response body.

    Returns:
        ``(entries, format)`` with ``format`` ``json`` or ``atom``; ``((), None)`` when the body
        is not a service document.
    """
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            entries = _json_entries(json.loads(stripped))
        except ValueError:
            entries = None
        return (tuple(entries), "json") if entries is not None else ((), None)
    if stripped.startswith("<"):
        entries = _atom_entries(stripped)
        return (tuple(entries), "atom") if entries is not None else ((), None)
    return (), None


# ===========================================================================
# Fetching
# ===========================================================================


def _get(client: httpx.Client, url: str, *, accept: str, headers: Mapping[str, str], what: str) -> str:
    """GET ``url`` and return its body, mapping failures to intake codes.

    Raises:
        ImportSourceError: ``SOURCE_NOT_FOUND`` (404), ``SOURCE_AUTH_REQUIRED`` (401/403),
            ``SOURCE_UNREACHABLE`` (network error, other status), ``INPUT_TOO_LARGE``.
    """
    try:
        response = client.get(url, headers={"User-Agent": _UA, "Accept": accept, **dict(headers)})
    except SSRFError as exc:
        raise ImportSourceError(f"The OData {what} URL is not allowed: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ImportSourceError(f"Could not reach the OData {what} at {url}: {exc}", code="SOURCE_UNREACHABLE") from exc
    if response.status_code == 404:
        raise ImportSourceError(f"The OData {what} was not found at {url} (HTTP 404).", code="SOURCE_NOT_FOUND")
    if response.status_code in (401, 403):
        raise ImportSourceError(
            f"The OData {what} at {url} needs credentials (HTTP {response.status_code}).",
            code="SOURCE_AUTH_REQUIRED",
        )
    if response.status_code >= 400:
        raise ImportSourceError(
            f"The OData {what} at {url} returned HTTP {response.status_code}.", code="SOURCE_UNREACHABLE"
        )
    if len(response.content) > MAX_DISCOVERY_BYTES:
        raise ImportSourceError(
            f"The OData {what} exceeds the {MAX_DISCOVERY_BYTES}-byte limit.", code="INPUT_TOO_LARGE"
        )
    return response.content.decode("utf-8", errors="replace")


def _auth_headers(auth_type: Optional[str], auth_payload: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Request headers for a credential-vault entry (``{}`` for none)."""
    if not auth_type or auth_type == AUTH_TYPE_NONE:
        return {}
    if auth_payload is None:
        raise ImportSourceError(f"auth_type={auth_type!r} requires a credential payload")
    try:
        return build_auth_headers(auth_type, dict(auth_payload))
    except CredentialPayloadError as exc:
        raise ImportSourceError(str(exc)) from exc


def discover_odata_service(
    url: str,
    *,
    auth_type: Optional[str] = None,
    auth_payload: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.Client] = None,
) -> ODataDiscovery:
    """Fetch a live OData service's ``$metadata`` and service document.

    Args:
        url: The service root, or its ``$metadata`` URL.
        auth_type: Credential-vault auth type (``none``/``bearer``/``header``/``oauth2``…).
        auth_payload: The decrypted credential for ``auth_type``.
        headers: Extra request headers (after the auth headers).
        client: An httpx client to inject (tests); production uses the SSRF-guarded client.

    Returns:
        The discovery result.

    Raises:
        ImportSourceError: When the URL is unsafe or not http(s), the credential is malformed, or
            the ``$metadata`` document cannot be fetched (see :func:`_get` for the codes).
    """
    service_root, metadata_url = service_urls(url)
    try:
        validate_url(metadata_url)
    except SSRFError as exc:
        raise ImportSourceError(f"The OData service URL is not allowed: {exc}") from exc
    request_headers = {**_auth_headers(auth_type, auth_payload), **dict(headers or {})}

    owns_client = client is None
    http = client if client is not None else build_guarded_client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        metadata = _get(
            http,
            metadata_url,
            accept="application/xml, application/json;q=0.9",
            headers=request_headers,
            what="$metadata document",
        )
        notes: List[str] = []
        entries: Tuple[ODataServiceEntry, ...] = ()
        document_format: Optional[str] = None
        try:
            body = _get(
                http,
                service_root + "/",
                accept="application/json, application/atomsvc+xml;q=0.9",
                headers=request_headers,
                what="service document",
            )
            entries, document_format = parse_service_document(body)
            if document_format is None:
                notes.append("The service root did not return an OData service document.")
        except ImportSourceError as exc:
            notes.append(f"Service document unavailable: {exc}")
    finally:
        if owns_client:
            http.close()
    return ODataDiscovery(
        service_url=service_root,
        metadata_url=metadata_url,
        metadata=metadata,
        service_document=entries,
        service_document_format=document_format,
        notes=tuple(notes),
    )
