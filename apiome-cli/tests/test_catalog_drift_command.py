"""Tests for ``apiome catalog drift`` and ``apiome catalog drift-alerts`` (MFI-31.3 / #4400)."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client.catalog_drift import (
    alerts_body,
    alerts_rows,
    change_rows,
    event_rows,
)
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_ITEM = "11111111-2222-4333-8444-555555555555"
_EVENT = "55555555-5555-4555-8555-555555555555"
_BASE = "http://localhost:8000/v1/catalog/acme-corp"
_ALERTS = f"{_BASE}/drift-notifications"
_EVENTS = f"{_BASE}/{_ITEM}/drift"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _settings(**extra: object) -> dict:
    body = {
        "notifyBreaking": True,
        "notifyDangerous": True,
        "notifySafe": False,
        "delivery": "immediate",
        "breakingImmediate": True,
        "emailEnabled": False,
        "configured": False,
        "updatedAt": None,
        "lastDigestAt": None,
    }
    body.update(extra)
    return body


def _event(**extra: object) -> dict:
    body = {
        "eventId": _EVENT,
        "severity": "breaking",
        "versionId": "v-2",
        "versionLabel": "2026-10-28T12:00Z",
        "parentVersionLabel": "1.0.0",
        "changeCount": 2,
        "counts": {"safe": 1, "dangerous": 0, "breaking": 1},
        "trigger": "sweep",
        "notification": "sent",
        "dismissedAt": None,
        "changes": [
            {
                "severity": "breaking",
                "key": "Order.total",
                "rationale": "field 'Order.total' was removed",
            },
            {"severity": "safe", "key": "Query.orders", "rationale": "added"},
        ],
    }
    body.update(extra)
    return body


# --- pure helpers ----------------------------------------------------------------------------


def test_alerts_body_keeps_unspecified_settings():
    body = alerts_body(
        _settings(notifySafe=True), delivery="daily_digest", notifyBreaking=None
    )
    assert body == {
        "notifyBreaking": True,
        "notifyDangerous": True,
        "notifySafe": True,
        "delivery": "daily_digest",
        "breakingImmediate": True,
        "emailEnabled": False,
    }


def test_alerts_body_rejects_an_unknown_delivery():
    with pytest.raises(ValueError, match="immediate, daily_digest"):
        alerts_body(_settings(), delivery="hourly")


def test_alerts_rows_say_defaults_and_email_is_not_sent():
    rows = {row["field"]: row["value"] for row in alerts_rows(_settings())}
    assert rows["Notify breaking"] == "yes" and rows["Notify safe"] == "no"
    assert rows["Email opt-in (not sent yet)"] == "no"
    assert rows["Source"] == "defaults (never saved)"


def test_event_and_change_rows():
    [row] = event_rows([_event()])
    assert row["versions"] == "1.0.0 → 2026-10-28T12:00Z"
    assert row["changes"] == "2 (1 breaking, 0 dangerous)"
    assert row["state"] == "open"
    assert change_rows(_event())[0] == {
        "severity": "breaking",
        "key": "Order.total",
        "rationale": "field 'Order.total' was removed",
    }


# --- commands --------------------------------------------------------------------------------


def test_drift_list_prints_events_and_changes(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=_EVENTS, json={"events": [_event()]})
    result = runner.invoke(app, ["catalog", "drift", "list", _ITEM, "--changes"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "breaking" in out and "Order.total" in out and "2026-10-28T12:00Z" in out


def test_drift_list_empty(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=_EVENTS, json={"events": []})
    result = runner.invoke(app, ["catalog", "drift", "list", _ITEM])
    assert result.exit_code == EXIT_SUCCESS
    assert "No drift recorded" in strip_ansi(result.output)


def test_drift_dismiss(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{_EVENTS}/{_EVENT}/dismiss",
        json=_event(dismissedAt="2026-10-28T13:00:00+00:00"),
    )
    result = runner.invoke(app, ["catalog", "drift", "dismiss", _ITEM, _EVENT])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert f"Dismissed drift {_EVENT}" in strip_ansi(result.output)


def test_drift_dismiss_unknown_event_exits_2(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{_EVENTS}/{_EVENT}/dismiss",
        status_code=404,
        json={"detail": "Drift event not found"},
    )
    result = runner.invoke(app, ["catalog", "drift", "dismiss", _ITEM, _EVENT])
    assert result.exit_code == EXIT_USAGE


def test_alerts_show_json(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=_ALERTS, json=_settings())
    result = runner.invoke(app, ["catalog", "drift-alerts", "show", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.output)["delivery"] == "immediate"


def test_alerts_set_merges_with_the_current_settings(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", url=_ALERTS, json=_settings(notifyDangerous=False)
    )
    httpx_mock.add_response(
        method="PUT",
        url=_ALERTS,
        json=_settings(delivery="daily_digest", configured=True),
    )
    result = runner.invoke(
        app,
        [
            "catalog",
            "drift-alerts",
            "set",
            "--delivery",
            "daily_digest",
            "--breaking-in-digest",
            "--safe",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    sent = json.loads(httpx_mock.get_requests(method="PUT")[0].content)
    assert sent == {
        "notifyBreaking": True,
        "notifyDangerous": False,
        "notifySafe": True,
        "delivery": "daily_digest",
        "breakingImmediate": False,
        "emailEnabled": False,
    }


def test_alerts_set_rejects_a_bad_delivery(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=_ALERTS, json=_settings())
    result = runner.invoke(
        app, ["catalog", "drift-alerts", "set", "--delivery", "hourly"]
    )
    assert result.exit_code == EXIT_USAGE
