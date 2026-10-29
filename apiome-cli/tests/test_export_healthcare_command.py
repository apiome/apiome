"""``apiome export fhir`` / ``apiome export hl7v2`` — MFX-26.5 (#4161).

The healthcare targets are registry targets, so both verbs run through the generic export seam
(``export <format> <artifact>``, MFX-8.1): resolve the target from ``GET …/targets``, preview it, start
an export job with the ``--option`` values and download the artifact. These tests pin that both names
resolve, that the FHIR options (``fhir_version``, ``packaging``) reach the preview and the job as typed
values, that ``export targets`` lists both healthcare targets, and that ``--help`` documents each verb.
The targets fixture (``fixtures/export-targets-healthcare.json``) is recorded from the REST emitter
registry: the real descriptors, option schemas and defaults of the FHIR and HL7 v2 emitters.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-healthcare.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-lossless.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Patient API", "slug": "patient-api", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_BUNDLE = json.dumps({"resourceType": "Bundle", "type": "collection", "entry": []}).encode()
_SEGMENTS = b"MSH|^~\\&|APIOME\r"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object, body: bytes, filename: str) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/patient-api", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=body,
                            headers={"Content-Type": "application/fhir+json",
                                     "Content-Disposition": f'attachment; filename="{filename}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def test_both_healthcare_targets_resolve_by_key_and_format() -> None:
    targets = _TARGETS["targets"]
    assert resolve_export_target("fhir", targets) == "fhir"
    assert resolve_export_target("hl7v2", targets) == "hl7v2"


def test_the_fixture_carries_the_fhir_version_option() -> None:
    fhir = next(t for t in _TARGETS["targets"] if t["descriptor"]["key"] == "fhir")
    assert fhir["default_options"]["fhir_version"] == "R4"
    assert fhir["options_schema"]["properties"]["fhir_version"]["enum"] == ["R4", "R5"]
    assert fhir["options_schema"]["properties"]["packaging"]["enum"] == ["bundle", "per-type"]


def test_export_fhir_passes_the_version_and_packaging_options(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, _BUNDLE, "patient.bundle.json")
    out = tmp_path / "patient.bundle.json"
    result = runner.invoke(app, ["export", "fhir", "patient-api", "--version", "1.0.0", "--out", str(out),
                                 "--option", "fhir_version=R5", "--option", "packaging=bundle",
                                 "--poll-interval", "0.1"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_bytes() == _BUNDLE
    expected = {"fhir_version": "R5", "packaging": "bundle"}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("fhir", expected)


def test_export_hl7v2_runs_with_its_defaults(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, _SEGMENTS, "message.hl7")
    out = tmp_path / "message.hl7"
    result = runner.invoke(app, ["export", "hl7v2", "patient-api", "--version", "1.0.0", "--out", str(out),
                                 "--poll-interval", "0.1"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_bytes() == _SEGMENTS
    job = _posted(httpx_mock, "/jobs")
    assert job["target"] == "hl7v2" and "options" not in job


def test_export_targets_lists_both_healthcare_targets(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/patient-api", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["export", "targets", "--project", "patient-api", "--version", "1.0.0"],
                           terminal_width=240)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "fhir" in result.output and "hl7v2" in result.output


@pytest.mark.parametrize("verb", ["fhir", "hl7v2"])
def test_each_healthcare_verb_has_help(verb: str) -> None:
    result = runner.invoke(app, ["export", verb, "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert f"Export an artifact to {verb!r}" in result.output and "--option" in result.output
