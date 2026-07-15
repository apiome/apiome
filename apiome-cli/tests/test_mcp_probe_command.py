"""Tests for the ``mcp probe*`` commands (CLX-3.3, #4857)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_BASE = "http://localhost:8000/v1/mcp"
_CATALOG_URL = f"{_BASE}/probes/catalog"
_PROBE_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/versions/{_VERSION_ID}/probe"
_TARGETS_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/probe-targets"
_RUNS_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/probe-runs"

_CATALOG = {
    "profiles": [
        {"profile_id": "passive", "label": "Passive", "sends_requests": False},
        {"profile_id": "safe-active", "label": "Safe active", "sends_requests": True},
        {"profile_id": "payload-fuzzing", "label": "Payload fuzzing", "sends_requests": True},
    ],
    "classifications": [
        {"value": "suspected", "label": "Suspected"},
        {"value": "observed", "label": "Observed"},
        {"value": "exploited-in-test", "label": "Exploited in test"},
    ],
    "probes": [
        {
            "probe_id": "passive.protocol.id-not-echoed",
            "profile": "passive",
            "emits": "observed",
            "owasp_ids": ["MCP07"],
            "title": "Response did not echo id",
        }
    ],
}

_PASSIVE_REPORT = {
    "profile": "passive",
    "target_endpoint_id": _ENDPOINT_ID,
    "findings": [
        {
            "id": "mcp-probe-1",
            "probe_id": "passive.protocol.id-not-echoed",
            "path": "protocol.response-correlation",
            "classification": "observed",
            "message": "did not echo id",
            "observed": "1 exchange did not echo the id",
            "owasp_ids": ["MCP07"],
        }
    ],
    "classification_counts": {"observed": 1},
    "severity_counts": {"warning": 1},
    "exploited_count": 0,
    "requests_sent": 0,
    "skipped_probes": {},
    "evidence": [],
    "report_fingerprint": "fp",
}


@pytest.fixture()
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


def test_probe_catalog_json(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_CATALOG_URL, method="GET", json=_CATALOG)
    result = runner.invoke(app, ["mcp", "probe-catalog", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    body = json.loads(result.stdout)
    assert {p["profile_id"] for p in body["profiles"]} == {
        "passive",
        "safe-active",
        "payload-fuzzing",
    }


def test_probe_passive_run_human(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_PROBE_URL, method="POST", json=_PASSIVE_REPORT)
    result = runner.invoke(
        app, ["mcp", "probe", _ENDPOINT_ID, "--version", _VERSION_ID, "--profile", "passive"]
    )
    assert result.exit_code == EXIT_SUCCESS
    out = strip_ansi(result.stdout)
    assert "passive" in out
    assert "observed" in out


def test_probe_rejects_unknown_profile(mcp_env: None) -> None:
    result = runner.invoke(
        app, ["mcp", "probe", _ENDPOINT_ID, "--version", _VERSION_ID, "--profile", "nonsense"]
    )
    assert result.exit_code != EXIT_SUCCESS


def test_probe_target_add_requires_ownership_flag(mcp_env: None) -> None:
    # Without the ownership flag the command refuses locally, before any network call.
    result = runner.invoke(app, ["mcp", "probe-target-add", _ENDPOINT_ID])
    assert result.exit_code == EXIT_ERROR


def test_probe_target_add_with_ownership(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TARGETS_URL,
        method="POST",
        json={"target": {"id": "t1", "transport": "http", "ownershipDeclared": True}},
        status_code=201,
    )
    result = runner.invoke(
        app, ["mcp", "probe-target-add", _ENDPOINT_ID, "--i-own-or-am-authorized"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "Enrolled" in strip_ansi(result.stdout)


def test_probe_runs_audit_json(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_RUNS_URL}?limit=50",
        method="GET",
        json={"runs": [{"id": "r1", "profile": "safe-active", "status": "completed"}]},
    )
    result = runner.invoke(app, ["mcp", "probe-runs", _ENDPOINT_ID, "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["runs"][0]["status"] == "completed"
