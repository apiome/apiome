"""Integration tests for projects list/get output modes."""

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
_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

_LIST_PAYLOAD = {
    "total": 1,
    "items": [
        {
            "id": _PROJECT_ID,
            "tenant_id": _TENANT_ID,
            "name": "Payments API",
            "slug": "payments-api",
            "source": "manual",
            "data": {"title": "Payments API"},
            "enabled": True,
        },
    ],
}

_GET_PAYLOAD = _LIST_PAYLOAD["items"][0]


def test_projects_list_json_mode(httpx_mock: object) -> None:
    """--json projects list emits a {total, items} JSON envelope."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json=_LIST_PAYLOAD,
    )
    result = runner.invoke(app, ["--json", "projects", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == {"total": 1, "items": _LIST_PAYLOAD["items"]}


def test_projects_list_human_table(httpx_mock: object) -> None:
    """Default projects list renders a table on stdout."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json=_LIST_PAYLOAD,
    )
    result = runner.invoke(app, ["projects", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert "Payments API" in result.stdout
    assert "payments-api" in result.stdout
    assert "Showing 1 of 1" in result.stdout
    assert result.stdout.strip().startswith("{") is False


def test_projects_get_json_mode(httpx_mock: object) -> None:
    """--json projects get prints raw API JSON."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_GET_PAYLOAD,
    )
    result = runner.invoke(
        app,
        ["--json", "projects", "get", _PROJECT_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == _GET_PAYLOAD


def test_projects_get_human_table(httpx_mock: object) -> None:
    """Default projects get renders field/value rows."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/acme-corp/{_PROJECT_ID}",
        json=_GET_PAYLOAD,
    )
    result = runner.invoke(app, ["projects", "get", _PROJECT_ID], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert "Payments API" in result.stdout
    assert "Field" in result.stdout
    assert result.stdout.strip().startswith("{") is False


def test_projects_list_sends_api_key_header(httpx_mock: object) -> None:
    """RestClient forwards APIOME_API_KEY as X-API-Key."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json=_LIST_PAYLOAD,
    )
    result = runner.invoke(app, ["projects", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    request = httpx_mock.get_requests()[0]
    assert request.headers["X-API-Key"] == "obj_test_key"


def test_projects_get_rejects_invalid_uuid() -> None:
    """projects get fails fast when project id is not a UUID."""
    result = runner.invoke(app, ["projects", "get", "not-a-uuid"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_USAGE
