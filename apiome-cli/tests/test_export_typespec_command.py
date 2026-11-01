"""``apiome export typespec`` — MFX-15.4 (#3896).

The Microsoft TypeSpec document is a registry target (``typespec``), so the verb runs through the generic
export seam (``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that
the spelling resolves, that the options (``include_http_imports``, ``include_comments``) reach the preview
and the job as booleans, that the one ``.tsp`` file is written to ``--out``, that ``--json`` prints the tier,
and that a lossy export (a REST source's examples, servers and HTTP details TypeSpec does not keep) exits
non-zero unless ``--force``.

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_typespec_target_card.py``
keeps ``export-targets-typespec.json`` equal to the live descriptor, options schema and badge, and
``export-job-completed-typespec-lossy.json`` equal to the Petstore export's live fidelity and file name.
"""

from __future__ import annotations

import json
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
_TARGETS = json.loads((_FIXTURES / "export-targets-typespec.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-typespec-lossy.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_TSP_NAME = _JOB["result"]["files"][0]["path"]
_TSP_TEXT = 'import "@typespec/http";\n\nusing Http;\n\n@service(#{ title: "Pet Store" })\nnamespace PetStore;\n'


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the ``.tsp`` download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_TSP_TEXT.encode("utf-8"),
                            headers={"Content-Type": "text/plain",
                                     "Content-Disposition": f'attachment; filename="{_TSP_NAME}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "typespec", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["typespec", "TypeSpec"])
def test_the_spelling_resolves_to_the_typespec_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "typespec"


def test_the_fixture_carries_the_options_and_the_lossy_badge() -> None:
    target = _TARGETS["targets"][0]
    assert set(target["options_schema"]["properties"]) == {"include_comments", "include_http_imports"}
    assert target["default_options"] == {"include_comments": True, "include_http_imports": True}
    assert target["descriptor"]["multi_file"] is False
    assert target["fidelity"]["tier"] == "lossy"


def test_a_lossy_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.tsp"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _TSP_TEXT
    assert "lossy" in strip_ansi(result.stderr)


def test_force_writes_the_tsp_file(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.tsp"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_text(encoding="utf-8") == _TSP_TEXT


def test_the_options_reach_the_preview_and_the_job_as_booleans(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.tsp"), "--force",
                                      "--option", "include_http_imports=false", "--option", "include_comments=false"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"include_http_imports": False, "include_comments": False}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("typespec", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / "petstore.tsp"), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("typespec", "typespec")
    assert payload["fidelity"]["status"] == "lossy"


def test_export_targets_lists_typespec_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "typespec")["fidelity"]["tier"] == "lossy"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "typespec", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert "Export an artifact to 'typespec'" in output and "--option" in output
