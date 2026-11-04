"""``apiome export fix-orchestra`` — MFX-37.4 (#4326).

The FIX Orchestra export is the registry target ``fix-orchestra`` (MFX-37.1 emitter, MFX-37.2 fidelity pack,
MFX-37.3 validation). The CLI offers it as ``apiome export fix-orchestra`` (also ``orchestra``), through the
generic export seam (``export <format> <artifact>``, MFX-8.1). These tests pin that the spellings resolve to the
target, that ``--option version=…`` reaches the preview and the job, that a types-only export exits non-zero
unless ``--force``, that ``--json`` prints the tier, and that the export prints its fidelity **report** — the
critical types-only advisory, the message scenarios and the synthesized tags.

The fixtures are recorded from the REST emitter registry by
``apiome-rest/tests/test_fix_orchestra_target_card.py``: ``export-targets-fix-orchestra.json`` (the live
descriptor, options schema and badge) and ``export-job-completed-fix-orchestra.json`` (the Petstore export's
live fidelity envelope and file).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.export_output import sort_report_items_worst_first
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-fix-orchestra.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-fix-orchestra.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_NAME = _JOB["result"]["files"][0]["path"]
_XML = ('<?xml version="1.0" encoding="UTF-8"?>\n<fixr:repository '
        'xmlns:fixr="http://fixprotocol.io/2020/orchestra/repository" name="Pet Store" version="1.0"/>\n')


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_XML.encode("utf-8"),
                            headers={"Content-Type": "application/xml",
                                     "Content-Disposition": f'attachment; filename="{_NAME}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str, verb: str = "fix-orchestra") -> list[str]:
    return ["export", verb, "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["fix-orchestra", "FIX-Orchestra", "orchestra", "fixorchestra", "fix_orchestra"])
def test_every_spelling_resolves_to_the_fix_orchestra_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "fix-orchestra"


def test_the_fixture_carries_the_card_its_tier_and_the_version_option() -> None:
    target = _TARGETS["targets"][0]
    assert target["descriptor"]["label"] == "FIX Orchestra" and target["descriptor"]["paradigm"] == "data_schema"
    properties = target["options_schema"]["properties"]
    assert "version" in properties and "persisted_field_numbers" not in properties
    assert target["fidelity"]["tier"] == "types-only"
    assert _NAME.endswith(".orchestra.xml")


def test_the_job_report_carries_the_advisory_scenarios_and_synthesized_tags() -> None:
    items = _JOB["result"]["fidelity"]["report"]["items"]
    advisory = next(item for item in items if item.get("target_mapping") == "types-only")
    assert advisory["severity"] == "critical" and advisory["kind"] == "drop"
    mappings = {item.get("target_mapping") for item in items}
    assert {"operation → message scenario", "orchestra-tag-synthesized"} <= mappings


@pytest.mark.parametrize(("verb", "extra", "expected"), [
    ("fix-orchestra", [], {}),
    ("fix-orchestra", ["--option", "version=FIX.5.0SP2"], {"version": "FIX.5.0SP2"}),
    ("orchestra", [], {}),
])
def test_the_verb_and_options_reach_the_preview_and_the_job(
    httpx_mock: object, tmp_path: Path, verb: str, extra: list[str], expected: dict
) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / _NAME), "--force", *extra, verb=verb))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert (_posted(httpx_mock, "/preview").get("options") or {}) == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job.get("options") or {}) == ("fix-orchestra", expected)
    assert (tmp_path / _NAME).read_text(encoding="utf-8") == _XML


def test_a_types_only_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / _NAME
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _XML
    assert "types-only" in strip_ansi(result.stderr)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / _NAME), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["fidelity_target"] == "fix-orchestra" and payload["fidelity"]["status"] == "types-only"


def test_the_export_prints_its_fidelity_report_worst_losses_first(httpx_mock: object, tmp_path: Path) -> None:
    """The acceptance criterion: the CLI export works with its report — the summary and the worst losses."""
    report = _JOB["result"]["fidelity"]["report"]["items"]
    worst = next(item for item in sort_report_items_worst_first(report) if item["kind"] != "ok")
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / _NAME), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    stderr = strip_ansi(result.stderr)
    summary = _JOB["result"]["fidelity"]["summary"]
    assert f"({summary['preserved_percent']}% preserved)" in stderr
    assert "Per-construct losses:" in stderr and worst["construct"] in stderr
