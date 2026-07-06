"""Tests for the emitter-registry ``export`` command group (MFX-9.4).

Drive ``apiome export`` against a mocked REST surface (``pytest-httpx``): ``export openapi`` writes
the document via the browse reconstruction (``GET /v1/schema/...``) and surfaces the fidelity report
from the emitter-registry preview (``POST /v1/export/{tenant}/preview``), exiting non-zero on a lossy
export unless ``--force``; ``export targets`` lists the registered emitters (``GET .../targets``).
Fixtures live in ``tests/fixtures/export-*.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

_PROJECT = {"id": _PROJECT_ID, "name": "Payments API", "slug": "payments-api", "enabled": True}
_VERSION = {"id": _VERSION_ID, "project_id": _PROJECT_ID, "version": "1.0.0", "slug": "1.0.0"}

_OPENAPI_BYTES = (_FIXTURES / "export-openapi-lossless.json").read_bytes()
_PREVIEW_LOSSLESS = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
_PREVIEW_LOSSY = json.loads((_FIXTURES / "export-preview-lossy.json").read_text())
_TARGETS = json.loads((_FIXTURES / "export-targets.json").read_text())

_BASE = "http://localhost:8000"
_PREVIEW_URL = f"{_BASE}/v1/export/acme-corp/preview"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_SCHEMA_URL = f"{_BASE}/v1/schema/acme-corp/payments-api/1.0.0"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default API key + tenant scope for the Tier-2 export routes."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    """Mock the project/version slug resolution the browse export scope walks."""
    httpx_mock.add_response(
        url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT
    )
    httpx_mock.add_response(
        url=f"{_BASE}/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0", json=_VERSION
    )
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/{_PROJECT_ID}", json=_PROJECT)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}", json=_VERSION
    )


def _mock_schema(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=_SCHEMA_URL,
        content=_OPENAPI_BYTES,
        headers={"Content-Type": "application/json", "ETag": '"export-etag-1"'},
    )


def _mock_preview(httpx_mock: object, payload: dict) -> None:
    httpx_mock.add_response(url=_PREVIEW_URL, method="POST", json=payload)


def _openapi_args(out: str) -> list[str]:
    return [
        "export", "openapi",
        "--project", "payments-api",
        "--version", "1.0.0",
        "--output", out,
    ]


def test_export_openapi_writes_document_and_lossless_fidelity(
    httpx_mock: object, tmp_path: Path
) -> None:
    """A lossless export writes the document and reports 100% preserved, exit 0."""
    _mock_scope(httpx_mock)
    _mock_schema(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSLESS)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, _openapi_args(str(out_file)))

    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _OPENAPI_BYTES
    assert "Export to OpenAPI 3.1: fidelity lossless (100% preserved)." in result.stderr
    assert "Wrote" in result.stderr

    preview_request = next(
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/export/acme-corp/preview")
    )
    body = json.loads(preview_request.content)
    assert body == {"artifact": _PROJECT_ID, "target": "openapi", "version": "1.0.0"}


def test_export_openapi_lossy_exits_nonzero_and_shows_advisory(
    httpx_mock: object, tmp_path: Path
) -> None:
    """A lossy export still writes the document but exits non-zero with the advisory."""
    _mock_scope(httpx_mock)
    _mock_schema(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSY)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, _openapi_args(str(out_file)))

    assert result.exit_code == EXIT_ERROR
    assert out_file.read_bytes() == _OPENAPI_BYTES
    assert "fidelity lossy (60% preserved)" in result.stderr
    assert "1 dropped, 1 approximated" in result.stderr
    assert "drops 1 construct" in result.stderr
    assert "Lossy export" in result.stderr


def test_export_openapi_force_overrides_lossy_exit(httpx_mock: object, tmp_path: Path) -> None:
    """--force accepts a lossy export and exits 0."""
    _mock_scope(httpx_mock)
    _mock_schema(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSY)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, [*_openapi_args(str(out_file)), "--force"])

    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _OPENAPI_BYTES
    assert "fidelity lossy" in result.stderr


def test_export_openapi_json_metadata_carries_fidelity(
    httpx_mock: object, tmp_path: Path
) -> None:
    """--json folds the fidelity tier into the metadata payload on stdout."""
    _mock_scope(httpx_mock)
    _mock_schema(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSLESS)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, ["--json", *_openapi_args(str(out_file))])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["fidelity_target"] == "openapi"
    assert payload["fidelity"]["status"] == "lossless"
    assert payload["fidelity"]["preserved_percent"] == 100


def test_export_openapi_stdout_document_keeps_bytes_clean(httpx_mock: object) -> None:
    """--output - writes only document bytes to stdout; fidelity/metadata go to stderr."""
    _mock_scope(httpx_mock)
    _mock_schema(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSLESS)

    result = runner.invoke(app, _openapi_args("-"))

    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.encode() == _OPENAPI_BYTES
    assert "fidelity lossless" in result.stderr


def test_export_openapi_maps_schema_error_to_usage(httpx_mock: object, tmp_path: Path) -> None:
    """A 404 from the browse export exits with usage code."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_SCHEMA_URL, status_code=404, json={"message": "Not found", "code": 404})

    result = runner.invoke(app, _openapi_args(str(tmp_path / "missing.json")))

    assert result.exit_code == EXIT_USAGE
    assert "Not found" in result.stderr


def test_export_openapi_empty_output_is_usage_error() -> None:
    """An empty --output is rejected before any HTTP call."""
    result = runner.invoke(app, _openapi_args("   "))
    assert result.exit_code == EXIT_USAGE
    assert "--output cannot be empty." in result.stderr


def test_export_openapi_conflicting_serialization_flags(tmp_path: Path) -> None:
    """--yaml and --accept together is a usage error."""
    result = runner.invoke(
        app, [*_openapi_args(str(tmp_path / "o.json")), "--yaml", "--accept", "json"]
    )
    assert result.exit_code == EXIT_USAGE
    assert "Use only one of --yaml or --accept" in result.stderr


def test_export_openapi_requires_api_key(
    httpx_mock: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing API key exits with usage code before any request."""
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    result = runner.invoke(app, _openapi_args(str(tmp_path / "o.json")))
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []


def test_export_targets_lists_registered_emitters(httpx_mock: object) -> None:
    """export targets renders the registry descriptors + fidelity tiers as a table."""
    httpx_mock.add_response(
        url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT
    )
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)

    result = runner.invoke(
        app, ["export", "targets", "--project", "payments-api", "--version", "1.0.0"]
    )

    assert result.exit_code == EXIT_SUCCESS
    assert "openapi" in result.stdout
    assert "lossless" in result.stdout
    assert "sample" in result.stdout
    assert "types-o" in result.stdout


def test_export_targets_json_passthrough(httpx_mock: object) -> None:
    """export targets --json emits the raw registry response on stdout."""
    httpx_mock.add_response(
        url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT
    )
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)

    result = runner.invoke(
        app, ["--json", "export", "targets", "--project", "payments-api", "--version", "1.0.0"]
    )

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert [t["descriptor"]["key"] for t in payload["targets"]] == ["openapi", "sample"]
