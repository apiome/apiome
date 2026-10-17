"""``apiome tags update`` (CLI 11.6, #3265) — move a tag to another version.

The rules (:mod:`apiome_cli.tag_update`) and the command against a mocked
``PATCH /v1/version-tags/{tenant}/{project}/{tag}``: the plan names the move and a best-effort blast
radius (mock requests, frozen-snapshot downloads, other tags) that never blocks when a figure is
unavailable; it asks unless ``--yes``; ``--dry-run`` sends no PATCH; ``--description`` sets or clears
the message; an immutable tag exits 6; ``--json`` returns the updated tag.
"""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_TAG_LOCKED, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.tag_update import (
    BlastRadius,
    TagLocked,
    check_movable,
    other_tags_on,
    render_plan,
    sum_mock_requests,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V20 = "20202020-2020-4020-8020-202020202020"
_V21 = "21212121-2121-4121-8121-212121212121"
_TAG_ID = "5ab1e000-0000-4000-8000-000000000001"
_TAGS_URL = f"{_HOST}/version-tags/acme/{_PROJECT}"
_TAG_URL = f"{_TAGS_URL}/{_TAG_ID}"
_FREEZE_20 = f"{_HOST}/versions/acme/{_PROJECT}/{_V20}/freeze-schema"
_USAGE = f"{_HOST}/mocks/acme/usage?days=7&project_slug=payments-api&version_label=2.0.0"

_STABLE = {
    "id": _TAG_ID,
    "name": "stable",
    "version_id": _V20,
    "target_version_string": "2.0.0",
    "message": "GA",
    "immutable": False,
}
_TAGS = [_STABLE, {"id": "t-prod", "name": "prod", "version_id": _V20, "target_version_string": "2.0.0"}]
_VERSIONS = [
    {"id": _V21, "version_id": "2.1.0", "created_at": "2026-10-01T00:00:00Z"},
    {"id": _V20, "version_id": "2.0.0", "created_at": "2026-09-01T00:00:00Z"},
]
_USAGE_BODY = {
    "monthlyRequestCount": 900,
    "monthlyQuota": 10000,
    "mockRps": 1.0,
    "dailyRollups": [{"requestCount": 15}, {"requestCount": 8}],
}


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the confirmation runs."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


def _mock(
    httpx_mock, *, tags=_TAGS, usage=_USAGE_BODY, freeze=None, usage_status=200, patch_status=200
) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(method="GET", url=_TAGS_URL, json=list(tags))
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=_VERSIONS, is_optional=True)
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/{_PROJECT}",
        json={"id": _PROJECT, "slug": "payments-api"},
        is_optional=True,
    )
    httpx_mock.add_response(url=_USAGE, status_code=usage_status, json=usage, is_optional=True)
    httpx_mock.add_response(
        method="GET", url=_FREEZE_20, json=freeze or {"frozen": True, "downloadCount": 4}, is_optional=True
    )
    httpx_mock.add_response(
        method="PATCH",
        url=_TAG_URL,
        status_code=patch_status,
        json={**_STABLE, "version_id": _V21}
        if patch_status == 200
        else {"detail": {"code": "TAG_IMMUTABLE"}},
        is_optional=True,
    )


def _patches(httpx_mock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests() if r.method == "PATCH"]


# --- rules ----------------------------------------------------------------------------------


def test_an_immutable_tag_is_refused() -> None:
    with pytest.raises(TagLocked, match="immutable"):
        check_movable({"name": "ga", "immutable": True})
    check_movable(_STABLE)


def test_mock_requests_are_summed_and_unreadable_is_none() -> None:
    assert sum_mock_requests(_USAGE_BODY) == 23
    assert sum_mock_requests({"dailyRollups": [{"request_count": 2}]}) == 2
    assert sum_mock_requests({"detail": "Mock services are disabled"}) is None
    assert sum_mock_requests(None) is None


def test_other_tags_on_the_version() -> None:
    assert other_tags_on(_TAGS, _V20, besides=_TAG_ID) == ["prod"]


def test_the_plan() -> None:
    text = render_plan(
        name="stable",
        from_label="2.0.0",
        to_label="2.1.0",
        moves=True,
        message="Promoted",
        message_changes=True,
        radius=BlastRadius(mock_requests=23, snapshot_downloads=4, other_tags=["prod"]),
    )
    assert text.splitlines() == [
        "Moving 'stable' from 2.0.0 → 2.1.0.",
        "Description: Promoted",
        "Affected consumers of 2.0.0 (best effort):",
        "  Mock requests, last 7 days: 23",
        "  Frozen-snapshot downloads:  4",
        "  Other tags on 2.0.0:        prod",
    ]


