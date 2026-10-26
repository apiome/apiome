"""Tests for WSDL live fetch — MFI-13.3 (#3790).

A WCF-style service is stood in for by an :class:`httpx.MockTransport` serving
``tests/fixtures/wsdl_fetch``: ``service.wsdl`` (``?wsdl``) imports ``wsdl0.wsdl``
(``?wsdl=wsdl0``), which imports ``xsd0.xsd`` (``?xsd=xsd0``), which includes ``xsd1.xsd``
(``?xsd=xsd1``) by a relative location; ``single.wsdl`` (``?singleWsdl``) is the same service
already inlined.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Dict, List

import httpx
import pytest

from app import ssrf_guard
from app.import_source import ImportSourceError
from app.wsdl_fetch import (
    MAX_REFERENCED_DOCUMENTS,
    candidate_urls,
    fetch_wsdl_service,
    referenced_locations,
)
from app.wsdl_import_source import WsdlImportSource

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wsdl_fetch"
_BASE = "https://svc.example.com/Calc.svc"
_PUBLIC_IP = "93.184.216.34"


def _text(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


_ROUTES = {
    "singleWsdl": "single.wsdl",
    "wsdl": "service.wsdl",
    "wsdl=wsdl0": "wsdl0.wsdl",
    "xsd=xsd0": "xsd0.xsd",
    "xsd=xsd1": "xsd1.xsd",
}


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


def _service(
    routes: Dict[str, str], seen: List[httpx.Request], *, status: Dict[str, int] | None = None
) -> httpx.Client:
    """A client answering ``/Calc.svc?<query>`` from ``routes`` (query → fixture file)."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        query = request.url.query.decode() if isinstance(request.url.query, bytes) else request.url.query
        if status and query in status:
            return httpx.Response(status[query])
        if request.url.path == "/Calc.svc" and query in routes:
            return httpx.Response(200, text=_text(routes[query]), headers={"Content-Type": "text/xml"})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ===========================================================================
# URLs and references
# ===========================================================================


@pytest.mark.parametrize(
    "url, expected",
    [
        (_BASE, [f"{_BASE}?singleWsdl", f"{_BASE}?wsdl"]),
        (f"{_BASE}?wsdl", [f"{_BASE}?singleWsdl", f"{_BASE}?wsdl"]),
        (f"{_BASE}?WSDL", [f"{_BASE}?singleWsdl", f"{_BASE}?wsdl"]),
        (f"{_BASE}?singleWsdl", [f"{_BASE}?singleWsdl"]),
        ("https://h/files/service.wsdl", ["https://h/files/service.wsdl"]),
        ("https://h/ws?tenant=a&wsdl", ["https://h/ws?tenant=a&singleWsdl", "https://h/ws?tenant=a&wsdl"]),
    ],
)
def test_candidate_urls_prefer_single_wsdl(url: str, expected: List[str]):
    assert candidate_urls(url) == expected


@pytest.mark.parametrize("url", ["ftp://h/svc", "file:///etc/x.wsdl", "nonsense"])
def test_candidate_urls_need_http(url: str):
    with pytest.raises(ImportSourceError):
        candidate_urls(url)


def test_referenced_locations():
    assert referenced_locations(_text("service.wsdl")) == ["https://svc.example.com/Calc.svc?wsdl=wsdl0"]
    assert referenced_locations(_text("wsdl0.wsdl")) == ["https://svc.example.com/Calc.svc?xsd=xsd0"]
    assert referenced_locations(_text("xsd0.xsd")) == ["Calc.svc?xsd=xsd1"]
    assert referenced_locations(_text("single.wsdl")) == []
    assert referenced_locations("<not xml") == []


# ===========================================================================
# Fetching
# ===========================================================================


def test_single_wsdl_is_preferred_and_needs_nothing_else():
    seen: List[httpx.Request] = []
    fetched = fetch_wsdl_service(_BASE, client=_service(_ROUTES, seen))
    assert fetched.url == f"{_BASE}?singleWsdl"
    assert fetched.single_wsdl is True
    assert fetched.members == {}
    assert [str(r.url) for r in seen] == [f"{_BASE}?singleWsdl"]


def test_without_single_wsdl_every_import_is_fetched_transitively():
    routes = {k: v for k, v in _ROUTES.items() if k != "singleWsdl"}
    seen: List[httpx.Request] = []
    fetched = fetch_wsdl_service(
        f"{_BASE}?wsdl", auth_type="bearer", auth_payload={"token": "s3cret"}, client=_service(routes, seen)
    )
    assert fetched.url == f"{_BASE}?wsdl"
    assert fetched.single_wsdl is False
    assert fetched.fetched == (
        ("https://svc.example.com/Calc.svc?wsdl=wsdl0", f"{_BASE}?wsdl=wsdl0"),
        ("https://svc.example.com/Calc.svc?xsd=xsd0", f"{_BASE}?xsd=xsd0"),
        ("Calc.svc?xsd=xsd1", f"{_BASE}?xsd=xsd1"),  # relative to the document that names it
    )
    assert set(fetched.members) == {location for location, _ in fetched.fetched}
    assert fetched.notes == ()
    assert all(r.headers["Authorization"] == "Bearer s3cret" for r in seen)


