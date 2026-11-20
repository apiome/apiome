"""``apiome export openapi --refs bundle|dereference|split`` and ``--ref-cycles`` — COA-2.4 (#7047).

* ``--refs`` / ``--ref-cycles`` are shorthands for the OpenAPI target's ``refs`` / ``ref_cycles`` emit
  options; ``dereference`` and ``split`` run the export as a job (the browse download is the bundled
  document), ``bundle`` keeps the browse download.
* A split export is a multi-file bundle: ``--output`` a directory unpacks it, a ``.zip`` path keeps it.
* Misuse is a usage error: the same option twice, ``--ref-cycles`` without ``--refs dereference``, YAML.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from apiome_cli.commands.export import REF_CYCLE_POLICIES, REF_MODES, with_refs
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Payments API", "slug": "payments-api", "enabled": True}

_BASE = "http://localhost:8000"
_JOBS_URL = f"{_BASE}/v1/export/acme-corp/jobs"
_JOB_STATUS_URL = f"{_BASE}/v1/export/acme-corp/jobs/{_JOB_ID}"
_DOWNLOAD_URL = f"{_BASE}/v1/export/acme-corp/jobs/{_JOB_ID}/download"
_TARGETS_URL = f"{_BASE}/v1/export/acme-corp/targets?artifact={_PROJECT_ID}&version=1.0.0"
_PREVIEW_URL = f"{_BASE}/v1/export/acme-corp/preview"

_OPENAPI_BYTES = (_FIXTURES / "export-openapi-lossless.json").read_bytes()


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _split_zip() -> bytes:
    """A split OpenAPI export as the job serves it (root + unit files + manifest.json)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "openapi.json",
            json.dumps({"openapi": "3.1.0", "paths": {"/pets": {"$ref": "paths/pets.json"}}}),
        )
        archive.writestr("paths/pets.json", json.dumps({"get": {"responses": {}}}))
        archive.writestr("components/schemas/Pet.json", json.dumps({"type": "object"}))
        archive.writestr("manifest.json", "{}\n")
    return buffer.getvalue()


