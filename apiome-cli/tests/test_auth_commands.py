"""Tests for auth whoami, status, and tenants commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANTS_PAYLOAD = [
    {
        "id": "22222222-2222-4222-8222-222222222222",
        "slug": "acme",
        "name": "Acme",
        "role": "admin",
    },
]


def _tenants_me_page(items: list[dict]) -> dict:
    return {"total": len(items), "offset": 0, "limit": 100, "items": items}


@pytest.fixture
def session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_SESSION_TOKEN", "obj_sess_test_token")


def test_auth_whoami_requires_credentials() -> None:
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_auth_whoami_human_output(httpx_mock: object, session_env: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
        match_headers={"Authorization": "Bearer obj_sess_test_token"},
    )
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "acme" in output
    assert "admin" in output


def test_auth_whoami_json_output(httpx_mock: object, session_env: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
    )
    result = runner.invoke(app, ["--json", "auth", "whoami"])
    assert result.exit_code == EXIT_SUCCESS
    assert '"slug":"acme"' in result.stdout.replace(" ", "")


def test_auth_status_human_output(httpx_mock: object, session_env: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
    )
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "acme" in output
    assert "admin" in output


def test_auth_status_json_output(httpx_mock: object, session_env: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
    )
    result = runner.invoke(app, ["--json", "auth", "status"])
    assert result.exit_code == EXIT_SUCCESS
    assert '"items":' in result.stdout
    assert '"total":' in result.stdout


def test_auth_tenants_human_output(httpx_mock: object, session_env: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
    )
    result = runner.invoke(app, ["auth", "tenants"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Acme" in output
    assert "acme" in output


def test_auth_tenants_json_output(httpx_mock: object, session_env: None) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
    )
    result = runner.invoke(app, ["--json", "auth", "tenants"])
    assert result.exit_code == EXIT_SUCCESS
    assert '"slug":"acme"' in result.stdout.replace(" ", "")


def test_auth_session_token_flag_override(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=100",
        json=_tenants_me_page(_TENANTS_PAYLOAD),
        match_headers={"Authorization": "Bearer flag-token"},
    )
    result = runner.invoke(
        app,
        ["--session-token", "flag-token", "auth", "whoami"],
    )
    assert result.exit_code == EXIT_SUCCESS


def test_auth_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    help_text = strip_ansi(result.stdout)
    assert "whoami" in help_text
    assert "status" in help_text
    assert "tenants" in help_text
