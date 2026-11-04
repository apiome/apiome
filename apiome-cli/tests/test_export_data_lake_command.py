"""``apiome export parquet|bigquery|spark|iceberg`` — MFX-36.5 (#4321).

The data-lake exports are two registry targets: ``arrow`` (Apache Arrow / Parquet, with ``output`` modes
``arrow``, ``bigquery`` and ``spark``) and ``iceberg``. The CLI offers ``apiome export parquet``, ``bigquery`` and
``spark``, which run the ``arrow`` target and preset ``--option output=arrow|bigquery|spark``, ``apiome export
arrow`` (any mode, by ``--option``) and ``apiome export iceberg``. They run through the generic export seam
(``export <format> <artifact>``, MFX-8.1). These tests pin that the spellings resolve to the right target, that
the preset reaches the preview and the job, that a conflicting ``--option output=…`` is a usage error, that a
types-only export exits non-zero unless ``--force``, that ``--json`` prints the tier, and that the export prints
its fidelity **report** — the critical types-only advisory first.

The fixtures are recorded from the REST emitter registry by
``apiome-rest/tests/test_data_lake_target_cards.py``: ``export-targets-{arrow,iceberg}.json`` (the live
descriptors, options schemas and badges) and ``export-job-completed-{bigquery,iceberg}-types-only.json`` (the
Petstore export's live fidelity envelope and file).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.commands.export import DATA_LAKE_VERBS, with_data_lake_preset
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.export_output import sort_report_items_worst_first
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = {target: json.loads((_FIXTURES / f"export-targets-{target}.json").read_text())
            for target in ("arrow", "iceberg")}
_JOBS = {mode: json.loads((_FIXTURES / f"export-job-completed-{mode}-types-only.json").read_text())
         for mode in ("bigquery", "iceberg")}
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
_ALL_TARGETS = [*_TARGETS["arrow"]["targets"], *_TARGETS["iceberg"]["targets"]]

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
#: verb → (target fixture, job fixture). parquet and spark replay the bigquery job: only the options differ.
_VERB_FIXTURES = {"parquet": ("arrow", "bigquery"), "bigquery": ("arrow", "bigquery"), "spark": ("arrow", "bigquery"),
                  "arrow": ("arrow", "bigquery"), "iceberg": ("iceberg", "iceberg")}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _file(verb: str) -> tuple[str, bytes]:
    job = _JOBS[_VERB_FIXTURES[verb][1]]
    name = job["result"]["files"][0]["path"]
    return name, b'[{"name": "id", "type": "INTEGER", "mode": "REQUIRED"}]\n'


def _mock_export(httpx_mock: object, verb: str) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the file download."""
    targets, job = _VERB_FIXTURES[verb]
    name, body = _file(verb)
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS[targets])
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOBS[job])
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=body,
                            headers={"Content-Type": "application/json",
                                     "Content-Disposition": f'attachment; filename="{name}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, verb: str, *extra: str) -> list[str]:
    return ["export", verb, "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize(("spelling", "target"), [
    ("parquet", "arrow"), ("Parquet", "arrow"), ("bigquery", "arrow"), ("spark", "arrow"), ("arrow", "arrow"),
    ("iceberg", "iceberg"), ("ICEBERG", "iceberg"),
])
def test_every_data_lake_verb_resolves_to_its_target(spelling: str, target: str) -> None:
    assert resolve_export_target(spelling, _ALL_TARGETS) == target


def test_the_fixtures_carry_every_mode_and_the_types_only_badge() -> None:
    arrow = _TARGETS["arrow"]["targets"][0]
    assert arrow["descriptor"]["label"] == "Apache Arrow / Parquet"
    assert arrow["options_schema"]["properties"]["output"]["enum"] == ["arrow", "bigquery", "spark"]
    assert arrow["default_options"]["output"] == "arrow"
    iceberg = _TARGETS["iceberg"]["targets"][0]
    assert iceberg["descriptor"]["label"] == "Apache Iceberg"
    assert "persisted_field_numbers" not in iceberg["options_schema"]["properties"]
    assert {arrow["fidelity"]["tier"], iceberg["fidelity"]["tier"]} == {"types-only"}


