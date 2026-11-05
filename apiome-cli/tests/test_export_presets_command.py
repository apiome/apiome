"""``apiome export presets …`` and ``apiome export --preset NAME …`` (MFX-39.3).

Against a mocked REST surface (``pytest-httpx``): the bodies ``presets create`` / ``update`` send (targets
in order, ``TARGET:KEY=VALUE`` options parsed as JSON, a delivery profile by name, ``--no-deliver``), the
list / show / delete output, and running a preset — the job submitted with ``"preset"`` and the source,
a one-target result written as a file, a multi-target one as an archive with the outcome table, and the
preset's delivery reported after the download. Unknown options are still refused without ``--preset``.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_presets import build_targets, targets_summary
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000"
_PRESETS = f"{_BASE}/v1/export/acme-corp/presets"
_PROFILES = f"{_BASE}/v1/export/acme-corp/delivery-profiles"
_JOBS = f"{_BASE}/v1/export/acme-corp/jobs"
_PRESET_ID = "77777777-7777-4777-8777-777777777777"
_PROFILE_ID = "55555555-5555-4555-8555-555555555555"
_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_DOWNLOAD = f"/v1/export/acme-corp/jobs/{_JOB_ID}/download"

_PRESET = {
    "id": _PRESET_ID, "name": "nightly-sync", "description": "Nightly",
    "targets": [{"target": "openapi", "options": {"openapi_version": "3.0"}}, {"target": "protobuf", "options": None}],
    "deliveryProfileId": _PROFILE_ID, "deliveryProfileName": "lake",
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _sent(httpx_mock, method: str) -> dict:
    [request] = [r for r in httpx_mock.get_requests() if r.method == method]
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# Flags → targets
# ---------------------------------------------------------------------------
def test_build_targets_keeps_order_and_parses_option_values():
    assert build_targets(["openapi", "protobuf", "openapi"], ["openapi:openapi_version=3.0", "protobuf:emit_services=false",
                                                              'protobuf:package="acme.v1"']) == [
        {"target": "openapi", "options": {"openapi_version": 3.0}},
        {"target": "protobuf", "options": {"emit_services": False, "package": "acme.v1"}},
    ]
    assert build_targets(["openapi"], ["openapi:openapi_version=\"3.0\""])[0]["options"] == {"openapi_version": "3.0"}


@pytest.mark.parametrize("targets, options", [([], []), (["openapi"], ["openapi_version=3.0"]),
                                              (["openapi"], ["graphql:x=1"]), (["openapi"], ["openapi:=1"])])
def test_build_targets_refuses_bad_flags(targets, options):
    with pytest.raises(Exception) as caught:
        build_targets(targets, options)
    assert getattr(caught.value, "exit_code", None) == EXIT_USAGE


def test_targets_summary():
    assert targets_summary(_PRESET["targets"]) == "openapi (openapi_version=3.0), protobuf"


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------
def test_presets_create_with_options_and_a_delivery_profile_by_name(httpx_mock):
    httpx_mock.add_response(url=_PROFILES, json={"profiles": [{"id": _PROFILE_ID, "name": "lake"}]})
    httpx_mock.add_response(url=_PRESETS, method="POST", json=_PRESET, status_code=201)
    outcome = runner.invoke(app, ["export", "presets", "create", "nightly-sync", "--target", "openapi",
                                  "--option", 'openapi:openapi_version="3.0"', "--target", "protobuf",
                                  "--deliver", "lake", "--description", "Nightly"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _sent(httpx_mock, "POST") == {
        "name": "nightly-sync", "description": "Nightly", "deliveryProfileId": _PROFILE_ID,
        "targets": [{"target": "openapi", "options": {"openapi_version": "3.0"}}, {"target": "protobuf", "options": {}}],
    }
    assert "Created preset 'nightly-sync': openapi (openapi_version=3.0), protobuf, delivered with 'lake'" in outcome.output


def test_presets_list_show_and_delete(httpx_mock):
    httpx_mock.add_response(url=_PRESETS, json={"presets": [_PRESET]})
    httpx_mock.add_response(url=f"{_PRESETS}/nightly-sync", json=_PRESET)
    httpx_mock.add_response(url=f"{_PRESETS}/nightly-sync", method="DELETE", status_code=204)
    listed = runner.invoke(app, ["export", "presets", "list"])
    assert listed.exit_code == EXIT_SUCCESS, listed.output
    assert "nightly-sync" in listed.output and "lake" in listed.output
    shown = runner.invoke(app, ["export", "presets", "show", "nightly-sync"])
    assert "Target: openapi  options: {'openapi_version': '3.0'}" in shown.output
    assert "Delivery: lake" in shown.output
    deleted = runner.invoke(app, ["export", "presets", "delete", "nightly-sync", "--yes"])
    assert deleted.exit_code == EXIT_SUCCESS and "Deleted export preset 'nightly-sync'." in deleted.output


def test_presets_update_replaces_targets_and_removes_delivery(httpx_mock):
    httpx_mock.add_response(url=f"{_PRESETS}/nightly-sync", method="PATCH", json={**_PRESET, "deliveryProfileName": None})
    outcome = runner.invoke(app, ["export", "presets", "update", "nightly-sync", "--target", "graphql", "--no-deliver"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _sent(httpx_mock, "PATCH") == {"targets": [{"target": "graphql", "options": {}}], "deliveryProfileId": None}


def test_presets_update_refusals():
    assert runner.invoke(app, ["export", "presets", "update", "p"]).exit_code == EXIT_USAGE
    assert runner.invoke(app, ["export", "presets", "update", "p", "--option", "a:b=1"]).exit_code == EXIT_USAGE
    assert runner.invoke(app, ["export", "presets", "update", "p", "--deliver", "x", "--no-deliver"]).exit_code == EXIT_USAGE


# ---------------------------------------------------------------------------
# export --preset
# ---------------------------------------------------------------------------
def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("openapi-3.1/openapi.json", "{}")
    return buffer.getvalue()


def _mock_run(httpx_mock, preset: dict, *, result: dict, content: bytes, content_type: str, events: list):
    httpx_mock.add_response(url=f"{_PRESETS}/nightly-sync", json=preset)
    httpx_mock.add_response(url=_JOBS, method="POST", json={"job_id": _JOB_ID})
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}", json={"job_id": _JOB_ID, "state": "completed", "events": [],
                                                             "result": result})
    httpx_mock.add_response(url=f"{_BASE}{_DOWNLOAD}", content=content, headers={"Content-Type": content_type})
    if events is not None:
        httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}", json={"job_id": _JOB_ID, "state": "completed",
                                                                 "events": events, "result": result})


def test_export_preset_runs_a_multi_target_preset_and_reports_its_delivery(httpx_mock, tmp_path):
    result = {"artifact": _A, "download_path": _DOWNLOAD,
              "targets": [{"target": "openapi-3.1", "directory": "openapi-3.1", "fidelity": {"summary": {"tier": "lossless"}}}],
              "fidelity_rollup": {"tier": "lossless"}}
    _mock_run(httpx_mock, _PRESET, result=result, content=_zip(), content_type="application/zip",
              events=[{"code": "EXPORT_DELIVERED", "message": "Delivered with profile 'lake'"}])
    out = tmp_path / "bundle"
    outcome = runner.invoke(app, ["export", "--preset", "nightly-sync", _A, "--version", "1.0.0", "--out", str(out),
                                  "--confirm"], terminal_width=200)
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _sent(httpx_mock, "POST") == {"preset": _PRESET_ID, "confirm": True, "artifact": _A, "version": "1.0.0"}
    assert (out / "openapi-3.1" / "openapi.json").exists()
    assert "Exported with preset 'nightly-sync'" in outcome.output
    assert "Delivered: Delivered with profile 'lake'" in outcome.output


def test_export_preset_writes_a_one_target_file_and_adds_deliver_profiles(httpx_mock, tmp_path):
    preset = {**_PRESET, "targets": [_PRESET["targets"][0]], "deliveryProfileId": None, "deliveryProfileName": None}
    httpx_mock.add_response(url=_PROFILES, json={"profiles": [{"id": _PROFILE_ID, "name": "lake"}]})
    result = {"artifact": _A, "download_path": _DOWNLOAD, "fidelity": {"summary": {"tier": "lossless"}},
              "files": [{"path": "openapi.json", "media_type": "application/json", "size_bytes": 2}]}
    _mock_run(httpx_mock, preset, result=result, content=b"{}", content_type="application/json",
              events=[{"code": "EXPORT_DELIVERY_FAILED", "message": "bucket missing"}])
    out = tmp_path / "orders.json"
    outcome = runner.invoke(app, ["export", "--preset", "nightly-sync", _A, "--out", str(out), "--deliver", "lake"])
    assert outcome.exit_code == EXIT_ERROR, outcome.output
    assert _sent(httpx_mock, "POST")["delivery_profiles"] == [_PROFILE_ID]
    assert out.read_bytes() == b"{}"
    assert "Delivery failed: bucket missing" in outcome.output


def test_export_preset_usage_errors():
    assert runner.invoke(app, ["export", "--preset", "nightly-sync"]).exit_code == EXIT_USAGE
    no_out = runner.invoke(app, ["export", "--preset", "nightly-sync", _A])
    assert no_out.exit_code == EXIT_USAGE and "--out is required" in no_out.output
    both = runner.invoke(app, ["export", "--preset", "nightly-sync", _A, "--items", _A, "--out", "x"])
    assert both.exit_code == EXIT_USAGE


def test_an_unknown_option_without_a_preset_is_still_refused():
    outcome = runner.invoke(app, ["export", "--items", "x"])
    assert outcome.exit_code == EXIT_USAGE
    assert "No such option: --items" in outcome.output
