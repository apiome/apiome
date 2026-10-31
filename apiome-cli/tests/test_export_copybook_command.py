"""``apiome export copybook`` — MFX-23.5 (#4143).

The COBOL copybook target is a registry target (``cobolcopybook``), so the verb runs through the generic
export seam (``export <format> <artifact>``, MFX-8.1); ``copybook``, ``cobol`` and ``cobol-copybook`` are
its user-facing spellings. These tests pin that every spelling resolves, that the layout options
(``numeric_usage``, ``fixed_format``, ``default_string_length``, ``default_occurs``, ``decimal_scale``) reach
the preview and the job as typed values, that ``--json`` prints the metadata with the fidelity tier, and
that a REST source — copybook is one of the lossiest targets, ``types-only`` for anything that is not a
copybook — exits non-zero unless ``--force``.

The fixtures are recorded from the REST emitter registry (``apiome-rest/tests/test_copybook_target_card.py``
keeps ``export-targets-copybook.json`` equal to the live descriptor, options schema and badge); the job
envelopes carry the real fidelity of an OpenAPI order API (``types-only``) and a copybook item
(``lossless``), and ``export-copybook-order.cpy`` is the emitter's own output.

PL/I output (``--pli``) is not offered yet: it waits on the PL/I output mode, MFX-23.3 (#4141).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_registry import resolve_export_target
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-copybook.json").read_text())
_JOB_TYPES_ONLY = json.loads((_FIXTURES / "export-job-completed-copybook-types-only.json").read_text())
_JOB_LOSSLESS = json.loads((_FIXTURES / "export-job-completed-copybook-lossless.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
_COPYBOOK = (_FIXTURES / "export-copybook-order.cpy").read_bytes()

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Orders", "slug": "orders", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object, *, job: dict) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the .cpy download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/orders", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=job)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_COPYBOOK,
                            headers={"Content-Type": "text/plain",
                                     "Content-Disposition": 'attachment; filename="Order.cpy"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "copybook", "orders", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["copybook", "cobol", "cobol-copybook", "cobolcopybook", "COPYBOOK"])
def test_every_spelling_resolves_to_the_copybook_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "cobolcopybook"


def test_the_fixture_carries_the_layout_options_and_the_types_only_badge() -> None:
    target = _TARGETS["targets"][0]
    properties = target["options_schema"]["properties"]
    assert properties["numeric_usage"]["enum"] == ["comp", "display"]
    assert {"fixed_format", "default_string_length", "default_occurs", "decimal_scale"} <= set(properties)
    assert target["default_options"]["default_occurs"] == 10
    # The card's tier for a REST source: operations dropped, lengths and names synthesized.
    assert target["fidelity"]["tier"] == "types-only"


def test_a_rest_source_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_TYPES_ONLY)
    out = tmp_path / "Order.cpy"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The copybook is still written: the exit code only flags the loss.
    assert out.read_bytes() == _COPYBOOK
    assert "types-only" in result.stderr


def test_force_accepts_a_types_only_export(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_TYPES_ONLY)
    result = runner.invoke(app, _args(str(tmp_path / "Order.cpy"), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    job = _posted(httpx_mock, "/jobs")
    assert job["target"] == "cobolcopybook" and "options" not in job


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS)
    out = tmp_path / "Order.cpy"
    result = runner.invoke(app, ["--json", *_args(str(out))])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("copybook", "cobolcopybook")
    assert payload["fidelity"]["status"] == "lossless"
    assert payload["output"] == str(out)


def test_layout_options_reach_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS)
    result = runner.invoke(app, _args(str(tmp_path / "Order.cpy"),
                                      "--option", "numeric_usage=display", "--option", "fixed_format=false",
                                      "--option", "default_string_length=40", "--option", "default_occurs=25",
                                      "--option", "decimal_scale=4"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"numeric_usage": "display", "fixed_format": False, "default_string_length": 40,
                "default_occurs": 25, "decimal_scale": 4}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    assert _posted(httpx_mock, "/jobs")["options"] == expected


def test_stdout_output_keeps_the_copybook_bytes_clean(httpx_mock: object) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS)
    result = runner.invoke(app, _args("-"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout_bytes == _COPYBOOK


def test_export_targets_lists_the_copybook_target_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/orders", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "orders", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    row = next(r for r in rows if r["descriptor"]["key"] == "cobolcopybook")
    assert row["fidelity"]["tier"] == "types-only"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "copybook", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Export an artifact to 'copybook'" in result.output and "--option" in result.output
