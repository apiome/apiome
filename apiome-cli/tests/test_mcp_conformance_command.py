"""Tests for the ``mcp conformance`` gate command (#4855)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_ENDPOINTS_URL = f"http://localhost:8000/v1/mcp/{_TENANT_SLUG}/endpoints"
_ENDPOINT_URL = f"{_ENDPOINTS_URL}/{_ENDPOINT_ID}"
_CONFORMANCE_URL = f"{_ENDPOINT_URL}/versions/{_VERSION_ID}/conformance"
_RULES_URL = "http://localhost:8000/v1/mcp/conformance/rules"

_DEFAULT_QUERY = "profile=mcp-conformance&failOn=error&format=json"

# Mirrors the camelCase conformance report wire shape.
_REPORT_PASSED = {
    "success": True,
    "endpointId": _ENDPOINT_ID,
    "versionId": _VERSION_ID,
    "versionSeq": 1,
    "versionTag": "2026-07-14",
    "profile": "mcp-conformance",
    "specVersion": "2025-06-18",
    "score": 92,
    "grade": "A",
    "findings": [
        {
            "id": "mcp-conf-1",
            "path": "tools.search",
            "category": "readiness",
            "rule": "readiness.tool-unbounded-list",
            "severity": "info",
            "message": "Tool returns an unbounded list.",
        }
    ],
    "ruleHits": {"readiness.tool-unbounded-list": 1},
    "severityCounts": {"error": 0, "warning": 0, "info": 1},
    "reportFingerprint": "abc123",
    "evaluatedRules": ["readiness.tool-unbounded-list"],
    "skippedRules": [],
    "transcriptCaptured": False,
    "gate": {"passed": True, "failOn": "error", "minScore": None, "reasons": []},
}

_REPORT_FAILED = {
    **_REPORT_PASSED,
    "score": 61,
    "grade": "D",
    "findings": [
        {
            "id": "mcp-conf-2",
            "path": "tools.delete_all",
            "category": "protocol",
            "rule": "protocol.tool-missing-input-schema",
            "severity": "error",
            "message": "Tool has no inputSchema.",
        }
    ],
    "severityCounts": {"error": 1, "warning": 0, "info": 0},
    "gate": {
        "passed": False,
        "failOn": "error",
        "minScore": None,
        "reasons": ["1 error-severity finding(s) at or above fail-on=error"],
    },
}

_REPORT_SKIPPED = {
    **_REPORT_PASSED,
    "evaluatedRules": ["readiness.tool-unbounded-list"],
    "skippedRules": ["protocol.initialize-handshake", "protocol.tools-list-pagination"],
    "transcriptCaptured": False,
}

_RULES = {
    "success": True,
    "specVersion": "2025-06-18",
    "profiles": [
        {
            "profileId": "mcp-conformance",
            "label": "MCP conformance (all rules)",
            "categories": ["protocol", "readiness"],
            "description": "Protocol conformance plus agent readiness.",
        }
    ],
    "rules": [
        {
            "ruleId": "protocol.tool-missing-input-schema",
            "category": "protocol",
            "severity": "error",
            "specVersion": "2025-06-18",
            "specReference": "https://modelcontextprotocol.io/specification/2025-06-18/server/tools",
            "rationale": "Tools must declare an inputSchema.",
            "requiresTranscript": False,
        },
        {
            "ruleId": "protocol.initialize-handshake",
            "category": "protocol",
            "severity": "error",
            "specVersion": "2025-06-18",
            "specReference": "https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle",
            "rationale": "Servers must complete the initialize handshake.",
            "requiresTranscript": True,
        },
    ],
}


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


def _endpoint_with_current(version_id: str) -> dict[str, object]:
    return {
        "id": _ENDPOINT_ID,
        "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "name": "Weather MCP",
        "slug": "weather-mcp",
        "endpoint_url": "https://mcp.example.com/sse",
        "transport": "streamable_http",
        "visibility": "private",
        "published": False,
        "enabled": True,
        "consecutive_failures": 0,
        "quarantined": False,
        "current_version_id": version_id,
    }


def test_conformance_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "conformance", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_conformance_rejects_invalid_profile(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID, "--profile", "nope"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--profile" in strip_ansi(result.stderr)


def test_conformance_rejects_invalid_fail_on(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID, "--fail-on", "loud"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--fail-on" in strip_ansi(result.stderr)


def test_conformance_rejects_invalid_format(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID, "--format", "csv"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--format" in strip_ansi(result.stderr)


def test_conformance_human_output_gate_passed(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_PASSED,
    )
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "MCP conformance profile: mcp-conformance  (spec 2025-06-18)" in output
    assert "Score: 92/100  (grade A)" in output
    assert "Gate: PASSED" in output
    assert "readiness.tool-unbounded-list" in output


def test_conformance_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_PASSED,
    )
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID, "--output", "json"],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["score"] == 92
    assert payload["specVersion"] == "2025-06-18"
    assert payload["gate"]["passed"] is True


def test_conformance_gate_failure_exits_error(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_FAILED,
    )
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID],
    )
    assert result.exit_code == EXIT_ERROR
    output = strip_ansi(result.stdout)
    assert "Gate: FAILED" in output
    assert "protocol.tool-missing-input-schema" in output


def test_conformance_passes_profile_fail_on_and_min_score(
    httpx_mock: object, mcp_env: None
) -> None:
    httpx_mock.add_response(
        url=(
            f"{_CONFORMANCE_URL}?profile=mcp-agent-readiness&failOn=warning"
            "&format=json&minScore=80"
        ),
        method="GET",
        json=_REPORT_PASSED,
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "conformance",
            _ENDPOINT_ID,
            "--version",
            _VERSION_ID,
            "--profile",
            "mcp-agent-readiness",
            "--fail-on",
            "warning",
            "--min-score",
            "80",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS


def test_conformance_resolves_current_version(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _endpoint_with_current(_VERSION_ID)},
    )
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_PASSED,
    )
    result = runner.invoke(app, ["mcp", "conformance", _ENDPOINT_ID])
    assert result.exit_code == EXIT_SUCCESS


def test_conformance_skipped_rules_note(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_SKIPPED,
    )
    result = runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "NOT EVALUATED" in output
    assert "no protocol transcript was captured" in output
    assert "protocol.initialize-handshake" in output


def _invoke_format(fmt: str) -> object:
    return runner.invoke(
        app,
        ["mcp", "conformance", _ENDPOINT_ID, "--version", _VERSION_ID, "--format", fmt],
    )


def test_conformance_sarif_raw_passthrough_gate_passed(
    httpx_mock: object, mcp_env: None
) -> None:
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_PASSED,
    )
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?profile=mcp-conformance&failOn=error&format=sarif",
        method="GET",
        json={"version": "2.1.0", "runs": []},
    )
    result = _invoke_format("sarif")
    assert result.exit_code == EXIT_SUCCESS
    assert "2.1.0" in result.stdout


def test_conformance_sarif_failing_gate_exits_error(httpx_mock: object, mcp_env: None) -> None:
    """A SARIF run must still fail CI: the gate is read from the JSON report."""
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_FAILED,
    )
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?profile=mcp-conformance&failOn=error&format=sarif",
        method="GET",
        json={"version": "2.1.0", "runs": [{"results": [{"ruleId": "x"}]}]},
    )
    result = _invoke_format("sarif")
    assert result.exit_code == EXIT_ERROR
    # The raw artifact is still emitted so CI can upload it alongside the failure.
    assert "2.1.0" in result.stdout


def test_conformance_junit_raw_passthrough_gate_passed(
    httpx_mock: object, mcp_env: None
) -> None:
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_PASSED,
    )
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?profile=mcp-conformance&failOn=error&format=junit",
        method="GET",
        text='<?xml version="1.0"?><testsuites name="mcp-conformance"/>',
    )
    result = _invoke_format("junit")
    assert result.exit_code == EXIT_SUCCESS
    assert "<testsuites" in result.stdout


def test_conformance_junit_failing_gate_exits_error(httpx_mock: object, mcp_env: None) -> None:
    """A JUnit run must still fail CI: the gate is read from the JSON report."""
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?{_DEFAULT_QUERY}",
        method="GET",
        json=_REPORT_FAILED,
    )
    httpx_mock.add_response(
        url=f"{_CONFORMANCE_URL}?profile=mcp-conformance&failOn=error&format=junit",
        method="GET",
        text='<?xml version="1.0"?><testsuites name="mcp-conformance" failures="1"/>',
    )
    result = _invoke_format("junit")
    assert result.exit_code == EXIT_ERROR
    assert "<testsuites" in result.stdout


def test_conformance_rules_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_RULES)
    result = runner.invoke(app, ["mcp", "conformance-rules"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "MCP conformance rules (spec 2025-06-18)" in output
    assert "protocol.tool-missing-input-schema" in output
    assert "modelcontextprotocol.io" in output


def test_conformance_rules_profile_filter_json(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_RULES_URL}?profile=mcp-protocol",
        method="GET",
        json=_RULES,
    )
    result = runner.invoke(
        app,
        ["mcp", "conformance-rules", "--profile", "mcp-protocol", "--output", "json"],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["specVersion"] == "2025-06-18"
    assert payload["rules"][0]["ruleId"] == "protocol.tool-missing-input-schema"


def test_conformance_rules_rejects_invalid_profile(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "conformance-rules", "--profile", "bogus"])
    assert result.exit_code == EXIT_USAGE
    assert "--profile" in strip_ansi(result.stderr)
