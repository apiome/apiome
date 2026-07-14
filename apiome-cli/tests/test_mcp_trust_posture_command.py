"""Tests for the ``mcp trust-posture`` gate and ``mcp source`` commands (CLX-3.2, #4856)."""

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
_SOURCE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

_BASE = "http://localhost:8000/v1/mcp"
_POSTURE_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/versions/{_VERSION_ID}/trust-posture"
_SOURCES_URL = f"{_BASE}/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/sources"
_RULES_URL = f"{_BASE}/trust-posture/rules"

_DEFAULT_QUERY = "profile=mcp-trust-posture&failOn=error&format=json"

_REPORT_SIGNALS = {
    "success": True,
    "endpointId": _ENDPOINT_ID,
    "versionId": _VERSION_ID,
    "versionSeq": 1,
    "profile": "mcp-trust-posture",
    "owaspRevision": "2025",
    "score": 40,
    "grade": "F",
    "findings": [
        {
            "id": "mcp-posture-1",
            "path": "tools.read_file",
            "rule": "metadata.hidden-instruction",
            "severity": "error",
            "message": "hidden instruction",
            "origin": "metadata",
            "originLabel": "Advertised metadata",
            "owaspIds": ["MCP01", "MCP02"],
            "exploitability": "static_signal",
            "exploitabilityLabel": "Signal — not proven exploitable",
            "confidence": "high",
            "excerpt": None,
            "remediation": "Rewrite the description.",
        }
    ],
    "severityCounts": {"error": 1, "warning": 0, "info": 0},
    "originCounts": {"metadata": 1},
    "owaspCounts": {"MCP01": 1, "MCP02": 1},
    "owaspCoverage": {"covered": ["MCP01"], "uncovered": []},
    "reportFingerprint": "fp",
    "evaluatedRules": ["metadata.hidden-instruction"],
    "skippedRules": [],
    "skipReasons": {},
    "provenCount": 0,
    "source": None,
    "gate": {"passed": False, "failOn": "error", "minScore": None, "requireFullCoverage": False, "reasons": ["1 error"]},
}

_REPORT_CLEAN = {
    **_REPORT_SIGNALS,
    "score": 100,
    "grade": "A",
    "findings": [],
    "severityCounts": {"error": 0, "warning": 0, "info": 0},
    "gate": {"passed": True, "failOn": "error", "minScore": None, "requireFullCoverage": False, "reasons": []},
}

_RULES = {
    "success": True,
    "owaspRevision": "2025",
    "profiles": [
        {
            "profileId": "mcp-trust-posture",
            "label": "MCP trust posture",
            "origins": ["metadata", "source", "dependency", "protocol"],
            "description": "Full posture.",
        }
    ],
    "rules": [
        {
            "ruleId": "metadata.hidden-instruction",
            "origin": "metadata",
            "originLabel": "Advertised metadata",
            "severity": "error",
            "owaspIds": ["MCP01", "MCP02"],
            "rationale": "A directive the operator never wrote.",
            "reference": "https://owasp.org/www-project-mcp-top-10/",
            "requires": "surface",
        }
    ],
    "owaspRisks": [
        {"riskId": "MCP01", "title": "Prompt injection", "description": "x", "reference": "https://owasp.org/"}
    ],
}

_SOURCE = {
    "id": _SOURCE_ID,
    "sourceKind": "git",
    "locator": "https://github.com/acme/srv",
    "purl": None,
    "revision": "main",
    "digest": None,
    "digestAlgorithm": None,
    "provenance": "operator_declared",
    "verificationState": "unverified",
    "retiredAt": None,
    "createdAt": "2026-07-14T12:00:00Z",
}


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


# --- validation ---


def test_trust_posture_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "trust-posture", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_trust_posture_rejects_invalid_profile(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "trust-posture", _ENDPOINT_ID, "--version", _VERSION_ID, "--profile", "nope"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--profile" in strip_ansi(result.stderr)


# --- scan output & gate ---


def test_trust_posture_human_output_labels_signals(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=f"{_POSTURE_URL}?{_DEFAULT_QUERY}", method="GET", json=_REPORT_SIGNALS)
    result = runner.invoke(app, ["mcp", "trust-posture", _ENDPOINT_ID, "--version", _VERSION_ID])
    assert result.exit_code == EXIT_ERROR  # gate failed
    output = strip_ansi(result.stdout)
    assert "MCP trust posture profile: mcp-trust-posture" in output
    assert "Proven exploitable: 0" in output
    assert "SIGNAL" in output
    assert "metadata.hidden-instruction" in output
    assert "Gate: FAILED" in output


def test_trust_posture_clean_passes(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=f"{_POSTURE_URL}?{_DEFAULT_QUERY}", method="GET", json=_REPORT_CLEAN)
    result = runner.invoke(app, ["mcp", "trust-posture", _ENDPOINT_ID, "--version", _VERSION_ID])
    assert result.exit_code == EXIT_SUCCESS
    assert "Gate: PASSED" in strip_ansi(result.stdout)


def test_trust_posture_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=f"{_POSTURE_URL}?{_DEFAULT_QUERY}", method="GET", json=_REPORT_SIGNALS)
    result = runner.invoke(
        app, ["mcp", "trust-posture", _ENDPOINT_ID, "--version", _VERSION_ID, "--output", "json"]
    )
    assert result.exit_code == EXIT_ERROR
    payload = json.loads(result.stdout)
    assert payload["provenCount"] == 0
    assert payload["owaspRevision"] == "2025"


# --- rules ---


def test_trust_posture_rules_json(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_RULES)
    result = runner.invoke(app, ["mcp", "trust-posture-rules", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["rules"][0]["owaspIds"] == ["MCP01", "MCP02"]


# --- source subcommands ---


def test_source_link(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="POST", json={"success": True, "source": _SOURCE}, status_code=201)
    result = runner.invoke(
        app,
        [
            "mcp",
            "source",
            "link",
            _ENDPOINT_ID,
            "--kind",
            "git",
            "--reference",
            "https://github.com/acme/srv",
            "--revision",
            "main",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "unverified" in strip_ansi(result.stdout)


def test_source_link_rejects_bad_kind(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "source", "link", _ENDPOINT_ID, "--kind", "svn", "--reference", "x"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--kind" in strip_ansi(result.stderr)


def test_source_list(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_SOURCES_URL, method="GET", json={"success": True, "endpointId": _ENDPOINT_ID, "sources": [_SOURCE]}
    )
    result = runner.invoke(app, ["mcp", "source", "list", _ENDPOINT_ID])
    assert result.exit_code == EXIT_SUCCESS
    assert _SOURCE_ID in strip_ansi(result.stdout)
