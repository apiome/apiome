"""Tests for OData live discovery — MFI-11.3 (#3778).

A live service is stood in for by an :class:`httpx.MockTransport` serving the corpus metadata
(``apiome-ui/examples/odata/06-trippin-reference.edmx`` for v4, the SAP Gateway v2 example for
AtomPub) and a service document in each of its three spellings.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Dict, List

import httpx
import pytest

from app import ssrf_guard
from app.import_source import ImportSourceError
from app.odata_csdl_json import csdl_xml_to_json
from app.odata_discovery import (
    MAX_DISCOVERY_BYTES,
    discover_odata_service,
    parse_service_document,
    service_urls,
)
from app.odata_import_source import ODataImportSource

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_TRIPPIN = (_EXAMPLES / "odata" / "06-trippin-reference.edmx").read_text(encoding="utf-8")
_SAP = (_EXAMPLES / "odata-v2" / "05-real-world-sap-gateway-service.xml").read_text(encoding="utf-8")

_V4_SERVICE_DOCUMENT = json.dumps(
    {
        "@odata.context": "https://api.example.com/trippin/$metadata",
        "value": [
            {"name": "People", "kind": "EntitySet", "url": "People"},
            {"name": "Airlines", "kind": "EntitySet", "url": "Airlines"},
            {"name": "Me", "kind": "Singleton", "url": "Me"},
        ],
    }
)
_V2_JSON_SERVICE_DOCUMENT = json.dumps({"d": {"EntitySets": ["BusinessPartnerSet", "SalesOrderSet"]}})
_ATOM_SERVICE_DOCUMENT = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<app:service xmlns:app="http://www.w3.org/2007/app" xmlns:atom="http://www.w3.org/2005/Atom">'
    "<app:workspace><atom:title>Default</atom:title>"
    '<app:collection href="BusinessPartnerSet"><atom:title>BusinessPartnerSet</atom:title></app:collection>'
    '<app:collection href="SalesOrderSet"><atom:title>SalesOrderSet</atom:title></app:collection>'
    '<app:collection href="SalesOrderLineItemSet"><atom:title>SalesOrderLineItemSet</atom:title></app:collection>'
    "</app:workspace></app:service>"
)


_PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve host names to a public address (the sandbox has no DNS); IP literals and
    ``localhost`` keep their private addresses so the SSRF guard still sees them."""

    def resolve(host: str) -> List[str]:
        if host == "localhost":
            return ["127.0.0.1"]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [_PUBLIC_IP]
        return [host]

    monkeypatch.setattr(ssrf_guard, "_resolve_host_ips", resolve)


