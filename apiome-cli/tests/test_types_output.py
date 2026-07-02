"""Integration tests for types list/show/search output modes."""

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

_TYPE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

_LIST_PAYLOAD = {
    "total": 2,
    "items": [
        {
            "id": _TYPE_ID,
            "name": "Email",
            "slug": "email",
            "description": "A valid RFC 5321 email address",
        },
        {
            "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "name": "Timestamp",
            "slug": "timestamp",
            "description": "ISO 8601 date-time string",
        },
    ],
}

_GET_PAYLOAD = {
    "id": _TYPE_ID,
    "name": "Email",
    "slug": "email",
    "description": "A valid RFC 5321 email address",
    "body": {"type": "string", "format": "email"},
    "enabled": True,
}


def test_types_list_json_mode(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/primitives/acme-corp",
        json=_LIST_PAYLOAD,
    )
    result = runner.invoke(app, ["--json", "types", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == _LIST_PAYLOAD["items"]


def test_types_show_by_uuid(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/primitives/acme-corp/{_TYPE_ID}",
        json=_GET_PAYLOAD,
    )
    result = runner.invoke(app, ["types", "show", _TYPE_ID], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert "Email" in result.stdout


def test_types_show_not_found(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/primitives/acme-corp",
        json={"total": 0, "items": []},
    )
    result = runner.invoke(app, ["types", "show", "missing-type"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_USAGE
