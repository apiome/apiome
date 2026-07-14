"""Tests for the ``compat`` oasdiff evidence command (CLX-2.3 / #4853)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_BASE_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_PROJECT = {
    "id": _PROJECT_ID,
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "name": "Payments API",
    "slug": "payments-api",
    "source": "manual",
    "enabled": True,
}
_VERSION = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "1.0.0",
    "source": "import",
    "enabled": True,
}
_BASE_VERSION = {
    "id": _BASE_VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "0.9.0",
    "slug": "0.9.0",
    "source": "import",
    "enabled": True,
}

_EVIDENCE_SAFE = {
    "schemaVersion": 1,
    "scannerId": "oasdiff.breaking",
    "baseRevisionId": _BASE_VERSION_ID,
    "headRevisionId": _VERSION_ID,
    "outcome": "passed",
    "overall": "safe",
    "counts": {"breaking": 0, "dangerous": 0, "informational": 0, "total": 0},
    "findings": [],
    "coverage": {"state": "full"},
    "changelogMarkdown": "# API Changelog\n\nNo changes detected\n",
    "evidenceRunId": "run-1",
}

_EVIDENCE_BREAKING = {
    **_EVIDENCE_SAFE,
    "overall": "breaking",
    "outcome": "findings",
    "counts": {"breaking": 1, "dangerous": 0, "informational": 0, "total": 1},
    "findings": [
        {
            "ruleId": "api-path-removed-without-deprecation",
            "message": "api path removed without deprecation",
            "severity": "error",
            "changeClass": "breaking",
            "location": {"path": "openapi.yaml", "startLine": 7},
        }
    ],
}

_POST_URL = (
    f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/compatibility/evidence"
)
_GET_URL = (
    f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/"
    f"{_VERSION_ID}/compatibility/evidence"
)


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/0.9.0",
        json=_BASE_VERSION,
    )


def test_compat_human_safe(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_POST_URL, method="POST", json=_EVIDENCE_SAFE)
    result = runner.invoke(
        app,
        [
            "compat",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--base-version",
            "0.9.0",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "overall: safe" in result.stdout


def test_compat_breaking_exits_nonzero(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_POST_URL, method="POST", json=_EVIDENCE_BREAKING)
    result = runner.invoke(
        app,
        [
            "compat",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--base-version",
            "0.9.0",
        ],
    )
    assert result.exit_code == EXIT_ERROR
    assert "breaking" in result.stdout


def test_compat_json_mode(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_POST_URL, method="POST", json=_EVIDENCE_SAFE)
    result = runner.invoke(
        app,
        [
            "--json",
            "compat",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--base-version",
            "0.9.0",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["overall"] == "safe"
    assert payload["scannerId"] == "oasdiff.breaking"


def test_compat_sarif_format_fetches_gate_artifact(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_POST_URL, method="POST", json=_EVIDENCE_SAFE)
    httpx_mock.add_response(
        url=f"{_GET_URL}?format=sarif",
        json={"version": "2.1.0", "runs": []},
    )
    result = runner.invoke(
        app,
        [
            "compat",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--base-version",
            "0.9.0",
            "--format",
            "sarif",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "2.1.0" in result.stdout


def test_compat_fail_on_info_exits_on_any_finding(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    info_only = {
        **_EVIDENCE_SAFE,
        "overall": "safe",
        "counts": {"breaking": 0, "dangerous": 0, "informational": 1, "total": 1},
        "findings": [
            {
                "ruleId": "response-property-became-required",
                "changeClass": "informational",
                "severity": "info",
                "message": "name became required",
            }
        ],
    }
    httpx_mock.add_response(url=_POST_URL, method="POST", json=info_only)
    result = runner.invoke(
        app,
        [
            "compat",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--base-version",
            "0.9.0",
            "--fail-on",
            "info",
        ],
    )
    assert result.exit_code == EXIT_ERROR
