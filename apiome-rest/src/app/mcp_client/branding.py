"""Server branding capture from the MCP ``initialize`` ``serverInfo`` (V2-MCP-34.2, #4656).

A modern MCP server may advertise *branding* alongside its identity in the ``initialize``
result's ``serverInfo`` object: a ``websiteUrl`` and one or more ``icons`` (each an object
with a ``src`` URL and optional ``mimeType``/``sizes``). Surfacing a logo and a site link
makes a catalog card far more recognizable than the text-only fallback.

This module is a **pure**, dependency-light validator/selector: it turns the verbatim,
untrusted advertisement carried on :class:`~app.mcp_client.handshake.ServerInfo` into a small,
storage-ready :class:`ServerBranding` — a single display icon URL (plus its MIME type, when
declared) and a website URL — that the catalog persists on the version snapshot and the cards
render. It never performs network I/O.

Safety model (the acceptance criteria's "remote assets fetched within guards or omitted"):

* **Referenced, never executed.** Branding assets are *referenced* URLs — the browser renders
  the icon as an ``<img>`` and the site as a link. Nothing here (or server-side) fetches or
  executes them.
* **HTTPS only.** Only ``https://`` URLs are accepted. Plaintext ``http://``, ``data:``
  (which could smuggle an arbitrarily large inline payload), ``file:``/``javascript:`` and any
  other scheme are dropped.
* **SSRF class excluded.** The host must not be a private / non-globally-routable IP literal —
  the same class the transport's SSRF guard blocks
  (:func:`app.mcp_client.resilience.private_address_reason`). A hostname (needing DNS to
  resolve) is *allowed*, because the URL is only ever handed to the browser as a reference, not
  fetched by the server; the literal-IP check stops the obvious ``https://10.0.0.1/logo`` abuse.
* **Bounded.** Over-long URLs are rejected, so a pathological advertisement cannot bloat the
  snapshot row.

Every guard degrades to *omission*: an unvalidatable or absent value simply yields ``None`` for
that field (and an all-``None`` branding is dropped entirely by :meth:`ServerBranding.to_row_value`),
so the card falls back to its text form rather than showing anything unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

from .handshake import ServerInfo
from .resilience import private_address_reason

__all__ = [
    "MAX_BRANDING_URL_LENGTH",
    "ServerBranding",
    "extract_server_branding",
    "safe_branding_url",
]

#: Upper bound on a persisted branding URL. Real logo/site URLs are far shorter; this simply
#: stops a pathological advertisement from bloating the immutable snapshot row. A longer URL is
#: dropped (treated as not advertised) rather than truncated.
MAX_BRANDING_URL_LENGTH = 2048


@dataclass(frozen=True)
class ServerBranding:
    """The validated, storage-ready branding for one discovery snapshot.

    Each field is independently optional: a server may advertise only a website, only an icon,
    both, or neither (or advertise values that fail validation, which are dropped to ``None``).

    Attributes:
        website_url: A validated ``https://`` website URL, or ``None``.
        icon_url: A validated ``https://`` URL for the preferred display icon, or ``None``.
        icon_mime_type: The declared MIME type of :attr:`icon_url` (e.g. ``"image/png"``) when the
            server advertised one, else ``None``. Purely descriptive — the browser sniffs the
            actual type on render — so it is never a gate on whether the icon is kept.
    """

    website_url: Optional[str] = None
    icon_url: Optional[str] = None
    icon_mime_type: Optional[str] = None

    def is_empty(self) -> bool:
        """True when no branding field survived validation (nothing to persist or render)."""
        return (
            self.website_url is None
            and self.icon_url is None
            and self.icon_mime_type is None
        )

    def to_row_value(self) -> Optional[Dict[str, Any]]:
        """Project to the ``mcp_endpoint_versions.server_branding`` JSON value, or ``None``.

        Returns a compact dict containing only the fields that are present, so an absent field
        never appears as an explicit ``null`` in storage. An all-empty branding returns ``None``
        (stored as SQL ``NULL``), which the read side and cards treat as "no branding advertised".
        """
        if self.is_empty():
            return None
        row: Dict[str, Any] = {}
        if self.website_url is not None:
            row["website_url"] = self.website_url
        if self.icon_url is not None:
            row["icon_url"] = self.icon_url
        if self.icon_mime_type is not None:
            row["icon_mime_type"] = self.icon_mime_type
        return row


def safe_branding_url(value: Any) -> Optional[str]:
    """Return ``value`` as a safe, referenceable branding URL, or ``None`` if it fails a guard.

    A value is accepted only when it is a string that parses to an absolute ``https://`` URL with
    a host, is at most :data:`MAX_BRANDING_URL_LENGTH` characters, and whose host is **not** a
    private / non-globally-routable IP literal (:func:`private_address_reason`). Every other
    input — a non-string, a relative URL, a non-``https`` scheme (``http``/``data``/``file``/…), a
    hostless or over-long URL, or a private-IP host — yields ``None``.

    Args:
        value: The untrusted advertised URL (an ``icons[].src`` or ``websiteUrl``).

    Returns:
        The URL unchanged when it clears every guard, else ``None``.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_BRANDING_URL_LENGTH:
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme.lower() != "https":
        return None
    host = parts.hostname
    if not host:
        return None
    # The host is only ever handed to the browser as a reference; a hostname is fine (we do not
    # resolve it). Reject the obvious SSRF-class literal targets (loopback / RFC 1918 / link-local
    # / reserved / …) exactly as the transport guard does.
    if private_address_reason(host) is not None:
        return None
    return candidate


def extract_server_branding(server_info: ServerInfo) -> ServerBranding:
    """Select and validate the branding a server advertised in its ``serverInfo``.

    Picks the first icon whose ``src`` clears :func:`safe_branding_url` (honouring the server's
    declared icon order as its preference) and validates the ``websiteUrl`` the same way. A field
    that is absent or fails validation is simply omitted, so the result always contains only safe,
    referenceable URLs — or is empty when the server advertised no usable branding.

    Args:
        server_info: The parsed identity from the handshake, carrying the verbatim advertised
            ``website_url`` and ``icons``.

    Returns:
        The validated :class:`ServerBranding` (possibly empty).
    """
    website_url = safe_branding_url(server_info.website_url)

    icon_url: Optional[str] = None
    icon_mime_type: Optional[str] = None
    for icon in server_info.icons:
        if not isinstance(icon, Mapping):
            continue
        candidate = safe_branding_url(icon.get("src"))
        if candidate is None:
            continue
        icon_url = candidate
        mime = icon.get("mimeType")
        icon_mime_type = mime.strip() if isinstance(mime, str) and mime.strip() else None
        break

    return ServerBranding(
        website_url=website_url,
        icon_url=icon_url,
        icon_mime_type=icon_mime_type,
    )
