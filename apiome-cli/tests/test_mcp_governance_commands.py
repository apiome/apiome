"""Tests for ``mcp policy`` and ``mcp key capabilities`` (MTG-5.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_POLICY_URL = f"http://localhost:8000/v1/tenants/{_TENANT_SLUG}/mcp-policy"
_KEY_URL = f"http://localhost:8000/v1/tenants/{_TENANT_SLUG}/mcp-keys/{_KEY_ID}"
_CAPS_URL = f"{_KEY_URL}/capabilities"
_SESSION = "obj_sess_test_token"

_POLICY = {
    "default_mode": "all",
    "allow_anonymous_mcp": True,
    "tools": [
        {
            "tool_id": "ping",
            "in_ceiling": True,
            "default_enabled": True,
            "anonymous_enabled": True,
        }
    ],
    "updated_at": "2026-07-01T00:00:00Z",
    "updated_by": "user-1",
}

_KEY_RECORD = {
    "id": _KEY_ID,
    "prefix": "mcp_abcd",
    "label": "dev",
    "scope_json": {"tenants": [], "projects": []},
    "capability_mode": "inherit",
    "enabled_tools": [],
    "created_at": "2026-07-01T00:00:00Z",
    "expires_at": None,
    "revoked_at": None,
    "last_used_at": None,
    "created_by": "user-1",
}


@pytest.fixture
def gov_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session token + base URL + slug tenant scope."""
    monkeypatch.setenv("APIOME_SESSION_TOKEN", _SESSION)
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


@pytest.fixture
def session_only_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_SESSION_TOKEN", _SESSION)
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")


# --------------------------------------------------------------------------- #
# Auth / scope guards
# --------------------------------------------------------------------------- #


def test_policy_get_requires_session_token() -> None:
    result = runner.invoke(app, ["mcp", "policy", "get"])
    assert result.exit_code == EXIT_USAGE
    assert "Session token required" in strip_ansi(result.stderr)


def test_policy_get_requires_tenant_scope(session_only_env: None) -> None:
    result = runner.invoke(app, ["mcp", "policy", "get"])
    assert result.exit_code == EXIT_USAGE
    assert "Tenant scope required" in strip_ansi(result.stderr)


def test_key_capabilities_get_requires_session_token() -> None:
    result = runner.invoke(app, ["mcp", "key", "capabilities", "get", _KEY_ID])
    assert result.exit_code == EXIT_USAGE
    assert "Session token required" in strip_ansi(result.stderr)


# --------------------------------------------------------------------------- #
# policy get / set
# --------------------------------------------------------------------------- #


