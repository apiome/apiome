"""Tests for ``apiome mcp server-json export`` (AAU-5.1, #5722)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.commands.mcp import server_json_text
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_TOOLSET = "0b8e6a4e-9a52-4d1f-8f43-6f1c2f6f4a11"
_TOOLSET_URL = f"http://localhost:8000/v1/tenants/acme/agent-toolsets/{_TOOLSET}/server.json"
_TENANT_URL = "http://localhost:8000/v1/tenants/acme/agent-access/server.json"

#: A ``server.json`` as the REST API returns it, keys deliberately out of order.
_DOCUMENT = {
    "version": "1.0.0",
    "name": f"apiome.acme/agent-toolset-{_TOOLSET}",
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "remotes": [{"url": "https://agents.example.com/agent/mcp", "type": "streamable-http"}],
    "description": "Agent Access to Pets 1.0.0: 2 MCP tools — read only.",
    "_meta": {"dev.apiome/agent-runtime": {"digest": "ab" * 32, "toolCount": 2}},
}


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme")


def test_export_toolset_prints_canonical_json(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_TOOLSET_URL, json=_DOCUMENT)
    result = runner.invoke(app, ["mcp", "server-json", "export", "--toolset", _TOOLSET])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == server_json_text(_DOCUMENT)
    assert json.loads(result.stdout) == _DOCUMENT
    assert result.stdout.endswith("}\n") and not result.stdout.endswith("\n\n")
    assert "—" in result.stdout  # not ascii-escaped


def test_output_is_byte_stable_whatever_the_key_order() -> None:
    reordered = json.loads(json.dumps(_DOCUMENT))
    reordered = {key: reordered[key] for key in reversed(list(reordered))}
    assert server_json_text(reordered) == server_json_text(_DOCUMENT)
    lines = server_json_text(_DOCUMENT).splitlines()
    assert lines[1].startswith('  "$schema"')


def test_export_tenant_wide(httpx_mock: object, mcp_env: None) -> None:
    document = {**_DOCUMENT, "name": "apiome.acme/agent-runtime"}
    httpx_mock.add_response(url=_TENANT_URL, json=document)
    result = runner.invoke(app, ["mcp", "server-json", "export", "--tenant-wide"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["name"] == "apiome.acme/agent-runtime"


def test_export_to_file(httpx_mock: object, mcp_env: None, tmp_path: Path) -> None:
    httpx_mock.add_response(url=_TOOLSET_URL, json=_DOCUMENT)
    target = tmp_path / "server.json"
    result = runner.invoke(
        app, ["mcp", "server-json", "export", "--toolset", _TOOLSET, "--out", str(target)]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert target.read_text(encoding="utf-8") == server_json_text(_DOCUMENT)
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [[], ["--toolset", _TOOLSET, "--tenant-wide"]],
)
def test_exactly_one_scope_is_required(mcp_env: None, args: list) -> None:
    result = runner.invoke(app, ["mcp", "server-json", "export", *args])
    assert result.exit_code == EXIT_USAGE
    assert "exactly one of --toolset" in result.output


def test_invalid_toolset_id_is_a_usage_error(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "server-json", "export", "--toolset", "not-a-uuid"])
    assert result.exit_code == EXIT_USAGE


def test_api_error_is_reported(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TOOLSET_URL,
        status_code=404,
        json={"detail": {"code": "agent-toolset-not-found", "errors": ["no such agent toolset"]}},
    )
    result = runner.invoke(app, ["mcp", "server-json", "export", "--toolset", _TOOLSET])
    assert result.exit_code != EXIT_SUCCESS
