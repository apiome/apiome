"""Tests for ``apiome export … --overlay <file>`` (GVM-4.2, #5877)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.export_overlays import MAX_OVERLAYS, format_overlay_summary, load_overlay_files
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Payments API", "slug": "payments-api", "enabled": True}

_OPENAPI_BYTES = (_FIXTURES / "export-openapi-lossless.json").read_bytes()
_TARGETS = json.loads((_FIXTURES / "export-targets.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
_JOB_LOSSLESS = json.loads((_FIXTURES / "export-job-completed-lossless.json").read_text())

_BASE = "http://localhost:8000"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_JOB_STATUS_URL = f"{_BASE}/v1/export/acme-corp/jobs/{_JOB_ID}"
_DOWNLOAD_URL = f"{_BASE}/v1/export/acme-corp/jobs/{_JOB_ID}/download"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_PREVIEW_URL = f"{_BASE}/v1/export/acme-corp/preview"

_PARTNER_YAML = """\
overlay: 1.0.0
info:
  title: Partner edition
  version: 1.0.0
actions:
  - target: $.info
    update:
      title: Payments for Partners
"""

_OVERLAY_REPORT = {
    "applied": ["partner.yaml"],
    "ledger": [
        {
            "pointer": "/info/title",
            "kind": "replaced",
            "overlay": "partner.yaml",
            "action_index": 0,
            "target": "$.info",
            "detail": "The value at /info/title was replaced by overlay 'partner.yaml'.",
        }
    ],
    "findings": [
        {
            "rule": "overlay.unmatched-target",
            "severity": "warning",
            "overlay": "partner.yaml",
            "action_index": 1,
            "target": "$.paths['/gone']",
            "message": "Target matched nothing.",
        }
    ],
    "changes": 1,
    "truncated": False,
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _mock_job(httpx_mock: object) -> None:
    """Mock project lookup, targets, preview and a completed job carrying an overlay report."""
    status = copy.deepcopy(_JOB_LOSSLESS)
    status["result"]["overlay"] = _OVERLAY_REPORT
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=_PREVIEW_URL, method="POST", json=_PREVIEW)
    httpx_mock.add_response(
        url=_JOBS_URL,
        method="POST",
        json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"},
        status_code=202,
    )
    httpx_mock.add_response(url=_JOB_STATUS_URL, json=status)
    httpx_mock.add_response(
        url=_DOWNLOAD_URL,
        content=_OPENAPI_BYTES,
        headers={
            "Content-Type": "application/json",
            "Content-Disposition": 'attachment; filename="openapi.json"',
        },
    )


def _job_body(httpx_mock: object) -> dict:
    request = next(
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/jobs") and r.method == "POST"
    )
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# load_overlay_files / format_overlay_summary
# ---------------------------------------------------------------------------
def test_load_overlay_files_reads_yaml_and_json_in_order(tmp_path: Path) -> None:
    first = _write(tmp_path, "partner.yaml", _PARTNER_YAML)
    second = _write(
        tmp_path,
        "env.json",
        json.dumps({"overlay": "1.1.0", "info": {"title": "e", "version": "1"}, "actions": []}),
    )
    overlays = load_overlay_files([first, second])
    assert [o["name"] for o in overlays] == ["partner.yaml", "env.json"]
    assert overlays[0]["document"]["actions"][0]["update"]["title"] == "Payments for Partners"
    assert load_overlay_files([]) == []


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("base.yaml", "openapi: 3.1.0\ninfo: {title: t, version: '1'}\n"),
        ("broken.yaml", "overlay: [unclosed\n"),
        ("list.json", "[1, 2]"),
    ],
)
def test_load_overlay_files_refuses_a_non_overlay(tmp_path: Path, name: str, text: str) -> None:
    with pytest.raises(typer.Exit) as exc:
        load_overlay_files([_write(tmp_path, name, text)])
    assert exc.value.exit_code == EXIT_USAGE


def test_load_overlay_files_refuses_a_missing_file_and_too_many(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        load_overlay_files([str(tmp_path / "nope.yaml")])
    path = _write(tmp_path, "partner.yaml", _PARTNER_YAML)
    with pytest.raises(typer.Exit):
        load_overlay_files([path] * (MAX_OVERLAYS + 1))


def test_format_overlay_summary_lists_the_chain_and_each_finding() -> None:
    lines = format_overlay_summary(_OVERLAY_REPORT)
    assert lines[0] == "Overlays: applied partner.yaml — 1 value(s) changed"
    assert "overlay.unmatched-target in 'partner.yaml'" in lines[1]
    assert "target $.paths['/gone']" in lines[1]
    assert format_overlay_summary(None) == []
    assert "first 500" in format_overlay_summary({**_OVERLAY_REPORT, "truncated": True})[0]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def test_generic_export_sends_overlays_and_skips_the_preview_snapshot(
    httpx_mock: object, tmp_path: Path
) -> None:
    _mock_job(httpx_mock)
    overlay = _write(tmp_path, "partner.yaml", _PARTNER_YAML)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(
        app,
        [
            "export", "openapi-3.1", "payments-api", "--version", "1.0.0",
            "--out", str(out_file), "--poll-interval", "0.1", "--overlay", overlay,
        ],
    )

    assert result.exit_code == EXIT_SUCCESS, result.output
    body = _job_body(httpx_mock)
    assert body["overlays"][0]["name"] == "partner.yaml"
    assert body["overlays"][0]["document"]["overlay"] == "1.0.0"
    # The preview cannot see the overlays, so the job is not pinned to its snapshot.
    assert "acknowledged_snapshot" not in body
    assert "Overlays: applied partner.yaml" in result.stderr
    assert "overlay.unmatched-target" in result.stderr


def test_export_openapi_with_overlay_runs_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_job(httpx_mock)
    overlay = _write(tmp_path, "partner.yaml", _PARTNER_YAML)
    out_file = tmp_path / "openapi.json"

    result = runner.invoke(
        app,
        [
            "export", "openapi", "--project", "payments-api", "--version", "1.0.0",
            "--output", str(out_file), "--overlay", overlay,
        ],
    )

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out_file.read_bytes() == _OPENAPI_BYTES
    assert _job_body(httpx_mock)["target"] == "openapi"


def test_export_openapi_overlay_refuses_yaml(tmp_path: Path) -> None:
    overlay = _write(tmp_path, "partner.yaml", _PARTNER_YAML)
    result = runner.invoke(
        app,
        [
            "export", "openapi", "--project", "payments-api", "--version", "1.0.0",
            "--output", str(tmp_path / "o.yaml"), "--yaml", "--overlay", overlay,
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "drop --yaml" in result.stderr


def test_overlay_with_items_is_a_usage_error(tmp_path: Path) -> None:
    overlay = _write(tmp_path, "partner.yaml", _PARTNER_YAML)
    result = runner.invoke(
        app,
        ["export", "openapi-3.1", "--items", "a,b", "--out", str(tmp_path / "x.zip"), "--overlay", overlay],
    )
    assert result.exit_code == EXIT_USAGE
    assert "cannot be combined with --items" in result.stderr