@pytest.mark.parametrize("mode", ["bigquery", "iceberg"])
def test_the_job_report_starts_with_the_critical_types_only_advisory(mode: str) -> None:
    items = _JOBS[mode]["result"]["fidelity"]["report"]["items"]
    advisory = next(item for item in items if item.get("target_mapping") == "types-only")
    assert advisory["severity"] == "critical" and advisory["kind"] == "drop"


def test_the_iceberg_report_lists_the_synthesized_field_ids() -> None:
    items = _JOBS["iceberg"]["result"]["fidelity"]["report"]["items"]
    assert any(item["kind"] == "synth" and item.get("target_mapping") == "synthesized field ID (persisted)"
               for item in items)


@pytest.mark.parametrize(("verb", "extra", "target", "expected"), [
    ("parquet", [], "arrow", {"output": "arrow"}),
    ("parquet", ["--option", "parquet=false"], "arrow", {"output": "arrow", "parquet": False}),
    ("bigquery", [], "arrow", {"output": "bigquery"}),
    ("bigquery", ["--option", "bundle=true"], "arrow", {"output": "bigquery", "bundle": True}),
    ("spark", [], "arrow", {"output": "spark"}),
    ("spark", ["--option", "output=spark"], "arrow", {"output": "spark"}),
    ("arrow", ["--option", "output=bigquery"], "arrow", {"output": "bigquery"}),
    ("arrow", [], "arrow", {}),
    ("iceberg", [], "iceberg", {}),
    ("iceberg", ["--option", "table=Pet"], "iceberg", {"table": "Pet"}),
])
def test_the_verb_reaches_the_preview_and_the_job(httpx_mock: object, tmp_path: Path, verb: str, extra: list[str],
                                                  target: str, expected: dict) -> None:
    _mock_export(httpx_mock, verb)
    result = runner.invoke(app, _args(str(tmp_path / _file(verb)[0]), verb, "--force", *extra))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert (_posted(httpx_mock, "/preview").get("options") or {}) == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job.get("options") or {}) == (target, expected)


@pytest.mark.parametrize(("verb", "mode"), [("bigquery", "spark"), ("spark", "arrow"), ("parquet", "bigquery")])
def test_a_conflicting_output_is_a_usage_error(verb: str, mode: str, tmp_path: Path) -> None:
    result = runner.invoke(app, _args(str(tmp_path / "out.json"), verb, "--option", f"output={mode}"))
    assert result.exit_code == EXIT_USAGE
    assert f"writes output={DATA_LAKE_VERBS[verb]}" in strip_ansi(result.stderr)


def test_the_preset_helper_appends_only_when_needed() -> None:
    assert with_data_lake_preset(("bundle=true",), "bigquery") == ("bundle=true", "output=bigquery")
    assert with_data_lake_preset(("output=spark",), "spark") == ("output=spark",)


@pytest.mark.parametrize("verb", ["bigquery", "iceberg"])
def test_a_types_only_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path, verb: str) -> None:
    _mock_export(httpx_mock, verb)
    name, body = _file(verb)
    out = tmp_path / name
    result = runner.invoke(app, _args(str(out), verb))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_bytes() == body
    assert "types-only" in strip_ansi(result.stderr)


@pytest.mark.parametrize(("verb", "target"), [("spark", "arrow"), ("iceberg", "iceberg")])
def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path, verb: str,
                                                     target: str) -> None:
    _mock_export(httpx_mock, verb)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / _file(verb)[0]), verb, "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["fidelity_target"] == target and payload["fidelity"]["status"] == "types-only"


@pytest.mark.parametrize("verb", ["bigquery", "iceberg"])
def test_the_export_prints_its_fidelity_report_worst_losses_first(httpx_mock: object, tmp_path: Path,
                                                                  verb: str) -> None:
    job = _JOBS[_VERB_FIXTURES[verb][1]]
    report = job["result"]["fidelity"]["report"]["items"]
    worst = next(item for item in sort_report_items_worst_first(report) if item["kind"] != "ok")
    _mock_export(httpx_mock, verb)
    result = runner.invoke(app, _args(str(tmp_path / _file(verb)[0]), verb, "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    stderr = strip_ansi(result.stderr)
    summary = job["result"]["fidelity"]["summary"]
    assert f"({summary['preserved_percent']}% preserved)" in stderr
    assert "Per-construct losses:" in stderr and worst["construct"] in stderr
