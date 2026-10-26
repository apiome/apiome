"""OData service discovery for ``apiome import odata --discover`` (MFI-11.3, #3778).

An OData service publishes its model at ``<service root>/$metadata``. :func:`odata_metadata_url`
turns a service root (or its ``$metadata`` URL) into that URL; the document is then imported
through the ordinary registry-dispatch import, so the server parses, validates, normalizes,
versions and lints it exactly as it would a ``--url`` import. The rules mirror the REST adapter's
live discovery (``app.odata_discovery.service_urls``).
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_METADATA = "$metadata"


def odata_metadata_url(service_url: str) -> str:
    """Return the ``$metadata`` URL to import for an OData service.

    Args:
        service_url: The service root (``https://host/odata/trippin/``) or its ``$metadata`` URL.
            A query string (SAP's ``sap-client=100``) is kept.

    Returns:
        ``<service root>/$metadata`` with the query string.

    Raises:
        ValueError: When the URL is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (service_url or "").strip()
    if not cleaned:
        raise ValueError("OData service URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("OData service URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("OData service URL has no host")
    path = parts.path.rstrip("/")
    if path.endswith("/" + _METADATA) or path == _METADATA:
        path = path[: -len(_METADATA)].rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc, f"{path}/{_METADATA}", parts.query, ""))
