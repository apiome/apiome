"""Tests for ``apiome login`` and ``apiome logout`` (#5501)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli import config as config_module
from apiome_cli.commands import login as login_module
from apiome_cli.config import read_user_config_file, write_user_config_file
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

BASE = "http://localhost:8000"
START_URL = f"{BASE}/v1/cli/login"
TOKEN_URL = f"{BASE}/v1/cli/login/token"
KEY_URL = f"{BASE}/v1/cli/login/key"

STARTED = {
    "device_code": "dev-code-secret",
    "user_code": "KTXR-MWDB",
    "verification_uri": "https://app.apiome.dev/cli/login",
    "verification_uri_complete": "https://app.apiome.dev/cli/login?code=KTXR-MWDB",
    "expires_in": 600,
    "interval": 5,
}

ISSUED = {
    "api_key": "sk_" + "a" * 64,
    "key_id": "33333333-3333-4333-8333-333333333333",
    "key_prefix": "sk_aaaaaaaaa...",
    "key_name": "CLI login · apiome-cli on box · 1234abcd",
    "tenant_slug": "northwind",
    "tenant_name": "Northwind",
    "expires_at": "2026-11-06T17:00:00Z",
}


def _pending(code: str = "authorization_pending") -> dict:
    return {"detail": {"error": code, "message": "…"}}


@pytest.fixture
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "apiome" / "config.toml"
    monkeypatch.setattr(config_module, "user_config_path", lambda: path)
    monkeypatch.setattr(login_module, "user_config_path", lambda: path)
    return path


@pytest.fixture
def no_wait(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make polling instant; return the sleeps the command asked for."""
    sleeps: list[float] = []
    clock = {"now": 0.0}

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(login_module, "_sleep", fake_sleep)
    monkeypatch.setattr(login_module, "_monotonic", lambda: clock["now"])
    return sleeps


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr(login_module, "_open_browser", lambda url: opened.append(url) or True)
    return opened


def test_login_opens_the_browser_polls_and_saves_the_key(
    httpx_mock, config_file: Path, no_wait: list[float], browser: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=400, json=_pending())
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=400, json=_pending("slow_down"))
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=200, json=ISSUED)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == EXIT_SUCCESS, result.output
    stderr = strip_ansi(result.stderr)
    assert "Your code: KTXR-MWDB" in stderr
    assert STARTED["verification_uri_complete"] in stderr
    assert browser == [STARTED["verification_uri_complete"]]
    # slow_down adds five seconds to the interval.
    assert no_wait == [5, 5, 10]
    assert "Signed in to Northwind (northwind)" in strip_ansi(result.stdout)

    saved = read_user_config_file(config_file)
    assert saved == {"base_url": BASE, "api_key": ISSUED["api_key"], "tenant_id": "northwind"}

    start_request, *polls = httpx_mock.get_requests()
    assert "X-API-Key" not in start_request.headers
    assert json.loads(start_request.content)["client_name"].startswith("apiome-cli")
    assert all(json.loads(p.content) == {"device_code": "dev-code-secret"} for p in polls)


def test_login_keeps_other_saved_settings_and_warns_about_the_env_key(
    httpx_mock, config_file: Path, no_wait: list[float], browser: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_user_config_file({"base_url": BASE, "api_key": "sk_old", "tenant_id": "harbor"}, path=config_file)
    monkeypatch.setenv("APIOME_API_KEY", "sk_from_env")
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=200, json=ISSUED)

    result = runner.invoke(app, ["--json", "login"])

    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.stdout)
    assert payload["tenant_slug"] == "northwind" and "api_key" not in payload
    assert "APIOME_API_KEY is set" in strip_ansi(result.stderr)
    assert read_user_config_file(config_file)["api_key"] == ISSUED["api_key"]
    # The env key never reaches the anonymous login endpoints.
    assert all("X-API-Key" not in request.headers for request in httpx_mock.get_requests())


