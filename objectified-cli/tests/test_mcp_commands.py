"""Tests for the ``mcp`` catalog command group (register/list/show)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from objectified_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from objectified_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_ENDPOINTS_URL = f"http://localhost:8000/v1/mcp/{_TENANT_SLUG}/endpoints"
_ENDPOINT_URL = f"{_ENDPOINTS_URL}/{_ENDPOINT_ID}"
_CREDENTIALS_URL = f"{_ENDPOINT_URL}/credentials"

_ENDPOINT = {
    "id": _ENDPOINT_ID,
    "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "name": "Weather MCP",
    "slug": "weather-mcp",
    "endpoint_url": "https://mcp.example.com/sse",
    "transport": "streamable_http",
    "description": "Weather lookups",
    "category": "tools",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "discovery_cadence_seconds": None,
    "last_discovered_at": "2026-06-20T12:00:00Z",
    "last_discovery_status": "success",
    "consecutive_failures": 0,
    "next_discovery_after": None,
    "quarantined": False,
    "quarantined_at": None,
    "quarantine_reason": None,
    "current_version_id": None,
    "created_at": "2026-06-01T00:00:00Z",
    "updated_at": None,
}

_CREDENTIAL_STATUS = {
    "success": True,
    "credential": {
        "endpoint_id": _ENDPOINT_ID,
        "auth_type": "bearer",
        "configured": True,
        "masked_secret": "****",
        "key_version": 1,
        "oauth_metadata": {},
        "last_refreshed_at": None,
        "created_at": "2026-06-01T00:00:00Z",
        "updated_at": None,
    },
}


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("OBJECTIFIED_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("OBJECTIFIED_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("OBJECTIFIED_TENANT_ID", _TENANT_SLUG)


@pytest.fixture
def api_key_only_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECTIFIED_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("OBJECTIFIED_BASE_URL", "http://localhost:8000")


# --------------------------------------------------------------------------- #
# Auth / scope guards
# --------------------------------------------------------------------------- #


def test_mcp_list_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_mcp_list_requires_tenant_scope(api_key_only_env: None) -> None:
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_USAGE
    assert "Tenant scope required" in strip_ansi(result.stderr)


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #


def test_mcp_register_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Weather MCP" in output
    assert "weather-mcp" in output
    assert "streamable_http" in output

    request = httpx_mock.get_request(url=_ENDPOINTS_URL, method="POST")
    body = json.loads(request.content)
    assert body == {
        "name": "Weather MCP",
        "endpoint_url": "https://mcp.example.com/sse",
        "transport": "streamable_http",
        "visibility": "private",
    }


def test_mcp_register_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--transport",
            "sse",
            "--description",
            "Weather lookups",
            "--category",
            "tools",
            "--visibility",
            "public",
            "--slug",
            "weather",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoint"]["id"] == _ENDPOINT_ID

    request = httpx_mock.get_request(url=_ENDPOINTS_URL, method="POST")
    body = json.loads(request.content)
    assert body == {
        "name": "Weather MCP",
        "endpoint_url": "https://mcp.example.com/sse",
        "transport": "sse",
        "visibility": "public",
        "slug": "weather",
        "description": "Weather lookups",
        "category": "tools",
    }


def test_mcp_register_with_bearer_sets_credential(
    httpx_mock: object,
    mcp_env: None,
) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
    )
    httpx_mock.add_response(
        url=_CREDENTIALS_URL,
        method="PUT",
        json=_CREDENTIAL_STATUS,
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--bearer",
            "s3cret-token",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "Credential set (bearer)." in strip_ansi(result.stdout)

    cred_request = httpx_mock.get_request(url=_CREDENTIALS_URL, method="PUT")
    cred_body = json.loads(cred_request.content)
    assert cred_body == {"auth_type": "bearer", "payload": {"token": "s3cret-token"}}


def test_mcp_register_with_header_sets_credential(
    httpx_mock: object,
    mcp_env: None,
) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
    )
    httpx_mock.add_response(
        url=_CREDENTIALS_URL,
        method="PUT",
        json=_CREDENTIAL_STATUS,
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--header",
            "X-Api-Token: abc123",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    cred_request = httpx_mock.get_request(url=_CREDENTIALS_URL, method="PUT")
    cred_body = json.loads(cred_request.content)
    assert cred_body == {
        "auth_type": "header",
        "payload": {"name": "X-Api-Token", "value": "abc123"},
    }


def test_mcp_register_rejects_bearer_and_header_together(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--bearer",
            "tok",
            "--header",
            "X-Api-Token: abc",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "not both" in strip_ansi(result.stderr)


def test_mcp_register_rejects_malformed_header(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--header",
            "no-colon-here",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "Name:Value" in strip_ansi(result.stderr)


def test_mcp_register_rejects_bad_transport(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--transport",
            "carrier-pigeon",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--transport must be" in strip_ansi(result.stderr)


def test_mcp_register_rejects_bad_visibility(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--visibility",
            "secret",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--visibility must be" in strip_ansi(result.stderr)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_mcp_list_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": [_ENDPOINT]},
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Weather MCP" in output
    assert "weather-mcp" in output
    assert "streamable_http" in output
    assert "private" in output


def test_mcp_list_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": [_ENDPOINT]},
    )
    result = runner.invoke(app, ["mcp", "list", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoints"][0]["id"] == _ENDPOINT_ID


def test_mcp_list_global_json_flag(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": [_ENDPOINT]},
    )
    result = runner.invoke(app, ["--json", "mcp", "list"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoints"][0]["name"] == "Weather MCP"


def test_mcp_list_empty(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": []},
    )
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_SUCCESS
    assert "No MCP endpoints." in strip_ansi(result.stdout)


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #


def test_mcp_show_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _ENDPOINT},
    )
    result = runner.invoke(app, ["mcp", "show", _ENDPOINT_ID])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Weather MCP" in output
    assert "https://mcp.example.com/sse" in output
    assert "success" in output


def test_mcp_show_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _ENDPOINT},
    )
    result = runner.invoke(app, ["mcp", "show", _ENDPOINT_ID, "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoint"]["slug"] == "weather-mcp"


def test_mcp_show_not_found(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        status_code=404,
        json={"detail": "MCP endpoint not found"},
    )
    result = runner.invoke(app, ["mcp", "show", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE


def test_mcp_show_rejects_non_uuid(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "show", "not-a-uuid"])
    assert result.exit_code == EXIT_USAGE
