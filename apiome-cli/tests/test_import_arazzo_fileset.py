"""Tests for ``apiome import arazzo`` with a multi-file fileset — COA-1.2 (#7038).

An archive (``.zip``/``.tar.gz``) or a directory holding an Arazzo workflow and the
OpenAPI/AsyncAPI files its ``sourceDescriptions`` name is sent to the registry's Arazzo
adapter as one fileset, and the completed job's ``arazzo_sources`` block — where each
source was resolved from, and every unresolved one with its reason code — is printed.
A single Arazzo document keeps its current not-supported behaviour
(``test_import_arazzo_command.py``). These tests drive the command against a mocked REST
service.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.import_.sources import format_arazzo_sources
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_ARAZZO = {
    "key": "arazzo",
    "label": "Arazzo",
    "description": "Import an Arazzo workflow description.",
    "icon": "workflow",
    "paradigm": "rest",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["arazzo"],
    "file_extensions": [".arazzo.yaml", ".yaml", ".json"],
}

_FLOW = """arazzo: 1.0.1
info: {title: Adopt a pet, version: 1.0.0}
sourceDescriptions:
  - {name: pets, url: ./pets.yaml, type: openapi}
  - {name: users, url: ./users.yaml, type: openapi}
workflows:
  - workflowId: adopt
    steps:
      - {stepId: find, operationId: listPets}
"""

_REPORT: dict[str, Any] = {
    "resolved": 2,
    "unresolved": 1,
    "by_tier": {"fileset": 2, "catalog": 0, "remote": 0},
    "sources": [
        {"name": "pets", "url": "./pets.yaml", "tier": "fileset", "path": "pets.yaml"},
        {"name": "users", "url": "./users.yaml", "tier": "fileset", "path": "users.yaml"},
    ],
    "unresolved_sources": [
        {
            "name": "billing",
            "url": "https://apis.example.com/billing.yaml",
            "reason": "resolution-disabled",
            "detail": "remote resolution is off for this import",
        }
    ],
    "truncated": False,
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


@pytest.fixture()
def workflow_dir(tmp_path: Path) -> Path:
    """A directory with a workflow and the two OpenAPI files it calls."""
    root = tmp_path / "adopt"
    root.mkdir()
    (root / "flow.arazzo.yaml").write_text(_FLOW, encoding="utf-8")
    (root / "pets.yaml").write_text("openapi: 3.0.3\ninfo: {title: Pets, version: '1'}\npaths: {}\n")
    (root / "users.yaml").write_text("openapi: 3.0.3\ninfo: {title: Users, version: '1'}\npaths: {}\n")
    return root


def _zip(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(directory.iterdir()):
            archive.writestr(path.name, path.read_text(encoding="utf-8"))
    return buffer.getvalue()


def _mock_import(httpx_mock: Any, *, report: dict[str, Any] | None = _REPORT) -> None:
    summary: dict[str, Any] = {
        "source": "arazzo",
        "paradigm": "rest",
        "format": "arazzo",
        "fingerprint": "sha256:flow",
        "counts": {"services": 1, "operations": 1, "types": 0, "channels": 0},
        "lint": {"score": 95, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
        "dry_run": True,
        "incremental_mode": False,
        "persisted": False,
    }
    if report is not None:
        summary["arazzo_sources"] = report
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_ARAZZO]})
    httpx_mock.add_response(
        url=_IMPORT_URL, method="POST", status_code=202, json={"job_id": _JOB_ID, "state": "pending"}
    )
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json={"state": "completed", "job_id": _JOB_ID, "summary": summary},
    )


def _post_body(httpx_mock: Any) -> dict:
    for request in httpx_mock.get_requests():
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


def test_an_archive_is_sent_to_the_arazzo_adapter(httpx_mock: Any, workflow_dir: Path, tmp_path: Path):
    archive = tmp_path / "adopt.zip"
    archive.write_bytes(_zip(workflow_dir))
    _mock_import(httpx_mock)

    result = runner.invoke(app, ["import", "arazzo", str(archive), "--dry-run"])

    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "arazzo"
    assert body["filename"] == "adopt.zip"
    assert base64.b64decode(body["document_base64"]) == archive.read_bytes()
    text = strip_ansi(result.output)
    assert "Arazzo sources: 2 resolved (2 fileset), 1 unresolved" in text
    assert "billing https://apis.example.com/billing.yaml: resolution-disabled" in text


def test_a_directory_is_packed_and_the_server_picks_the_workflow(httpx_mock: Any, workflow_dir: Path):
    _mock_import(httpx_mock)

    result = runner.invoke(app, ["import", "arazzo", str(workflow_dir)])

    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["filename"] == "adopt.zip"
    # No directory convention for Arazzo: the server ranks the members (the workflow wins).
    assert "archive_root" not in body["metadata"].get("options", {})
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(body["document_base64"]))) as packed:
        assert packed.namelist() == ["flow.arazzo.yaml", "pets.yaml", "users.yaml"]
    assert "Packed 3 file(s)" in strip_ansi(result.output)


def test_root_names_the_workflow_explicitly(httpx_mock: Any, workflow_dir: Path):
    _mock_import(httpx_mock)

    result = runner.invoke(app, ["import", "arazzo", str(workflow_dir), "--root", "flow.arazzo.yaml"])

    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["archive_root"] == "flow.arazzo.yaml"


def test_json_mode_emits_the_report_verbatim(httpx_mock: Any, workflow_dir: Path):
    _mock_import(httpx_mock)

    result = runner.invoke(app, ["--json", "import", "arazzo", str(workflow_dir)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["arazzo_sources"] == _REPORT


def test_format_arazzo_sources_renders_nothing_without_a_block():
    assert format_arazzo_sources(None) == []
    assert format_arazzo_sources("nope") == []


def test_format_arazzo_sources_names_every_tier_and_marks_truncation():
    lines = format_arazzo_sources(
        {
            "resolved": 3,
            "unresolved": 1,
            "by_tier": {"fileset": 1, "catalog": 1, "remote": 1},
            "unresolved_sources": [{"name": "", "url": "", "reason": "invalid-source-description"}],
            "truncated": True,
        }
    )
    assert lines[0] == "  Arazzo sources: 3 resolved (1 fileset, 1 catalog, 1 remote), 1 unresolved"
    assert lines[1] == "    - (unnamed): invalid-source-description"
    assert "truncated" in lines[2]
