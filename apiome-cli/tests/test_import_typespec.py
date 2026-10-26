"""Tests for ``apiome import typespec`` — MFI-14.5 (#3798).

TypeSpec rides the registry-driven adapter import (MFI-1.4), like the collection formats in
``test_import_collections.py``. What is TypeSpec-specific is the project directory:
``apiome import typespec ./my-api/`` packs the directory (``.tsp`` files, ``tspconfig.yaml``)
into the archive an upload would send, with ``package.json``'s ``tspMain`` (else ``main.tsp``)
as the root. These tests drive that against a mocked REST service.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.import_.project_dir import (
    MAX_PROJECT_FILES,
    ProjectDirectoryError,
    pack_project_directory,
    project_root,
)
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_TYPESPEC = {
    "key": "typespec",
    "label": "TypeSpec",
    "description": "Import a Microsoft TypeSpec API definition (.tsp).",
    "icon": "file-code",
    "paradigm": "rest",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["typespec", "tsp", "cadl"],
    "file_extensions": [".tsp", ".cadl", ".zip", ".tar.gz", ".tgz", ".tar"],
}

_MAIN = 'import "@typespec/http";\nimport "./models.tsp";\n\n@service({ title: "Shop" })\nnamespace Shop;\n'


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A TypeSpec project directory with tooling folders that must not be packed."""
    root = tmp_path / "shop-api"
    (root / "ops").mkdir(parents=True)
    (root / "main.tsp").write_text(_MAIN, encoding="utf-8")
    (root / "models.tsp").write_text("namespace Shop;\nmodel Item { id: string; }\n", encoding="utf-8")
    (root / "ops" / "items.tsp").write_text("namespace Shop;\n", encoding="utf-8")
    (root / "tspconfig.yaml").write_text("options:\n  '@typespec/openapi3':\n    omit-unreachable-types: true\n")
    for skipped in ("node_modules/@typespec/http/index.js", "tsp-output/openapi.json", ".git/HEAD"):
        (root / skipped).parent.mkdir(parents=True, exist_ok=True)
        (root / skipped).write_text("x", encoding="utf-8")
    return root


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_TYPESPEC]})  # type: ignore[attr-defined]
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
                "source": "typespec",
                "paradigm": "rest",
                "format": "typespec",
                "fingerprint": "sha256:tsp",
                "counts": {"services": 1, "operations": 2, "types": 1, "channels": 0},
                "lint": {"score": 90, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
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


def _archive_names(body: dict) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(body["document_base64"]))) as archive:
        return archive.namelist()


# ===========================================================================
# Packing
# ===========================================================================


def test_pack_skips_dependencies_build_output_and_hidden_folders(project: Path):
    packed = pack_project_directory(project, "typespec")
    assert packed.members == ["main.tsp", "models.tsp", "ops/items.tsp", "tspconfig.yaml"]
    assert packed.skipped == [".git/HEAD", "node_modules/@typespec/http/index.js", "tsp-output/openapi.json"]
    assert packed.filename == "shop-api.zip"
    assert packed.root == "main.tsp"


def test_pack_is_deterministic(project: Path):
    assert pack_project_directory(project, "typespec").archive == pack_project_directory(project, "typespec").archive


def test_the_root_follows_package_json_tsp_main(project: Path):
    (project / "package.json").write_text(json.dumps({"tspMain": "./ops/items.tsp"}), encoding="utf-8")
    packed = pack_project_directory(project, "typespec")
    assert packed.root == "ops/items.tsp"


def test_a_tsp_main_that_is_not_packed_falls_back_to_main_tsp(project: Path):
    (project / "package.json").write_text(json.dumps({"tspMain": "missing.tsp"}), encoding="utf-8")
    assert pack_project_directory(project, "typespec").root == "main.tsp"
    (project / "package.json").write_text("not json", encoding="utf-8")
    assert pack_project_directory(project, "typespec").root == "main.tsp"


def test_other_formats_let_the_server_choose_the_root(project: Path):
    assert project_root(project, "thrift", ["main.tsp"]) is None
    assert project_root(project, "typespec", ["a.tsp"]) is None


def test_an_empty_or_oversized_directory_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ProjectDirectoryError, match="no files"):
        pack_project_directory(tmp_path, "typespec")
    (tmp_path / "a.tsp").write_text("x")
    (tmp_path / "b.tsp").write_text("x")
    monkeypatch.setattr("apiome_cli.import_.project_dir.MAX_PROJECT_FILES", 1)
    with pytest.raises(ProjectDirectoryError, match="too large"):
        pack_project_directory(tmp_path, "typespec")
    assert MAX_PROJECT_FILES == 2000


# ===========================================================================
# The command
# ===========================================================================


def test_import_typespec_directory_sends_the_project_as_an_archive(httpx_mock: object, project: Path):
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "typespec", str(project)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "typespec"
    assert body["filename"] == "shop-api.zip"
    assert body["metadata"]["options"]["archive_root"] == "main.tsp"
    assert _archive_names(body) == ["main.tsp", "models.tsp", "ops/items.tsp", "tspconfig.yaml"]
    text = strip_ansi(result.output)
    assert "Packed 4 file(s)" in text
    assert "root main.tsp" in text


def test_root_flag_overrides_the_directory_convention(httpx_mock: object, project: Path):
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "typespec", str(project), "--root", "ops/items.tsp"])
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["archive_root"] == "ops/items.tsp"


def test_a_single_tsp_file_is_sent_verbatim(httpx_mock: object, project: Path):
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "typespec", str(project / "main.tsp")])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert base64.b64decode(body["document_base64"]).decode("utf-8") == _MAIN
    assert "archive_root" not in body["metadata"].get("options", {})


def test_an_empty_directory_is_a_usage_error(httpx_mock: object, tmp_path: Path):
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_TYPESPEC]})  # type: ignore[attr-defined]
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["import", "typespec", str(empty)])
    assert result.exit_code != 0
    assert "has no files to import" in strip_ansi(result.output)
