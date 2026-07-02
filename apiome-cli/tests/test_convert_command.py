"""Tests for the ``convert`` command (MFI-22.6).

Drive ``apiome convert`` against a mocked REST convert endpoint (``pytest-httpx``): the request
shape (dryRun query + body target/defaults), the human + ``--json`` output, ``--out`` write-out on a
dry-run, and the low-fidelity non-zero exit hint gated by ``--force``.
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

_ITEM = "cat-1"
_CONVERT_BASE = f"http://localhost:8000/v1/catalog/acme-corp/{_ITEM}/convert"

_OPENAPI_DOC = {"openapi": "3.1.0", "info": {"title": "Ping", "version": "1.0.0"}, "paths": {}}


def _report(tier: str = "medium", grade: str = "C", score: int = 74) -> dict:
    return {
        "score": score, "grade": grade, "tier": tier,
        "items": [{"title": "Servers", "coverage": "missing", "reason": "no servers"}],
        "losses": [], "coverage_counts": {}, "penalty": 100 - score,
    }


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def test_convert_commit_human_output(httpx_mock) -> None:
    """A commit prints the fidelity summary + the created project/version ids."""
    httpx_mock.add_response(
        url=f"{_CONVERT_BASE}?dryRun=false",
        json={
            "report": _report(), "projectId": "proj-9", "versionId": "1.0.0",
            "versionRecordId": "ver-9", "createdProject": True, "reconverted": False,
            "provenanceId": "prov-9",
        },
    )
    result = runner.invoke(app, ["convert", _ITEM, "--to", "openapi"])
    assert result.exit_code == EXIT_SUCCESS
    assert "fidelity C (74/100), tier medium" in result.stdout
    assert "Converted into project proj-9 version 1.0.0" in result.stdout


def test_convert_dry_run_sends_dryrun_query_and_body(httpx_mock) -> None:
    """--dry-run hits ?dryRun=true and posts target/dryRun in the body; no commit is claimed."""
    httpx_mock.add_response(
        url=f"{_CONVERT_BASE}?dryRun=true",
        json={"report": _report(), "openapi": _OPENAPI_DOC, "sourceFormat": "graphql", "target": "openapi"},
    )
    result = runner.invoke(app, ["convert", _ITEM, "--dry-run"])
    assert result.exit_code == EXIT_SUCCESS
    request = httpx_mock.get_requests()[-1]
    assert request.url.params["dryRun"] == "true"
    body = json.loads(request.content)
    assert body["target"] == "openapi"
    assert body["dryRun"] is True
    assert "into project" not in result.stdout


def test_convert_forwards_defaults(httpx_mock) -> None:
    """--title/--api-version/--server become the request defaults bag."""
    httpx_mock.add_response(
        url=f"{_CONVERT_BASE}?dryRun=true",
        json={"report": _report(), "openapi": _OPENAPI_DOC, "target": "openapi"},
    )
    result = runner.invoke(
        app,
        ["convert", _ITEM, "--dry-run", "--title", "My API", "--api-version", "2.0.0",
         "--server", "https://a", "--server", "https://b"],
    )
    assert result.exit_code == EXIT_SUCCESS
    body = json.loads(httpx_mock.get_requests()[-1].content)
    assert body["defaults"] == {"title": "My API", "version": "2.0.0", "servers": ["https://a", "https://b"]}


def test_convert_out_writes_openapi_document(tmp_path: Path, httpx_mock) -> None:
    """--out writes the would-be OpenAPI document to a file on a dry-run."""
    httpx_mock.add_response(
        url=f"{_CONVERT_BASE}?dryRun=true",
        json={"report": _report(), "openapi": _OPENAPI_DOC, "target": "openapi"},
    )
    out = tmp_path / "converted.openapi.json"
    result = runner.invoke(app, ["convert", _ITEM, "--dry-run", "--out", str(out)])
    assert result.exit_code == EXIT_SUCCESS
    written = json.loads(out.read_text())
    assert written == _OPENAPI_DOC


def test_convert_json_output(httpx_mock) -> None:
    """--json emits the raw API response on stdout."""
    payload = {"report": _report(), "openapi": _OPENAPI_DOC, "target": "openapi"}
    httpx_mock.add_response(url=f"{_CONVERT_BASE}?dryRun=true", json=payload)
    result = runner.invoke(app, ["--json", "convert", _ITEM, "--dry-run"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["target"] == "openapi"


def test_convert_low_tier_exits_nonzero(httpx_mock) -> None:
    """A low-fidelity result exits non-zero as a hint (the summary still prints)."""
    httpx_mock.add_response(
        url=f"{_CONVERT_BASE}?dryRun=true",
        json={"report": _report(tier="low", grade="F", score=30), "openapi": _OPENAPI_DOC, "target": "openapi"},
    )
    result = runner.invoke(app, ["convert", _ITEM, "--dry-run"])
    assert result.exit_code == EXIT_ERROR
    assert "Low fidelity" in result.stdout


def test_convert_low_tier_force_exits_zero(httpx_mock) -> None:
    """--force accepts a low-fidelity result and exits zero."""
    httpx_mock.add_response(
        url=f"{_CONVERT_BASE}?dryRun=false",
        json={
            "report": _report(tier="low", grade="F", score=30), "projectId": "p", "versionId": "1.0.0",
            "versionRecordId": "v", "createdProject": True, "reconverted": False, "provenanceId": "pr",
        },
    )
    result = runner.invoke(app, ["convert", _ITEM, "--force"])
    assert result.exit_code == EXIT_SUCCESS


def test_convert_rejects_unknown_target() -> None:
    """--to only accepts 'openapi' today; anything else is a usage error (no HTTP)."""
    result = runner.invoke(app, ["convert", _ITEM, "--to", "graphql"])
    assert result.exit_code == EXIT_USAGE


def test_convert_out_requires_dry_run() -> None:
    """--out only makes sense for a dry-run; using it on a commit is a usage error."""
    result = runner.invoke(app, ["convert", _ITEM, "--out", "x.json"])
    assert result.exit_code == EXIT_USAGE
