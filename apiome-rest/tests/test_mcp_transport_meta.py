"""Unit tests for host & transport metadata capture (V2-MCP-34.1, #4655).

Exercises :mod:`app.mcp_client.transport_meta` in isolation: certificate summarization from the
``getpeercert()`` shape, OpenSSL datetime parsing, the notable-header allow-list, and end-to-end
capture from an :class:`httpx.Response` whose ``network_stream`` extension carries a fake TLS
session. The acceptance-criterion edges — a plain-``http`` endpoint, a missing/empty peer
certificate, and a wholly absent network stream — must degrade to empty fields, never raise.
"""

import httpx

from app.mcp_client.transport_meta import (
    NOTABLE_RESPONSE_HEADERS,
    TlsCertificateSummary,
    TransportMetadata,
    capture_transport_metadata,
    summarize_peer_cert,
)

# A representative validated-certificate dict, in the exact nested-tuple shape
# ``ssl.SSLObject.getpeercert()`` returns.
_PEER_CERT = {
    "subject": ((("commonName", "mcp.example.com"),),),
    "issuer": (
        (("countryName", "US"),),
        (("organizationName", "Let's Encrypt"),),
        (("commonName", "R3"),),
    ),
    "version": 3,
    "serialNumber": "03AB9F",
    "notBefore": "Jun  1 00:00:00 2026 GMT",
    "notAfter": "Aug 30 23:59:59 2026 GMT",
    "subjectAltName": (
        ("DNS", "mcp.example.com"),
        ("DNS", "www.mcp.example.com"),
        ("IP Address", "203.0.113.1"),
    ),
}


