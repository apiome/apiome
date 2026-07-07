"""Host & transport metadata capture during MCP discovery (V2-MCP-34.1, #4655).

The discovery handshake (:mod:`app.mcp_client.transport_http` → ``initialize``) already opens
one connection to the server. This module extracts the *non-invasive transport facts* that
connection reveals — nothing beyond what the existing exchange already carries, so it adds **no
extra network calls**:

* **Host** — the hostname/authority and port the endpoint lives on, and whether the connection
  is TLS (``https``) at all.
* **TLS certificate summary** — for an HTTPS endpoint, the leaf certificate's issuer, validity
  window (``notBefore``/``notAfter``), subject, and Subject Alternative Names, taken from the
  already-negotiated TLS session (:meth:`ssl.SSLObject.getpeercert`). The TLS *protocol* and
  *cipher* are recorded too when the runtime exposes them.
* **Notable HTTP response headers** — a small allow-list (server banner, rate-limit hints, HSTS,
  ``Via``/``X-Powered-By``) rather than the whole header set, so we keep the operationally useful
  facts without hoarding volatile or sensitive values.
* **Connect/handshake timing** — how long the first request (TCP connect + TLS handshake + request
  + response headers) took, a coarse responsiveness signal.

Everything here is **best-effort and defensive**: a missing certificate (a plain-``http`` endpoint,
or a runtime that does not surface the peer cert), an unparseable validity date, or a wholly absent
network stream must never raise. The acceptance criterion is explicit — *missing/invalid cert
handled and reported, not fatal to discovery* — so extraction degrades to ``None`` fields rather
than failing the run. The caller (:mod:`app.mcp_discovery_engine`) persists the resulting document
on the endpoint (``mcp_endpoints.transport_metadata``) as the latest observation.

This module is deliberately free of any dependency on the transport/handshake layers (it takes a
plain :class:`httpx.Response`), so it can be unit-tested in isolation and imported without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

# The response headers worth keeping. Deliberately a *small allow-list* rather than the whole set:
# these are the operationally meaningful, non-sensitive facts the identity card / report want (who
# serves this, does it advertise rate limits, does it enforce HTTPS). Everything else — cookies,
# auth challenges, tracing ids, content negotiation — is excluded. Matched case-insensitively.
NOTABLE_RESPONSE_HEADERS: Tuple[str, ...] = (
    "server",
    "via",
    "x-powered-by",
    "strict-transport-security",
    "retry-after",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)

# OpenSSL renders certificate timestamps like ``"Jun  1 00:00:00 2026 GMT"`` (note the padding space
# before a single-digit day). We normalize the whitespace and parse without the zone suffix, then
# stamp UTC — ``getpeercert`` only ever emits GMT/UTC for these fields.
_CERT_DATETIME_FORMAT = "%b %d %H:%M:%S %Y"


# ===========================================================================
# Value objects
# ===========================================================================


@dataclass(frozen=True)
class TlsCertificateSummary:
    """A compact summary of a server's TLS leaf certificate.

    Every field is optional: a certificate may omit a SAN, and a runtime may surface only part of
    the certificate (or none of it). The summary is derived from :meth:`ssl.SSLObject.getpeercert`,
    whose parsed form is only available when the peer certificate validated against the trust store.

    Attributes:
        subject_common_name: The leaf certificate subject's Common Name (``CN``), if present.
        issuer: A human-readable issuer label (the issuer's Organization, falling back to its CN).
        issuer_common_name: The issuer's Common Name, if present.
        not_before: Start of the validity window, ISO-8601 UTC (``None`` if unparseable/absent).
        not_after: End of the validity window, ISO-8601 UTC (``None`` if unparseable/absent).
        subject_alt_names: The DNS Subject Alternative Names, in certificate order.
        serial_number: The certificate serial number as a hex string, if present.
        version: The X.509 version integer, if present.
    """

    subject_common_name: Optional[str] = None
    issuer: Optional[str] = None
    issuer_common_name: Optional[str] = None
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    subject_alt_names: Tuple[str, ...] = ()
    serial_number: Optional[str] = None
    version: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Render the summary as a JSON-ready dict (for the ``transport_metadata`` document)."""
        return {
            "subject_common_name": self.subject_common_name,
            "issuer": self.issuer,
            "issuer_common_name": self.issuer_common_name,
            "not_before": self.not_before,
            "not_after": self.not_after,
            "subject_alt_names": list(self.subject_alt_names),
            "serial_number": self.serial_number,
            "version": self.version,
        }


@dataclass(frozen=True)
class TransportMetadata:
    """Non-invasive host/transport facts captured from one discovery handshake.

    Attributes:
        host: The endpoint hostname/authority, if parseable from the URL.
        port: The connection port (explicit, or the scheme default), if known.
        scheme: The URL scheme (``https``/``http``), lowercased.
        tls: Whether the connection used TLS (``https``).
        tls_protocol: Negotiated TLS protocol version (e.g. ``TLSv1.3``), when exposed.
        tls_cipher: Negotiated cipher suite name, when exposed.
        certificate: The :class:`TlsCertificateSummary`, or ``None`` for non-TLS / no peer cert.
        response_headers: The allow-listed notable response headers (lowercased keys).
        connect_ms: Wall-clock milliseconds for the observed request (connect + TLS + first
            response headers); ``None`` if not measured.
    """

    host: Optional[str] = None
    port: Optional[int] = None
    scheme: Optional[str] = None
    tls: bool = False
    tls_protocol: Optional[str] = None
    tls_cipher: Optional[str] = None
    certificate: Optional[TlsCertificateSummary] = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    connect_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Render the observation as the JSON document stored in ``mcp_endpoints.transport_metadata``."""
        return {
            "host": self.host,
            "port": self.port,
            "scheme": self.scheme,
            "tls": self.tls,
            "tls_protocol": self.tls_protocol,
            "tls_cipher": self.tls_cipher,
            "certificate": self.certificate.to_dict() if self.certificate is not None else None,
            "response_headers": dict(self.response_headers),
            "connect_ms": self.connect_ms,
        }


# ===========================================================================
# Capture
# ===========================================================================


def capture_transport_metadata(
    url: str,
    response: httpx.Response,
    *,
    connect_seconds: Optional[float] = None,
) -> TransportMetadata:
    """Extract host/TLS/header/timing facts from one (still-open) handshake response.

    Reuses the connection the ``initialize`` request already opened — it makes **no** further
    network calls. The TLS session and peer certificate are read from the response's
    ``network_stream`` extension, which httpx populates while a streamed response is open; when that
    extension is absent (a mocked transport, or a plain-``http`` endpoint) the TLS fields are simply
    left empty. Header and host extraction never depend on TLS.

    Args:
        url: The endpoint URL the request was sent to (source of host/port/scheme).
        response: The open :class:`httpx.Response` from the first handshake request.
        connect_seconds: Measured wall-clock seconds for the request (connect + TLS + response
            headers); converted to milliseconds on :attr:`TransportMetadata.connect_ms`.

    Returns:
        The :class:`TransportMetadata` observation. Never raises: any extraction failure degrades
        the affected fields to ``None``/empty rather than aborting discovery.
    """
    scheme, host, port = _split_authority(url)
    tls = scheme == "https"

    tls_protocol, tls_cipher, certificate = _extract_tls(response)

    return TransportMetadata(
        host=host,
        port=port,
        scheme=scheme,
        tls=tls,
        tls_protocol=tls_protocol,
        tls_cipher=tls_cipher,
        certificate=certificate,
        response_headers=_notable_headers(response.headers),
        connect_ms=round(connect_seconds * 1000.0, 3) if connect_seconds is not None else None,
    )


def summarize_peer_cert(cert: Any) -> Optional[TlsCertificateSummary]:
    """Summarize a parsed peer certificate (the dict :meth:`ssl.SSLObject.getpeercert` returns).

    ``getpeercert()`` returns a dict of nested tuples for a validated certificate, ``{}`` when the
    peer sent no certificate, or ``None`` when validation was disabled. Only a non-empty mapping
    yields a summary; anything else returns ``None`` (a missing certificate, reported as absent,
    is not an error per the acceptance criteria).

    Args:
        cert: The value returned by ``getpeercert()`` (a mapping, ``{}``, or ``None``).

    Returns:
        A :class:`TlsCertificateSummary`, or ``None`` when no certificate detail is available.
    """
    if not isinstance(cert, dict) or not cert:
        return None

    version = cert.get("version")
    return TlsCertificateSummary(
        subject_common_name=_rdn_value(cert.get("subject"), "commonName"),
        issuer=_issuer_label(cert.get("issuer")),
        issuer_common_name=_rdn_value(cert.get("issuer"), "commonName"),
        not_before=_iso_cert_datetime(cert.get("notBefore")),
        not_after=_iso_cert_datetime(cert.get("notAfter")),
        subject_alt_names=_subject_alt_names(cert.get("subjectAltName")),
        serial_number=_optional_str(cert.get("serialNumber")),
        version=version if isinstance(version, int) else None,
    )


# ===========================================================================
# Helpers
# ===========================================================================


def _extract_tls(
    response: httpx.Response,
) -> Tuple[Optional[str], Optional[str], Optional[TlsCertificateSummary]]:
    """Read (tls_protocol, tls_cipher, certificate) from the response's network stream.

    All three are best-effort: a mocked transport or a plain-``http`` connection has no SSL object,
    so this returns ``(None, None, None)`` rather than raising.
    """
    ssl_object = _ssl_object(response)
    if ssl_object is None:
        return None, None, None

    protocol = _safe_call(ssl_object, "version")
    cipher_info = _safe_call(ssl_object, "cipher")
    cipher = cipher_info[0] if isinstance(cipher_info, (tuple, list)) and cipher_info else None

    certificate: Optional[TlsCertificateSummary] = None
    try:
        certificate = summarize_peer_cert(ssl_object.getpeercert())
    except Exception:  # noqa: BLE001 - a peer-cert read must never break discovery
        certificate = None

    return _optional_str(protocol), _optional_str(cipher), certificate


def _ssl_object(response: httpx.Response) -> Any:
    """Return the ``ssl.SSLObject`` behind the response, or ``None`` when unavailable.

    httpx exposes the live connection via the ``network_stream`` extension while a streamed
    response is open; ``get_extra_info("ssl_object")`` yields the TLS session for an HTTPS
    connection (and ``None`` for plaintext or a mocked transport).
    """
    try:
        network_stream = response.extensions.get("network_stream")
        if network_stream is None:
            return None
        return network_stream.get_extra_info("ssl_object")
    except Exception:  # noqa: BLE001 - extension shape varies across httpx transports
        return None


def _safe_call(obj: Any, method_name: str) -> Any:
    """Call ``obj.method_name()`` defensively, returning ``None`` on any failure/absence."""
    method = getattr(obj, method_name, None)
    if method is None:
        return None
    try:
        return method()
    except Exception:  # noqa: BLE001 - TLS introspection is strictly best-effort
        return None


def _notable_headers(headers: httpx.Headers) -> Dict[str, str]:
    """Project the response headers onto the :data:`NOTABLE_RESPONSE_HEADERS` allow-list.

    Keys are matched case-insensitively (``httpx.Headers`` already does this) and stored lowercased
    so the persisted document is stable regardless of the server's header casing. Absent headers
    are omitted rather than stored as ``None``.
    """
    result: Dict[str, str] = {}
    for name in NOTABLE_RESPONSE_HEADERS:
        value = headers.get(name)
        if value is not None:
            result[name] = value
    return result


def _split_authority(url: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Return ``(scheme, host, port)`` from a URL, defaulting the port to the scheme's standard."""
    try:
        parsed = httpx.URL(url)
    except Exception:  # noqa: BLE001 - a malformed URL should not break capture
        return None, None, None
    scheme = (parsed.scheme or "").lower() or None
    host = parsed.host or None
    port = parsed.port
    if port is None and scheme in ("https", "http"):
        port = 443 if scheme == "https" else 80
    return scheme, host, port


def _iso_cert_datetime(value: Any) -> Optional[str]:
    """Parse an OpenSSL certificate timestamp into an ISO-8601 UTC string (``None`` on failure).

    Accepts the ``getpeercert`` textual form (``"Jun  1 00:00:00 2026 GMT"``). The extra padding
    space before a single-digit day is normalized away before parsing, and the trailing zone token
    (always GMT/UTC for these fields) is dropped; the result is stamped UTC-aware.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    tokens = value.split()
    # Drop a trailing zone token (e.g. "GMT"); the remaining tokens are the datetime.
    if tokens and tokens[-1].isalpha():
        tokens = tokens[:-1]
    normalized = " ".join(tokens)
    try:
        parsed = datetime.strptime(normalized, _CERT_DATETIME_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def _subject_alt_names(san: Any) -> Tuple[str, ...]:
    """Return the DNS Subject Alternative Names from a ``getpeercert`` ``subjectAltName`` tuple.

    The value is a tuple of ``(type, value)`` pairs (e.g. ``("DNS", "example.com")``); only the
    ``DNS`` entries are kept, in certificate order. A non-tuple / absent value yields ``()``.
    """
    if not isinstance(san, (tuple, list)):
        return ()
    names = [
        str(entry[1])
        for entry in san
        if isinstance(entry, (tuple, list))
        and len(entry) == 2
        and str(entry[0]).lower() == "dns"
        and entry[1]
    ]
    return tuple(names)


def _issuer_label(issuer: Any) -> Optional[str]:
    """Derive a human-readable issuer label: its Organization, falling back to its Common Name."""
    return _rdn_value(issuer, "organizationName") or _rdn_value(issuer, "commonName")


def _rdn_value(rdn_sequence: Any, attribute: str) -> Optional[str]:
    """Pull one attribute (e.g. ``commonName``) out of a ``getpeercert`` name structure.

    ``subject``/``issuer`` are sequences of Relative Distinguished Names, each itself a sequence of
    ``(attr, value)`` pairs — e.g. ``((("commonName", "example.com"),),)``. This walks that nesting
    and returns the first value whose attribute matches, or ``None``.
    """
    if not isinstance(rdn_sequence, (tuple, list)):
        return None
    for rdn in rdn_sequence:
        if not isinstance(rdn, (tuple, list)):
            continue
        for pair in rdn:
            if (
                isinstance(pair, (tuple, list))
                and len(pair) == 2
                and pair[0] == attribute
                and pair[1]
            ):
                return str(pair[1])
    return None


def _optional_str(value: Any) -> Optional[str]:
    """Return ``value`` as a string when it is a non-empty string, else ``None``."""
    return value if isinstance(value, str) and value != "" else None
