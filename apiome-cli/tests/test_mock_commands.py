"""Tests for the ``mock`` hosted-mock management commands (SIM-2.4, #4445)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.client.mock_settings import version_usage_request_count
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

_PROJECT = {
    "id": _PROJECT_ID,
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "name": "Payments API",
    "slug": "payments-api",
    "source": "manual",
    "enabled": True,
}

_VERSION_LOOKUP = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "1.0.0",
    "source": "import",
    "enabled": True,
}

# Short base URL so Rich table cells do not wrap in the 80-column test console.
_MOCK_BASE_URL = "http://mock.local/m/abc123"

_RECORD_ENABLED = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version_id": "1.0.0",
    "published": True,
    "mockEnabled": True,
    "mockBaseUrl": _MOCK_BASE_URL,
}

_RECORD_DISABLED = {
    **_RECORD_ENABLED,
    "mockEnabled": False,
    "mockBaseUrl": None,
}

_USAGE = {
    "monthlyRequestCount": 1234,
    "monthlyQuota": 100000,
    "mockRps": 5.0,
    "dailyRollups": [
        {
            "usageDate": "2026-07-08",
            "projectSlug": "payments-api",
            "versionLabel": "1.0.0",
            "requestCount": 100,
        },
        {
            "usageDate": "2026-07-07",
            "projectSlug": "payments-api",
            "versionLabel": "1.0.0",
            "requestCount": 34,
        },
    ],
}

_VERSION_RECORD_URL = f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}"
_MOCK_TOGGLE_URL = f"{_VERSION_RECORD_URL}/mock"
_USAGE_URL = (
    "http://localhost:8000/v1/mocks/acme-corp/usage"
    "?days=30&project_slug=payments-api&version_label=1.0.0"
)


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    """Register project/version slug-to-UUID resolution responses."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION_LOOKUP,
    )


