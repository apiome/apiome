"""Tests for ``apiome import smithy`` — MFI-17.5 (#3812).

Smithy rides the registry-driven adapter import (MFI-1.4). Its three inputs reach the server as
follows, against a mocked REST service:

* a ``.smithy`` file and a JSON AST ``.json`` are sent verbatim;
* a model directory is packed into the archive an upload would send (MFI-14.5); Smithy has no
  entry-point convention, so no root is sent and the server ranks the members — a multi-file
  model is assembled through the Smithy CLI there (MFI-17.1).
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "smithy"
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_SMITHY = {
    "key": "smithy",
    "label": "Smithy",
    "description": "Import a Smithy IDL model (structures, enums, services, operations).",
    "icon": "hammer",
    "paradigm": "rpc",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["smithy"],
    "file_extensions": [".smithy", ".json", ".zip", ".tar.gz", ".tgz", ".tar"],
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_SMITHY]})  # type: ignore[attr-defined]
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
                "source": "smithy",
                "paradigm": "rpc",
                "format": "smithy",
                "fingerprint": "sha256:smithy",
                "counts": {"services": 1, "operations": 3, "types": 8, "channels": 0},
                "lint": {"score": 88, "grade": "B", "report_fingerprint": "fp", "findings": 2, "severity_counts": {}},
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


@pytest.mark.parametrize(
    "name", ["01-weather-service.smithy", "07-json-ast-weather.json"], ids=["idl", "json-ast"]
)
def test_a_model_file_is_sent_verbatim(httpx_mock: object, name: str) -> None:
    _mock_import(httpx_mock)
    path = _EXAMPLES / name
    result = runner.invoke(app, ["import", "smithy", str(path)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "smithy"
    assert body["filename"] == name
    assert base64.b64decode(body["document_base64"]) == path.read_bytes()
    assert "Paradigm: rpc" in strip_ansi(result.output)


def test_a_model_directory_is_sent_as_an_archive_without_a_root(httpx_mock: object, tmp_path: Path) -> None:
    model = tmp_path / "weather-model"
    model.mkdir()
    (model / "main.smithy").write_text('$version: "2"\nnamespace example.weather\n', encoding="utf-8")
    (model / "common.smithy").write_text('$version: "2"\nnamespace example.common\n', encoding="utf-8")
    (model / "smithy-build.json").write_text('{"version": "1.0"}', encoding="utf-8")
    (model / "build" / "smithy").mkdir(parents=True)
    (model / "build" / "smithy" / "out.json").write_text("{}", encoding="utf-8")
    _mock_import(httpx_mock)

    result = runner.invoke(app, ["import", "smithy", str(model)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["filename"] == "weather-model.zip"
    assert "archive_root" not in body["metadata"].get("options", {})
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(body["document_base64"]))) as archive:
        # smithy-build.json travels with the model (the server never stages it); build output does not.
        assert archive.namelist() == ["common.smithy", "main.smithy", "smithy-build.json"]
    assert "Packed 3 file(s)" in strip_ansi(result.output)


def test_root_flag_picks_the_root_of_a_model_directory(httpx_mock: object, tmp_path: Path) -> None:
    model = tmp_path / "m"
    model.mkdir()
    (model / "a.smithy").write_text("namespace a\n", encoding="utf-8")
    (model / "b.smithy").write_text("namespace b\n", encoding="utf-8")
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "smithy", str(model), "--root", "b.smithy"])
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["archive_root"] == "b.smithy"