def _service(routes: Dict[str, httpx.Response], seen: List[httpx.Request]) -> httpx.Client:
    """A client whose transport answers ``path → response`` and records each request."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return routes.get(request.url.path, httpx.Response(404))

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(text: str, content_type: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"Content-Type": content_type})


# ===========================================================================
# URLs and service documents
# ===========================================================================


@pytest.mark.parametrize(
    "url, root, metadata",
    [
        ("https://h/svc", "https://h/svc", "https://h/svc/$metadata"),
        ("https://h/svc/", "https://h/svc", "https://h/svc/$metadata"),
        ("https://h/svc/$metadata", "https://h/svc", "https://h/svc/$metadata"),
        (
            "https://h/sap/opu/odata/sap/ZBP_SRV/?sap-client=100",
            "https://h/sap/opu/odata/sap/ZBP_SRV?sap-client=100",
            "https://h/sap/opu/odata/sap/ZBP_SRV/$metadata?sap-client=100",
        ),
    ],
)
def test_service_urls(url: str, root: str, metadata: str):
    assert service_urls(url) == (root, metadata)


@pytest.mark.parametrize("url", ["ftp://h/svc", "not a url", "file:///etc/passwd"])
def test_service_urls_need_http(url: str):
    with pytest.raises(ImportSourceError):
        service_urls(url)


def test_parse_the_three_service_document_spellings():
    entries, fmt = parse_service_document(_V4_SERVICE_DOCUMENT)
    assert fmt == "json"
    assert [(e.name, e.kind, e.url) for e in entries] == [
        ("People", "EntitySet", "People"),
        ("Airlines", "EntitySet", "Airlines"),
        ("Me", "Singleton", "Me"),
    ]
    entries, fmt = parse_service_document(_V2_JSON_SERVICE_DOCUMENT)
    assert (fmt, [e.name for e in entries]) == ("json", ["BusinessPartnerSet", "SalesOrderSet"])
    entries, fmt = parse_service_document(_ATOM_SERVICE_DOCUMENT)
    assert fmt == "atom"
    assert [e.name for e in entries] == ["BusinessPartnerSet", "SalesOrderSet", "SalesOrderLineItemSet"]


@pytest.mark.parametrize("text", ['{"openapi": "3.1.0"}', "<html><body>Hi</body></html>", "plain", "{broken"])
def test_anything_else_is_not_a_service_document(text: str):
    assert parse_service_document(text) == ((), None)


# ===========================================================================
# Fetching
# ===========================================================================


def test_discovery_fetches_metadata_and_the_service_document():
    seen: List[httpx.Request] = []
    client = _service(
        {
            "/trippin/$metadata": _ok(_TRIPPIN, "application/xml"),
            "/trippin/": _ok(_V4_SERVICE_DOCUMENT, "application/json"),
        },
        seen,
    )
    discovery = discover_odata_service(
        "https://api.example.com/trippin", auth_type="bearer", auth_payload={"token": "t0k"}, client=client
    )
    assert discovery.service_url == "https://api.example.com/trippin"
    assert discovery.metadata_url == "https://api.example.com/trippin/$metadata"
    assert discovery.metadata == _TRIPPIN
    assert discovery.service_document_format == "json"
    assert [e.name for e in discovery.service_document] == ["People", "Airlines", "Me"]
    assert discovery.notes == ()
    assert [r.url.path for r in seen] == ["/trippin/$metadata", "/trippin/"]
    assert all(r.headers["Authorization"] == "Bearer t0k" for r in seen)
    assert seen[0].headers["Accept"].startswith("application/xml")


def test_a_missing_service_document_is_noted_not_fatal():
    client = _service({"/svc/$metadata": _ok(_TRIPPIN, "application/xml")}, [])
    discovery = discover_odata_service("https://api.example.com/svc", client=client)
    assert discovery.service_document == ()
    assert discovery.service_document_format is None
    assert discovery.notes and "Service document unavailable" in discovery.notes[0]


def test_a_root_that_is_not_a_service_document_is_noted():
    client = _service(
        {"/svc/$metadata": _ok(_TRIPPIN, "application/xml"), "/svc/": _ok("<html></html>", "text/html")}, []
    )
    discovery = discover_odata_service("https://api.example.com/svc", client=client)
    assert discovery.notes == ("The service root did not return an OData service document.",)


@pytest.mark.parametrize(
    "status, code",
    [
        (404, "SOURCE_NOT_FOUND"),
        (401, "SOURCE_AUTH_REQUIRED"),
        (403, "SOURCE_AUTH_REQUIRED"),
        (503, "SOURCE_UNREACHABLE"),
    ],
)
def test_metadata_failures_map_to_intake_codes(status: int, code: str):
    client = _service({"/svc/$metadata": httpx.Response(status)}, [])
    with pytest.raises(ImportSourceError) as exc:
        discover_odata_service("https://api.example.com/svc", client=client)
    assert exc.value.code == code


def test_a_network_failure_is_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ImportSourceError) as exc:
        discover_odata_service("https://api.example.com/svc", client=client)
    assert exc.value.code == "SOURCE_UNREACHABLE"


def test_an_oversized_metadata_document_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.odata_discovery.MAX_DISCOVERY_BYTES", 100)
    client = _service({"/svc/$metadata": _ok(_TRIPPIN, "application/xml")}, [])
    with pytest.raises(ImportSourceError) as exc:
        discover_odata_service("https://api.example.com/svc", client=client)
    assert exc.value.code == "INPUT_TOO_LARGE"
    assert MAX_DISCOVERY_BYTES == 16 * 1024 * 1024


@pytest.mark.parametrize("url", ["http://127.0.0.1/svc", "http://169.254.169.254/latest", "http://localhost/svc"])
def test_private_targets_are_refused_before_any_request(url: str):
    seen: List[httpx.Request] = []
    with pytest.raises(ImportSourceError, match="not allowed"):
        discover_odata_service(url, client=_service({}, seen))
    assert seen == []


def test_a_malformed_credential_is_refused():
    with pytest.raises(ImportSourceError):
        discover_odata_service(
            "https://api.example.com/svc", auth_type="bearer", auth_payload=None, client=_service({}, [])
        )


# ===========================================================================
# The adapter
# ===========================================================================


def _discover(routes: Dict[str, httpx.Response], url: str = "https://api.example.com/svc"):
    source = ODataImportSource()
    return source, source.discover(url, client=_service(routes, []))


def test_the_adapter_declares_live_discovery():
    descriptor = ODataImportSource.descriptor()
    assert descriptor.supports_live_discovery is True
    assert "discovery" in [kind.value if hasattr(kind, "value") else kind for kind in descriptor.input_kinds]


def test_a_discovered_v4_service_imports_with_its_service_document():
    source, document = _discover(
        {"/svc/$metadata": _ok(_TRIPPIN, "application/xml"), "/svc/": _ok(_V4_SERVICE_DOCUMENT, "application/json")}
    )
    api = source.normalize(document)
    assert api.extras["odata_service_url"] == "https://api.example.com/svc"
    assert [e["name"] for e in api.extras["odata_service_document"]] == ["People", "Airlines", "Me"]
    # Airports is declared in $metadata but the service document does not list it.
    assert api.extras["odata_unlisted_entity_sets"] == ["Airports"]
    assert api.extras["odata_csdl_valid"] is True
    assert "odata_discovery_notes" not in api.extras


def test_a_discovered_sap_v2_service_reads_its_atom_service_document():
    source, document = _discover(
        {
            "/sap/opu/odata/sap/ZBP_SRV/$metadata": _ok(_SAP, "application/xml"),
            "/sap/opu/odata/sap/ZBP_SRV/": _ok(_ATOM_SERVICE_DOCUMENT, "application/atomsvc+xml"),
        },
        url="https://sap.example.com/sap/opu/odata/sap/ZBP_SRV/$metadata",
    )
    api = source.normalize(document)
    assert api.extras["odata_service_url"] == "https://sap.example.com/sap/opu/odata/sap/ZBP_SRV"
    assert len(api.extras["odata_service_document"]) == 3
    assert "odata_unlisted_entity_sets" not in api.extras
    assert api.version == "2.0"


def test_a_discovered_service_without_a_service_document_still_imports():
    source, document = _discover({"/svc/$metadata": _ok(_TRIPPIN, "application/xml")})
    api = source.normalize(document)
    assert api.extras["odata_service_document"] == []
    assert api.extras["odata_discovery_notes"]
    assert "odata_unlisted_entity_sets" not in api.extras


def test_csdl_json_metadata_is_discovered_too():
    csdl = json.dumps(csdl_xml_to_json(_TRIPPIN))
    source, document = _discover({"/svc/$metadata": _ok(csdl, "application/json")})
    assert document.csdl_json is not None
    assert source.normalize(document).extras["odata_csdl_valid"] is True


def test_an_uploaded_document_records_no_discovery():
    source = ODataImportSource()
    api = source.normalize(source.parse(_TRIPPIN))
    assert not any(key.startswith("odata_service") for key in api.extras)


def test_unparseable_metadata_is_refused():
    with pytest.raises(ImportSourceError):
        _discover({"/svc/$metadata": _ok("<html>not metadata</html>", "text/html")})
