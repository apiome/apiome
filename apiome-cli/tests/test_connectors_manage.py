"""Tests for ``apiome connectors list|add|show|sync|runs|items|remove`` (CDG-1.7 / #5958)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client.connectors import (
    parse_scope,
    read_credentials,
    refusal,
    run_outcome,
    run_rows,
    schedule_label,
    sync_exit_code,
)
from apiome_cli.commands import connectors as connectors_cmd
from apiome_cli.exit_codes import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    EXIT_SYNC_FAILED,
    EXIT_USAGE,
)
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000/v1/tenants/acme-corp"
_CONNECTORS = f"{_BASE}/connectors"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _connector(**extra: object) -> dict:
    return {
        "id": "c1",
        "kind": "kong-admin",
        "name": "Prod Kong",
        "baseUrl": "https://kong.example.com:8001",
        "scope": {},
        "refreshIntervalSeconds": 86400,
        "conflictPolicy": "hold-for-review",
        "status": "active",
        "hasCredentials": False,
        "syncable": True,
        "lastRunAt": None,
        **extra,
    }


def _run(status: str = "succeeded", **extra: object) -> dict:
    return {
        "id": "r1",
        "connectorId": "c1",
        "refreshSource": "connector",
        "status": status,
        "errorClass": None,
        "httpStatus": None,
        "errorMessage": None,
        "summary": {"imported": 2, "candidates": 3},
        **extra,
    }


def _refused(code: str, message: str, status: int) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "detail": {"code": code, "message": message},
            "error": {"message": "Request failed"},
        },
    )


# --- helpers ---------------------------------------------------------------------------


def test_parse_scope_inline_file_and_errors(tmp_path: Path) -> None:
    assert parse_scope(None) == {}
    assert parse_scope('{"region": "eu"}') == {"region": "eu"}
    scope_file = tmp_path / "scope.json"
    scope_file.write_text('{"regions": ["eu-west-1"]}', encoding="utf-8")
    assert parse_scope(f"@{scope_file}") == {"regions": ["eu-west-1"]}
    with pytest.raises(ValueError, match="JSON object"):
        parse_scope("[1]")
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_scope("{nope")
    with pytest.raises(ValueError, match="cannot read"):
        parse_scope(f"@{tmp_path / 'missing.json'}")


def test_read_credentials(tmp_path: Path) -> None:
    assert read_credentials(None) is None
    creds = tmp_path / "creds.json"
    creds.write_text('{"token": "s3cret"}', encoding="utf-8")
    assert read_credentials(str(creds)) == {"token": "s3cret"}
    assert read_credentials("-", '{"token": "x"}') == {"token": "x"}
    with pytest.raises(ValueError, match="non-empty"):
        read_credentials("-", "{}")
    with pytest.raises(ValueError, match="must be a string"):
        read_credentials("-", '{"token": 1}')


def test_refusal_shapes() -> None:
    assert refusal(_refused("connector-check-failed", "No.", 422)) == (
        "No.",
        "connector-check-failed",
    )
    assert refusal(httpx.Response(404, json={"detail": "Gone."})) == ("Gone.", None)
    validation = httpx.Response(
        422, json={"detail": [{"loc": ["body", "scope"], "msg": "bad"}]}
    )
    assert refusal(validation) == ("scope: bad", None)


def test_outcomes_and_exit_codes() -> None:
    assert run_outcome(_run()) == "Imported 2 of 3"
    assert run_outcome(_run(summary={"imported": 0, "candidates": 4})) == (
        "Unchanged (4 checked)"
    )
    assert run_outcome(_run("failed", errorClass="auth", httpStatus=401)) == (
        "Failed: auth (HTTP 401)"
    )
    assert run_outcome({"source": "git", "status": "succeeded"}) == "Refreshed"
    assert sync_exit_code(_run()) == EXIT_SUCCESS
    assert sync_exit_code(_run("failed")) == EXIT_SYNC_FAILED
    assert schedule_label(None) == "default"
    assert schedule_label(86400) == "every 1d"
    assert schedule_label(5400) == "every 90m"


def test_run_rows_name_git_and_connector_runs() -> None:
    rows = run_rows(
        [
            {"id": "a", "source": "connector", "connectorName": "Prod Kong"},
            {
                "id": "b",
                "source": "git",
                "repositoryName": "acme/apis",
                "branch": "main",
                "path": "openapi.yaml",
                "status": "succeeded",
            },
        ]
    )
    assert rows[0]["what"] == "Prod Kong"
    assert rows[1]["what"] == "acme/apis main openapi.yaml"


# --- commands --------------------------------------------------------------------------


def test_list_table_and_json(httpx_mock: HTTPXMock) -> None:
    body = {"connectors": [_connector()], "kinds": [], "syncableKinds": []}
    httpx_mock.add_response(url=_CONNECTORS, json=body)
    result = runner.invoke(app, ["connectors", "list"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "Prod Kong" in out and "every 1d" in out

    httpx_mock.add_response(url=_CONNECTORS, json=body)
    result = runner.invoke(app, ["connectors", "list", "--format", "json"])
    assert json.loads(result.stdout) == body


def test_add_dry_runs_then_creates_and_stores_credentials(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    creds = tmp_path / "creds.json"
    creds.write_text('{"token": "s3cret"}', encoding="utf-8")
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/dry-run",
        method="POST",
        json={"itemCount": 3, "items": [], "truncated": False, "findings": []},
    )
    httpx_mock.add_response(
        url=_CONNECTORS, method="POST", status_code=201, json=_connector()
    )
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/c1/credentials", method="PUT", json={"ok": True}
    )
    result = runner.invoke(
        app,
        [
            "connectors",
            "add",
            "--kind",
            "kong-admin",
            "--name",
            "Prod Kong",
            "--base-url",
            "https://kong.example.com:8001",
            "--scope",
            '{"workspace": "default"}',
            "--credentials-file",
            str(creds),
            "--refresh-interval",
            "3600",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Dry run: 3 APIs would sync." in result.stderr
    assert json.loads(result.stdout)["hasCredentials"] is True
    assert "s3cret" not in result.output

    dry, create, put = httpx_mock.get_requests()
    assert json.loads(dry.content) == {
        "kind": "kong-admin",
        "scope": {"workspace": "default"},
        "baseUrl": "https://kong.example.com:8001",
        "credentials": {"token": "s3cret"},
    }
    created = json.loads(create.content)
    assert "credentials" not in created
    assert created["refreshIntervalSeconds"] == 3600
    assert created["conflictPolicy"] == "hold-for-review"
    assert json.loads(put.content) == {"credentials": {"token": "s3cret"}}


def test_add_a_registry_crawl_connector(httpx_mock: HTTPXMock) -> None:
    """MFI-18.5: a ``registry`` connector names its crawl in the scope."""
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/dry-run",
        method="POST",
        json={"itemCount": 2, "items": [], "truncated": False, "findings": []},
    )
    httpx_mock.add_response(
        url=_CONNECTORS,
        method="POST",
        status_code=201,
        json=_connector(kind="registry"),
    )
    result = runner.invoke(
        app,
        [
            "connectors",
            "add",
            "--kind",
            "registry",
            "--name",
            "Schemas",
            "--base-url",
            "https://xreg.example.com/reg",
            "--scope",
            '{"protocol": "xregistry", "groups": ["orders"]}',
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    dry, create = httpx_mock.get_requests()
    assert json.loads(dry.content)["kind"] == "registry"
    assert json.loads(create.content)["scope"] == {
        "protocol": "xregistry",
        "groups": ["orders"],
    }


def test_add_failing_dry_run_saves_nothing(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/dry-run",
        method="POST",
        status_code=422,
        json={
            "detail": {
                "code": "connector-check-failed",
                "message": "The dry run failed (auth, HTTP 401): invalid token",
            }
        },
    )
    result = runner.invoke(
        app,
        ["connectors", "add", "--kind", "kong-konnect", "--name", "K", "--scope", "{}"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "The dry run failed (auth, HTTP 401): invalid token" in result.stderr
    assert len(httpx_mock.get_requests()) == 1


def test_add_rejects_bad_options_before_calling() -> None:
    result = runner.invoke(
        app, ["connectors", "add", "--kind", "url", "--name", "x", "--scope", "[]"]
    )
    assert result.exit_code == EXIT_USAGE
    result = runner.invoke(
        app,
        ["connectors", "add", "--kind", "url", "--name", "x", "--conflict-policy", "x"],
    )
    assert result.exit_code == EXIT_USAGE


def test_add_without_dry_run(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=_CONNECTORS, method="POST", status_code=201, json=_connector()
    )
    result = runner.invoke(
        app,
        ["connectors", "add", "--kind", "kong-admin", "--name", "P", "--no-dry-run"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Added connector Prod Kong (c1)." in result.stdout


def test_show(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{_CONNECTORS}/c1", json=_connector())
    result = runner.invoke(app, ["connectors", "show", "c1", "--format", "json"])
    assert json.loads(result.stdout)["id"] == "c1"


def test_show_unknown_connector(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/nope",
        status_code=404,
        json={"detail": {"code": "connector-not-found", "message": "No such."}},
    )
    result = runner.invoke(app, ["connectors", "show", "nope"])
    assert result.exit_code == EXIT_USAGE
    assert "No such." in result.stderr


@pytest.mark.parametrize(
    ("status", "wait", "expected"),
    [
        ("succeeded", True, EXIT_SUCCESS),
        ("failed", True, EXIT_SYNC_FAILED),
        ("failed", False, EXIT_SUCCESS),
    ],
)
def test_sync_exit_code_follows_the_run_with_wait(
    httpx_mock: HTTPXMock, status: str, wait: bool, expected: int
) -> None:
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/c1/sync",
        method="POST",
        json=_run(status, errorClass="auth" if status == "failed" else None),
    )
    args = ["connectors", "sync", "c1"] + (["--wait"] if wait else [])
    result = runner.invoke(app, args)
    assert result.exit_code == expected, result.output


def test_sync_wait_follows_a_running_sync(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connectors_cmd.time, "sleep", lambda _s: None)
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/c1/sync",
        method="POST",
        status_code=409,
        json={"detail": {"code": "connector-sync-running", "message": "Running."}},
    )
    runs_url = f"{_CONNECTORS}/c1/runs?limit=1"
    httpx_mock.add_response(url=runs_url, json={"runs": [_run("running")]})
    httpx_mock.add_response(
        url=runs_url, json={"runs": [_run("failed", errorClass="timeout")]}
    )
    result = runner.invoke(app, ["connectors", "sync", "c1", "--wait"])
    assert result.exit_code == EXIT_SYNC_FAILED, result.output
    assert "Failed: timeout" in result.stdout


def test_sync_running_without_wait_is_refused(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/c1/sync",
        method="POST",
        status_code=409,
        json={"detail": {"code": "connector-sync-running", "message": "Running."}},
    )
    result = runner.invoke(app, ["connectors", "sync", "c1"])
    assert result.exit_code == EXIT_USAGE
    assert "Running." in result.stderr


def test_sync_wait_times_out(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connectors_cmd.time, "sleep", lambda _s: None)
    clock = iter([0.0, 0.0, 5.0])
    monkeypatch.setattr(connectors_cmd.time, "monotonic", lambda: next(clock))
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/c1/sync",
        method="POST",
        status_code=409,
        json={"detail": {"code": "connector-sync-running", "message": "Running."}},
    )
    runs_url = f"{_CONNECTORS}/c1/runs?limit=1"
    httpx_mock.add_response(
        url=runs_url, json={"runs": [_run("running")]}, is_reusable=True
    )
    result = runner.invoke(
        app, ["connectors", "sync", "c1", "--wait", "--timeout", "2"]
    )
    assert result.exit_code == EXIT_ERROR
    assert "did not finish within 2s" in result.stderr


def test_runs_ledger_with_filters(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/refresh-runs?connector=c1&source=connector&limit=10",
        json={"runs": [{"id": "r1", "source": "connector", "status": "succeeded"}]},
    )
    result = runner.invoke(
        app,
        ["connectors", "runs", "c1", "--source", "connector", "--limit", "10"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "r1" in strip_ansi(result.output)


def test_runs_rejects_unknown_source() -> None:
    result = runner.invoke(app, ["connectors", "runs", "--source", "svn"])
    assert result.exit_code == EXIT_USAGE


def test_items(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_CONNECTORS}/c1/items?status=imported&limit=50",
        json={
            "items": [
                {
                    "remoteId": "svc-orders",
                    "remoteName": "orders",
                    "status": "imported",
                    "catalogItemId": "cat-1",
                }
            ],
            "total": 1,
        },
    )
    result = runner.invoke(app, ["connectors", "items", "c1", "--status", "imported"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "cat-1" in strip_ansi(result.output)


def test_remove_needs_yes_when_not_interactive() -> None:
    result = runner.invoke(app, ["connectors", "remove", "c1"])
    assert result.exit_code != EXIT_SUCCESS
    assert "--yes" in result.output


def test_remove(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{_CONNECTORS}/c1", method="DELETE", status_code=204)
    result = runner.invoke(app, ["connectors", "remove", "c1", "--yes"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Removed connector c1." in result.output
