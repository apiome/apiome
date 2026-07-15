"""Tests for the ``mcp trust-baseline* / trust-drift / shadowing`` commands (CLX-3.4, #4858)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

_BASE = "http://localhost:8000/v1/mcp"
_BASELINE_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/trust-baseline"
_DRIFT_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/trust-drift"
_SHADOW_URL = f"{_BASE}/{_TENANT_SLUG}/data-quality/shadowing"

_DRIFT = {
    "drift": {
        "alert_severity": "security_regression",
        "gate": {"status": "blocked", "enforced": False, "reason": "risk delta"},
        "category_counts": {
            "security_regression": 1,
            "coverage_loss": 0,
            "quality_regression": 0,
            "normal_change": 0,
        },
        "changes": [
            {
                "category": "security_regression",
                "component": "capability",
                "path": "tool:search",
                "summary": "tool 'search' no longer declares readOnlyHint",
            }
        ],
    },
    "notified": [],
}


@pytest.fixture()
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


def test_trust_baseline_approve_requires_rationale(mcp_env: None) -> None:
    # --rationale is a required option; omitting it is a local usage error, no network call.
    result = runner.invoke(app, ["mcp", "trust-baseline-approve", _ENDPOINT_ID])
    assert result.exit_code != EXIT_SUCCESS


def test_trust_baseline_approve_rejects_unknown_gate(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "trust-baseline-approve", _ENDPOINT_ID, "--rationale", "ok", "--gate", "nope"],
    )
    assert result.exit_code != EXIT_SUCCESS


def test_trust_baseline_approve_posts_rationale(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_BASELINE_URL,
        method="POST",
        json={"baseline": {"id": "b1"}},
        status_code=201,
    )
    result = runner.invoke(
        app, ["mcp", "trust-baseline-approve", _ENDPOINT_ID, "--rationale", "Approved for prod."]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "b1" in strip_ansi(result.stdout)
    request = httpx_mock.get_requests()[0]
    assert json.loads(request.content)["rationale"] == "Approved for prod."


def test_trust_drift_human_shows_gate_and_changes(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_DRIFT_URL, method="GET", json=_DRIFT)
    result = runner.invoke(app, ["mcp", "trust-drift", _ENDPOINT_ID])
    assert result.exit_code == EXIT_SUCCESS
    out = strip_ansi(result.stdout)
    assert "security_regression" in out
    assert "blocked" in out
    assert "tool:search" in out


def test_trust_drift_notify_query(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=f"{_DRIFT_URL}?notify=true", method="GET", json=_DRIFT)
    result = runner.invoke(app, ["mcp", "trust-drift", _ENDPOINT_ID, "--notify", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["drift"]["alert_severity"] == "security_regression"


def test_shadowing_report_json(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_SHADOW_URL,
        method="GET",
        json={
            "advisory": True,
            "group_count": 1,
            "same_host_count": 0,
            "cross_host_count": 1,
            "groups": [
                {"item_type": "tool", "name": "search", "host_scope": "cross_host", "endpoint_count": 2}
            ],
        },
    )
    result = runner.invoke(app, ["mcp", "shadowing", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["groups"][0]["name"] == "search"
