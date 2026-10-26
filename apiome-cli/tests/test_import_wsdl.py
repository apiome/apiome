"""Tests for ``apiome import wsdl --discover`` (MFI-13.3, #3790).

``--discover`` tries a SOAP service's ``?singleWsdl`` (every import inlined), then ``?wsdl``, and
imports the first that answers with WSDL through the registry-dispatch import, against a mocked
REST service and a mocked SOAP service.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.import_.wsdl import discover_wsdl_url, wsdl_candidate_urls
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_EXAMPLE = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "wsdl" / "01-calculator.wsdl"
_WSDL = _EXAMPLE.read_text(encoding="utf-8")
_SERVICE = "https://soap.example.com/Calculator.svc"
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_WSDL_SOURCE = {
    "key": "wsdl",
    "label": "WSDL",
    "description": "Import a SOAP WSDL 1.1 or 2.0 service description.",
    "icon": "network",
    "paradigm": "rpc",
    "input_kinds": ["file", "url", "paste", "discovery", "fileset"],
    "supports_live_discovery": True,
    "formats": ["wsdl", "wsdl-2.0"],
    "file_extensions": [".wsdl", ".xml", ".zip", ".tar.gz", ".tgz", ".tar"],
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_WSDL_SOURCE]})  # type: ignore[attr-defined]
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL, method="POST", status_code=202, json={"job_id": _JOB_ID, "state": "pending"}
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "summary": {
                "source": "wsdl",
                "paradigm": "rpc",
                "format": "wsdl",
                "fingerprint": "sha256:wsdl",
                "counts": {"services": 1, "operations": 1, "types": 2, "channels": 0},
                "lint": {"score": 90, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
                "dry_run": False,
                "incremental_mode": False,
                "persisted": False,
            },
        },
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


@pytest.mark.parametrize(
    "url, expected",
    [
        (_SERVICE, [f"{_SERVICE}?singleWsdl", f"{_SERVICE}?wsdl"]),
        (f"{_SERVICE}?wsdl", [f"{_SERVICE}?singleWsdl", f"{_SERVICE}?wsdl"]),
        (f"{_SERVICE}?singleWsdl", [f"{_SERVICE}?singleWsdl"]),
        ("https://h/files/calc.wsdl", ["https://h/files/calc.wsdl"]),
    ],
)
def test_wsdl_candidate_urls(url: str, expected: list[str]) -> None:
    assert wsdl_candidate_urls(url) == expected


@pytest.mark.parametrize("url", ["", "ftp://h/svc", "https:///nohost"])
def test_wsdl_candidate_urls_refuse_unusable_urls(url: str) -> None:
    with pytest.raises(ValueError):
        wsdl_candidate_urls(url)


def _client(routes: dict[str, httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: routes.get(str(r.url), httpx.Response(404))))


def test_single_wsdl_is_preferred() -> None:
    client = _client({f"{_SERVICE}?singleWsdl": httpx.Response(200, text=_WSDL)})
    assert discover_wsdl_url(_SERVICE, client=client) == f"{_SERVICE}?singleWsdl"


def test_wsdl_is_the_fallback_when_single_wsdl_is_missing_or_not_wsdl() -> None:
    client = _client(
        {
            f"{_SERVICE}?singleWsdl": httpx.Response(200, text="<html>no</html>"),
            f"{_SERVICE}?wsdl": httpx.Response(200, text=_WSDL),
        }
    )
    assert discover_wsdl_url(_SERVICE, client=client) == f"{_SERVICE}?wsdl"


def test_no_wsdl_anywhere_is_an_error() -> None:
    with pytest.raises(OSError, match="No WSDL description found"):
        discover_wsdl_url(_SERVICE, client=_client({}))


def test_discover_imports_the_found_description(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    httpx_mock.add_response(url=f"{_SERVICE}?singleWsdl", method="GET", status_code=400)  # type: ignore[attr-defined]
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=f"{_SERVICE}?wsdl", method="GET", text=_WSDL, headers={"Content-Type": "text/xml"}, is_reusable=True
    )
    result = runner.invoke(app, ["import", "wsdl", "--discover", _SERVICE])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "wsdl"
    assert base64.b64decode(body["document_base64"]).decode("utf-8") == _WSDL
    assert f"Discovered WSDL at {_SERVICE}?wsdl" in strip_ansi(result.output)


def test_discover_is_the_only_input() -> None:
    result = runner.invoke(app, ["import", "wsdl", "calc.wsdl", "--discover", _SERVICE])
    assert result.exit_code != 0
    assert "Provide only one input" in strip_ansi(result.output)