def test_mock_status_enabled_shows_url_and_usage(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_ENABLED)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT,
    )
    httpx_mock.add_response(url=_USAGE_URL, json=_USAGE)

    result = runner.invoke(app, ["mock", "status", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Mock Enabled" in result.stdout
    assert "True" in result.stdout
    assert _MOCK_BASE_URL in result.stdout
    assert "Usage (last 30 days):" in result.stdout
    assert "Requests (this version): 134" in result.stdout
    assert "Tenant monthly usage: 1234 / 100000" in result.stdout
    assert "Rate limit: 5.0 rps" in result.stdout


def test_mock_status_disabled_skips_usage(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_DISABLED)

    result = runner.invoke(app, ["mock", "status", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "False" in result.stdout
    assert "Usage (" not in result.stdout


def test_mock_status_json_envelope(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_ENABLED)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT,
    )
    httpx_mock.add_response(url=_USAGE_URL, json=_USAGE)

    result = runner.invoke(app, ["--json", "mock", "status", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["version"]["mockEnabled"] is True
    assert payload["version"]["mockBaseUrl"] == _MOCK_BASE_URL
    assert payload["usage"]["monthlyQuota"] == 100000


def test_mock_status_json_usage_null_when_disabled(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_DISABLED)

    result = runner.invoke(app, ["--json", "mock", "status", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["version"]["mockEnabled"] is False
    assert payload["usage"] is None


def test_mock_status_survives_unavailable_usage_endpoint(httpx_mock: object) -> None:
    """Usage is best-effort: a 404 (mock server disabled) never fails status."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_ENABLED)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=_USAGE_URL,
        status_code=404,
        json={"code": 404, "message": "Mock Server is disabled."},
    )

    result = runner.invoke(app, ["mock", "status", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert _MOCK_BASE_URL in result.stdout
    assert "Usage (" not in result.stdout


def test_mock_status_survives_failed_project_slug_lookup(httpx_mock: object) -> None:
    """A failed slug lookup skips the usage fetch instead of failing status."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_ENABLED)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        status_code=500,
        json={"code": 500, "message": "Internal error"},
    )

    result = runner.invoke(app, ["mock", "status", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Usage (" not in result.stdout


def test_mock_status_custom_days_window(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_VERSION_RECORD_URL, json=_RECORD_ENABLED)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=(
            "http://localhost:8000/v1/mocks/acme-corp/usage"
            "?days=7&project_slug=payments-api&version_label=1.0.0"
        ),
        json=_USAGE,
    )

    result = runner.invoke(app, ["mock", "status", "payments-api", "1.0.0", "--days", "7"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Usage (last 7 days):" in result.stdout


def test_mock_enable_success(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        method="PUT",
        url=_MOCK_TOGGLE_URL,
        match_json={"enabled": True},
        json=_RECORD_ENABLED,
    )

    result = runner.invoke(app, ["mock", "enable", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Mock Enabled" in result.stdout
    assert "True" in result.stdout
    assert _MOCK_BASE_URL in result.stdout


def test_mock_enable_json_output(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        method="PUT",
        url=_MOCK_TOGGLE_URL,
        match_json={"enabled": True},
        json=_RECORD_ENABLED,
    )

    result = runner.invoke(app, ["--json", "mock", "enable", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["mockEnabled"] is True
    assert payload["mockBaseUrl"] == _MOCK_BASE_URL


def test_mock_enable_draft_version_is_readable_usage_error(httpx_mock: object) -> None:
    """The SIM-2.1 draft rejection surfaces verbatim with a non-zero exit."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        method="PUT",
        url=_MOCK_TOGGLE_URL,
        match_json={"enabled": True},
        status_code=400,
        json={"code": 400, "message": "Mock can only be enabled on a published version."},
    )

    result = runner.invoke(app, ["mock", "enable", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_USAGE
    assert "Mock can only be enabled on a published version." in result.stderr


def test_mock_enable_insufficient_role_is_usage_error(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        method="PUT",
        url=_MOCK_TOGGLE_URL,
        match_json={"enabled": True},
        status_code=403,
        json={
            "code": 403,
            "message": "Only the version creator or a tenant administrator can change mock settings",
        },
    )

    result = runner.invoke(app, ["mock", "enable", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_USAGE
    assert "version creator or a tenant administrator" in result.stderr


def test_mock_disable_success(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        method="PUT",
        url=_MOCK_TOGGLE_URL,
        match_json={"enabled": False},
        json=_RECORD_DISABLED,
    )

    result = runner.invoke(app, ["mock", "disable", "payments-api", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS
    assert "False" in result.stdout


def test_mock_unknown_project_is_usage_error(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/nope",
        status_code=404,
        json={"code": 404, "message": "Project not found: nope"},
    )

    result = runner.invoke(app, ["mock", "status", "nope", "1.0.0"])
    assert result.exit_code == EXIT_USAGE
    assert "Project not found" in result.stderr


def test_mock_unknown_version_is_usage_error(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/9.9.9",
        status_code=404,
        json={"code": 404, "message": "Version not found: 9.9.9"},
    )

    result = runner.invoke(app, ["mock", "status", "payments-api", "9.9.9"])
    assert result.exit_code == EXIT_USAGE
    assert "Version not found" in result.stderr


def test_mock_group_without_subcommand_prints_help() -> None:
    result = runner.invoke(app, ["mock"])
    assert "status" in result.stdout
    assert "enable" in result.stdout
    assert "disable" in result.stdout


def test_version_usage_request_count_ignores_malformed_rollups() -> None:
    """The rollup sum skips non-dict entries and non-integer counts."""
    usage = {
        "dailyRollups": [
            {"requestCount": 5},
            {"requestCount": "not-a-number"},
            "junk",
            {"requestCount": 7},
        ]
    }
    assert version_usage_request_count(usage) == 12
    assert version_usage_request_count({}) == 0
    assert version_usage_request_count({"dailyRollups": "junk"}) == 0
