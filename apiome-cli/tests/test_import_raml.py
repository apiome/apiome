"""Tests for ``apiome import raml`` and its migrate-to-OpenAPI path (MFI-15.5, #3803).

The committed fixtures — a self-contained RAML 1.0 file and a set that pulls a type in with
``!include`` and a ``uses`` library from sibling folders — reach the server verbatim under
``source_kind: raml``: the file as itself, the set as one archive with its relative paths, which the
server resolves with AMF (MFI-15.1). The migrate-to-OpenAPI off-ramp is ``apiome convert``, which
prints the RAML conversion pack that shaped the document (MFI-22.8).
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.conversion_output import format_conversion_pack
from apiome_cli.main import app

runner = CliRunner()

_FIXTURES = Path(__file__).parent / "fixtures"
_SINGLE = _FIXTURES / "petstore-raml10.raml"
_SET = _FIXTURES / "bookstore-raml-set"
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "efefefef-efef-4fef-8fef-efefefefefef"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"
_CONVERT_URL = "http://localhost:8000/v1/catalog/acme-corp/cat-raml/convert"

_RAML = {
    "key": "raml",
    "label": "RAML",
    "description": "Import a RAML 1.0 REST API definition with types and resources.",
    "icon": "book-marked",
    "paradigm": "rest",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["raml"],
    "file_extensions": [".raml", ".zip", ".tar.gz", ".tgz", ".tar"],
}

#: The ``conversionPack`` a RAML dry-run returns (``app.conversion_packs.RamlPack``).
_RAML_PACK = {
    "key": "raml",
    "label": "RAML",
    "strategy": "native",
    "expected_tiers": ["high"],
    "refinements": [],
    "documented_losses": ["Resource types and traits are applied, not preserved as reusable definitions."],
    "external_converter": None,
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_RAML]})  # type: ignore[attr-defined]
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
                "source": "raml",
                "paradigm": "rest",
                "format": "raml",
                "fingerprint": "sha256:raml",
                "counts": {"services": 1, "operations": 3, "types": 2, "channels": 0},
                "lint": {"score": 92, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
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


# --- import ----------------------------------------------------------------------------------


def test_the_self_contained_fixture_imports_verbatim(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "raml", str(_SINGLE)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "raml"
    assert base64.b64decode(body["document_base64"]) == _SINGLE.read_bytes()


def test_the_set_is_sent_as_one_archive_with_its_folders(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "raml", str(_SET)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "raml"
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(body["document_base64"]))) as archive:
        names = sorted(archive.namelist())
        assert names == ["api.raml", "libraries/common.raml", "types/book.raml"]
        for name in names:
            assert archive.read(name) == (_SET / name).read_bytes()


@pytest.mark.parametrize(
    "fixture, marker",
    [
        ("petstore-raml10.raml", "#%RAML 1.0\n"),
        ("petstore-raml10.raml", "resourceTypes:"),
        ("petstore-raml10.raml", "traits:"),
        ("bookstore-raml-set/api.raml", "Book: !include types/book.raml"),
        ("bookstore-raml-set/api.raml", "common: libraries/common.raml"),
        ("bookstore-raml-set/types/book.raml", "#%RAML 1.0 DataType"),
        ("bookstore-raml-set/libraries/common.raml", "#%RAML 1.0 Library"),
    ],
)
def test_the_fixtures_are_what_they_claim(fixture: str, marker: str) -> None:
    assert marker in (_FIXTURES / fixture).read_text(encoding="utf-8")


def test_the_self_contained_fixture_references_no_other_file() -> None:
    # The server reads a self-contained document without AMF; a stray `!include` or `uses` (even in
    # a comment) would route it through AMF instead.
    text = _SINGLE.read_text(encoding="utf-8")
    assert "!include" not in text
    assert "uses:" not in text


# --- migrate to OpenAPI ----------------------------------------------------------------------


def test_convert_names_the_raml_pack(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=f"{_CONVERT_URL}?dryRun=true",
        json={
            "report": {"score": 88, "grade": "B", "tier": "high", "items": [], "losses": []},
            "openapi": {"openapi": "3.1.0", "info": {"title": "Pet Store", "version": "v1"}, "paths": {}},
            "sourceFormat": "raml",
            "target": "openapi",
            "conversionPack": _RAML_PACK,
        },
    )
    result = runner.invoke(app, ["convert", "cat-raml", "--to", "openapi", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Conversion pack: RAML (native projection)." in result.stdout
    assert "Known loss: Resource types and traits are applied" in result.stdout


def test_format_conversion_pack_without_a_pack_is_empty() -> None:
    assert format_conversion_pack(None) == []
    assert format_conversion_pack("raml") == []


def test_format_conversion_pack_names_an_external_converter_and_a_fallback() -> None:
    used = {
        "label": "Smithy",
        "strategy": "external",
        "refinements": ["Read @http on 3 operations."],
        "documented_losses": [],
        "external_converter": {"tool": "smithy-openapi", "name": "smithy-openapi", "used": True},
    }
    assert format_conversion_pack(used) == [
        "Conversion pack: Smithy (external converter smithy-openapi).",
        "  - Refined: Read @http on 3 operations.",
    ]
    fell_back = {
        "label": "gRPC / Protobuf",
        "strategy": "native",
        "external_converter": {"tool": "protoc-gen-openapiv2", "name": "protoc-gen-openapiv2", "used": False,
                               "fallback_reason": "not installed"},
    }
    assert format_conversion_pack(fell_back) == [
        "Conversion pack: gRPC / Protobuf (native projection).",
        "  - protoc-gen-openapiv2 not used: not installed",
    ]
