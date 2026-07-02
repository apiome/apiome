"""Tests for spec export and original-artifact download commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_TENANT_ID = "11111111-1111-4111-8111-111111111111"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

_PROJECT = {
    "id": _PROJECT_ID,
    "tenant_id": _TENANT_ID,
    "name": "Payments API",
    "slug": "payments-api",
    "source": "manual",
    "enabled": True,
}
_VERSION = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "1.0.0",
    "source": "import",
    "enabled": True,
    "data": {
        "x-import-source-openapi-version": "3.1.0",
        "x-import-fidelity-target": "to-source",
    },
}
_OPENAPI_JSON = b'{"openapi":"3.2.0","info":{"title":"Payments","version":"1.0.0"}}'
_ORIGINAL_BYTES = b"openapi: 3.1.0\ninfo:\n  title: Payments\n"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a default API key and tenant scope for tests that need Tier-2 routes."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_project_version_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}",
        json=_VERSION,
    )


def _mock_browse_openapi_export(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/schema/acme-corp/payments-api/1.0.0",
        content=_OPENAPI_JSON,
        headers={
            "Content-Type": "application/json",
            "ETag": '"export-etag-1"',
        },
    )


def test_spec_export_writes_file(httpx_mock: object, tmp_path: Path) -> None:
    """spec export writes reconstructed document bytes to --output file."""
    _mock_project_version_scope(httpx_mock)
    _mock_browse_openapi_export(httpx_mock)
    out_file = tmp_path / "openapi.json"
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--format",
            "openapi",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _OPENAPI_JSON
    assert "ETag: \"export-etag-1\"" in result.stderr


def test_spec_export_stdout_document_and_stderr_metadata(httpx_mock: object) -> None:
    """--output - writes document to stdout and human metadata to stderr."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}",
        json=_VERSION,
    )
    _mock_browse_openapi_export(httpx_mock)
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--project",
            _PROJECT_ID,
            "--version",
            _VERSION_ID,
            "--output",
            "-",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.encode() == _OPENAPI_JSON
    assert "Wrote" in result.stderr
    assert "ETag:" in result.stderr


def test_spec_export_output_whitespace_dash_writes_stdout(httpx_mock: object) -> None:
    """Whitespace-padded '-' output sentinel still writes bytes to stdout."""
    _mock_project_version_scope(httpx_mock)
    _mock_browse_openapi_export(httpx_mock)
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--output",
            " - ",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.encode() == _OPENAPI_JSON


def test_spec_export_allows_slug_scope_without_api_key(
    httpx_mock: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public browse export works without API key when tenant/project/version are slugs."""
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    httpx_mock.add_response(
        url="http://localhost:8000/v1/schema/acme-corp/payments-api/1.0.0",
        content=_OPENAPI_JSON,
        headers={"Content-Type": "application/json", "ETag": '"export-etag-1"'},
    )
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--tenant",
            "acme-corp",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--output",
            "-",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.encode() == _OPENAPI_JSON
    assert "API key required for this command." not in result.stderr
    assert len(httpx_mock.get_requests()) == 1
    request_headers = {h.lower() for h in httpx_mock.get_requests()[0].headers}
    assert "x-api-key" not in request_headers


def test_spec_export_json_metadata_on_stdout_when_output_is_file(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """Global --json emits metadata JSON on stdout when document goes to a file."""
    _mock_project_version_scope(httpx_mock)
    _mock_browse_openapi_export(httpx_mock)
    out_file = tmp_path / "spec.json"
    result = runner.invoke(
        app,
        [
            "--json",
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _OPENAPI_JSON
    payload = json.loads(result.stdout.strip())
    assert payload["etag"] == '"export-etag-1"'
    assert payload["format"] == "openapi"
    assert "source_openapi_version" not in payload


def test_spec_export_json_metadata_on_stderr_when_output_is_stdout(httpx_mock: object) -> None:
    """Global --json with --output - keeps stdout byte-safe; metadata on stderr."""
    _mock_project_version_scope(httpx_mock)
    _mock_browse_openapi_export(httpx_mock)
    result = runner.invoke(
        app,
        [
            "--json",
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--output",
            "-",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.encode() == _OPENAPI_JSON
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["output"] == "-"
    assert payload["format"] == "openapi"


def test_spec_export_yaml_query(httpx_mock: object, tmp_path: Path) -> None:
    """--yaml requests YAML serialization from browse spec export."""
    _mock_project_version_scope(httpx_mock)
    yaml_body = b"openapi: 3.2.0\n"
    httpx_mock.add_response(
        url=(
            "http://localhost:8000/v1/arazzo/acme-corp/payments-api/1.0.0?accept=yaml"
        ),
        content=yaml_body,
        headers={"Content-Type": "application/yaml", "ETag": '"arazzo-etag"'},
    )
    out_file = tmp_path / "workflow.yaml"
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--format",
            "arazzo",
            "--yaml",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == yaml_body
    assert "Format: arazzo" in result.stderr
    assert "Serialization: yaml" in result.stderr


def test_spec_export_maps_api_error_to_usage(httpx_mock: object, tmp_path: Path) -> None:
    """404 browse responses exit with usage code."""
    _mock_project_version_scope(httpx_mock)
    httpx_mock.add_response(
        url="http://localhost:8000/v1/schema/acme-corp/payments-api/1.0.0",
        status_code=404,
        json={"message": "Not found", "code": 404},
    )
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--output",
            str(tmp_path / "missing.json"),
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "Not found" in result.stderr


def test_spec_export_requires_tenant_scope(httpx_mock: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing tenant configuration exits with usage code."""
    monkeypatch.delenv("APIOME_TENANT_ID", raising=False)
    result = runner.invoke(
        app,
        [
            "spec",
            "export",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--output",
            str(tmp_path / "out.json"),
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "Tenant scope required" in result.stderr


def test_download_original_not_supported_via_rest() -> None:
    """download-original is not exposed on /v1 REST."""
    result = runner.invoke(
        app,
        [
            "spec",
            "download-original",
            "--import-id",
            _VERSION_ID,
            "--output",
            "-",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "not supported via the /v1 REST API" in result.stderr
