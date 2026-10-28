"""``apiome export <format> --targets / --items`` (E1-3, #6219).

Pins the multi-target (ARTIFACT + ``--targets``) and batch (``--items``) shapes of the generic
export command: the job body each submits, the per-item outcome table, the archive write, and
the exit codes (0 all completed, 7 some items failed, the job's failure code when all failed).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_ERROR,
    EXIT_EXPORT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.export_multi_dispatch import (
    outcome_rows,
    parse_item_refs,
    parse_target_list,
)
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets.json").read_text())

_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_B = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_BASE = "http://localhost:8000"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_DOWNLOAD = f"/v1/export/acme-corp/jobs/{_JOB_ID}/download"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _zip(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "{}")
    return buffer.getvalue()


def _batch_item(artifact: str, state: str, *, error: str | None = None) -> dict:
    return {
        "artifact": artifact,
        "version": "latest",
        "version_label": "1.0.0",
        "target": "openapi-3.1",
        "state": state,
        "tier": "lossless" if state == "completed" else None,
        "directory": f"{artifact[:4]}/openapi-3.1" if state == "completed" else None,
        "error": {"code": "SOURCE_LOAD_FAILED", "message": error} if error else None,
    }


def _mock_job(httpx_mock, *, result: dict | None, state: str = "completed", error: dict | None = None):
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/targets?artifact={_A}", json=_TARGETS)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", json={"job_id": _JOB_ID})
    httpx_mock.add_response(
        url=f"{_JOBS_URL}/{_JOB_ID}",
        json={"job_id": _JOB_ID, "state": state, "percent": 100, "events": [], "result": result, "error": error},
    )
    if result is not None:
        httpx_mock.add_response(
            url=f"{_BASE}{_DOWNLOAD}",
            content=_zip(["manifest.json", "aaaa/openapi-3.1/openapi.json"]),
            headers={"Content-Type": "application/zip"},
        )


def _posted_body(httpx_mock) -> dict:
    [request] = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# Pure parsing
# ---------------------------------------------------------------------------
def test_parse_target_list_drops_blanks_and_repeats():
    assert parse_target_list(" graphql, ,openapi,graphql") == ["graphql", "openapi"]


def test_parse_item_refs_reads_optional_versions():
    assert parse_item_refs("a, b@1.0.0") == [("a", None), ("b", "1.0.0")]


@pytest.mark.parametrize("raw", ["a,,b", "a@", "a,a"])
def test_parse_item_refs_rejects_bad_entries(raw):
    with pytest.raises(Exception) as excinfo:
        parse_item_refs(raw)
    assert getattr(excinfo.value, "exit_code", None) == EXIT_USAGE


def test_outcome_rows_cover_a_multi_target_result():
    result = {
        "artifact": _A,
        "version_label": "2.0.0",
        "targets": [{"target": "openapi-3.1", "directory": "openapi-3.1", "fidelity": {"summary": {"tier": "lossy"}}}],
    }
    assert outcome_rows(result) == [
        {"item": _A, "version": "2.0.0", "target": "openapi-3.1", "state": "completed", "tier": "lossy",
         "detail": "openapi-3.1"},
    ]


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
def test_items_run_one_batch_job_and_exit_zero_when_all_complete(httpx_mock, tmp_path):
    result = {
        "artifact": "2 items",
        "download_path": _DOWNLOAD,
        "batch": {"item_count": 2, "failed_count": 0, "items": [_batch_item(_A, "completed"), _batch_item(_B, "completed")]},
    }
    _mock_job(httpx_mock, result=result)
    out = tmp_path / "bundle"
    outcome = runner.invoke(
        app, ["export", "sample", "--items", f"{_A},{_B}@1.0.0", "--out", str(out)], terminal_width=200
    )
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _posted_body(httpx_mock) == {
        "confirm": False,
        "items": [{"artifact": _A}, {"artifact": _B, "version": "1.0.0"}],
        "targets": [{"target": "sample"}],
    }
    assert (out / "aaaa/openapi-3.1/openapi.json").exists()
    assert "completed" in outcome.stdout


def test_items_exit_seven_when_some_items_failed(httpx_mock, tmp_path):
    result = {
        "artifact": "2 items",
        "download_path": _DOWNLOAD,
        "batch": {
            "item_count": 2,
            "failed_count": 1,
            "items": [_batch_item(_A, "completed"), _batch_item(_B, "failed", error="Artifact not found.")],
        },
    }
    _mock_job(httpx_mock, result=result)
    outcome = runner.invoke(
        app, ["export", "sample", "--items", f"{_A},{_B}", "--out", str(tmp_path / "o")], terminal_width=200
    )
    assert outcome.exit_code == EXIT_EXPORT_PARTIAL
    assert "Artifact not found." in outcome.stdout
    assert "1 of 2 items failed" in outcome.stderr


def test_items_fail_when_every_item_failed(httpx_mock, tmp_path):
    _mock_job(
        httpx_mock,
        result=None,
        state="failed",
        error={"code": "EXPORT_BATCH_FAILED", "message": "Every item failed.", "category": "source"},
    )
    outcome = runner.invoke(app, ["export", "sample", "--items", _A, "--out", str(tmp_path / "o")])
    assert outcome.exit_code not in (EXIT_SUCCESS, EXIT_EXPORT_PARTIAL)


def test_targets_run_one_multi_target_job(httpx_mock, tmp_path):
    result = {
        "artifact": _A,
        "download_path": _DOWNLOAD,
        "fidelity_rollup": {"tier": "lossless"},
        "targets": [
            {"target": "openapi-3.1", "directory": "openapi-3.1", "fidelity": {"summary": {"tier": "lossless"}}},
            {"target": "sample", "directory": "sample", "fidelity": {"summary": {"tier": "lossless"}}},
        ],
    }
    _mock_job(httpx_mock, result=result)
    outcome = runner.invoke(
        app,
        ["export", "sample", _A, "--targets", "openapi", "--option", "pretty=true", "--out", str(tmp_path / "o.zip")],
        terminal_width=200,
    )
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _posted_body(httpx_mock) == {
        "confirm": False,
        "artifact": _A,
        "targets": [{"target": "sample", "options": {"pretty": True}}, {"target": "openapi"}],
    }
    assert (tmp_path / "o.zip").read_bytes()[:2] == b"PK"


def test_targets_lossy_rollup_exits_non_zero_without_force(httpx_mock, tmp_path):
    result = {"artifact": _A, "download_path": _DOWNLOAD, "fidelity_rollup": {"tier": "lossy"}, "targets": []}
    _mock_job(httpx_mock, result=result)
    outcome = runner.invoke(app, ["export", "sample", _A, "--targets", "openapi", "--out", str(tmp_path / "o")])
    assert outcome.exit_code == EXIT_ERROR


@pytest.mark.parametrize(
    "args",
    [
        ["export", "sample", "--out", "o"],  # neither ARTIFACT nor --items
        ["export", "sample", _A, "--items", _B, "--out", "o"],
        ["export", "sample", "--items", _A, "--version", "1.0.0", "--out", "o"],
        ["export", "sample", "--items", _A, "--out", "-"],
        ["export", "sample", "--items", _A, "--min-grade", "B", "--out", "o"],
        ["export", "sample", "--items", ",".join(f"{_A[:-2]}{i:02d}" for i in range(51)),
         "--targets", "openapi", "--out", "o"],
    ],
)
def test_inconsistent_requests_are_usage_errors(args):
    outcome = runner.invoke(app, args)
    assert outcome.exit_code == EXIT_USAGE, outcome.output