def test_a_referenced_document_that_fails_is_noted_and_skipped():
    routes = {k: v for k, v in _ROUTES.items() if k not in ("singleWsdl", "xsd=xsd1")}
    fetched = fetch_wsdl_service(_BASE, client=_service(routes, []))
    assert len(fetched.fetched) == 2
    assert fetched.notes and fetched.notes[0].startswith("Calc.svc?xsd=xsd1:")


def test_a_reference_to_a_private_address_is_not_fetched():
    evil = _text("service.wsdl").replace("https://svc.example.com/Calc.svc?wsdl=wsdl0", "http://169.254.169.254/latest")
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.query in (b"wsdl", "wsdl"):
            return httpx.Response(200, text=evil)
        return httpx.Response(404)

    fetched = fetch_wsdl_service(_BASE, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert "169.254.169.254" not in " ".join(str(r.url) for r in seen)
    assert fetched.notes and "not allowed" in fetched.notes[0]


def test_the_referenced_document_cap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.wsdl_fetch.MAX_REFERENCED_DOCUMENTS", 1)
    routes = {k: v for k, v in _ROUTES.items() if k != "singleWsdl"}
    fetched = fetch_wsdl_service(_BASE, client=_service(routes, []))
    assert len(fetched.fetched) == 1
    assert any("more than 1 referenced documents" in note for note in fetched.notes)
    assert MAX_REFERENCED_DOCUMENTS == 50


def test_the_total_size_cap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.wsdl_fetch.MAX_TOTAL_BYTES", len(_text("service.wsdl")) + 10)
    routes = {k: v for k, v in _ROUTES.items() if k != "singleWsdl"}
    with pytest.raises(ImportSourceError) as exc:
        fetch_wsdl_service(_BASE, client=_service(routes, []))
    assert exc.value.code == "INPUT_TOO_LARGE"


@pytest.mark.parametrize(
    "status, code", [(404, "SOURCE_NOT_FOUND"), (401, "SOURCE_AUTH_REQUIRED"), (500, "SOURCE_UNREACHABLE")]
)
def test_a_description_that_cannot_be_fetched(status: int, code: str):
    with pytest.raises(ImportSourceError) as exc:
        fetch_wsdl_service(_BASE, client=_service({}, [], status={"singleWsdl": status, "wsdl": status}))
    assert exc.value.code == code


def test_a_url_that_does_not_answer_with_wsdl():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Service</body></html>")

    with pytest.raises(ImportSourceError) as exc:
        fetch_wsdl_service(_BASE, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert exc.value.code == "FORMAT_MISMATCH"


@pytest.mark.parametrize("url", ["http://127.0.0.1/Calc.svc", "http://localhost/Calc.svc"])
def test_a_private_service_is_refused_before_any_request(url: str):
    seen: List[httpx.Request] = []
    with pytest.raises(ImportSourceError, match="not allowed"):
        fetch_wsdl_service(url, client=_service(_ROUTES, seen))
    assert seen == []


# ===========================================================================
# The adapter
# ===========================================================================


def _shape(api) -> tuple:
    return (
        sorted(t.name for t in api.types),
        sorted(op.name for service in api.services for op in service.operations),
    )


def test_the_adapter_declares_live_discovery():
    descriptor = WsdlImportSource.descriptor()
    assert descriptor.supports_live_discovery is True
    assert "discovery" in [kind.value if hasattr(kind, "value") else kind for kind in descriptor.input_kinds]


def test_wsdl_and_single_wsdl_import_the_same_api():
    source = WsdlImportSource()
    single = source.normalize(source.discover(_BASE, client=_service(_ROUTES, [])))
    routes = {k: v for k, v in _ROUTES.items() if k != "singleWsdl"}
    inlined = source.normalize(source.discover(_BASE, client=_service(routes, [])))
    assert _shape(single) == _shape(inlined)
    assert "Operand" in _shape(inlined)[0]
    assert single.extras["wsdl_single_wsdl"] is True
    assert single.extras["wsdl_fetched_documents"] == []
    assert inlined.extras["wsdl_single_wsdl"] is False
    assert inlined.extras["wsdl_source_url"] == f"{_BASE}?wsdl"
    assert [d["url"] for d in inlined.extras["wsdl_fetched_documents"]] == [
        f"{_BASE}?wsdl=wsdl0",
        f"{_BASE}?xsd=xsd0",
        f"{_BASE}?xsd=xsd1",
    ]


def test_an_uploaded_wsdl_records_no_fetch():
    source = WsdlImportSource()
    api = source.normalize(source.parse(_text("single.wsdl")))
    assert not any(key in api.extras for key in ("wsdl_source_url", "wsdl_fetched_documents"))


def test_a_wsdl_import_split_resolves_from_a_fileset_too():
    from app.fileset import IntakeFileset

    members = {
        "service.wsdl": _text("service.wsdl").replace("https://svc.example.com/Calc.svc?wsdl=wsdl0", "wsdl0.wsdl"),
        "wsdl0.wsdl": _text("wsdl0.wsdl").replace("https://svc.example.com/Calc.svc?xsd=xsd0", "xsd0.xsd"),
        "xsd0.xsd": _text("xsd0.xsd").replace("Calc.svc?xsd=xsd1", "xsd1.xsd"),
        "xsd1.xsd": _text("xsd1.xsd"),
    }
    source = WsdlImportSource()
    api = source.normalize(source.parse_fileset(IntakeFileset.from_members(members, root="service.wsdl")))
    assert _shape(api) == _shape(source.normalize(source.parse(_text("single.wsdl"))))
