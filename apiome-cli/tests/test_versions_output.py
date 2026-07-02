"""Integration tests for ``versions list`` / ``versions get`` output modes.

These exercise the real command surface in ``commands/versions.py``:

- ``versions list`` optionally takes ``--project-id``. With it, the command
  reads one project's versions (``GET /v1/versions/{tenant}/{project_id}``) plus
  that project's record (``GET /v1/projects/{tenant}/{project_id}``). Without it,
  it lists every project (``GET /v1/projects/{tenant}``) and each project's
  versions. JSON mode emits ``{"total", "items"}``. There is no pagination /
  ``--all`` / ``--limit`` flag.
- ``versions get`` requires ``--project-id`` and a version-id argument and reads
  ``GET /v1/versions/{tenant}/{project_id}/{version_id}``.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_API_KEY_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

_PROJECT_RECORD = {
    "id": _PROJECT_ID,
    "name": "Payments API",
    "slug": "payments-api",
    "enabled": True,
}

_PROJECTS_PAYLOAD = [_PROJECT_RECORD]

_VERSION_RECORD = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "v1-0-0",
    "source": "manual",
    "data": {"description": "Initial release"},
    "enabled": True,
}

_VERSIONS_PAYLOAD = [_VERSION_RECORD]


def _mock_projects_lookup(httpx_mock: object) -> None:
    """Mock the all-projects listing used by the unfiltered ``list`` path."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json=_PROJECTS_PAYLOAD,
    )


def _mock_project_record(httpx_mock: object) -> None:
    """Mock the single-project record fetched by ``list --project-id``."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_PROJECT_RECORD,
    )


def _mock_versions_for_project(httpx_mock: object) -> None:
    """Mock one project's versions listing."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}",
        json=_VERSIONS_PAYLOAD,
    )


def test_versions_list_json_mode(httpx_mock: object) -> None:
    """--json versions list emits a {total, items} JSON envelope."""
    _mock_projects_lookup(httpx_mock)
    _mock_versions_for_project(httpx_mock)
    result = runner.invoke(app, ["--json", "versions", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == {"total": 1, "items": _VERSIONS_PAYLOAD}


def test_versions_list_human_table(httpx_mock: object) -> None:
    """Default versions list renders a table with project name/slug and version data."""
    _mock_projects_lookup(httpx_mock)
    _mock_versions_for_project(httpx_mock)
    result = runner.invoke(app, ["versions", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert "1.0.0" in result.stdout
    assert "v1-0-0" in result.stdout
    assert "manual" in result.stdout
    assert "Payments" in result.stdout
    assert "API" in result.stdout
    assert "payments-" in result.stdout
    assert "Project" in result.stdout
    assert "Showing 1 of 1" in result.stdout
    assert result.stdout.strip().startswith("{") is False


def test_versions_list_with_project_id_filter(httpx_mock: object) -> None:
    """--project-id reads one project's versions plus that project's record."""
    _mock_versions_for_project(httpx_mock)
    _mock_project_record(httpx_mock)
    result = runner.invoke(
        app,
        ["versions", "list", "--project-id", _PROJECT_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "1.0.0" in result.stdout
    assert "Payments" in result.stdout
    assert "API" in result.stdout
    assert "Showing 1 of 1" in result.stdout


def test_versions_list_with_project_id_filter_json(httpx_mock: object) -> None:
    """--json --project-id emits a JSON envelope filtered to the given project."""
    _mock_versions_for_project(httpx_mock)
    _mock_project_record(httpx_mock)
    result = runner.invoke(
        app,
        ["--json", "versions", "list", "--project-id", _PROJECT_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["total"] == 1
    assert payload["items"][0]["project_id"] == _PROJECT_ID


def test_versions_list_rejects_invalid_project_uuid() -> None:
    """versions list --project-id fails fast when the value is not a UUID."""
    result = runner.invoke(app, ["versions", "list", "--project-id", "not-a-uuid"])
    assert result.exit_code == EXIT_USAGE


def test_versions_list_sends_api_key_header(httpx_mock: object) -> None:
    """RestClient forwards APIOME_API_KEY as X-API-Key on the list path."""
    _mock_projects_lookup(httpx_mock)
    _mock_versions_for_project(httpx_mock)
    result = runner.invoke(app, ["versions", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    request = httpx_mock.get_requests()[0]
    assert request.headers["X-API-Key"] == "obj_test_key"


def test_versions_get_json_mode(httpx_mock: object) -> None:
    """--json versions get prints the raw API record."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}",
        json=_VERSION_RECORD,
    )
    result = runner.invoke(
        app,
        ["--json", "versions", "get", "--project-id", _PROJECT_ID, _VERSION_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == _VERSION_RECORD


def test_versions_get_human_table(httpx_mock: object) -> None:
    """Default versions get renders field/value rows including the version."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}",
        json=_VERSION_RECORD,
    )
    result = runner.invoke(
        app,
        ["versions", "get", "--project-id", _PROJECT_ID, _VERSION_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "1.0.0" in result.stdout
    assert "Version" in result.stdout
    assert result.stdout.strip().startswith("{") is False


def test_versions_get_rejects_invalid_uuid() -> None:
    """versions get fails fast when the version id is not a UUID."""
    result = runner.invoke(
        app, ["versions", "get", "--project-id", _PROJECT_ID, "not-a-uuid"]
    )
    assert result.exit_code == EXIT_USAGE


def test_versions_get_requires_project_id() -> None:
    """versions get without --project-id is a usage error (option is required)."""
    result = runner.invoke(app, ["versions", "get", _VERSION_ID])
    assert result.exit_code == EXIT_USAGE
