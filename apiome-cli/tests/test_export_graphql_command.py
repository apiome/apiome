"""Tests for ``apiome export graphql`` — MFX-13.5 (#3888).

Drive the command against a mocked REST surface (``pytest-httpx``). GraphQL SDL is emitted through
the Emitter SPI: the command ``POST``s ``/v1/export/{tenant}/document`` (target ``graphql``) for the
SDL bytes and ``POST``s ``/v1/export/{tenant}/preview`` for the honest fidelity report, exiting
non-zero on a lossy export (a rich REST/OpenAPI source) unless ``--force``. A native GraphQL source
exports lossless.

Fixtures: ``export-graphql.graphql`` (the emitted document) and
``export-preview-graphql-{lossless,lossy}.json`` (the fidelity envelopes).
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

_GRAPHQL_BYTES = (_FIXTURES / "export-graphql.graphql").read_bytes()
_PREVIEW_LOSSLESS = json.loads((_FIXTURES / "export-preview-graphql-lossless.json").read_text())
_PREVIEW_LOSSY = json.loads((_FIXTURES / "export-preview-graphql-lossy.json").read_text())

_BASE = "http://localhost:8000"
_DOCUMENT_URL = f"{_BASE}/v1/export/acme-corp/document"
_PREVIEW_URL = f"{_BASE}/v1/export/acme-corp/preview"

_GRAPHQL_TARGET = "graphql"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default API key + tenant scope for the tenant-scoped export routes."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_document(httpx_mock: object, *, content: bytes = _GRAPHQL_BYTES) -> None:
    headers = {
        "Content-Type": "application/graphql",
        "Content-Disposition": 'attachment; filename="schema.graphql"',
    }
    httpx_mock.add_response(url=_DOCUMENT_URL, method="POST", content=content, headers=headers)


def _mock_preview(httpx_mock: object, payload: dict) -> None:
    httpx_mock.add_response(url=_PREVIEW_URL, method="POST", json=payload)


def _graphql_args(out: str) -> list[str]:
    return [
        "export", "graphql",
        "--project", _PROJECT_ID,
        "--version", "1.0.0",
        "--output", out,
    ]


def test_export_graphql_writes_document_and_lossless_fidelity(
    httpx_mock: object, tmp_path: Path
) -> None:
    """A native GraphQL source exports lossless: the document is written, exit 0, 100% preserved."""
    _mock_document(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSLESS)
    out_file = tmp_path / "schema.graphql"

    result = runner.invoke(app, _graphql_args(str(out_file)))

    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _GRAPHQL_BYTES
    assert "Export to GraphQL SDL: fidelity lossless (100% preserved)." in result.stderr
    assert "Wrote" in result.stderr

    document_request = next(
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/export/acme-corp/document")
    )
    assert json.loads(document_request.content) == {
        "artifact": _PROJECT_ID,
        "target": _GRAPHQL_TARGET,
        "version": "1.0.0",
    }

    preview_request = next(
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/export/acme-corp/preview")
    )
    assert json.loads(preview_request.content) == {
        "artifact": _PROJECT_ID,
        "target": _GRAPHQL_TARGET,
        "version": "1.0.0",
    }


def test_export_graphql_lossy_exits_nonzero_and_shows_advisory(
    httpx_mock: object, tmp_path: Path
) -> None:
    """A rich REST source still writes the document but exits non-zero with the advisory."""
    _mock_document(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSY)
    out_file = tmp_path / "schema.graphql"

    result = runner.invoke(app, _graphql_args(str(out_file)))

    assert result.exit_code == EXIT_ERROR
    assert out_file.read_bytes() == _GRAPHQL_BYTES
    assert "fidelity lossy (58% preserved)" in result.stderr
    assert "1 dropped, 4 approximated" in result.stderr
    assert "Lossy export" in result.stderr


def test_export_graphql_force_overrides_lossy_exit(httpx_mock: object, tmp_path: Path) -> None:
    """--force accepts a lossy export and exits 0."""
    _mock_document(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSY)
    out_file = tmp_path / "schema.graphql"

    result = runner.invoke(app, [*_graphql_args(str(out_file)), "--force"])

    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _GRAPHQL_BYTES
    assert "fidelity lossy" in result.stderr


def test_export_graphql_json_metadata_carries_fidelity(
    httpx_mock: object, tmp_path: Path
) -> None:
    """--json folds the fidelity tier + target into the metadata payload on stdout."""
    _mock_document(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSLESS)
    out_file = tmp_path / "schema.graphql"

    result = runner.invoke(app, ["--json", *_graphql_args(str(out_file))])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["fidelity_target"] == _GRAPHQL_TARGET
    assert payload["format"] == "graphql"
    assert payload["filename"] == "schema.graphql"
    assert payload["fidelity"]["status"] == "lossless"
    assert payload["fidelity"]["preserved_percent"] == 100


def test_export_graphql_stdout_document_keeps_bytes_clean(httpx_mock: object) -> None:
    """--output - writes only document bytes to stdout; fidelity/metadata go to stderr."""
    _mock_document(httpx_mock)
    _mock_preview(httpx_mock, _PREVIEW_LOSSLESS)

    result = runner.invoke(app, _graphql_args("-"))

    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.encode() == _GRAPHQL_BYTES
    assert "fidelity lossless" in result.stderr


def test_export_graphql_maps_document_error_to_usage(httpx_mock: object, tmp_path: Path) -> None:
    """A 404 from the emit route exits with usage code and surfaces the message."""
    httpx_mock.add_response(
        url=_DOCUMENT_URL, method="POST", status_code=404, json={"message": "Not found", "code": 404}
    )

    result = runner.invoke(app, _graphql_args(str(tmp_path / "missing.graphql")))

    assert result.exit_code == EXIT_USAGE
    assert "Not found" in result.stderr


def test_export_graphql_empty_output_is_usage_error() -> None:
    """An empty --output is rejected before any HTTP call."""
    result = runner.invoke(app, _graphql_args("   "))
    assert result.exit_code == EXIT_USAGE
    assert "--output cannot be empty." in result.stderr
