"""End-to-end tests for registry-driven import dispatch (MFI-1.4).

Covers ``apiome import --list`` and the generic
``apiome import <format> <input>`` seam against a mocked REST service.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_SOURCES = [
    {
        "key": "openapi",
        "label": "OpenAPI / Swagger",
        "description": "REST API description.",
        "icon": "FileJson",
        "paradigm": "rest",
        "input_kinds": ["file", "url", "paste"],
        "supports_live_discovery": False,
        "formats": ["openapi-3.0", "openapi-3.1"],
    },
    {
        "key": "sample",
        "label": "Sample",
        "description": "No-op acceptance adapter.",
        "icon": "Beaker",
        "paradigm": "rest",
        "input_kinds": ["file"],
        "supports_live_discovery": False,
        "formats": [],
    },
]

# The in-process adapter pipeline returns a preview summary (not a persisted
# ImportResult), carried under the job's ``summary`` field.
_PREVIEW_SUMMARY = {
    "source": "sample",
    "paradigm": "rest",
    "format": "sample-1.0",
    "fingerprint": "sha256:abc123",
    "counts": {"services": 1, "operations": 2, "types": 3, "channels": 0},
    "lint": {
        "score": 88,
        "grade": "B",
        "report_fingerprint": "lintfp",
        "findings": 2,
        "severity_counts": {"warning": 2},
    },
    "dry_run": False,
    "incremental_mode": False,
    "persisted": False,
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_sources(httpx_mock: object, *, sources: list | None = None) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL,
        method="GET",
        json={"sources": _SOURCES if sources is None else sources},
    )


def _mock_import_completed(httpx_mock: object, *, summary: dict | None = None) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL,
        method="POST",
        status_code=202,
        json={"job_id": _JOB_ID, "state": "pending"},
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "summary": _PREVIEW_SUMMARY if summary is None else summary,
        },
    )


def _post_body(httpx_mock: object) -> dict:
    """Return the parsed JSON body of the spec-import POST."""
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


# --- import --list ---------------------------------------------------------


def test_list_sources_table(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    result = runner.invoke(app, ["import", "--list"])
    assert result.exit_code == 0, result.output
    text = strip_ansi(result.output)
    assert "openapi" in text
    assert "sample" in text
    # The label may wrap at narrow terminal widths; assert on a stable token.
    assert "OpenAPI" in text
    assert "rest" in text


def test_list_sources_json(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    result = runner.invoke(app, ["--json", "import", "--list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [s["key"] for s in payload["sources"]] == ["openapi", "sample"]


def test_list_sources_empty(httpx_mock: object) -> None:
    _mock_sources(httpx_mock, sources=[])
    result = runner.invoke(app, ["import", "--list"])
    assert result.exit_code == 0, result.output
    assert "No import sources" in strip_ansi(result.output)


# --- import <format> <input> ----------------------------------------------


def test_generic_dispatch_uploads_and_summarizes(
    httpx_mock: object, tmp_path: Path
) -> None:
    document = tmp_path / "thing.sample"
    document.write_bytes(b"hello-sample-bytes")
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "sample", str(document)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "sample"
    assert body["metadata"]["options"]["dry_run"] is False
    assert base64.b64decode(body["document_base64"]) == b"hello-sample-bytes"

    text = strip_ansi(result.output)
    assert "Import preview completed." in text
    assert "sample (sample-1.0)" in text
    assert "Lint score: 88 (B)" in text
    assert "preview only" in text


def test_generic_dispatch_with_file_flag_and_dry_run(
    httpx_mock: object, tmp_path: Path
) -> None:
    document = tmp_path / "thing.sample"
    document.write_bytes(b"abc")
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app, ["import", "sample", "--file", str(document), "--dry-run"]
    )
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["options"]["dry_run"] is True
    assert "Dry run completed" in strip_ansi(result.output)


def test_generic_dispatch_json_mode_emits_raw_summary(
    httpx_mock: object, tmp_path: Path
) -> None:
    document = tmp_path / "thing.sample"
    document.write_bytes(b"abc")
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app, ["--json", "--no-progress", "import", "sample", str(document)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"] == "sample"
    assert payload["counts"]["operations"] == 2


def test_generic_dispatch_unknown_format(httpx_mock: object, tmp_path: Path) -> None:
    document = tmp_path / "thing.txt"
    document.write_text("x")
    _mock_sources(httpx_mock)

    result = runner.invoke(app, ["import", "graphql", str(document)])
    assert result.exit_code == EXIT_USAGE
    text = strip_ansi(result.output)
    assert "Unknown import format 'graphql'" in text
    assert "openapi, sample" in text


def test_generic_dispatch_requires_input() -> None:
    result = runner.invoke(app, ["import", "sample"])
    assert result.exit_code == EXIT_USAGE
    assert "Provide an input document" in strip_ansi(result.output)


def test_dedicated_verb_takes_precedence_over_generic() -> None:
    """``import openapi`` resolves to the full-featured verb, not the generic seam."""
    result = runner.invoke(app, ["import", "openapi", "--help"])
    assert result.exit_code == 0, result.output
    text = strip_ansi(result.output)
    # The dedicated verb carries format-specific flags the generic seam does not.
    assert "--project-name" in text
    assert "--publish" in text


def test_generic_dispatch_rejects_multiple_inputs(tmp_path: Path) -> None:
    document = tmp_path / "thing.sample"
    document.write_text("x")
    result = runner.invoke(
        app, ["import", "sample", str(document), "--url", "http://x/y"]
    )
    assert result.exit_code == EXIT_USAGE
    assert "Provide only one input" in strip_ansi(result.output)
