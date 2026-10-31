"""``apiome export x12`` — MFX-24.5 (#4149).

The X12 implementation guide is a registry target (``x12-guide``), so the verb runs through the generic
export seam (``export <format> <artifact>``, MFX-8.1). ``x12`` names the **guide**; the X12 interchange
target stays ``apiome export edix12``. These tests pin that the spellings resolve (and that ``x12`` picks
the guide even beside the interchange), that the transaction-set picker (``transaction_set``, ``version``)
reaches the preview and the job, that the three-file zip unpacks into ``--out``, that ``--json`` prints the
tier, and that a types-only export (every source is, for a guide) exits non-zero unless ``--force``.

The fixtures are recorded from the REST emitter registry (``apiome-rest/tests/test_x12_guide_target_card.py``
keeps ``export-targets-x12-guide.json`` equal to the live descriptor, options schema and badge); the job
envelope carries the real fidelity of the Petstore OpenAPI.

The UN/EDIFACT message guide (``apiome export edifact``) waits on its emitter, MFX-24.2 (#4146).
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

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-x12-guide.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-x12-guide-types-only.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_GUIDE_FILES = [row["path"] for row in _JOB["result"]["files"]]


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _bundle() -> bytes:
    """The guide as the job delivers it: the JSON guide, the segment CSV and the Markdown guide, zipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in _GUIDE_FILES:
            archive.writestr(path, f"{path}\n")
        archive.writestr("manifest.json", json.dumps({"files": _GUIDE_FILES}))
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
                                     "Content-Disposition": 'attachment; filename="pet-store-x12-guide.zip"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "x12", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["x12", "X12", "x12guide", "x12-guide"])
def test_every_spelling_resolves_to_the_guide(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "x12-guide"


def test_x12_picks_the_guide_and_edix12_the_interchange_when_both_are_listed() -> None:
    interchange = {"descriptor": {"key": "edix12", "format": "edix12"}}
    targets = [interchange, *_TARGETS["targets"]]
    assert resolve_export_target("x12", targets) == "x12-guide"
    assert resolve_export_target("edix12", targets) == "edix12"


def test_the_fixture_carries_the_transaction_set_picker_and_the_types_only_badge() -> None:
    target = _TARGETS["targets"][0]
    properties = target["options_schema"]["properties"]
    assert {"transaction_set", "version", "default_element_length", "max_code_length"} <= set(properties)
    assert target["descriptor"]["multi_file"] is True
    assert target["fidelity"]["tier"] == "types-only"


def test_a_types_only_guide_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "guide"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The files are still written: the exit code only flags the loss.
    assert sorted(p.name for p in out.iterdir()) == sorted([*_GUIDE_FILES, "manifest.json"])
    assert "types-only" in result.stderr


def test_the_transaction_set_picker_reaches_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "guide"), "--force",
                                      "--option", "transaction_set=810", "--option", "version=004010"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    # The picker values are strings: "810" must not be sent as the number 810.
    expected = {"transaction_set": "810", "version": "004010"}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("x12-guide", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "guide"
    result = runner.invoke(app, ["--json", *_args(str(out), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("x12", "x12-guide")
    assert payload["fidelity"]["status"] == "types-only"


def test_export_targets_lists_the_guide_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "x12-guide")["fidelity"]["tier"] == "types-only"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "x12", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Export an artifact to 'x12'" in result.output and "--option" in result.output


_SCHEMA = {"properties": {
    "transaction_set": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "label": {"type": "string"},
    "default_element_length": {"type": "integer"},
    "either": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
    "flag": {"type": "boolean"},
}}


def test_a_text_option_keeps_the_typed_text_when_the_schema_says_string() -> None:
    from apiome_cli.export_dispatch import parse_export_options

    options = parse_export_options(
        ["transaction_set=810", "label=true", "default_element_length=35", "either=7", "flag=false", "other=12"],
        options_schema=_SCHEMA,
    )
    assert options == {"transaction_set": "810", "label": "true", "default_element_length": 35, "either": 7,
                       "flag": False, "other": 12}


def test_without_a_schema_values_are_parsed_as_json() -> None:
    from apiome_cli.export_dispatch import parse_export_options

    assert parse_export_options(["transaction_set=810", "version=004010"]) == {
        "transaction_set": 810, "version": "004010"}
