"""Tests for ``apiome connectors shadow-report`` (CDG-1.6 / #5957) against mocked REST."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client.shadow_report import (
    failing_categories,
    parse_fail_on,
    table_rows,
)
from apiome_cli.exit_codes import EXIT_SHADOW_FOUND, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_URL = "http://localhost:8000/v1/tenants/acme-corp/shadow-report"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _row(name: str, **extra: object) -> dict:
    return {
        "itemId": f"i-{name}",
        "connectorId": "c1",
        "connectorName": "Prod Kong",
        "remoteId": name,
        "name": name,
        "environment": "prod",
        "hosts": [f"{name}.example.com"],
        "basePath": None,
        **extra,
    }


def _report(**overrides: object) -> dict:
    report = {
        "generatedAt": "2026-10-18T12:00:00Z",
        "filters": {"connector": None, "environment": None},
        "connectors": [
            {"id": "c1", "name": "Prod Kong", "status": "active", "stale": False}
        ],
        "stale": [],
        "summary": {
            "shadow": 2,
            "possibleMatches": 1,
            "undeployed": 0,
            "drift": 0,
            "ignored": 0,
        },
        "shadow": [_row("billing"), _row("metrics")],
        "possibleMatches": [
            _row(
                "orders",
                basePath="/v2",
                match={
                    "tier": "host",
                    "confidence": 0.9,
                    "target": {"name": "Orders API"},
                },
            )
        ],
        "undeployed": [],
        "drift": [],
        "ignored": [],
    }
    report.update(overrides)
    return report


def test_the_table_lists_every_section_and_exits_zero(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_URL, json=_report())
    result = runner.invoke(app, ["connectors", "shadow-report"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert (
        "Shadow APIs: shadow 2, possible-matches 1, undeployed 0, drift 0, ignored 0"
        in out
    )
    assert "billing" in out and "Orders API (host, 90%)" in out
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "test-key"


def test_filters_are_sent_as_query_parameters(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET", url=f"{_URL}?connector=c1&environment=prod", json=_report()
    )
    result = runner.invoke(
        app,
        [
            "connectors",
            "shadow-report",
            "--connector",
            "c1",
            "--environment",
            "prod",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.output)["summary"]["shadow"] == 2


@pytest.mark.parametrize(
    ("fail_on", "code"),
    [
        ("shadow", EXIT_SHADOW_FOUND),
        ("drift", EXIT_SUCCESS),
        ("shadow,drift", EXIT_SHADOW_FOUND),
        ("undeployed,drift", EXIT_SUCCESS),
        ("possible-matches", EXIT_SHADOW_FOUND),
    ],
)
def test_fail_on_exits_non_zero_only_for_named_categories(
    httpx_mock: HTTPXMock, fail_on: str, code: int
) -> None:
    httpx_mock.add_response(method="GET", url=_URL, json=_report())
    result = runner.invoke(
        app, ["connectors", "shadow-report", "--format", "json", "--fail-on", fail_on]
    )
    assert result.exit_code == code, result.output


def test_an_unknown_fail_on_category_is_a_usage_error() -> None:
    result = runner.invoke(
        app, ["connectors", "shadow-report", "--fail-on", "shadow,ghosts"]
    )
    assert result.exit_code == EXIT_USAGE
    assert "ghosts" in strip_ansi(result.output)


def test_a_stale_inventory_is_reported_on_stderr(httpx_mock: HTTPXMock) -> None:
    stale = [
        {
            "connectorId": "c1",
            "message": "Inventory stale since 2026-10-17T09:30:00Z: the last sync failed.",
        }
    ]
    httpx_mock.add_response(
        method="GET",
        url=_URL,
        json=_report(
            stale=stale, shadow=[], summary={"shadow": 0, "possibleMatches": 0}
        ),
    )
    result = runner.invoke(app, ["connectors", "shadow-report", "--fail-on", "shadow"])
    assert result.exit_code == EXIT_SUCCESS
    assert "warning: Inventory stale since 2026-10-17T09:30:00Z" in strip_ansi(
        result.output
    )


def test_a_rejected_request_exits_with_usage(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{_URL}?connector=nope",
        status_code=404,
        json={"detail": {"code": "connector-not-found"}},
    )
    result = runner.invoke(app, ["connectors", "shadow-report", "--connector", "nope"])
    assert result.exit_code == EXIT_USAGE


def test_helpers() -> None:
    assert parse_fail_on(" Drift , shadow,drift ") == ["shadow", "drift"]
    assert parse_fail_on(None) == []
    with pytest.raises(ValueError):
        parse_fail_on("nope")
    assert failing_categories(_report(), ["drift", "shadow"]) == ["shadow"]
    rows = table_rows(
        _report(
            undeployed=[
                {
                    "projectId": "p",
                    "name": "Idle",
                    "kind": "project",
                    "servers": ["https://idle.example.com"],
                }
            ],
            drift=[_row("pay", deployedRevision="r9", catalogRevision="r8")],
            ignored=[
                _row("quiet", ignored={"reason": "Health check", "reappeared": False})
            ],
        )
    )
    by_api = {row["api"]: row for row in rows}
    assert by_api["orders"]["served_at"] == "orders.example.com/v2"
    assert by_api["Idle"]["detail"] == "Project"
    assert by_api["pay"]["detail"] == "deployed r9 vs catalog r8"
    assert by_api["quiet"]["detail"] == "Health check"
