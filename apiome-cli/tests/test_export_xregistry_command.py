"""``apiome export xregistry`` — MFX-34.4 (#4309).

The xRegistry document is a registry target (``xregistry``, MFX-34.1), so the verb runs through the generic
export seam (``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that the
spelling resolves, that the ``registry_id`` / ``source`` / ``indent`` options reach the preview and the job,
that the one ``.xregistry.json`` file is written to ``--out``, that ``--json`` prints the tier, that a lossy
export exits non-zero unless ``--force``, and that the export prints its fidelity **report** — the worst losses
first, starting with the critical event-registry advisory of a REST source (MFX-34.3).

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_xregistry_target_card.py``
keeps ``export-targets-xregistry.json`` equal to the live descriptor, options schema and badge, and
``export-job-completed-xregistry-lossy.json`` equal to the Petstore export's live fidelity envelope (summary,
report, advisory) and file name.
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
_TARGETS = json.loads((_FIXTURES / "export-targets-xregistry.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-xregistry-lossy.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_XREG_NAME = _JOB["result"]["files"][0]["path"]
_XREG_TEXT = '{\n  "specversion": "1.0-rc1",\n  "registryid": "pet-store",\n  "schemagroups": {}\n}\n'


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the ``.xregistry.json`` download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_XREG_TEXT.encode("utf-8"),
                            headers={"Content-Type": "application/json",
                                     "Content-Disposition": f'attachment; filename="{_XREG_NAME}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "xregistry", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["xregistry", "xRegistry", "XREGISTRY"])
def test_the_spelling_resolves_to_the_xregistry_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "xregistry"


def test_the_fixture_carries_the_options_and_the_lossy_badge() -> None:
    target = _TARGETS["targets"][0]
    assert target["descriptor"]["label"] == "xRegistry" and target["descriptor"]["paradigm"] == "event"
    assert set(target["options_schema"]["properties"]) == {"registry_id", "source", "indent"}
    assert target["default_options"] == {"registry_id": None, "source": None, "indent": 2}
    assert target["descriptor"]["multi_file"] is False
    assert target["fidelity"]["tier"] == "lossy"


def test_the_job_fixture_writes_one_xregistry_document() -> None:
    assert [row["path"].endswith(".xregistry.json") for row in _JOB["result"]["files"]] == [True]


def test_the_job_report_carries_the_critical_event_registry_advisory() -> None:
    """A REST source: the report starts with the MFX-34.3 critical advisory the CLI prints."""
    items = _JOB["result"]["fidelity"]["report"]["items"]
    advisory = next(item for item in items if item.get("target_mapping") == "event-registry-only")
    assert advisory["severity"] == "critical" and advisory["kind"] == "drop"


def test_a_lossy_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.xregistry.json"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _XREG_TEXT
    assert "lossy" in strip_ansi(result.stderr)


def test_force_writes_the_xregistry_document(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.xregistry.json"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_text(encoding="utf-8") == _XREG_TEXT


def test_the_options_reach_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.xregistry.json"), "--force",
                                      "--option", "registry_id=shop", "--option", "source=/shop/orders",
                                      "--option", "indent=0"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"registry_id": "shop", "source": "/shop/orders", "indent": 0}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("xregistry", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / "petstore.xregistry.json"), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("xregistry", "xregistry")
    assert payload["fidelity"]["status"] == "lossy"


def test_export_targets_lists_xregistry_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "xregistry")["fidelity"]["tier"] == "lossy"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "xregistry", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert "Export an artifact to 'xregistry'" in output and "--option" in output


def test_the_export_prints_its_fidelity_report_worst_losses_first(httpx_mock: object, tmp_path: Path) -> None:
    """The acceptance criterion: the CLI export works *with report* — the summary and the worst losses."""
    report = _JOB["result"]["fidelity"]["report"]["items"]
    worst = next(item for item in sort_report_items_worst_first(report) if item["kind"] != "ok")
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.xregistry.json"), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    stderr = strip_ansi(result.stderr)
    summary = _JOB["result"]["fidelity"]["summary"]
    assert f"fidelity lossy ({summary['preserved_percent']}% preserved)" in stderr
    assert f"{summary['dropped']} dropped" in stderr and f"{summary['approximated']} approximated" in stderr
    assert "Per-construct losses:" in stderr and worst["construct"] in stderr
