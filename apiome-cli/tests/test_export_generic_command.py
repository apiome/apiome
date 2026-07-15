"""Tests for generic ``apiome export <format> <artifact>`` (MFX-8.1 / #3863)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.export_dispatch import is_zip_bundle, parse_export_options, write_export_artifact
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_PROJECT = {"id": _PROJECT_ID, "name": "Payments API", "slug": "payments-api", "enabled": True}

_OPENAPI_BYTES = (_FIXTURES / "export-openapi-lossless.json").read_bytes()
_TARGETS = json.loads((_FIXTURES / "export-targets.json").read_text())
_JOB_LOSSLESS = json.loads((_FIXTURES / "export-job-completed-lossless.json").read_text())
_JOB_LOSSY = json.loads((_FIXTURES / "export-job-completed-lossy.json").read_text())

_BASE = "http://localhost:8000"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_JOB_STATUS_URL = f"{_BASE}/v1/export/acme-corp/jobs/{_JOB_ID}"
_DOWNLOAD_URL = f"{_BASE}/v1/export/acme-corp/jobs/{_JOB_ID}/download"
_TARGETS_URL = (
    f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
)
_TARGETS_URL_NO_VERSION = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


_PREVIEW_URL = f"{_BASE}/v1/export/acme-corp/preview"
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT
    )


def _mock_preview(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_PREVIEW_URL, method="POST", json=_PREVIEW)


def _mock_targets(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)


def _mock_job_pipeline(
    httpx_mock: object,
    *,
    status_payload: dict,
    download_body: bytes,
    content_type: str = "application/json",
) -> None:
    httpx_mock.add_response(
        url=_JOBS_URL,
        method="POST",
        json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"},
        status_code=202,
    )
    httpx_mock.add_response(url=_JOB_STATUS_URL, json=status_payload)
    httpx_mock.add_response(
        url=_DOWNLOAD_URL,
        content=download_body,
        headers={
            "Content-Type": content_type,
            "Content-Disposition": 'attachment; filename="openapi.json"',
        },
    )


def _generic_args(out: str) -> list[str]:
    return [
        "export",
        "openapi-3.1",
        "payments-api",
        "--version",
        "1.0.0",
        "--out",
        out,
        "--poll-interval",
        "0.1",
    ]


def test_resolve_export_target_matches_key_and_format() -> None:
    assert resolve_export_target("openapi", _TARGETS["targets"]) == "openapi"
    assert resolve_export_target("openapi-3.1", _TARGETS["targets"]) == "openapi"
    assert resolve_export_target("sample", _TARGETS["targets"]) == "sample"


def test_parse_export_options_parses_json_values() -> None:
    assert parse_export_options(['openapi_version="3.1"', "flag=true"]) == {
        "openapi_version": "3.1",
        "flag": True,
    }


def test_is_zip_bundle_detects_zip_content_type_and_magic() -> None:
    assert is_zip_bundle(content_type="application/zip", body=b"")
    assert is_zip_bundle(content_type=None, body=b"PK\x03\x04xx")


def test_write_export_artifact_unzips_bundle_to_directory(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("widgets.proto", 'syntax = "proto3";\n')
        archive.writestr("pkg/common.proto", "message C {}\n")
    body = buffer.getvalue()
    out_dir = tmp_path / "bundle"

    total, effective = write_export_artifact(
        body,
        out=str(out_dir),
        content_type="application/zip",
        files=None,
        disposition_filename=None,
    )

    assert effective == str(out_dir)
    assert total > 0
    assert (out_dir / "widgets.proto").read_text() == 'syntax = "proto3";\n'
    assert (out_dir / "pkg" / "common.proto").read_text() == "message C {}\n"


def test_generic_export_writes_single_file_and_lossless_exit(
    httpx_mock: object, tmp_path: Path
) -> None:
    _mock_scope(httpx_mock)
    _mock_targets(httpx_mock)
    _mock_preview(httpx_mock)
    _mock_job_pipeline(httpx_mock, status_payload=_JOB_LOSSLESS, download_body=_OPENAPI_BYTES)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, _generic_args(str(out_file)))

    assert result.exit_code == EXIT_SUCCESS
    assert out_file.read_bytes() == _OPENAPI_BYTES
    assert "fidelity lossless" in result.stderr

    job_request = next(
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/jobs") and r.method == "POST"
    )
    body = json.loads(job_request.content)
    assert body == {
        "artifact": _PROJECT_ID,
        "target": "openapi",
        "version": "1.0.0",
        "confirm": False,
        "acknowledged_snapshot": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    }


def test_generic_export_lossy_exits_nonzero(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    _mock_targets(httpx_mock)
    _mock_preview(httpx_mock)
    lossy_job = {**_JOB_LOSSY, "job_id": _JOB_ID}
    _mock_job_pipeline(httpx_mock, status_payload=lossy_job, download_body=_OPENAPI_BYTES)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, _generic_args(str(out_file)))

    assert result.exit_code == EXIT_ERROR
    assert out_file.read_bytes() == _OPENAPI_BYTES
    assert "Lossy export" in result.stderr


def test_generic_export_force_accepts_lossy(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    _mock_targets(httpx_mock)
    _mock_preview(httpx_mock)
    _mock_job_pipeline(httpx_mock, status_payload=_JOB_LOSSY, download_body=_OPENAPI_BYTES)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, [*_generic_args(str(out_file)), "--force"])

    assert result.exit_code == EXIT_SUCCESS


def test_generic_export_json_metadata(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    _mock_targets(httpx_mock)
    _mock_preview(httpx_mock)
    _mock_job_pipeline(httpx_mock, status_payload=_JOB_LOSSLESS, download_body=_OPENAPI_BYTES)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(app, ["--json", *_generic_args(str(out_file))])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["fidelity_target"] == "openapi"
    assert payload["fidelity"]["status"] == "lossless"
    assert payload["snapshot_hash"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_generic_export_unknown_format_is_usage_error(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_TARGETS_URL_NO_VERSION, json=_TARGETS)

    result = runner.invoke(
        app,
        ["export", "not-a-format", "payments-api", "--out", str(tmp_path / "x.json")],
    )

    assert result.exit_code == EXIT_USAGE
    assert "Unknown export format" in result.stderr


def test_generic_export_missing_out_is_usage_error() -> None:
    result = runner.invoke(app, ["export", "sample", "payments-api"])
    assert result.exit_code == EXIT_USAGE
    assert "--out is required" in result.stderr
