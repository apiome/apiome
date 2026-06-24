"""Tests for the ``lint`` quality-scoring command."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from objectified_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from objectified_cli.main import app

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

_REPORT = {
    "projectId": _PROJECT_ID,
    "versionRecordId": _VERSION_ID,
    "versionId": "1.0.0",
    "score": 72,
    "grade": "C",
    "findings": [
        {
            "id": "lint-0123456789abcdef",
            "path": "components.schemas.payment",
            "category": "naming",
            "rule": "naming.schema-pascal-case",
            "severity": "warning",
            "message": "Schema 'payment' is not PascalCase.",
        }
    ],
    "ruleHits": {"naming.schema-pascal-case": 1},
    "severityCounts": {"error": 0, "warning": 1, "info": 0},
    "reportFingerprint": "deadbeef",
    "baseRevisionId": None,
    "compatibilityOverall": None,
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key."""
    monkeypatch.setenv("OBJECTIFIED_API_KEY", "test-key")
    monkeypatch.setenv("OBJECTIFIED_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("OBJECTIFIED_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION,
    )


def test_lint_human_output(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint",
        json=_REPORT,
    )
    result = runner.invoke(
        app, ["lint", "--project", "payments-api", "--version", "1.0.0"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "Quality score: 72/100" in result.stdout
    assert "grade C" in result.stdout
    assert "naming.schema-pascal-case" in result.stdout


def test_lint_json_output(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint",
        json=_REPORT,
    )
    result = runner.invoke(
        app, ["--json", "lint", "--project", "payments-api", "--version", "1.0.0"]
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["score"] == 72
    assert payload["grade"] == "C"


def test_lint_min_grade_gate_fails(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint",
        json=_REPORT,
    )
    result = runner.invoke(
        app,
        ["lint", "--project", "payments-api", "--version", "1.0.0", "--min-grade", "B"],
    )
    assert result.exit_code == EXIT_ERROR


def test_lint_min_grade_gate_passes(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint",
        json=_REPORT,
    )
    result = runner.invoke(
        app,
        ["lint", "--project", "payments-api", "--version", "1.0.0", "--min-grade", "D"],
    )
    assert result.exit_code == EXIT_SUCCESS


def test_lint_invalid_min_grade_is_usage_error() -> None:
    result = runner.invoke(
        app,
        ["lint", "--project", "payments-api", "--version", "1.0.0", "--min-grade", "Z"],
    )
    assert result.exit_code == EXIT_USAGE


def test_lint_with_base_version(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/0.9.0",
        json={**_VERSION, "id": _BASE_VERSION_ID, "version": "0.9.0", "slug": "0.9.0"},
    )
    report = {**_REPORT, "baseRevisionId": _BASE_VERSION_ID, "compatibilityOverall": "breaking"}
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}"
            f"/lint?baseRevisionId={_BASE_VERSION_ID}"
        ),
        json=report,
    )
    result = runner.invoke(
        app,
        [
            "lint",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--base-version",
            "0.9.0",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "breaking" in result.stdout
