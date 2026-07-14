"""Tests for the ``lint`` quality-scoring command."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
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

_POLICY_PASSED = {
    "policyVersion": {"id": "pv1", "versionNumber": 1},
    "evaluation": {
        "subjectType": "catalog_revision",
        "subjectId": _VERSION_ID,
        "policyVersionId": "pv1",
        "policyContentFingerprint": "abc",
        "passed": True,
        "gateResults": {
            "unwaived_errors": {"passed": True},
            "required_coverage": {"passed": True},
            "axis_gates": {"passed": True},
        },
    },
    "findings": [],
}

_POLICY_FAILED = {
    "policyVersion": {"id": "pv1", "versionNumber": 1},
    "evaluation": {
        "subjectType": "catalog_revision",
        "subjectId": _VERSION_ID,
        "policyVersionId": "pv1",
        "policyContentFingerprint": "abc",
        "passed": False,
        "gateResults": {
            "unwaived_errors": {"passed": False},
            "required_coverage": {"passed": True},
            "axis_gates": {"passed": True},
        },
    },
    "findings": [],
}

_LINT_URL = f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint"
_POLICY_URL = (
    f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint/policy"
)


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key."""
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


def test_lint_surfaces_stale_captured_score(httpx_mock: object) -> None:
    """A stale persisted (MFI-4.4) score prints the stored grade alongside the live recompute."""
    _mock_scope(httpx_mock)
    report = {
        **_REPORT,
        "capturedScore": 55,
        "capturedGrade": "D",
        "capturedReportFingerprint": "oldfingerprint",
        "scoreIsStale": True,
    }
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint",
        json=report,
    )
    result = runner.invoke(app, ["lint", "--project", "payments-api", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Stored score: 55/100" in result.stdout
    assert "grade D" in result.stdout
    assert "out of date" in result.stdout


def test_lint_omits_stored_score_line_when_current(httpx_mock: object) -> None:
    """When the persisted score is current (not stale), no stored-score line is printed."""
    _mock_scope(httpx_mock)
    report = {
        **_REPORT,
        "capturedScore": 72,
        "capturedGrade": "C",
        "capturedReportFingerprint": "deadbeef",
        "scoreIsStale": False,
    }
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint",
        json=report,
    )
    result = runner.invoke(app, ["lint", "--project", "payments-api", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Stored score" not in result.stdout


def test_lint_fail_on_policy_exits_when_failed(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_LINT_URL, json=_REPORT)
    httpx_mock.add_response(url=_POLICY_URL, json=_POLICY_FAILED)
    result = runner.invoke(
        app,
        ["lint", "--project", "payments-api", "--version", "1.0.0", "--fail-on-policy"],
    )
    assert result.exit_code == EXIT_ERROR
    assert "Policy evaluation: passed no" in result.stdout
    assert "Failed gates: unwaived_errors" in result.stdout


def test_lint_fail_on_policy_passes_when_ok(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_LINT_URL, json=_REPORT)
    httpx_mock.add_response(url=_POLICY_URL, json=_POLICY_PASSED)
    result = runner.invoke(
        app,
        ["lint", "--project", "payments-api", "--version", "1.0.0", "--fail-on-policy"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "Policy evaluation: passed yes" in result.stdout
    assert "Failed gates:" not in result.stdout


def test_lint_fail_on_policy_json_output(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_LINT_URL, json=_REPORT)
    httpx_mock.add_response(url=_POLICY_URL, json=_POLICY_PASSED)
    result = runner.invoke(
        app,
        [
            "--json",
            "lint",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--fail-on-policy",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["lint"]["score"] == 72
    assert payload["policy"]["evaluation"]["passed"] is True


def test_lint_fail_on_policy_with_base_version(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/0.9.0",
        json={**_VERSION, "id": _BASE_VERSION_ID, "version": "0.9.0", "slug": "0.9.0"},
    )
    httpx_mock.add_response(
        url=f"{_LINT_URL}?baseRevisionId={_BASE_VERSION_ID}",
        json=_REPORT,
    )
    httpx_mock.add_response(
        url=f"{_POLICY_URL}?baseRevisionId={_BASE_VERSION_ID}",
        json=_POLICY_PASSED,
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
            "--fail-on-policy",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
