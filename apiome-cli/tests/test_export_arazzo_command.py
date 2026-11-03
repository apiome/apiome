"""``apiome export arazzo`` — MFX-10.4 (#3873).

The Arazzo workflow document is a registry target (``arazzo``), so the verb runs through the generic export seam
(``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that the spelling
resolves, that ``pretty_print`` reaches the preview and the job as a boolean and ``arazzo_version`` as text (``1.1``
is not the number ``1.1``), that the one ``.arazzo.yaml`` file is written to ``--out``, that ``--json`` prints the
tier, that a lossy export exits non-zero unless ``--force``, that the export prints its fidelity **report** — led by
*this target captures workflows, not the full API surface* — and that an item with nothing to sequence is refused
before any job starts.

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_arazzo_target_card.py`` keeps
``export-targets-arazzo.json`` (a REST item) and ``export-targets-arazzo-data.json`` (a set of types) equal to the
live descriptor, options schema and badge, and ``export-job-completed-arazzo-lossy.json`` equal to the Petstore
export's live fidelity envelope (summary, report, advisory) and file name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-arazzo.json").read_text())
_DATA_TARGETS = json.loads((_FIXTURES / "export-targets-arazzo-data.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-arazzo-lossy.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_ARAZZO_NAME = _JOB["result"]["files"][0]["path"]
_ARAZZO_TEXT = (
    "arazzo: 1.0.1\ninfo:\n  title: Pet Store\n  version: 1.0.0\nworkflows:\n- workflowId: default\n"
    "  steps:\n  - stepId: listPets\n    operationId: listPets\n"
)
#: The warning every report from a non-Arazzo item leads with (MFX-10.2).
_WORKFLOWS_ONLY = "this target captures workflows, not the full API surface"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the ``.arazzo.yaml`` download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_ARAZZO_TEXT.encode("utf-8"),
                            headers={"Content-Type": "application/yaml",
                                     "Content-Disposition": f'attachment; filename="{_ARAZZO_NAME}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "arazzo", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


def _flat(text: str) -> str:
    """``text`` without ANSI codes and with every run of whitespace as one space (Rich wraps long lines)."""
    return " ".join(strip_ansi(text).split())


@pytest.mark.parametrize("spelling", ["arazzo", "Arazzo"])
def test_the_spelling_resolves_to_the_arazzo_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "arazzo"


def test_the_fixture_carries_the_options_and_the_lossy_badge() -> None:
    target = _TARGETS["targets"][0]
    assert set(target["options_schema"]["properties"]) == {"pretty_print", "arazzo_version"}
    assert target["default_options"] == {"pretty_print": True, "arazzo_version": None}
    assert target["descriptor"]["multi_file"] is False
    assert target["fidelity"]["tier"] == "lossy"


def test_the_job_fixture_writes_one_arazzo_document() -> None:
    assert [row["path"].endswith(".arazzo.yaml") for row in _JOB["result"]["files"]] == [True]


def test_a_lossy_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.arazzo.yaml"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _ARAZZO_TEXT
    assert "lossy" in strip_ansi(result.stderr)


def test_force_writes_the_arazzo_document(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.arazzo.yaml"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_text(encoding="utf-8") == _ARAZZO_TEXT


def test_the_options_reach_the_preview_and_the_job_typed(httpx_mock: object, tmp_path: Path) -> None:
    """``pretty_print`` is a boolean; ``arazzo_version`` is text only, so ``1.1`` stays ``"1.1"``."""
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.arazzo.yaml"), "--force",
                                      "--option", "pretty_print=false", "--option", "arazzo_version=1.1"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"pretty_print": False, "arazzo_version": "1.1"}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("arazzo", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / "petstore.arazzo.yaml"), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("arazzo", "arazzo")
    assert payload["fidelity"]["status"] == "lossy"


def test_export_targets_lists_arazzo_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "arazzo")["fidelity"]["tier"] == "lossy"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "arazzo", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert "Export an artifact to 'arazzo'" in output and "--option" in output


def test_the_export_prints_the_workflows_only_warning_and_its_report(httpx_mock: object, tmp_path: Path) -> None:
    """The report the CLI prints: the summary, then the losses — the workflows-only warning among them."""
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.arazzo.yaml"), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    stderr = _flat(result.stderr)
    summary = _JOB["result"]["fidelity"]["summary"]
    assert f"fidelity lossy ({summary['preserved_percent']}% preserved)" in stderr
    assert f"{summary['dropped']} dropped" in stderr and f"{summary['approximated']} approximated" in stderr
    assert "Per-construct losses:" in stderr and _WORKFLOWS_ONLY in stderr


def test_an_item_with_nothing_to_sequence_is_refused_before_any_job(httpx_mock: object, tmp_path: Path) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_DATA_TARGETS)
    out = tmp_path / "types.arazzo.yaml"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_USAGE, result.output
    stderr = _flat(result.stderr)
    assert "not available" in stderr and "at least one operation to sequence" in stderr
    assert not out.exists()
    assert not [r for r in httpx_mock.get_requests() if r.method == "POST"]
