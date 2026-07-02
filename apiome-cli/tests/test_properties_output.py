"""Integration tests for properties list/get output modes."""

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
_PROPERTY_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

_LIST_PAYLOAD = {
    "total": 1,
    "items": [
        {
            "id": _PROPERTY_ID,
            "tenant_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "name": "color",
            "description": "A color value",
            "body": {"type": "string"},
            "enabled": True,
        },
    ],
}

_GET_PAYLOAD = _LIST_PAYLOAD["items"][0]


def test_properties_list_json_mode(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/properties/acme-corp/{_PROJECT_ID}",
        json=_LIST_PAYLOAD,
    )
    result = runner.invoke(
        app,
        ["--json", "properties", "list", "--project-id", _PROJECT_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == {"total": 1, "items": _LIST_PAYLOAD["items"]}


def test_properties_get_json_mode(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/properties/acme-corp/{_PROJECT_ID}/{_PROPERTY_ID}",
        json=_GET_PAYLOAD,
    )
    result = runner.invoke(
        app,
        [
            "--json",
            "properties",
            "get",
            _PROPERTY_ID,
            "--project-id",
            _PROJECT_ID,
        ],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == _GET_PAYLOAD


def test_properties_get_rejects_invalid_uuid() -> None:
    result = runner.invoke(
        app,
        ["properties", "get", "not-a-uuid", "--project-id", _PROJECT_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_USAGE
