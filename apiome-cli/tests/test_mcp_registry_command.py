"""Tests for ``apiome mcp registry list`` (AAU-5.3, #5724)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_SERVERS_URL = "http://localhost:8000/v1/tenants/acme/mcp-registry/v0.1/servers"


def _entry(slug: str, *, grade: str = "B") -> dict:
    """A registry ``ServerResponse`` as the REST API returns it."""
    return {
        "server": {
            "name": f"apiome.acme/{slug}",
            "version": "1.2.0",
            "remotes": [{"type": "streamable-http", "url": f"https://mcp.example.com/{slug}"}],
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "isLatest": True,
                "updatedAt": "2026-10-01T12:00:00Z",
            },
            "dev.apiome/catalog": {
                "grade": grade,
                "visibility": "public",
                "trustPosture": {"score": 90, "grade": "A", "gatePassed": True},
            },
        },
    }


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme")


def test_registry_list_follows_cursor_and_renders_table(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100",
        json={"servers": [_entry("alpha")], "metadata": {"count": 1, "nextCursor": "c1"}},
    )
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100&cursor=c1",
        json={"servers": [_entry("bravo", grade="C")], "metadata": {"count": 1}},
    )
    result = runner.invoke(app, ["mcp", "registry", "list"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "apiome.acme/alpha" in out and "apiome.acme/bravo" in out
    assert "https://mcp.example.com/alpha" in out
    assert "1.2.0" in out


def test_registry_list_json_merges_pages(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100",
        json={"servers": [_entry("alpha")], "metadata": {"count": 1, "nextCursor": "c1"}},
    )
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100&cursor=c1",
        json={"servers": [_entry("bravo")], "metadata": {"count": 1}},
    )
    result = runner.invoke(app, ["mcp", "registry", "list", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["metadata"] == {"count": 2}
    assert [e["server"]["name"] for e in payload["servers"]] == ["apiome.acme/alpha", "apiome.acme/bravo"]


def test_registry_list_since_is_sent_as_updated_since(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100&updated_since=2026-10-01T00%3A00%3A00Z",
        json={"servers": [], "metadata": {"count": 0}},
    )
    result = runner.invoke(app, ["mcp", "registry", "list", "--since", "2026-10-01T00:00:00Z"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "No servers in the registry." in strip_ansi(result.output)


def test_registry_list_bad_since_is_usage_error(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "registry", "list", "--since", "yesterday"])
    assert result.exit_code == EXIT_USAGE
    assert "--since" in strip_ansi(result.output)


def test_registry_list_stops_on_a_repeated_cursor(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100",
        json={"servers": [_entry("alpha")], "metadata": {"nextCursor": "loop"}},
    )
    httpx_mock.add_response(
        url=f"{_SERVERS_URL}?limit=100&cursor=loop",
        json={"servers": [_entry("bravo")], "metadata": {"nextCursor": "loop"}},
    )
    result = runner.invoke(app, ["mcp", "registry", "list", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.output)["metadata"]["count"] == 2
