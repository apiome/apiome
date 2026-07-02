"""Integration tests for schemas list/get output modes."""

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

_SCHEMA_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

_LIST_PAYLOAD = {
    "total": 1,
    "items": [
        {
            "id": _SCHEMA_ID,
            "tenant_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "name": "product",
            "description": "Product schema",
            "body": {"type": "object"},
            "enabled": True,
        },
    ],
}

_GET_PAYLOAD = _LIST_PAYLOAD["items"][0]


def test_schemas_list_json_mode(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/classes/acme-corp",
        json=_LIST_PAYLOAD,
    )
    result = runner.invoke(app, ["--json", "schemas", "list"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == {"total": 1, "items": _LIST_PAYLOAD["items"]}


def test_schemas_get_json_mode(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/classes/acme-corp/{_SCHEMA_ID}",
        json=_GET_PAYLOAD,
    )
    result = runner.invoke(
        app,
        ["--json", "schemas", "get", _SCHEMA_ID],
        env=_API_KEY_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout.strip()) == _GET_PAYLOAD


def test_schemas_get_rejects_invalid_uuid() -> None:
    result = runner.invoke(app, ["schemas", "get", "not-a-uuid"], env=_API_KEY_ENV)
    assert result.exit_code == EXIT_USAGE
