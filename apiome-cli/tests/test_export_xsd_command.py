"""``apiome export xsd`` — MFX-22.6 (#4137).

The standalone W3C XML Schema is a registry target (``xsd``), so the verb runs through the generic export seam
(``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that the spelling
resolves, that the options (``xsd_version`` as a string, ``include_xml_declaration`` / ``include_comments`` as
booleans) reach the preview and the job, that the ``.xsd`` file is written to ``--out``, that ``--json`` prints
the tier, and that a types-only export (a REST source whose operations XSD does not keep) exits non-zero unless
``--force``.

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_xsd_target_card.py`` keeps
``export-targets-xsd.json`` equal to the live descriptor, options schema and badge, and
``export-job-completed-xsd-types-only.json`` equal to the Petstore export's live fidelity and file name.
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
_TARGETS = json.loads((_FIXTURES / "export-targets-xsd.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-xsd-types-only.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_XSD_NAME = _JOB["result"]["files"][0]["path"]
_XSD_TEXT = '<?xml version="1.0" encoding="UTF-8"?>\n<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" />\n'


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the ``.xsd`` download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_XSD_TEXT.encode("utf-8"),
                            headers={"Content-Type": "application/xml",
                                     "Content-Disposition": f'attachment; filename="{_XSD_NAME}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "xsd", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["xsd", "XSD"])
def test_the_spelling_resolves_to_the_xsd_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "xsd"


def test_the_fixture_carries_the_options_and_the_types_only_badge() -> None:
    target = _TARGETS["targets"][0]
    assert set(target["options_schema"]["properties"]) == {"include_comments", "include_xml_declaration", "xsd_version"}
    assert target["options_schema"]["properties"]["xsd_version"]["enum"] == ["1.0", "1.1"]
    assert target["default_options"] == {"include_comments": True, "include_xml_declaration": True,
                                         "xsd_version": "1.0"}
    assert target["descriptor"]["multi_file"] is False
    assert target["fidelity"]["tier"] == "types-only"


def test_the_job_fixture_writes_one_xsd_file() -> None:
    assert [row["path"].endswith(".xsd") for row in _JOB["result"]["files"]] == [True]


def test_a_types_only_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.xsd"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _XSD_TEXT
    assert "types-only" in strip_ansi(result.stderr)


def test_force_writes_the_xsd_file(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.xsd"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_text(encoding="utf-8") == _XSD_TEXT


def test_the_options_reach_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.xsd"), "--force",
                                      "--option", "xsd_version=1.1", "--option", "include_xml_declaration=false"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"xsd_version": "1.1", "include_xml_declaration": False}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("xsd", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / "petstore.xsd"), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("xsd", "xsd")
    assert payload["fidelity"]["status"] == "types-only"


def test_export_targets_lists_xsd_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "xsd")["fidelity"]["tier"] == "types-only"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "xsd", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert "Export an artifact to 'xsd'" in output and "--option" in output
