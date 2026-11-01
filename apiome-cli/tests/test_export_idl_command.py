"""``apiome export idl`` — MFX-28.4 (#4171).

The OMG IDL definition (CORBA or DDS profile) is a registry target keyed ``corbaidl``; ``idl``, ``omg-idl`` and
``corba-idl`` resolve to it (``_EXPORT_TARGET_ALIASES``), so the verb runs through the generic export seam
(``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that every spelling
resolves, that the options (``profile`` and ``module`` as strings, ``key_fields`` as a JSON map,
``include_comments`` as a boolean) reach the preview and the job, that the one ``.idl`` file is written to
``--out``, that ``--json`` prints the tier, and that a lossy export exits non-zero unless ``--force``.

The fixtures are recorded from the REST emitter registry: ``apiome-rest/tests/test_corbaidl_target_card.py``
keeps ``export-targets-corbaidl.json`` equal to the live descriptor, options schema and badge, and
``export-job-completed-corbaidl-lossy.json`` equal to the Petstore export's live fidelity and file name.
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
_TARGETS = json.loads((_FIXTURES / "export-targets-corbaidl.json").read_text())
_JOB = json.loads((_FIXTURES / "export-job-completed-corbaidl-lossy.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pet Store", "slug": "pet-store", "enabled": True}
_BASE = "http://localhost:8000"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_IDL_NAME = _JOB["result"]["files"][0]["path"]
_IDL_TEXT = "// Generated OMG IDL 4.2 (DDS profile) for Pet Store\n\nmodule PetStore {\n  struct Pet {\n    @key long long id;\n  };\n};\n"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_export(httpx_mock: object) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and the ``.idl`` download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=_JOB)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=_IDL_TEXT.encode("utf-8"),
                            headers={"Content-Type": "text/plain",
                                     "Content-Disposition": f'attachment; filename="{_IDL_NAME}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "idl", "pet-store", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


@pytest.mark.parametrize("spelling", ["idl", "IDL", "omg-idl", "corba-idl", "corbaidl"])
def test_every_spelling_resolves_to_the_corbaidl_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "corbaidl"


def test_the_fixture_carries_the_options_and_the_lossy_badge() -> None:
    target = _TARGETS["targets"][0]
    assert set(target["options_schema"]["properties"]) == {"include_comments", "key_fields", "module", "profile"}
    assert target["options_schema"]["properties"]["profile"]["enum"] == ["corba", "dds"]
    assert target["default_options"] == {"include_comments": True, "key_fields": {}, "module": None,
                                         "profile": "corba"}
    assert target["descriptor"]["multi_file"] is False
    assert target["fidelity"]["tier"] == "lossy"


def test_the_job_fixture_writes_one_idl_file() -> None:
    assert [row["path"].endswith(".idl") for row in _JOB["result"]["files"]] == [True]


def test_a_lossy_export_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.idl"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The file is still written: the exit code only flags the loss.
    assert out.read_text(encoding="utf-8") == _IDL_TEXT
    assert "lossy" in strip_ansi(result.stderr)


def test_force_writes_the_idl_file(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    out = tmp_path / "petstore.idl"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert out.read_text(encoding="utf-8") == _IDL_TEXT


def test_the_options_reach_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, _args(str(tmp_path / "petstore.idl"), "--force",
                                      "--option", "profile=dds", "--option", 'key_fields={"Pet": ["id"]}',
                                      "--option", "module=acme::pets"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"profile": "dds", "key_fields": {"Pet": ["id"]}, "module": "acme::pets"}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    job = _posted(httpx_mock, "/jobs")
    assert (job["target"], job["options"]) == ("corbaidl", expected)


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock)
    result = runner.invoke(app, ["--json", *_args(str(tmp_path / "petstore.idl"), "--force")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert (payload["format"], payload["fidelity_target"]) == ("idl", "corbaidl")
    assert payload["fidelity"]["status"] == "lossy"


def test_export_targets_lists_corbaidl_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    assert next(r for r in rows if r["descriptor"]["key"] == "corbaidl")["fidelity"]["tier"] == "lossy"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "idl", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.output)
    assert "Export an artifact to 'idl'" in output and "--option" in output
