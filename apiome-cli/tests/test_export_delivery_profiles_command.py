"""``apiome export profiles …``, ``export deliver``, ``export deliveries`` and ``--deliver`` (MFX-38.4).

Pins the delivery-profile commands against a mocked REST surface (``pytest-httpx``): the bodies
``profiles create`` / ``update`` send for each channel (a webhook secret read from an environment
variable, never argv), name-or-id resolution, the list / show / delete output, delivering a finished
job (exit 1 when a delivery failed), a job's delivery list, and ``export <format> --items … --deliver``
— the job body carries the profile ids, and the deliveries made on completion print after the download.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.client.export_delivery_profiles import (
    build_destination,
    format_delivery_events,
    wait_for_job_deliveries,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000"
_PROFILES = f"{_BASE}/v1/export/acme-corp/delivery-profiles"
_PROFILE_ID = "55555555-5555-4555-8555-555555555555"
_REPO = "33333333-3333-4333-8333-333333333333"
_CREDENTIAL = "66666666-6666-4666-8666-666666666666"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOBS = f"{_BASE}/v1/export/acme-corp/jobs"
_DOWNLOAD = f"/v1/export/acme-corp/jobs/{_JOB_ID}/download"
_TARGETS = json.loads((Path(__file__).resolve().parent / "fixtures" / "export-targets.json").read_text())

_PROFILE = {
    "id": _PROFILE_ID, "name": "lake", "channel": "object_storage", "description": None,
    "destination": {"credentialId": _CREDENTIAL, "bucket": "data-lake", "prefix": "exports", "partitioning": []},
    "credentialRef": {"kind": "storage_credential", "id": _CREDENTIAL},
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _posted(httpx_mock, method: str = "POST") -> dict:
    [request] = [r for r in httpx_mock.get_requests() if r.method == method]
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# The destination flags
# ---------------------------------------------------------------------------
def test_build_destination_shapes_each_channel():
    assert build_destination("git", repository=_REPO, path="specs", base_branch="main") == {
        "git": {"repositoryId": _REPO, "targetPath": "specs", "mode": "pr", "baseBranch": "main"}}
    assert build_destination("webhook", url="https://h.example.com", secret="s" * 20) == {
        "webhook": {"url": "https://h.example.com", "artifact": "auto", "secret": "s" * 20}}
    assert build_destination("object_storage", credential=_CREDENTIAL, bucket="b", partitioning="artifact, target") == {
        "objectStorage": {"credentialId": _CREDENTIAL, "bucket": "b", "prefix": "", "partitioning": ["artifact", "target"]}}
    assert build_destination("git", require=False) is None


@pytest.mark.parametrize("channel, flags", [
    ("git", {}),
    ("webhook", {"url": "https://h.example.com"}),
    ("object_storage", {"bucket": "b"}),
    ("git", {"repository": _REPO, "bucket": "b"}),
    ("ftp", {}),
])
def test_build_destination_refuses_missing_or_stray_flags(channel, flags):
    with pytest.raises(Exception) as caught:
        build_destination(channel, **flags)
    assert getattr(caught.value, "exit_code", None) == EXIT_USAGE


def test_waiting_for_deliveries_stops_at_the_expected_count_or_the_deadline(httpx_mock):
    from apiome_cli.client.http import RestClient
    from apiome_cli.config import load_settings

    status = {"state": "completed", "events": [{"code": "EXPORT_COMPLETED"},
                                               {"code": "EXPORT_DELIVERED", "message": "Delivered to b"}]}
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}", json=status, is_reusable=True)
    client = RestClient(load_settings())
    events = wait_for_job_deliveries(client, "acme-corp", _JOB_ID, expected=1, poll_interval=0.01, timeout=5)
    assert [e["code"] for e in events] == ["EXPORT_DELIVERED"]
    clock = iter([0.0, 0.0, 10.0])
    events = wait_for_job_deliveries(client, "acme-corp", _JOB_ID, expected=2, poll_interval=0.01, timeout=1,
                                     sleep=lambda _s: None, monotonic=lambda: next(clock))
    assert len(events) == 1
    assert format_delivery_events(events, 2, _JOB_ID)[-1] == (
        f"1 delivery is still running; see apiome export deliveries {_JOB_ID}.")


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------
def test_profiles_create_storage(httpx_mock):
    httpx_mock.add_response(url=_PROFILES, method="POST", json=_PROFILE, status_code=201)
    outcome = runner.invoke(app, ["export", "profiles", "create", "lake", "--channel", "object_storage",
                                  "--credential", _CREDENTIAL, "--bucket", "data-lake", "--prefix", "exports",
                                  "--partitioning", "", "--description", "Nightly"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _posted(httpx_mock) == {"name": "lake", "channel": "object_storage", "description": "Nightly",
                                   "objectStorage": {"credentialId": _CREDENTIAL, "bucket": "data-lake",
                                                     "prefix": "exports", "partitioning": []}}
    assert "Created object_storage profile 'lake'" in outcome.output


def test_profiles_create_webhook_reads_the_secret_from_the_environment(httpx_mock, monkeypatch):
    monkeypatch.setenv("HOOK_SECRET", "a-very-long-signing-secret")
    httpx_mock.add_response(url=_PROFILES, method="POST", json={**_PROFILE, "channel": "webhook"}, status_code=201)
    outcome = runner.invoke(app, ["export", "profiles", "create", "ci", "--channel", "webhook",
                                  "--url", "https://ci.example.com/h", "--secret-env", "HOOK_SECRET"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _posted(httpx_mock)["webhook"] == {"url": "https://ci.example.com/h", "artifact": "auto",
                                              "secret": "a-very-long-signing-secret"}
    assert "a-very-long-signing-secret" not in outcome.output


def test_profiles_create_webhook_without_its_secret_variable_is_a_usage_error(monkeypatch):
    monkeypatch.delenv("HOOK_SECRET", raising=False)
    outcome = runner.invoke(app, ["export", "profiles", "create", "ci", "--channel", "webhook",
                                  "--url", "https://ci.example.com/h", "--secret-env", "HOOK_SECRET"])
    assert outcome.exit_code == EXIT_USAGE
    assert "HOOK_SECRET is not set" in outcome.output


def test_profiles_list_and_show_by_name(httpx_mock):
    httpx_mock.add_response(url=_PROFILES, json={"profiles": [_PROFILE]}, is_reusable=True)
    httpx_mock.add_response(url=f"{_PROFILES}/{_PROFILE_ID}", json=_PROFILE)
    listed = runner.invoke(app, ["export", "profiles", "list"], terminal_width=200)
    assert listed.exit_code == EXIT_SUCCESS, listed.output
    assert "lake" in listed.output and "data-lake/exports" in listed.output
    shown = runner.invoke(app, ["export", "profiles", "show", "lake"])
    assert shown.exit_code == EXIT_SUCCESS, shown.output
    assert f"ID: {_PROFILE_ID}" in shown.output and "storage_credential" in shown.output


def test_an_unknown_profile_name_is_a_usage_error(httpx_mock):
    httpx_mock.add_response(url=_PROFILES, json={"profiles": [_PROFILE]})
    outcome = runner.invoke(app, ["export", "profiles", "show", "nope"])
    assert outcome.exit_code == EXIT_USAGE
    assert "No delivery profile named 'nope'" in outcome.output


def test_profiles_update_replaces_the_destination_of_its_own_channel(httpx_mock):
    httpx_mock.add_response(url=f"{_PROFILES}/{_PROFILE_ID}", json=_PROFILE)
    httpx_mock.add_response(url=f"{_PROFILES}/{_PROFILE_ID}", method="PATCH", json={**_PROFILE, "name": "lake-2"})
    outcome = runner.invoke(app, ["export", "profiles", "update", _PROFILE_ID, "--name", "lake-2",
                                  "--credential", _CREDENTIAL, "--bucket", "other"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _posted(httpx_mock, "PATCH") == {"name": "lake-2", "objectStorage": {
        "credentialId": _CREDENTIAL, "bucket": "other", "prefix": ""}}


def test_profiles_update_refuses_another_channel_s_flags_or_nothing(httpx_mock):
    httpx_mock.add_response(url=f"{_PROFILES}/{_PROFILE_ID}", json=_PROFILE, is_reusable=True)
    stray = runner.invoke(app, ["export", "profiles", "update", _PROFILE_ID, "--url", "https://h.example.com"])
    assert stray.exit_code == EXIT_USAGE
    empty = runner.invoke(app, ["export", "profiles", "update", _PROFILE_ID])
    assert empty.exit_code == EXIT_USAGE and "Nothing to change" in empty.output


def test_profiles_delete_with_yes(httpx_mock):
    httpx_mock.add_response(url=f"{_PROFILES}/{_PROFILE_ID}", method="DELETE", status_code=204)
    outcome = runner.invoke(app, ["export", "profiles", "delete", _PROFILE_ID, "--yes"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert "Deleted delivery profile" in outcome.output


# ---------------------------------------------------------------------------
# deliver / deliveries
# ---------------------------------------------------------------------------
def _attempt(**fields) -> dict:
    return {"channel": "object_storage", "runId": "r1", "jobId": _JOB_ID, "status": "delivered",
            "outcome": "delivered", "profileId": _PROFILE_ID, "profileName": "lake",
            "destination": "data-lake/exports", "attemptCount": 1, "errorCode": None, "errorMessage": None,
            **fields}


def test_deliver_a_finished_job_and_exit_1_when_it_failed(httpx_mock):
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}/deliveries", method="POST", json=_attempt())
    ok = runner.invoke(app, ["export", "deliver", _JOB_ID, "--profile", _PROFILE_ID])
    assert ok.exit_code == EXIT_SUCCESS, ok.output
    assert _posted(httpx_mock) == {"profileId": _PROFILE_ID}
    assert "delivered: object_storage delivery with 'lake' to data-lake/exports" in ok.output
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}/deliveries", method="POST",
                            json=_attempt(outcome="failed", status="failed", errorCode="x", errorMessage="no bucket"))
    failed = runner.invoke(app, ["export", "deliver", _JOB_ID, "--profile", _PROFILE_ID])
    assert failed.exit_code == EXIT_ERROR
    assert "x: no bucket" in failed.output


def test_deliveries_lists_a_job_s_deliveries_as_json(httpx_mock):
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}/deliveries", json={"deliveries": [_attempt()]})
    outcome = runner.invoke(app, ["--json", "export", "deliveries", _JOB_ID])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert json.loads(outcome.output)["deliveries"][0]["profileName"] == "lake"


# ---------------------------------------------------------------------------
# --deliver on an export
# ---------------------------------------------------------------------------
def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{}")
    return buffer.getvalue()


@pytest.mark.parametrize("code, exit_code", [("EXPORT_DELIVERED", EXIT_SUCCESS),
                                             ("EXPORT_DELIVERY_FAILED", EXIT_ERROR)])
def test_export_with_deliver_submits_the_profiles_and_reports_the_deliveries(httpx_mock, tmp_path, code, exit_code):
    httpx_mock.add_response(url=_PROFILES, json={"profiles": [_PROFILE]})
    httpx_mock.add_response(url=f"{_BASE}/v1/export/acme-corp/targets?artifact={_A}", json=_TARGETS)
    httpx_mock.add_response(url=_JOBS, method="POST", json={"job_id": _JOB_ID})
    result = {"artifact": "1 item", "download_path": _DOWNLOAD,
              "batch": {"item_count": 1, "failed_count": 0, "items": []}}
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}", json={"job_id": _JOB_ID, "state": "completed", "events": [],
                                                             "result": result})
    httpx_mock.add_response(url=f"{_BASE}{_DOWNLOAD}", content=_zip(), headers={"Content-Type": "application/zip"})
    httpx_mock.add_response(url=f"{_JOBS}/{_JOB_ID}", json={"job_id": _JOB_ID, "state": "completed", "result": result,
                                                             "events": [{"code": code, "message": "with 'lake'"}]})
    outcome = runner.invoke(app, ["export", "sample", "--items", _A, "--out", str(tmp_path / "out"),
                                  "--deliver", "lake"], terminal_width=200)
    assert outcome.exit_code == exit_code, outcome.output
    [submitted] = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    assert json.loads(submitted.content)["delivery_profiles"] == [_PROFILE_ID]
    assert ("Delivered: with 'lake'" if code == "EXPORT_DELIVERED" else "Delivery failed: with 'lake'") in outcome.output
