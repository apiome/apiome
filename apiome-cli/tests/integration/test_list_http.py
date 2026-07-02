"""httpx-mocked integration tests for list commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

_LIST_PAYLOAD = {
    "total": 1,
    "offset": 0,
    "limit": 50,
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


def test_projects_list_sync_200(
    httpx_mock: object,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /v1/projects/{tenant} returns paginated items without live network."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json=_LIST_PAYLOAD,
    )

    result = runner.invoke(app, ["projects", "list"])

    assert result.exit_code == EXIT_SUCCESS
    assert "Payments API" in result.stdout
    assert "payments-api" in result.stdout
    assert len(httpx_mock.get_requests()) == 1


def test_projects_list_422_exits_usage(
    httpx_mock: object,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server 422 on the list endpoint maps to EXIT_USAGE."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        status_code=422,
        json={
            "code": 422,
            "message": "limit must not exceed 200",
            "details": [
                {
                    "type": "less_than_equal",
                    "loc": ["query", "limit"],
                    "msg": "Input should be less than or equal to 200",
                },
            ],
        },
    )

    result = runner.invoke(app, ["projects", "list"])

    assert result.exit_code == EXIT_USAGE
    assert "HTTP 422" in result.stderr
    assert "limit" in result.stderr.lower()


def test_projects_list_json_mode(
    httpx_mock: object,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--json projects list emits the API envelope on stdout."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json=_LIST_PAYLOAD,
    )

    result = runner.invoke(app, ["--json", "projects", "list"])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload == {"total": 1, "items": _LIST_PAYLOAD["items"]}


def test_schemas_list_sync_200(
    httpx_mock: object,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /v1/classes/{tenant} list succeeds with mocked pagination response."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/classes/acme-corp",
        json={
            "total": 1,
            "offset": 0,
            "limit": 50,
            "items": [
                {
                    "id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                    "tenant_id": _TENANT_ID,
                    "name": "User",
                    "description": "User record",
                    "enabled": True,
                },
            ],
        },
    )

    result = runner.invoke(app, ["schemas", "list"])

    assert result.exit_code == EXIT_SUCCESS
    assert "User" in result.stdout
    assert len(httpx_mock.get_requests()) == 1