class _FakeSslObject:
    """Minimal stand-in for ``ssl.SSLObject`` exposing the introspection we read."""

    def __init__(self, cert=_PEER_CERT, protocol="TLSv1.3", cipher=("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)):
        self._cert = cert
        self._protocol = protocol
        self._cipher = cipher

    def getpeercert(self, binary_form=False):
        return self._cert

    def version(self):
        return self._protocol

    def cipher(self):
        return self._cipher


class _FakeNetworkStream:
    """Stand-in for httpx's network stream extension."""

    def __init__(self, ssl_object):
        self._ssl_object = ssl_object

    def get_extra_info(self, name):
        return self._ssl_object if name == "ssl_object" else None


def _https_response(headers=None, ssl_object=None) -> httpx.Response:
    return httpx.Response(
        200,
        headers=headers or {},
        extensions={"network_stream": _FakeNetworkStream(ssl_object)},
    )


# ===========================================================================
# Certificate summarization
# ===========================================================================


def test_summarize_peer_cert_extracts_identity_and_validity():
    summary = summarize_peer_cert(_PEER_CERT)
    assert isinstance(summary, TlsCertificateSummary)
    assert summary.subject_common_name == "mcp.example.com"
    # Issuer label prefers the Organization; its CN is kept separately.
    assert summary.issuer == "Let's Encrypt"
    assert summary.issuer_common_name == "R3"
    assert summary.serial_number == "03AB9F"
    assert summary.version == 3
    # Only DNS SANs are kept (the IP entry is dropped), in certificate order.
    assert summary.subject_alt_names == ("mcp.example.com", "www.mcp.example.com")


def test_summarize_peer_cert_parses_openssl_datetimes_to_iso_utc():
    summary = summarize_peer_cert(_PEER_CERT)
    # The padded single-digit day ("Jun  1") parses, and the result is ISO-8601 UTC.
    assert summary.not_before == "2026-06-01T00:00:00+00:00"
    assert summary.not_after == "2026-08-30T23:59:59+00:00"


def test_summarize_peer_cert_returns_none_for_empty_or_missing():
    # No certificate ({} when the peer sent none, None when verification disabled) is not an error.
    assert summarize_peer_cert({}) is None
    assert summarize_peer_cert(None) is None


def test_summarize_peer_cert_tolerates_unparseable_dates():
    cert = {"subject": ((("commonName", "x"),),), "notBefore": "not-a-date"}
    summary = summarize_peer_cert(cert)
    assert summary is not None
    assert summary.not_before is None
    assert summary.subject_common_name == "x"


def test_summarize_peer_cert_handles_issuer_with_only_common_name():
    cert = {"issuer": ((("commonName", "Internal CA"),),)}
    summary = summarize_peer_cert(cert)
    # With no Organization, the issuer label falls back to the CN.
    assert summary.issuer == "Internal CA"
    assert summary.issuer_common_name == "Internal CA"


# ===========================================================================
# Full capture from a response
# ===========================================================================


def test_capture_https_records_host_tls_and_certificate():
    resp = _https_response(
        headers={"Server": "nginx", "Set-Cookie": "s=1", "X-RateLimit-Remaining": "42"},
        ssl_object=_FakeSslObject(),
    )
    meta = capture_transport_metadata("https://mcp.example.com/mcp", resp, connect_seconds=0.025)
    assert isinstance(meta, TransportMetadata)
    assert meta.host == "mcp.example.com"
    assert meta.port == 443
    assert meta.scheme == "https"
    assert meta.tls is True
    assert meta.tls_protocol == "TLSv1.3"
    assert meta.tls_cipher == "TLS_AES_256_GCM_SHA384"
    assert meta.certificate is not None
    assert meta.certificate.subject_common_name == "mcp.example.com"
    # Timing is surfaced in milliseconds.
    assert meta.connect_ms == 25.0


def test_capture_projects_only_notable_headers():
    resp = _https_response(
        headers={
            "Server": "nginx",
            "Retry-After": "30",
            "Set-Cookie": "secret=1",
            "Content-Type": "application/json",
            "WWW-Authenticate": "Bearer",
        },
        ssl_object=_FakeSslObject(),
    )
    meta = capture_transport_metadata("https://mcp.example.com/mcp", resp)
    assert meta.response_headers == {"server": "nginx", "retry-after": "30"}
    # Every stored key is on the allow-list.
    assert set(meta.response_headers).issubset(set(NOTABLE_RESPONSE_HEADERS))


def test_capture_http_endpoint_has_no_tls_or_certificate():
    resp = httpx.Response(200, headers={"Server": "dev"})
    meta = capture_transport_metadata("http://localhost:9000/mcp", resp, connect_seconds=0.001)
    assert meta.scheme == "http"
    assert meta.tls is False
    assert meta.port == 9000
    assert meta.certificate is None
    assert meta.tls_protocol is None


def test_capture_tolerates_missing_network_stream():
    # A mocked transport (httpx.MockTransport) yields no network stream: TLS fields stay empty,
    # host/header capture still works, and nothing raises.
    resp = httpx.Response(200, headers={"Server": "mock"})
    meta = capture_transport_metadata("https://mcp.example.com/mcp", resp)
    assert meta.tls is True  # scheme says https…
    assert meta.certificate is None  # …but no cert could be read
    assert meta.response_headers == {"server": "mock"}


def test_capture_tolerates_ssl_object_without_certificate():
    # TLS session present but the peer cert is empty (verification disabled upstream) → no summary,
    # but protocol/cipher still recorded.
    resp = _https_response(headers={"Server": "nginx"}, ssl_object=_FakeSslObject(cert={}))
    meta = capture_transport_metadata("https://mcp.example.com/mcp", resp)
    assert meta.certificate is None
    assert meta.tls_protocol == "TLSv1.3"


def test_capture_without_timing_omits_connect_ms():
    resp = _https_response(ssl_object=_FakeSslObject())
    meta = capture_transport_metadata("https://mcp.example.com/mcp", resp)
    assert meta.connect_ms is None


def test_to_dict_is_json_ready_and_round_trips_fields():
    resp = _https_response(headers={"Server": "nginx"}, ssl_object=_FakeSslObject())
    doc = capture_transport_metadata(
        "https://mcp.example.com/mcp", resp, connect_seconds=0.01
    ).to_dict()
    assert doc["host"] == "mcp.example.com"
    assert doc["tls"] is True
    assert doc["certificate"]["issuer"] == "Let's Encrypt"
    assert doc["certificate"]["subject_alt_names"] == ["mcp.example.com", "www.mcp.example.com"]
    assert doc["connect_ms"] == 10.0