def test_login_no_browser_only_prints_the_link(
    httpx_mock, config_file: Path, no_wait: list[float], browser: list[str]
) -> None:
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=200, json=ISSUED)
    result = runner.invoke(app, ["login", "--no-browser"])
    assert result.exit_code == EXIT_SUCCESS
    assert browser == []


def test_login_reports_a_browser_that_will_not_open(
    httpx_mock, config_file: Path, no_wait: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(login_module, "_open_browser", lambda url: False)
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=200, json=ISSUED)
    result = runner.invoke(app, ["login"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Could not open a browser" in strip_ansi(result.stderr)


def test_login_denied_saves_nothing(httpx_mock, config_file: Path, no_wait: list[float], browser: list[str]) -> None:
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=400, json=_pending("access_denied"))
    result = runner.invoke(app, ["login"])
    assert result.exit_code == EXIT_USAGE
    assert "denied" in strip_ansi(result.stderr)
    assert not config_file.exists()


def test_login_expired_by_the_server(httpx_mock, config_file: Path, no_wait: list[float], browser: list[str]) -> None:
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=400, json=_pending("expired_token"))
    result = runner.invoke(app, ["login"])
    assert result.exit_code == EXIT_USAGE
    assert "expired" in strip_ansi(result.stderr)
    assert not config_file.exists()


def test_login_gives_up_at_the_deadline(
    httpx_mock, config_file: Path, no_wait: list[float], browser: list[str]
) -> None:
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json={**STARTED, "expires_in": 12})
    httpx_mock.add_response(url=TOKEN_URL, method="POST", status_code=400, json=_pending(), is_reusable=True)
    result = runner.invoke(app, ["login"])
    assert result.exit_code == EXIT_USAGE
    assert "expired before it was approved" in strip_ansi(result.stderr)
    assert no_wait == [5, 5, 5]


def test_login_ctrl_c_cancels(
    httpx_mock, config_file: Path, monkeypatch: pytest.MonkeyPatch, browser: list[str]
) -> None:
    def interrupt(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(login_module, "_sleep", interrupt)
    httpx_mock.add_response(url=START_URL, method="POST", status_code=201, json=STARTED)
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 130
    assert "cancelled" in strip_ansi(result.stderr)


def test_logout_revokes_and_forgets_the_key(httpx_mock, config_file: Path) -> None:
    write_user_config_file({"base_url": BASE, "api_key": "sk_login", "tenant_id": "northwind"}, path=config_file)
    httpx_mock.add_response(
        url=KEY_URL, method="DELETE", status_code=204, match_headers={"X-API-Key": "sk_login"}
    )
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Signed out" in strip_ansi(result.stdout)
    assert read_user_config_file(config_file) == {"base_url": BASE, "tenant_id": "northwind"}


def test_logout_forgets_an_already_expired_key(httpx_mock, config_file: Path) -> None:
    write_user_config_file({"api_key": "sk_old"}, path=config_file)
    httpx_mock.add_response(url=KEY_URL, method="DELETE", status_code=401, json={"detail": "Invalid or expired API key"})
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == EXIT_SUCCESS
    assert "already expired" in strip_ansi(result.stdout)
    assert not config_file.exists()


def test_logout_keeps_a_permanent_key(httpx_mock, config_file: Path) -> None:
    write_user_config_file({"api_key": "sk_permanent"}, path=config_file)
    httpx_mock.add_response(url=KEY_URL, method="DELETE", status_code=409, json={"detail": "not a login key"})
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == EXIT_USAGE
    assert "was not created by `apiome login`" in strip_ansi(result.stderr)
    assert read_user_config_file(config_file)["api_key"] == "sk_permanent"


def test_logout_uses_the_saved_key_not_the_env_key(
    httpx_mock, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "sk_env")
    write_user_config_file({"api_key": "sk_saved"}, path=config_file)
    httpx_mock.add_response(url=KEY_URL, method="DELETE", status_code=204, match_headers={"X-API-Key": "sk_saved"})
    assert runner.invoke(app, ["logout"]).exit_code == EXIT_SUCCESS


def test_logout_when_not_signed_in(config_file: Path) -> None:
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Not signed in" in strip_ansi(result.stdout)