def test_policy_get_json(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(
        url=_POLICY_URL,
        method="GET",
        json=_POLICY,
        match_headers={"Authorization": f"Bearer {_SESSION}"},
    )
    result = runner.invoke(app, ["--json", "mcp", "policy", "get"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == _POLICY
    request = httpx_mock.get_request()
    assert "X-API-Key" not in request.headers


def test_policy_get_human_table(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(url=_POLICY_URL, method="GET", json=_POLICY)
    result = runner.invoke(app, ["mcp", "policy", "get"])
    assert result.exit_code == EXIT_SUCCESS
    out = strip_ansi(result.stdout)
    assert "default_mode" in out or "Default mode" in out
    assert "ping" in out


def test_policy_set_from_file(httpx_mock: object, gov_env: None, tmp_path: Path) -> None:
    body = {
        "default_mode": "explicit",
        "allow_anonymous_mcp": False,
        "tools": [
            {
                "tool_id": "ping",
                "in_ceiling": True,
                "default_enabled": False,
                "anonymous_enabled": False,
            }
        ],
    }
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(body), encoding="utf-8")

    httpx_mock.add_response(url=_POLICY_URL, method="PUT", json={**body, "updated_at": None, "updated_by": "admin"})

    result = runner.invoke(app, ["mcp", "policy", "set", "--file", str(policy_file)])
    assert result.exit_code == EXIT_SUCCESS
    assert "Tenant MCP policy updated" in strip_ansi(result.stdout)

    request = httpx_mock.get_request()
    assert request.method == "PUT"
    assert request.headers["Authorization"] == f"Bearer {_SESSION}"
    assert "X-API-Key" not in request.headers
    assert json.loads(request.content.decode()) == body


def test_policy_set_strips_metadata_and_merges_flags(
    httpx_mock: object, gov_env: None, tmp_path: Path
) -> None:
    policy_file = tmp_path / "from-get.json"
    policy_file.write_text(json.dumps(_POLICY), encoding="utf-8")

    httpx_mock.add_response(
        url=_POLICY_URL,
        method="PUT",
        json={
            "default_mode": "all",
            "allow_anonymous_mcp": False,
            "tools": _POLICY["tools"],
            "updated_at": "2026-07-14T00:00:00Z",
            "updated_by": "admin",
        },
    )

    result = runner.invoke(
        app,
        ["mcp", "policy", "set", "--file", str(policy_file), "--allow-anonymous", "false"],
    )
    assert result.exit_code == EXIT_SUCCESS
    sent = json.loads(httpx_mock.get_request().content.decode())
    assert "updated_at" not in sent
    assert "updated_by" not in sent
    assert sent["allow_anonymous_mcp"] is False
    assert sent["default_mode"] == "all"
    assert sent["tools"] == _POLICY["tools"]


def test_policy_set_flags_fetch_and_merge(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(url=_POLICY_URL, method="GET", json=_POLICY)
    httpx_mock.add_response(
        url=_POLICY_URL,
        method="PUT",
        json={
            "default_mode": "inherit_registry",
            "allow_anonymous_mcp": True,
            "tools": _POLICY["tools"],
            "updated_at": None,
            "updated_by": None,
        },
    )

    result = runner.invoke(app, ["mcp", "policy", "set", "--default-mode", "inherit_registry"])
    assert result.exit_code == EXIT_SUCCESS

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].method == "GET"
    assert requests[1].method == "PUT"
    sent = json.loads(requests[1].content.decode())
    assert sent["default_mode"] == "inherit_registry"
    assert sent["allow_anonymous_mcp"] is True
    assert sent["tools"] == _POLICY["tools"]


def test_policy_set_requires_input(gov_env: None) -> None:
    result = runner.invoke(app, ["mcp", "policy", "set"])
    assert result.exit_code == EXIT_USAGE


def test_policy_set_rejects_bad_default_mode(gov_env: None) -> None:
    result = runner.invoke(app, ["mcp", "policy", "set", "--default-mode", "nope"])
    assert result.exit_code == EXIT_USAGE


def test_policy_set_rejects_invalid_json(
    httpx_mock: object, gov_env: None, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    result = runner.invoke(app, ["mcp", "policy", "set", "--file", str(bad)])
    assert result.exit_code == EXIT_USAGE
    assert "Invalid JSON" in strip_ansi(result.stderr)


def test_policy_set_rejects_default_enabled_without_ceiling(
    gov_env: None, tmp_path: Path
) -> None:
    body = {
        "default_mode": "all",
        "allow_anonymous_mcp": True,
        "tools": [
            {
                "tool_id": "ping",
                "in_ceiling": False,
                "default_enabled": True,
                "anonymous_enabled": True,
            }
        ],
    }
    path = tmp_path / "bad-tools.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    result = runner.invoke(app, ["mcp", "policy", "set", "--file", str(path)])
    assert result.exit_code == EXIT_USAGE


def test_policy_set_json_output(httpx_mock: object, gov_env: None, tmp_path: Path) -> None:
    body = {
        "default_mode": "all",
        "allow_anonymous_mcp": True,
        "tools": [],
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    response = {**body, "updated_at": None, "updated_by": None}
    httpx_mock.add_response(url=_POLICY_URL, method="PUT", json=response)

    result = runner.invoke(
        app, ["--json", "mcp", "policy", "set", "--file", str(path)]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == response


# --------------------------------------------------------------------------- #
# key capabilities get / set
# --------------------------------------------------------------------------- #


def test_key_capabilities_get_maps_fields(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(
        url=_KEY_URL,
        method="GET",
        json={
            **_KEY_RECORD,
            "capability_mode": "explicit",
            "enabled_tools": ["ping", "spec.list"],
        },
        match_headers={"Authorization": f"Bearer {_SESSION}"},
    )
    result = runner.invoke(
        app, ["--json", "mcp", "key", "capabilities", "get", _KEY_ID]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == {
        "mode": "explicit",
        "enabled_tools": ["ping", "spec.list"],
    }
    assert "X-API-Key" not in httpx_mock.get_request().headers


def test_key_capabilities_get_human(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(url=_KEY_URL, method="GET", json=_KEY_RECORD)
    result = runner.invoke(app, ["mcp", "key", "capabilities", "get", _KEY_ID])
    assert result.exit_code == EXIT_SUCCESS
    out = strip_ansi(result.stdout)
    assert "inherit" in out


def test_key_capabilities_set_mode_inherit(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(
        url=_KEY_URL,
        method="GET",
        json={**_KEY_RECORD, "capability_mode": "explicit", "enabled_tools": ["ping"]},
    )
    httpx_mock.add_response(
        url=_CAPS_URL,
        method="PUT",
        json={"mode": "inherit", "enabled_tools": []},
    )

    result = runner.invoke(
        app, ["mcp", "key", "capabilities", "set", _KEY_ID, "--mode", "inherit"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "mode=inherit" in strip_ansi(result.stdout)

    put = [r for r in httpx_mock.get_requests() if r.method == "PUT"][0]
    assert put.headers["Authorization"] == f"Bearer {_SESSION}"
    assert json.loads(put.content.decode()) == {"mode": "inherit", "enabled_tools": None}


def test_key_capabilities_set_tools_flags(httpx_mock: object, gov_env: None) -> None:
    httpx_mock.add_response(url=_KEY_URL, method="GET", json=_KEY_RECORD)
    httpx_mock.add_response(
        url=_CAPS_URL,
        method="PUT",
        json={"mode": "explicit", "enabled_tools": ["ping", "spec.list"]},
    )

    result = runner.invoke(
        app,
        [
            "mcp",
            "key",
            "capabilities",
            "set",
            _KEY_ID,
            "--mode",
            "explicit",
            "--tool",
            "ping",
            "--tool",
            "spec.list",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    put = [r for r in httpx_mock.get_requests() if r.method == "PUT"][0]
    assert json.loads(put.content.decode()) == {
        "mode": "explicit",
        "enabled_tools": ["ping", "spec.list"],
    }


def test_key_capabilities_set_from_file(
    httpx_mock: object, gov_env: None, tmp_path: Path
) -> None:
    caps = {"mode": "explicit", "enabled_tools": ["ping"]}
    path = tmp_path / "caps.json"
    path.write_text(json.dumps(caps), encoding="utf-8")
    httpx_mock.add_response(url=_CAPS_URL, method="PUT", json=caps)

    result = runner.invoke(
        app,
        ["--json", "mcp", "key", "capabilities", "set", _KEY_ID, "--file", str(path)],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == caps
    assert json.loads(httpx_mock.get_request().content.decode()) == caps


def test_key_capabilities_set_requires_input(gov_env: None) -> None:
    result = runner.invoke(app, ["mcp", "key", "capabilities", "set", _KEY_ID])
    assert result.exit_code == EXIT_USAGE


def test_key_capabilities_set_rejects_bad_mode(gov_env: None) -> None:
    result = runner.invoke(
        app, ["mcp", "key", "capabilities", "set", _KEY_ID, "--mode", "nope"]
    )
    assert result.exit_code == EXIT_USAGE
