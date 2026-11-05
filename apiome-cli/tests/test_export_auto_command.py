"""``apiome export auto …`` — auto-export on version publish (MFX-39.4).

Against a mocked REST surface (``pytest-httpx``): ``add`` sends the project, preset, halt level and
pre-approval; ``update`` only what was given (and refuses nothing); ``list`` / ``runs`` render the table
with the loss and its reasons; ``remove`` confirms; ``release`` delivers a halted run and exits 1 when a
delivery failed.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000"
_SUBS = f"{_BASE}/v1/export/acme-corp/auto-exports"
_RUNS = f"{_BASE}/v1/export/acme-corp/auto-export-runs"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SUB = "88888888-8888-4888-8888-888888888888"
_RUN = "99999999-9999-4999-8999-999999999999"

_ROW = {"id": _SUB, "projectId": _PROJECT, "projectName": "Orders API", "presetId": "p", "presetName": "nightly",
        "haltAt": "critical", "approveLoss": False, "active": True}
_HALTED = {"id": _RUN, "projectId": _PROJECT, "projectName": "Orders API", "versionRecordId": "rev-1",
           "presetName": "nightly", "haltAt": "critical", "approveLoss": False, "status": "halted",
           "lossSeverity": "critical", "lossReasons": ["avro: a severe conversion (10% preserved)"], "deliveries": [],
           "createdAt": "2026-11-05T10:00:00Z"}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _sent(httpx_mock, method: str) -> dict:
    [request] = [r for r in httpx_mock.get_requests() if r.method == method]
    return json.loads(request.content)


def test_add_subscribes_a_preset_to_a_project(httpx_mock):
    httpx_mock.add_response(url=_SUBS, method="POST", json={**_ROW, "haltAt": "warn", "approveLoss": True},
                            status_code=201)
    outcome = runner.invoke(app, ["export", "auto", "add", _PROJECT, "--preset", "nightly", "--halt-at", "WARN",
                                  "--approve-loss"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _sent(httpx_mock, "POST") == {"projectId": _PROJECT, "preset": "nightly", "haltAt": "warn",
                                         "approveLoss": True, "active": True}
    assert "'nightly' runs on every publish of 'Orders API', halting at warn, loss pre-approved" in outcome.output


def test_add_refuses_an_unknown_halt_level():
    outcome = runner.invoke(app, ["export", "auto", "add", _PROJECT, "--preset", "nightly", "--halt-at", "info"])
    assert outcome.exit_code == EXIT_USAGE


def test_update_sends_only_what_changed(httpx_mock):
    httpx_mock.add_response(url=f"{_SUBS}/{_SUB}", method="PATCH", json={**_ROW, "active": False})
    outcome = runner.invoke(app, ["export", "auto", "update", _SUB, "--off", "--no-approve-loss"])
    assert outcome.exit_code == EXIT_SUCCESS, outcome.output
    assert _sent(httpx_mock, "PATCH") == {"approveLoss": False, "active": False}
    assert "(off)" in outcome.output
    assert runner.invoke(app, ["export", "auto", "update", _SUB]).exit_code == EXIT_USAGE


def test_list_and_runs(httpx_mock):
    httpx_mock.add_response(url=f"{_SUBS}?preset=nightly", json={"subscriptions": [_ROW]})
    httpx_mock.add_response(url=f"{_RUNS}?limit=5", json={"runs": [_HALTED]})
    listed = runner.invoke(app, ["export", "auto", "list", "--preset", "nightly"])
    assert listed.exit_code == EXIT_SUCCESS and "Orders API" in listed.output and "critical" in listed.output
    runs = runner.invoke(app, ["export", "auto", "runs", "--limit", "5"])
    assert runs.exit_code == EXIT_SUCCESS, runs.output
    assert "halted" in runs.output and "severe conversion" in runs.output


def test_remove_with_yes(httpx_mock):
    httpx_mock.add_response(url=f"{_SUBS}/{_SUB}", method="DELETE", status_code=204)
    outcome = runner.invoke(app, ["export", "auto", "remove", _SUB, "--yes"])
    assert outcome.exit_code == EXIT_SUCCESS and "Removed auto-export subscription" in outcome.output


@pytest.mark.parametrize("status, exit_code", [("delivered", EXIT_SUCCESS), ("delivery_failed", EXIT_ERROR)])
def test_release_delivers_a_halted_run(httpx_mock, status, exit_code):
    outcome_row = {"profileName": "lake", "outcome": "failed" if status == "delivery_failed" else "delivered",
                   "errorCode": "gone" if status == "delivery_failed" else None}
    httpx_mock.add_response(url=f"{_RUNS}/{_RUN}/release", method="POST",
                            json={**_HALTED, "status": status, "deliveries": [outcome_row]})
    outcome = runner.invoke(app, ["export", "auto", "release", _RUN])
    assert outcome.exit_code == exit_code, outcome.output
    assert f"Released auto-export {_RUN}: {status}" in outcome.output