def _mock_export(httpx_mock: object, *, body: bytes, content_type: str) -> None:
    """Mock project lookup, targets, preview, a completed job and its download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=json.loads((_FIXTURES / "export-targets.json").read_text()))
    httpx_mock.add_response(
        url=_PREVIEW_URL,
        method="POST",
        json=json.loads((_FIXTURES / "export-preview-lossless.json").read_text()),
    )
    httpx_mock.add_response(
        url=_JOBS_URL,
        method="POST",
        json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"},
        status_code=202,
    )
    httpx_mock.add_response(
        url=_JOB_STATUS_URL, json=json.loads((_FIXTURES / "export-job-completed-lossless.json").read_text())
    )
    httpx_mock.add_response(
        url=_DOWNLOAD_URL,
        content=body,
        headers={"Content-Type": content_type, "Content-Disposition": 'attachment; filename="export.zip"'},
    )


def _job_options(httpx_mock: object) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith("/jobs") and r.method == "POST")
    return json.loads(request.content).get("options") or {}


def _openapi_args(output: str, *extra: str) -> list:
    return ["export", "openapi", "--project", "payments-api", "--version", "1.0.0", "--output", output, *extra]


# ---------------------------------------------------------------------------
# with_refs
# ---------------------------------------------------------------------------
def test_with_refs_appends_the_options() -> None:
    assert with_refs((), None, None) == ()
    assert with_refs(("a=1",), "split", None) == ("a=1", "refs=split")
    assert with_refs((), "dereference", "error") == ("refs=dereference", "ref_cycles=error")
    # --ref-cycles may pair with an --option refs=dereference.
    assert with_refs(("refs=dereference",), None, "keep-ref") == ("refs=dereference", "ref_cycles=keep-ref")


@pytest.mark.parametrize(
    ("values", "refs", "cycles"),
    [
        (("refs=split",), "split", None),
        (("ref_cycles=error",), "dereference", "error"),
        ((), "split", "error"),
        ((), None, "error"),
    ],
)
def test_with_refs_refuses_misuse(values: tuple, refs: str | None, cycles: str | None) -> None:
    with pytest.raises(typer.Exit) as exc:
        with_refs(values, refs, cycles)
    assert exc.value.exit_code == EXIT_USAGE


def test_the_choices_match_the_rest_option() -> None:
    assert REF_MODES == ("bundle", "dereference", "split")
    assert REF_CYCLE_POLICIES == ("keep-ref", "error")


# ---------------------------------------------------------------------------
# apiome export openapi --refs
# ---------------------------------------------------------------------------
def test_export_openapi_split_runs_the_job_and_unpacks_the_files(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, body=_split_zip(), content_type="application/zip")
    out = tmp_path / "payments-openapi"

    result = runner.invoke(app, _openapi_args(str(out), "--refs", "split"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _job_options(httpx_mock) == {"refs": "split"}
    assert json.loads((out / "openapi.json").read_text())["paths"]["/pets"] == {"$ref": "paths/pets.json"}
    assert (out / "paths" / "pets.json").is_file()
    assert (out / "components" / "schemas" / "Pet.json").is_file()


def test_export_openapi_split_to_a_zip_keeps_the_archive(httpx_mock: object, tmp_path: Path) -> None:
    body = _split_zip()
    _mock_export(httpx_mock, body=body, content_type="application/zip")
    out = tmp_path / "payments-openapi.zip"

    result = runner.invoke(app, _openapi_args(str(out), "--refs", "split"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert out.read_bytes() == body


def test_export_openapi_dereference_sends_the_cycle_policy(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, body=_OPENAPI_BYTES, content_type="application/json")
    out = tmp_path / "openapi.json"

    result = runner.invoke(app, _openapi_args(str(out), "--refs", "dereference", "--ref-cycles", "error"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _job_options(httpx_mock) == {"refs": "dereference", "ref_cycles": "error"}
    assert out.read_bytes() == _OPENAPI_BYTES


def test_export_openapi_refs_refuses_yaml(tmp_path: Path) -> None:
    result = runner.invoke(app, _openapi_args(str(tmp_path / "o.yaml"), "--yaml", "--refs", "split"))
    assert result.exit_code == EXIT_USAGE
    assert "--refs exports through the job pipeline" in result.stderr


def test_export_openapi_ref_cycles_needs_dereference(tmp_path: Path) -> None:
    result = runner.invoke(app, _openapi_args(str(tmp_path / "o.json"), "--refs", "bundle", "--ref-cycles", "error"))
    assert result.exit_code == EXIT_USAGE
    assert "--ref-cycles only applies to --refs dereference" in result.stderr


def test_export_openapi_rejects_an_unknown_mode(tmp_path: Path) -> None:
    result = runner.invoke(app, _openapi_args(str(tmp_path / "o.json"), "--refs", "inline"))
    assert result.exit_code == EXIT_USAGE


# ---------------------------------------------------------------------------
# apiome export openapi-3.1 <artifact> --refs (the job command)
# ---------------------------------------------------------------------------
def test_the_job_command_takes_refs_for_an_openapi_target(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, body=_split_zip(), content_type="application/zip")
    out = tmp_path / "split"

    result = runner.invoke(
        app,
        ["export", "openapi-3.1", "payments-api", "--version", "1.0.0", "--out", str(out),
         "--poll-interval", "0.1", "--refs", "split"],
    )

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _job_options(httpx_mock) == {"refs": "split"}
    assert (out / "paths" / "pets.json").is_file()


def test_the_job_command_has_no_refs_flag_for_other_targets(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["export", "protobuf", "payments-api", "--out", str(tmp_path / "x"), "--refs", "split"]
    )
    assert result.exit_code == EXIT_USAGE
    assert "No such option" in result.output + result.stderr
