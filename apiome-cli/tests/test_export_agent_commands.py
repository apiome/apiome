"""``apiome export mcp`` and ``apiome export a2a`` — MFX-32.5 (#4299).

Both agent-interface targets are registry targets (``mcp``, MFX-32.1; ``a2a``, MFX-32.2), so the verbs run
through the generic export seam (``export <format> <artifact>``, MFX-8.1) with no command code of their own.
These tests pin, for each target, that the spellings resolve, that options reach the preview and the job,
that the one file is written to ``--out``, that a lossy export exits non-zero unless ``--force``, that
``--json`` prints the tier, and that the export prints its fidelity **report** — the worst losses first.

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_agent_target_cards.py``
keeps ``export-targets-{mcp,a2a}.json`` equal to the live descriptor, options schema and badge, and
``export-job-completed-{mcp,a2a}-lossy.json`` equal to the Petstore export's live fidelity envelope
(summary, report, advisory) and file name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
TARGETS = ("mcp", "a2a")
_REGISTRY: dict[str, dict[str, Any]] = {
    target: json.loads((_FIXTURES / f"export-targets-{target}.json").read_text()) for target in TARGETS
}
_JOBS: dict[str, dict[str, Any]] = {
    target: json.loads((_FIXTURES / f"export-job-completed-{target}-lossy.json").read_text()) for target in TARGETS
}
#: A small stand-in for each downloaded file (its content is not what these tests check).
_BODIES = {
    "mcp": '{"mcpVersion": "2025-06-18", "server": {"name": "pet-store"}, "capabilities": {"tools": {}}, "tools": []}\n',
    "a2a": '{"protocolVersion": "0.3.0", "name": "Pet Store", "skills": []}\n',
}
#: One non-default option per target, as typed and as it reaches the REST API.
_OPTIONS = {
    "mcp": ("grouping=per-service", {"grouping": "per-service"}),
    "a2a": ("skills_from=tags", {"skills_from": "tags"}),
}

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _file_name(target: str) -> str:
    return _JOBS[target]["result"]["files"][0]["path"]


def _mock_export(httpx_mock: Any, target: str) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_REGISTRY[target])
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOBS[target])
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_BODIES[target].encode("utf-8"),
                            headers={"Content-Type": "application/json",
                                     "Content-Disposition": f'attachment; filename="{_file_name(target)}"'})


def _posted(httpx_mock: Any, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(target: str, out: str, *extra: str) -> list[str]:
    return ["export", target, "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize(("spelling", "key"), [("mcp", "mcp"), ("MCP", "mcp"), ("a2a", "a2a"), ("A2A", "a2a")])
def test_every_spelling_resolves_to_its_target(spelling: str, key: str) -> None:
    both = [*_REGISTRY["mcp"]["targets"], *_REGISTRY["a2a"]["targets"]]
    assert resolve_export_target(spelling, both) == key


def test_the_mcp_fixture_carries_its_options_and_the_lossy_badge() -> None:
    target = _REGISTRY["mcp"]["targets"][0]
    assert target["descriptor"]["label"] == "MCP Tool Definitions" and target["descriptor"]["paradigm"] == "agent"
    properties = target["options_schema"]["properties"]
    assert set(properties["grouping"]["enum"]) == {"single", "per-service"}
    assert set(properties["protocol_version"]["enum"]) == {"2025-06-18", "2025-03-26"}
    assert target["default_options"]["grouping"] == "single"
    assert target["fidelity"]["tier"] == "lossy"


def test_the_a2a_fixture_carries_its_options_and_the_lossy_badge() -> None:
    target = _REGISTRY["a2a"]["targets"][0]
    assert target["descriptor"]["label"] == "A2A Agent Card" and target["descriptor"]["paradigm"] == "agent"
    assert set(target["options_schema"]["properties"]["skills_from"]["enum"]) == {"operations", "tags"}
    assert target["default_options"]["skills_from"] == "operations"
    assert target["fidelity"]["tier"] == "lossy"


@pytest.mark.parametrize(("target", "suffix"), [("mcp", ".mcp.json"), ("a2a", "agent-card.json")])
def test_the_job_fixture_writes_one_file(target: str, suffix: str) -> None:
    assert [row["path"].endswith(suffix) for row in _JOBS[target]["result"]["files"]] == [True]


@pytest.mark.parametrize("target", TARGETS)
def test_a_lossy_export_exits_nonzero_without_force(httpx_mock: Any, tmp_path: Path, target: str) -> None:
    _mock_export(httpx_mock, target)
    out = tmp_path / _file_name(target)
    result = runner.invoke(app, _args(target, str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _BODIES[target]
    assert "lossy" in strip_ansi(result.stderr)


@pytest.mark.parametrize("target", TARGETS)
def test_force_writes_the_file(httpx_mock: Any, tmp_path: Path, target: str) -> None:
    _mock_export(httpx_mock, target)
    out = tmp_path / _file_name(target)
    result = runner.invoke(app, _args(target, str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_text(encoding="utf-8") == _BODIES[target]


@pytest.mark.parametrize("target", TARGETS)
def test_an_option_reaches_the_preview_and_the_job(httpx_mock: Any, tmp_path: Path, target: str) -> None:
    typed, expected = _OPTIONS[target]
    _mock_export(httpx_mock, target)
    result = runner.invoke(app, _args(target, str(tmp_path / _file_name(target)), "--force", "--option", typed))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == (target, expected)


@pytest.mark.parametrize("target", TARGETS)
def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: Any, tmp_path: Path, target: str) -> None:
    _mock_export(httpx_mock, target)
    result = runner.invoke(app, ["--json", *_args(target, str(tmp_path / _file_name(target)), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == (target, target)
    assert payload["fidelity"]["status"] == "lossy"


@pytest.mark.parametrize("target", TARGETS)
def test_export_targets_lists_the_target_with_its_tier(httpx_mock: Any, target: str) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_REGISTRY[target])
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == target)["fidelity"]["tier"] == "lossy"


@pytest.mark.parametrize("target", TARGETS)
def test_the_verb_has_help(target: str) -> None:
    result = runner.invoke(app, ["export", target, "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert f"Export an artifact to '{target}'" in output and "--option" in output and "--confirm" in output


@pytest.mark.parametrize("target", TARGETS)
def test_the_export_prints_its_fidelity_report_worst_losses_first(
    httpx_mock: Any, tmp_path: Path, target: str
) -> None:
    """The acceptance criterion: the CLI exports both targets *with reports* — the summary and the worst losses."""
    report = _JOBS[target]["result"]["fidelity"]["report"]["items"]
    worst = next(item for item in sort_report_items_worst_first(report) if item["kind"] != "ok")
    _mock_export(httpx_mock, target)
    result = runner.invoke(app, _args(target, str(tmp_path / _file_name(target)), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    stderr = strip_ansi(result.stderr)
    summary = _JOBS[target]["result"]["fidelity"]["summary"]
    assert f"fidelity lossy ({summary['preserved_percent']}% preserved)" in stderr
    assert f"{summary['dropped']} dropped" in stderr and f"{summary['approximated']} approximated" in stderr
    assert "Per-construct losses:" in stderr and worst["construct"] in stderr
