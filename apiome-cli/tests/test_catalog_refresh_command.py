"""Tests for ``apiome catalog refresh`` and ``apiome catalog refresh-policy`` (MFI-31.1 / #4398)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client.catalog_refresh import refresh_body, refresh_rows
from apiome_cli.exit_codes import (
    EXIT_ERROR,
    EXIT_REFRESH_CHECK_FAILED,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_ITEM = "11111111-2222-4333-8444-555555555555"
_BASE = "http://localhost:8000/v1/catalog/acme-corp"
_REFRESH = f"{_BASE}/{_ITEM}/refresh"
_SECRET = "s3cret-token-value"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _refresh(**extra: object) -> dict:
    body = {
        "itemId": _ITEM,
        "configured": True,
        "cadence": "daily",
        "adapter": "graphql",
        "endpoint": "https://api.example.com/graphql",
        "options": {},
        "authType": "bearer",
        "hasCredential": True,
        "status": "unchanged",
        "lastCheckedAt": "2026-10-27T10:00:00+00:00",
        "lastError": None,
        "lastFingerprint": "fp-1",
        "consecutiveFailures": 0,
        "nextCheckAt": "2026-10-28T10:00:00+00:00",
        "tenantEnabled": True,
    }
    body.update(extra)
    return body


# --- pure helpers ----------------------------------------------------------------------


def test_body_keeps_the_credential_by_default() -> None:
    body = refresh_body(
        cadence="daily", adapter="graphql", endpoint=" https://x.example.com ", secure=True,
        auth_type=None, credentials=None,
    )
    assert body == {"cadence": "daily", "adapter": "graphql", "endpoint": "https://x.example.com", "options": {}}


def test_body_clears_with_none_and_replaces_with_fields() -> None:
    cleared = refresh_body(cadence="daily", adapter="grpc", endpoint="h:443", secure=True, auth_type="none", credentials=None)
    assert cleared["credential"] is None and cleared["options"] == {"secure": True}
    replaced = refresh_body(
        cadence="hourly", adapter="graphql", endpoint="https://x", secure=False,
        auth_type="bearer", credentials={"token": "t"},
    )
    assert replaced["credential"] == {"authType": "bearer", "payload": {"token": "t"}}


@pytest.mark.parametrize(
    ("auth_type", "credentials", "message"),
    [("bearer", None, "needs --credentials-file"), (None, {"token": "t"}, "needs --auth-type")],
)
def test_body_refuses_half_a_credential(auth_type, credentials, message) -> None:
    with pytest.raises(ValueError, match=message):
        refresh_body(cadence="daily", adapter="graphql", endpoint="https://x", secure=False,
                     auth_type=auth_type, credentials=credentials)


def test_rows_never_carry_a_secret_and_show_a_failure() -> None:
    rows = {r["field"]: r["value"] for r in refresh_rows(_refresh(status="failed", lastError="boom", consecutiveFailures=2))}
    assert rows["Credential"] == "bearer (stored)"
    assert rows["Last error"] == "boom" and rows["Failures in a row"] == "2"
    assert refresh_rows({"configured": False}) == [{"field": "Refresh", "value": "Not set up (off)"}]


def test_rows_say_when_the_workspace_switched_it_off() -> None:
    rows = refresh_rows(_refresh(tenantEnabled=False))
    assert rows[-1] == {"field": "Workspace", "value": "catalog refresh is switched off"}


# --- commands --------------------------------------------------------------------------


def test_show_prints_the_setting(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_REFRESH, json=_refresh())
    result = runner.invoke(app, ["catalog", "refresh", "show", _ITEM])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "https://api.example.com/graphql" in out and "daily" in out


def test_show_json(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_REFRESH, json=_refresh())
    result = runner.invoke(app, ["catalog", "refresh", "show", _ITEM, "--format", "json"])
    assert json.loads(result.output)["cadence"] == "daily"


def test_set_reads_the_credential_from_a_file_never_the_command_line(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"token": _SECRET}))
    httpx_mock.add_response(method="PUT", url=_REFRESH, json=_refresh())
    result = runner.invoke(
        app,
        ["catalog", "refresh", "set", _ITEM, "--endpoint", "https://api.example.com/graphql",
         "--cadence", "hourly", "--auth-type", "bearer", "--credentials-file", str(creds)],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent == {
        "cadence": "hourly",
        "adapter": "graphql",
        "endpoint": "https://api.example.com/graphql",
        "options": {},
        "credential": {"authType": "bearer", "payload": {"token": _SECRET}},
    }
    assert _SECRET not in result.output


def test_set_grpc_with_tls_and_stdin_credentials(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="PUT", url=_REFRESH, json=_refresh(adapter="grpc", endpoint="g:443"))
    result = runner.invoke(
        app,
        ["catalog", "refresh", "set", _ITEM, "--adapter", "grpc", "--endpoint", "g:443", "--tls",
         "--auth-type", "header", "--credentials-file", "-"],
        input=json.dumps({"name": "X-Key", "value": "v"}),
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent["options"] == {"secure": True}
    assert sent["credential"] == {"authType": "header", "payload": {"name": "X-Key", "value": "v"}}


def test_set_refuses_an_unknown_cadence_without_calling_rest(httpx_mock: HTTPXMock) -> None:
    result = runner.invoke(app, ["catalog", "refresh", "set", _ITEM, "--endpoint", "https://x", "--cadence", "monthly"])
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []


def test_set_reports_a_rest_refusal(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="PUT", url=_REFRESH, status_code=422,
        json={"detail": {"code": "adapter-not-refreshable", "message": "Adapter 'openapi' cannot be refreshed."}},
    )
    result = runner.invoke(app, ["catalog", "refresh", "set", _ITEM, "--adapter", "openapi", "--endpoint", "https://x"])
    assert result.exit_code == EXIT_USAGE
    assert "cannot be refreshed" in strip_ansi(result.output)


def test_check_exits_zero_when_the_check_ran(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=f"{_REFRESH}/check", json=_refresh(status="changed"))
    result = runner.invoke(app, ["catalog", "refresh", "check", _ITEM])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "changed" in strip_ansi(result.output)


def test_check_exits_seven_when_the_check_failed(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{_REFRESH}/check",
        json=_refresh(status="failed", lastError="connection refused", consecutiveFailures=1),
    )
    result = runner.invoke(app, ["catalog", "refresh", "check", _ITEM])
    assert result.exit_code == EXIT_REFRESH_CHECK_FAILED
    assert "connection refused" in strip_ansi(result.output)


def test_check_reports_a_disabled_workspace(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{_REFRESH}/check", status_code=409,
        json={"detail": {"code": "refresh-disabled", "message": "Catalog refresh is switched off for this workspace."}},
    )
    result = runner.invoke(app, ["catalog", "refresh", "check", _ITEM])
    assert result.exit_code == EXIT_USAGE
    assert "switched off" in strip_ansi(result.output)


def test_check_unreachable_server_is_exit_one(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=f"{_REFRESH}/check", status_code=500, json={"detail": "boom"})
    result = runner.invoke(app, ["catalog", "refresh", "check", _ITEM])
    assert result.exit_code == EXIT_ERROR


def test_off_deletes_with_yes(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="DELETE", url=_REFRESH, status_code=204)
    result = runner.invoke(app, ["catalog", "refresh", "off", _ITEM, "--yes"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Removed the refresh setting" in result.output


def test_policy_show_and_set(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=f"{_BASE}/refresh-policy", json={"enabled": True})
    httpx_mock.add_response(method="PUT", url=f"{_BASE}/refresh-policy", json={"enabled": False})
    assert "Catalog refresh: on" in runner.invoke(app, ["catalog", "refresh-policy", "show"]).output
    result = runner.invoke(app, ["catalog", "refresh-policy", "set", "--disabled"])
    assert "Catalog refresh: off" in result.output
    assert json.loads(httpx_mock.get_requests()[-1].content) == {"enabled": False}
