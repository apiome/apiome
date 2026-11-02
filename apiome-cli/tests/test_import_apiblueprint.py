"""Tests for ``apiome import apiblueprint`` and its migrate-to-OpenAPI path (MFI-16.4, #3807).

The committed fixtures — an ``.apib`` blueprint with groups, a named request, response headers and
MSON inheritance / mixins, and a minimal blueprint saved as ``.md`` — reach the server verbatim
under ``source_kind: apiblueprint``. The migrate-to-OpenAPI off-ramp is ``apiome convert``, which
prints the API Blueprint conversion pack that produced the document (MFI-22.8).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.main import app

runner = CliRunner()

_FIXTURES = Path(__file__).parent / "fixtures"
_FIXTURE_FILES = [
    pytest.param("shelter-apiblueprint.apib", id="apib"),
    pytest.param("notes-apiblueprint.md", id="md"),
]
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "abcdabcd-abcd-4bcd-8bcd-abcdabcdabcd"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"
_CONVERT_URL = "http://localhost:8000/v1/catalog/acme-corp/cat-apib/convert"

_APIBLUEPRINT = {
    "key": "apiblueprint",
    "label": "API Blueprint",
    "description": "Import an API Blueprint 1A REST API description with MSON data structures.",
    "icon": "file-text",
    "paradigm": "rest",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["apiblueprint", "api-blueprint", "apib", "blueprint"],
    "file_extensions": [".apib", ".md", ".zip", ".tar.gz", ".tgz", ".tar"],
}

#: The ``conversionPack`` an API Blueprint dry-run returns (``app.conversion_packs.ApiBlueprintPack``).
_APIBLUEPRINT_PACK = {
    "key": "apiblueprint",
    "label": "API Blueprint",
    "strategy": "native",
    "expected_tiers": ["high"],
    "refinements": [],
    "documented_losses": ["Example transactions are not carried over as OpenAPI examples."],
    "external_converter": None,
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_APIBLUEPRINT]})  # type: ignore[attr-defined]
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
                "source": "apiblueprint",
                "paradigm": "rest",
                "format": "apiblueprint",
                "fingerprint": "sha256:apib",
                "counts": {"services": 1, "operations": 3, "types": 4, "channels": 0},
                "lint": {"score": 95, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
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


@pytest.mark.parametrize("fixture", _FIXTURE_FILES)
def test_a_fixture_imports_verbatim(httpx_mock: object, fixture: str) -> None:
    _mock_import(httpx_mock)
    path = _FIXTURES / fixture
    result = runner.invoke(app, ["import", "apiblueprint", str(path)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "apiblueprint"
    assert base64.b64decode(body["document_base64"]) == path.read_bytes()


@pytest.mark.parametrize(
    "fixture, marker",
    [
        ("shelter-apiblueprint.apib", "FORMAT: 1A\n"),
        ("shelter-apiblueprint.apib", "# Group Pets"),
        ("shelter-apiblueprint.apib", "+ Request Minimal (application/json)"),
        ("shelter-apiblueprint.apib", "+ Headers"),
        ("shelter-apiblueprint.apib", "## Cat (Pet)"),
        ("shelter-apiblueprint.apib", "+ Include Problem"),
        ("notes-apiblueprint.md", "FORMAT: 1A\n"),
    ],
)
def test_the_fixtures_are_what_they_claim(fixture: str, marker: str) -> None:
    assert marker in (_FIXTURES / fixture).read_text(encoding="utf-8")


def test_the_fixtures_start_with_the_format_marker() -> None:
    # The server claims a blueprint by a column-zero `FORMAT: 1A` line, whatever the extension.
    for fixture in ("shelter-apiblueprint.apib", "notes-apiblueprint.md"):
        assert (_FIXTURES / fixture).read_text(encoding="utf-8").startswith("FORMAT: 1A\n")


def test_convert_names_the_api_blueprint_pack(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=f"{_CONVERT_URL}?dryRun=true",
        json={
            "report": {"score": 90, "grade": "A", "tier": "high", "items": [], "losses": []},
            "openapi": {"openapi": "3.1.0", "info": {"title": "Shelter API", "version": "1.0.0"}, "paths": {}},
            "sourceFormat": "apiblueprint",
            "target": "openapi",
            "conversionPack": _APIBLUEPRINT_PACK,
        },
    )
    result = runner.invoke(app, ["convert", "cat-apib", "--to", "openapi", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Conversion pack: API Blueprint (native projection)." in result.stdout
    assert "Known loss: Example transactions are not carried over as OpenAPI examples." in result.stdout
