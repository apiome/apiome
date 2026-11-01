"""``apiome export wsdl`` — MFX-14.4 (#3892).

The SOAP / WSDL 1.1 description is a registry target (``wsdl``), so the verb runs through the generic export
seam (``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that the
spelling resolves, that the layout picker (``layout=bundle|single``) and ``include_comments`` reach the
preview and the job with their types intact, that the WSDL + XSD zip unpacks into ``--out``, that ``--json``
prints the tier, and that a lossy export (a REST source loses its HTTP method and path) exits non-zero
unless ``--force``.

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_wsdl_target_card.py``
keeps ``export-targets-wsdl.json`` equal to the live descriptor, options schema and badge, and
``export-job-completed-wsdl-lossy.json`` equal to the Petstore export's live fidelity and file names.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-wsdl.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-wsdl-lossy.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_BUNDLE_FILES = [row["path"] for row in _JOB["result"]["files"]]


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _bundle() -> bytes:
    """The export as the job delivers it: the WSDL and its XSD, zipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in _BUNDLE_FILES:
            archive.writestr(path, f"<!-- {path} -->\n")
        archive.writestr("manifest.json", json.dumps({"files": _BUNDLE_FILES}))
    return buffer.getvalue()


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the zip download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_bundle(),
                            headers={"Content-Type": "application/zip",
                                     "Content-Disposition": 'attachment; filename="pet-store-wsdl.zip"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "wsdl", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["wsdl", "WSDL"])
def test_the_spelling_resolves_to_the_wsdl_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "wsdl"


def test_the_fixture_carries_the_layout_picker_and_the_lossy_badge() -> None:
    target = _TARGETS["targets"][0]
    layout = target["options_schema"]["properties"]["layout"]
    assert layout["enum"] == ["bundle", "single"] and layout["default"] == "bundle"
    assert target["default_options"] == {"include_comments": True, "layout": "bundle"}
    assert target["descriptor"]["multi_file"] is True
    assert target["fidelity"]["tier"] == "lossy"


def test_a_lossy_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "wsdl"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The files are still written: the exit code only flags the loss.
    assert sorted(p.name for p in out.iterdir()) == sorted([*_BUNDLE_FILES, "manifest.json"])
    assert "lossy" in strip_ansi(result.stderr)


def test_force_unpacks_the_wsdl_and_its_xsd(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "wsdl"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert sorted(p.suffix for p in out.iterdir() if p.name != "manifest.json") == [".wsdl", ".xsd"]


def test_the_layout_picker_reaches_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "wsdl"), "--force",
                                      "--option", "layout=single", "--option", "include_comments=false"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    # ``layout`` stays text and ``include_comments`` a boolean, as the options schema types them.
    expected = {"layout": "single", "include_comments": False}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("wsdl", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / "wsdl"), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("wsdl", "wsdl")
    assert payload["fidelity"]["status"] == "lossy"


def test_export_targets_lists_wsdl_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "wsdl")["fidelity"]["tier"] == "lossy"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "wsdl", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert "Export an artifact to 'wsdl'" in output and "--option" in output
