"""``apiome export jsonschema`` — MFX-21.5 (#4130).

JSON Schema is a registry target (``json-schema``), so the verb runs through the generic export seam
(``export <format> <artifact>``, MFX-8.1). ``jsonschema`` (and ``json_schema``) are the hyphen-free
spellings of the key. These tests pin that every spelling resolves, that ``draft`` / ``packaging`` /
``mode`` reach the preview and the job as typed values, that a per-type export (a zip) unpacks into a
directory, that ``--json`` prints the metadata with the fidelity tier, and that a REST source — whose
operations a types-only target drops — exits non-zero unless ``--force``.

The fixtures are recorded from the REST emitter registry (``apiome-rest/tests/test_jsonschema_target_card.py``
keeps ``export-targets-json-schema.json`` equal to the live descriptor, options schema and defaults): the
job envelopes carry the real fidelity of the Petstore OpenAPI (``types-only``) and a JSON Schema item
(``lossless``), and the downloaded documents are the emitter's own output.
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
_TARGETS = json.loads((_FIXTURES / "export-targets-json-schema.json").read_text())
_JOB_TYPES_ONLY = json.loads((_FIXTURES / "export-job-completed-json-schema-types-only.json").read_text())
_JOB_LOSSLESS = json.loads((_FIXTURES / "export-job-completed-json-schema-lossless.json").read_text())
_PREVIEW = json.loads((_FIXTURES / "export-preview-lossless.json").read_text())
_BUNDLE = (_FIXTURES / "json-schema-bundle.schema.json").read_bytes()

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


def _mock_export(httpx_mock: object, *, job: dict, body: bytes, content_type: str, filename: str) -> None:
    """Serve one export: project lookup, targets, preview, job start, job status and download."""
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/preview", method="POST", json=_PREVIEW)
    httpx_mock.add_response(url=_JOBS_URL, method="POST", status_code=202,
                            json={"job_id": _JOB_ID, "status_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}"})
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}", json=job)
    httpx_mock.add_response(url=f"{_JOBS_URL}/{_JOB_ID}/download", content=body,
                            headers={"Content-Type": content_type,
                                     "Content-Disposition": f'attachment; filename="{filename}"'})


def _posted(httpx_mock: object, suffix: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(suffix) and r.method == "POST")
    return json.loads(request.content)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "jsonschema", "pet-store", "--version", "1.0.0", "--out", out,
            "--poll-interval", "0.1", *extra]


def _per_type_zip() -> bytes:
    """A per-type export as the job delivers it: one ``<Type>.schema.json`` per type, plus a manifest."""
    bundle = json.loads(_BUNDLE)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, schema in bundle["$defs"].items():
            archive.writestr(f"{name}.schema.json", json.dumps({"title": name, **schema}))
        archive.writestr("manifest.json", json.dumps({"files": sorted(bundle["$defs"])}))
    return buffer.getvalue()


@pytest.mark.parametrize("spelling", ["jsonschema", "json-schema", "json_schema", "JSONSchema"])
def test_every_spelling_resolves_to_the_json_schema_target(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "json-schema"


def test_jtd_is_its_own_target() -> None:
    assert resolve_export_target("jtd", _TARGETS["targets"]) == "jtd"


def test_the_fixture_carries_the_draft_packaging_and_mode_options() -> None:
    target = next(t for t in _TARGETS["targets"] if t["descriptor"]["key"] == "json-schema")
    properties = target["options_schema"]["properties"]
    assert properties["draft"]["enum"] == ["2020-12", "draft-07", "draft-04"]
    assert properties["packaging"]["enum"] == ["bundle", "per-type"]
    assert properties["mode"]["enum"] == ["json-schema", "jtd"]
    assert target["default_options"]["draft"] == "2020-12"
    # The card's tier for a REST source: its operations are dropped.
    assert target["fidelity"]["tier"] == "types-only"


def test_a_rest_source_exits_nonzero_without_force(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_TYPES_ONLY, body=_BUNDLE, content_type="application/json",
                 filename="Sample-Pet-Store-API-OpenAPI-3.0.schema.json")
    out = tmp_path / "pet.schema.json"
    result = runner.invoke(app, _args(str(out)))
    assert result.exit_code == EXIT_ERROR, result.output
    # The document is still written: the exit code only flags the loss.
    assert out.read_bytes() == _BUNDLE
    assert "types-only" in result.stderr


def test_force_accepts_a_types_only_export(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_TYPES_ONLY, body=_BUNDLE, content_type="application/json",
                 filename="Sample-Pet-Store-API-OpenAPI-3.0.schema.json")
    out = tmp_path / "pet.schema.json"
    result = runner.invoke(app, _args(str(out), "--force"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    job = _posted(httpx_mock, "/jobs")
    assert job["target"] == "json-schema" and "options" not in job


def test_json_mode_prints_the_metadata_with_the_tier(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS, body=_BUNDLE, content_type="application/json",
                 filename="Address-Book.schema.json")
    out = tmp_path / "address-book.schema.json"
    result = runner.invoke(app, ["--json", *_args(str(out))])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["format"] == "jsonschema"
    assert payload["fidelity_target"] == "json-schema"
    assert payload["fidelity"]["status"] == "lossless"
    assert payload["output"] == str(out)


def test_draft_downgrade_options_reach_the_preview_and_the_job(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS, body=_BUNDLE, content_type="application/json",
                 filename="Address-Book.schema.json")
    out = tmp_path / "address-book.schema.json"
    result = runner.invoke(app, _args(str(out), "--option", "draft=draft-04",
                                      "--option", "id_base=https://schemas.example.com/shop"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    expected = {"draft": "draft-04", "id_base": "https://schemas.example.com/shop"}
    assert _posted(httpx_mock, "/preview")["options"] == expected
    assert _posted(httpx_mock, "/jobs")["options"] == expected


def test_a_per_type_export_unpacks_into_the_out_directory(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS, body=_per_type_zip(), content_type="application/zip",
                 filename="pet-store-json-schema.zip")
    out = tmp_path / "schemas"
    result = runner.invoke(app, _args(str(out), "--option", "packaging=per-type"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert sorted(p.name for p in out.iterdir()) == ["Category.schema.json", "Pet.schema.json", "manifest.json"]
    assert json.loads((out / "Pet.schema.json").read_text())["title"] == "Pet"
    assert _posted(httpx_mock, "/jobs")["options"] == {"packaging": "per-type"}


def test_mode_jtd_is_passed_as_an_option(httpx_mock: object, tmp_path: Path) -> None:
    _mock_export(httpx_mock, job=_JOB_LOSSLESS, body=b'{"definitions": {}}\n', content_type="application/json",
                 filename="Address-Book.jtd.json")
    out = tmp_path / "address-book.jtd.json"
    result = runner.invoke(app, _args(str(out), "--option", "mode=jtd"))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posted(httpx_mock, "/jobs")["options"] == {"mode": "jtd"}


def test_export_targets_lists_json_schema_with_its_tier(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pet-store", json=_PROJECT)
    httpx_mock.add_response(url=_TARGETS_URL, json=_TARGETS)
    result = runner.invoke(app, ["--json", "export", "targets", "--project", "pet-store", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    rows = payload["targets"] if isinstance(payload, dict) else payload
    row = next(r for r in rows if r["descriptor"]["key"] == "json-schema")
    assert row["fidelity"]["tier"] == "types-only"


def test_the_verb_has_help() -> None:
    result = runner.invoke(app, ["export", "jsonschema", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Export an artifact to 'jsonschema'" in result.output and "--option" in result.output
