"""``apiome versions freeze`` (CLI 4.7, #3214).

The output rules (:mod:`apiome_cli.version_freeze`) and the command against a mocked REST API:
the server's dry run drives the preview (SHA-256, size, counts); the user confirms before
freezing; ``--json`` prints ``{frozen, sha256, size_bytes, snapshot_url, …}``; ``--unfreeze``
stops with exit 6 once the snapshot has been downloaded unless ``--force-unfreeze``.
"""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SNAPSHOT_DOWNLOADED, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.version_freeze import (
    downloaded_hint,
    json_result,
    render_freeze_preview,
    render_frozen,
    render_unfreeze_preview,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V21 = "22222222-2222-4222-8222-222222222222"
_FREEZE = f"{_HOST}/versions/acme/{_PROJECT}/{_V21}/freeze-schema"
_SHA = "7f2c" + "0" * 56 + "a041"

_PLAN = {
    "versionId": _V21,
    "versionLabel": "2.1.0",
    "frozen": False,
    "dryRun": True,
    "sha256": _SHA,
    "sizeBytes": 131379,
    "snapshotUrl": "/v1/schema/acme/payments-api/2.1.0",
    "classCount": 24,
    "propertyCount": 142,
    "pathCount": 18,
    "downloadCount": 0,
}
_FROZEN = {**_PLAN, "frozen": True, "dryRun": False, "frozenAt": "2026-10-16T12:00:00Z"}


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the confirmation runs."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


def _resolve(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme/{_PROJECT}/by-version/2.1.0", json={"id": _V21}, is_optional=True
    )


def _mock_freeze(httpx_mock) -> None:
    _resolve(httpx_mock)

    def respond(request: httpx.Request) -> httpx.Response:
        dry = json.loads(request.content).get("dryRun")
        return httpx.Response(200, json=_PLAN if dry else _FROZEN)

    httpx_mock.add_callback(respond, method="POST", url=_FREEZE, is_optional=True, is_reusable=True)


def _posts(httpx_mock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests() if r.method == "POST"]


# --- rules ----------------------------------------------------------------------------------


def test_the_preview_lists_counts_sha_and_size() -> None:
    assert render_freeze_preview(_PLAN) == "\n".join(
        [
            "Schema snapshot for 2.1.0:",
            "  Classes:    24",
            "  Properties: 142",
            "  Paths:      18",
            f"  SHA-256:    {_SHA}",
            "  Size:       128.3 KiB",
            "",
            "After freeze, edits to 2.1.0's classes, properties and paths will NOT alter the",
            "published schema at /v1/schema/acme/payments-api/2.1.0.",
        ]
    )


def test_the_frozen_line_names_the_snapshot_url() -> None:
    assert (
        render_frozen(_FROZEN)
        == f"✔ Frozen. Snapshot stored at /v1/schema/acme/payments-api/2.1.0 (SHA-256 {_SHA})"
    )


def test_the_json_shape() -> None:
    shaped = json_result(_FROZEN)
    assert {k: shaped[k] for k in ("frozen", "sha256", "size_bytes", "snapshot_url")} == {
        "frozen": True,
        "sha256": _SHA,
        "size_bytes": 131379,
        "snapshot_url": "/v1/schema/acme/payments-api/2.1.0",
    }
    assert (shaped["classes"], shaped["properties"], shaped["paths"]) == (24, 142, 18)


def test_the_unfreeze_preview_shows_downloads() -> None:
    assert "  Downloads:  3" in render_unfreeze_preview({**_FROZEN, "downloadCount": 3})
    assert "downloaded 3 time(s)" in downloaded_hint({**_FROZEN, "downloadCount": 3})


# --- freeze ---------------------------------------------------------------------------------


def test_confirming_freezes(httpx_mock, interactive) -> None:
    _mock_freeze(httpx_mock)
    result = runner.invoke(app, ["versions", "freeze", "payments-api", "v2.1.0"], env=_ENV, input="y\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Schema snapshot for 2.1.0:" in result.stderr
    assert "✔ Frozen. Snapshot stored at /v1/schema/acme/payments-api/2.1.0" in result.stdout
    assert _posts(httpx_mock) == [{"dryRun": True}, {"dryRun": False}]


def test_declining_freezes_nothing(httpx_mock, interactive) -> None:
    _mock_freeze(httpx_mock)
    result = runner.invoke(app, ["versions", "freeze", "payments-api", "2.1.0"], env=_ENV, input="n\n")
    assert result.exit_code == EXIT_SUCCESS
    assert _posts(httpx_mock) == [{"dryRun": True}]


def test_without_a_terminal_it_refuses_unless_yes(httpx_mock) -> None:
    _mock_freeze(httpx_mock)
    result = runner.invoke(app, ["versions", "freeze", "payments-api", "2.1.0"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "--yes" in result.stderr
    assert _posts(httpx_mock) == [{"dryRun": True}]


def test_json_prints_the_snapshot(httpx_mock) -> None:
    _mock_freeze(httpx_mock)
    result = runner.invoke(app, ["--json", "versions", "freeze", "payments-api", "2.1.0", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(result.stdout)
    assert body["frozen"] is True and body["sha256"] == _SHA and body["size_bytes"] == 131379
    assert body["snapshot_url"] == "/v1/schema/acme/payments-api/2.1.0"


def test_an_already_frozen_version_reports_the_server_message(httpx_mock) -> None:
    _resolve(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=_FREEZE,
        status_code=409,
        json={"detail": {"code": "already_frozen", "message": "2.1.0 is already frozen.", "sha256": _SHA}},
    )
    result = runner.invoke(app, ["versions", "freeze", "payments-api", "2.1.0", "--yes"], env=_ENV)
    assert result.exit_code != EXIT_SUCCESS
    assert "already frozen" in result.stderr


# --- unfreeze -------------------------------------------------------------------------------


def _mock_status(httpx_mock, **status) -> None:
    _resolve(httpx_mock)
    httpx_mock.add_response(method="GET", url=_FREEZE, json={**_FROZEN, **status})


def test_unfreeze_without_downloads(httpx_mock) -> None:
    _mock_status(httpx_mock, downloadCount=0)
    httpx_mock.add_response(method="DELETE", url=_FREEZE, json={**_FROZEN, "frozen": False})
    result = runner.invoke(
        app, ["versions", "freeze", "payments-api", "2.1.0", "--unfreeze", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "✔ Unfrozen 2.1.0." in result.stdout
    delete = [r for r in httpx_mock.get_requests() if r.method == "DELETE"][0]
    assert "force" not in delete.url.params


def test_unfreeze_after_downloads_exits_6(httpx_mock) -> None:
    _mock_status(httpx_mock, downloadCount=3)
    result = runner.invoke(
        app, ["versions", "freeze", "payments-api", "2.1.0", "--unfreeze", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SNAPSHOT_DOWNLOADED
    assert "--force-unfreeze" in result.stderr
    assert not [r for r in httpx_mock.get_requests() if r.method == "DELETE"]


def test_force_unfreeze_passes_force(httpx_mock) -> None:
    _mock_status(httpx_mock, downloadCount=3)
    httpx_mock.add_response(method="DELETE", url=f"{_FREEZE}?force=true", json={**_FROZEN, "frozen": False})
    result = runner.invoke(
        app, ["--json", "versions", "freeze", "payments-api", "2.1.0", "--force-unfreeze", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["frozen"] is False


def test_a_download_between_status_and_delete_still_exits_6(httpx_mock) -> None:
    _mock_status(httpx_mock, downloadCount=0)
    httpx_mock.add_response(
        method="DELETE",
        url=_FREEZE,
        status_code=409,
        json={"detail": {"code": "snapshot_downloaded", "message": "…", "download_count": 1}},
    )
    result = runner.invoke(
        app, ["versions", "freeze", "payments-api", "2.1.0", "--unfreeze", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SNAPSHOT_DOWNLOADED
    assert "downloaded 1 time(s)" in result.stderr


def test_a_non_admin_force_is_refused_by_the_server(httpx_mock) -> None:
    _mock_status(httpx_mock, downloadCount=3)
    httpx_mock.add_response(
        method="DELETE",
        url=f"{_FREEZE}?force=true",
        status_code=403,
        json={
            "detail": {
                "code": "force_unfreeze_requires_admin",
                "message": "Only a tenant administrator can force an unfreeze.",
            }
        },
    )
    result = runner.invoke(
        app, ["versions", "freeze", "payments-api", "2.1.0", "--force-unfreeze", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "tenant administrator" in result.stderr


def test_unfreezing_an_unfrozen_version_is_a_usage_error(httpx_mock) -> None:
    _resolve(httpx_mock)
    httpx_mock.add_response(method="GET", url=_FREEZE, json={**_PLAN, "frozen": False})
    result = runner.invoke(
        app, ["versions", "freeze", "payments-api", "2.1.0", "--unfreeze", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "is not frozen" in result.stderr