def test_unavailable_figures_are_labelled_not_fatal() -> None:
    text = render_plan(
        name="stable",
        from_label="2.0.0",
        to_label="2.1.0",
        moves=True,
        message=None,
        message_changes=False,
        radius=BlastRadius(mock_requests=None, snapshot_downloads=-1, other_tags=[]),
    )
    assert "Mock requests, last 7 days: unavailable" in text
    assert "Frozen-snapshot downloads:  not frozen" in text
    assert "Other tags on 2.0.0:        none" in text


# --- the command ----------------------------------------------------------------------------


def test_confirming_moves_the_tag(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "v2.1.0"], env=_ENV, input="y\n"
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Moving 'stable' from 2.0.0 → 2.1.0." in result.stderr
    assert "Mock requests, last 7 days: 23" in result.stderr
    assert "✔ Tag 'stable' now points to 2.1.0." in result.stdout
    assert _patches(httpx_mock) == [{"version_id": _V21}]


def test_declining_changes_nothing(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0"], env=_ENV, input="n\n"
    )
    assert result.exit_code == EXIT_SUCCESS
    assert _patches(httpx_mock) == []


def test_without_a_terminal_it_refuses_unless_yes(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert _patches(httpx_mock) == []


def test_dry_run_sends_no_patch(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0", "--dry-run"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "(dry run; nothing was changed)" in result.stdout
    assert _patches(httpx_mock) == []


def test_dry_run_json(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app,
        ["--json", "tags", "update", "payments-api", "stable", "--version", "2.1.0", "--dry-run"],
        env=_ENV,
    )
    body = json.loads(result.stdout)
    assert body["dryRun"] is True
    assert body["from"] == {"id": _V20, "version": "2.0.0"} and body["to"] == {"id": _V21, "version": "2.1.0"}
    assert body["affected"] == {
        "mockRequests7d": 23,
        "snapshotDownloads": 4,
        "frozen": True,
        "otherTags": ["prod"],
    }


def test_an_unavailable_usage_endpoint_never_blocks(httpx_mock) -> None:
    _mock(httpx_mock, usage={"detail": "Mock services are disabled"}, usage_status=404)
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Mock requests, last 7 days: unavailable" in result.stderr
    assert len(_patches(httpx_mock)) == 1


def test_a_transport_error_on_the_summary_never_blocks(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(method="GET", url=_TAGS_URL, json=_TAGS)
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=_VERSIONS)
    httpx_mock.add_exception(httpx.ConnectError("down"), url=f"{_HOST}/projects/acme/{_PROJECT}")
    httpx_mock.add_exception(httpx.ConnectError("down"), url=_FREEZE_20)
    httpx_mock.add_response(method="PATCH", url=_TAG_URL, json={**_STABLE, "version_id": _V21})
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Frozen-snapshot downloads:  unavailable" in result.stderr


def test_json_returns_the_updated_tag(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["--json", "tags", "update", "payments-api", "stable", "--version", "2.1.0", "--yes"], env=_ENV
    )
    assert json.loads(result.stdout) == {**_STABLE, "version_id": _V21}


def test_description_is_sent_with_the_move(httpx_mock) -> None:
    _mock(httpx_mock)
    runner.invoke(
        app,
        [
            "tags",
            "update",
            "payments-api",
            "stable",
            "--version",
            "2.1.0",
            "--description",
            "Promoted",
            "--yes",
        ],
        env=_ENV,
    )
    assert _patches(httpx_mock) == [{"version_id": _V21, "message": "Promoted"}]


def test_description_only_when_already_there(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app,
        ["tags", "update", "payments-api", "stable", "--version", "2.0.0", "--description", "", "--yes"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "only its description changes" in result.stderr
    assert _patches(httpx_mock) == [{"message": None}]


def test_nothing_to_change(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.0.0", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "already points to 2.0.0; nothing to change" in result.stdout
    assert _patches(httpx_mock) == []


def test_an_immutable_tag_exits_6_before_any_write(httpx_mock) -> None:
    _mock(httpx_mock, tags=[{**_STABLE, "immutable": True}])
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_TAG_LOCKED
    assert "immutable" in result.stderr
    assert _patches(httpx_mock) == []


def test_a_server_immutable_conflict_also_exits_6(httpx_mock) -> None:
    _mock(httpx_mock, patch_status=409)
    result = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "2.1.0", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_TAG_LOCKED


def test_unknown_tag_and_version_are_usage_errors(httpx_mock) -> None:
    _mock(httpx_mock)
    missing_tag = runner.invoke(
        app, ["tags", "update", "payments-api", "canary", "--version", "2.1.0"], env=_ENV
    )
    assert missing_tag.exit_code == EXIT_USAGE
    _mock(httpx_mock)
    missing_version = runner.invoke(
        app, ["tags", "update", "payments-api", "stable", "--version", "9.9.9"], env=_ENV
    )
    assert missing_version.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in missing_version.stderr
