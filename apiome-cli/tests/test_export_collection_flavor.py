"""``apiome export postman --flavor insomnia|bruno`` and collection bundles — MFX-31.5 (#4293).

* ``--flavor`` is the ``postman`` command's shorthand for its ``flavor`` emit option: it is sent with
  the export job, refuses an unknown value, clashes with ``--option flavor=…``, and is not offered on
  other targets;
* a Bruno collection is a multi-file bundle: ``--out`` a directory unpacks ``bruno.json`` and the
  ``.bru`` files, a ``.zip`` path keeps the archive;
* unpacking never writes outside ``--out`` (a ``..`` or absolute member is refused).
"""

from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.export_dispatch import write_export_artifact
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


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _targets() -> dict:
    """The registry fixture plus a ``postman`` target with its ``flavor`` option."""
    targets = json.loads((_FIXTURES / "export-targets.json").read_text())
    postman = copy.deepcopy(targets["targets"][0])
    postman["descriptor"].update(key="postman", format="postman", label="Postman")
    postman["options_schema"] = {
        "properties": {"flavor": {"enum": ["postman", "insomnia", "bruno"], "default": "postman", "type": "string"}}
    }
    postman["default_options"] = {"flavor": "postman"}
    targets["targets"].append(postman)
    return targets


def _bruno_zip() -> bytes:
    """A Bruno collection bundle as the export job serves it (files + manifest.json)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bruno.json", '{"version": "1", "name": "Payments API", "type": "collection"}\n')
        archive.writestr("Payments/List payments.bru", "meta {\n  name: List payments\n}\n")
        archive.writestr("environments/Default.bru", "vars {\n  baseUrl: https://api.example.com\n}\n")
        archive.writestr("manifest.json", "{}\n")
    return buffer.getvalue()


def _mock_export(httpx_mock: object, *, body: bytes, content_type: str) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_targets())
    httpx_mock.add_response(
        url=_PREVIEW_URL, method="POST", json=json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
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


def _args(out: str, *extra: str) -> list:
    return ["export", "postman", "payments-api", "--version", "1.0.0", "--out", out, "--poll-interval", "0.1", *extra]


def _job_options(httpx_mock: object) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith("/jobs") and r.method == "POST")
    return json.loads(request.content).get("options") or {}


def test_flavor_bruno_is_sent_and_the_bundle_is_unpacked(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, body=_bruno_zip(), content_type="application/zip")
    out = tmp_path / "payments-bruno"

    result = runner.invoke(app, _args(str(out), "--flavor", "bruno"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _job_options(httpx_mock) == {"flavor": "bruno"}
    assert json.loads((out / "bruno.json").read_text())["type"] == "collection"
    assert (out / "Payments" / "List payments.bru").is_file()
    assert (out / "environments" / "Default.bru").is_file()


def test_a_zip_out_path_keeps_the_archive(httpx_mock: object, tmp_path: Path) -> None:
    body = _bruno_zip()
    _mock_export(httpx_mock, body=body, content_type="application/zip")
    out = tmp_path / "payments-bruno.zip"

    result = runner.invoke(app, _args(str(out), "--flavor", "bruno"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert out.read_bytes() == body


def test_flavor_insomnia_writes_one_file(httpx_mock: object, tmp_path: Path) -> None:
    document = b'{"_type": "export", "__export_format": 4, "resources": []}\n'
    _mock_export(httpx_mock, body=document, content_type="application/json")
    out = tmp_path / "payments.insomnia.json"

    result = runner.invoke(app, _args(str(out), "--flavor", "insomnia"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _job_options(httpx_mock) == {"flavor": "insomnia"}
    assert out.read_bytes() == document


def test_flavor_and_option_flavor_together_are_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, _args(str(tmp_path / "x"), "--flavor", "bruno", "--option", "flavor=insomnia"))
    assert result.exit_code == EXIT_USAGE
    assert "--flavor or --option flavor" in result.stderr


def test_an_unknown_flavor_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, _args(str(tmp_path / "x"), "--flavor", "paw"))
    assert result.exit_code == 2
    assert "paw" in result.stderr


def test_other_targets_have_no_flavor_flag(tmp_path: Path) -> None:
    args = ["export", "openapi-3.1", "payments-api", "--out", str(tmp_path / "x"), "--flavor", "bruno"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "No such option" in result.stderr


def test_postman_help_documents_the_flavor_flag() -> None:
    result = runner.invoke(app, ["export", "postman", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "--flavor" in result.stdout and "insomnia" in result.stdout and "bruno" in result.stdout


@pytest.mark.parametrize("member", ["../escape.bru", "nested/../../escape.bru", "/abs/escape.bru"])
def test_unpacking_never_writes_outside_out(tmp_path: Path, member: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bruno.json", "{}")
        archive.writestr(member, "x")
    out = tmp_path / "out"

    with pytest.raises(Exception) as raised:
        write_export_artifact(
            buffer.getvalue(), out=str(out), content_type="application/zip", files=None, disposition_filename=None
        )

    assert getattr(raised.value, "exit_code", None) == EXIT_USAGE
    assert not (tmp_path / "escape.bru").exists() and not Path("/abs/escape.bru").exists()


def test_a_nested_member_inside_out_is_unpacked(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a/./b/../c.bru", "x")
    out = tmp_path / "out"
    write_export_artifact(buffer.getvalue(), out=str(out), content_type="application/zip", files=None,
                          disposition_filename=None)
    assert (out / "a" / "c.bru").read_text() == "x"
