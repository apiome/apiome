"""Tests for ``apiome import odata`` and its ``--discover`` (MFI-11.3, #3778; MFI-11.6, #3781).

``--discover`` turns a service root into its ``$metadata`` URL (the rules of the REST adapter's
live discovery) and imports that document through the registry-dispatch import, against a mocked
REST service and a mocked OData service.

The committed v2 (SAP Gateway-style) and v4 fixtures (MFI-11.6) are imported both ways — as a file
and discovered from a service root — so each CSDL generation is proven to reach the server verbatim
under ``source_kind: odata``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.import_.odata import odata_metadata_url
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "odata"
_FIXTURES = Path(__file__).parent / "fixtures"
#: The committed OData fixtures (MFI-11.6), one per CSDL generation the importer reads.
_VERSION_FIXTURES = [
    pytest.param("bookshop-odata-v4.edmx", id="v4"),
    pytest.param("sales-odata-v2.xml", id="v2"),
]
_METADATA = (_EXAMPLES / "06-trippin-reference.edmx").read_text(encoding="utf-8")
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "abababab-abab-4bab-8bab-abababababab"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_ODATA = {
    "key": "odata",
    "label": "OData",
    "description": "Import an OData v2, v3 or v4 CSDL / EDMX service metadata document.",
    "icon": "database",
    "paradigm": "rest",
    "input_kinds": ["file", "url", "paste", "discovery", "fileset"],
    "supports_live_discovery": True,
    "formats": ["odata", "odata-v2", "odata-v3", "edmx"],
    "file_extensions": [".edmx", ".xml", ".json", ".zip", ".tar.gz", ".tgz", ".tar"],
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_ODATA]})  # type: ignore[attr-defined]
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
                "source": "odata",
                "paradigm": "rest",
                "format": "odata",
                "fingerprint": "sha256:odata",
                "counts": {"services": 1, "operations": 12, "types": 6, "channels": 0},
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
        ("https://h/odata/trippin", "https://h/odata/trippin/$metadata"),
        ("https://h/odata/trippin/", "https://h/odata/trippin/$metadata"),
        ("https://h/odata/trippin/$metadata", "https://h/odata/trippin/$metadata"),
        ("HTTPS://h/sap/ZBP_SRV/?sap-client=100", "https://h/sap/ZBP_SRV/$metadata?sap-client=100"),
    ],
)
def test_odata_metadata_url(url: str, expected: str) -> None:
    assert odata_metadata_url(url) == expected


@pytest.mark.parametrize("url", ["", "ftp://h/svc", "https:///nohost"])
def test_odata_metadata_url_refuses_unusable_urls(url: str) -> None:
    with pytest.raises(ValueError):
        odata_metadata_url(url)


def test_discover_imports_the_services_metadata(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url="https://odata.example.com/trippin/$metadata",
        method="GET",
        text=_METADATA,
        headers={"Content-Type": "application/xml"},
    )
    result = runner.invoke(app, ["import", "odata", "--discover", "https://odata.example.com/trippin/"])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "odata"
    assert base64.b64decode(body["document_base64"]).decode("utf-8") == _METADATA
    assert "Discovered OData $metadata at https://odata.example.com/trippin/$metadata" in strip_ansi(result.output)


def test_discover_is_the_only_input(httpx_mock: object) -> None:
    result = runner.invoke(app, ["import", "odata", "x.edmx", "--discover", "https://odata.example.com/svc"])
    assert result.exit_code != 0
    assert "Provide only one input" in strip_ansi(result.output)


def test_discover_refuses_a_bad_url() -> None:
    result = runner.invoke(app, ["import", "odata", "--discover", "ftp://odata.example.com/svc"])
    assert result.exit_code != 0
    assert "http or https" in strip_ansi(result.output)


def test_a_metadata_file_is_still_sent_verbatim(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    path = _EXAMPLES / "07-csdl-json-trippin.json"
    result = runner.invoke(app, ["import", "odata", str(path)])
    assert result.exit_code == 0, result.output
    assert base64.b64decode(_post_body(httpx_mock)["document_base64"]) == path.read_bytes()


@pytest.mark.parametrize("fixture", _VERSION_FIXTURES)
def test_a_versioned_fixture_file_imports_verbatim(httpx_mock: object, fixture: str) -> None:
    _mock_import(httpx_mock)
    path = _FIXTURES / fixture
    result = runner.invoke(app, ["import", "odata", str(path)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "odata"
    assert base64.b64decode(body["document_base64"]) == path.read_bytes()


@pytest.mark.parametrize("fixture", _VERSION_FIXTURES)
def test_a_versioned_fixture_is_discovered_from_its_service_root(httpx_mock: object, fixture: str) -> None:
    _mock_import(httpx_mock)
    metadata = (_FIXTURES / fixture).read_text(encoding="utf-8")
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url="https://odata.example.com/sap/opu/odata/sap/ZSALES_SRV/$metadata?sap-client=100",
        method="GET",
        text=metadata,
        headers={"Content-Type": "application/xml"},
    )
    result = runner.invoke(
        app,
        ["import", "odata", "--discover", "https://odata.example.com/sap/opu/odata/sap/ZSALES_SRV/?sap-client=100"],
    )
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "odata"
    assert base64.b64decode(body["document_base64"]).decode("utf-8") == metadata


@pytest.mark.parametrize(
    "fixture, marker",
    [
        ("bookshop-odata-v4.edmx", 'xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0"'),
        ("sales-odata-v2.xml", 'm:DataServiceVersion="2.0"'),
    ],
)
def test_the_versioned_fixtures_are_the_generation_they_claim(fixture: str, marker: str) -> None:
    assert marker in (_FIXTURES / fixture).read_text(encoding="utf-8")
