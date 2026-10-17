"""``apiome versions unpublish`` (CLI 4.6, #3213).

The rules (:mod:`apiome_cli.version_unpublish`) and the command against a mocked REST API: the
server's dry run drives the preview; the typed confirmation must match the version exactly;
``--reason`` is required unless ``--silent``; the project's only published version is refused
(exit 6) unless ``--force``; ``--keep-tags`` / ``--silent`` reach the server; ``--json`` prints
the unpublished record; ``versions get`` shows the stored reason.
"""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_LAST_PUBLISHED_VERSION, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.version_unpublish import (
    UnpublishError,
    check_reason,
    parse_positionals,
    render_plan,
    render_result,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V21 = "22222222-2222-4222-8222-222222222222"
_V20 = "11111111-1111-4111-8111-111111111111"
_UNPUBLISH = f"{_HOST}/versions/acme-corp/{_PROJECT}/{_V21}/unpublish"

_PLAN = {
    "id": _V21,
    "project_id": _PROJECT,
    "version_id": "2.1.0",
    "published": True,
    "dryRun": True,
    "tagsMoved": [{"id": "t1", "name": "latest", "toVersionId": _V20, "toVersionLabel": "2.0.0"}],
    "tagsKept": [{"id": "t2", "name": "ga-2.1", "reason": "immutable"}],
    "previousPublishedVersionId": _V20,
    "previousPublishedVersionLabel": "2.0.0",
    "publishedVersionsRemaining": 1,
    "notify": True,
    "webhookSubscribers": 3,
}
_RESULT = {
    **_PLAN,
    "dryRun": False,
    "published": False,
    "unpublishReason": "Security regression",
    "unpublishedAt": "2026-10-16T12:00:00Z",
}


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the typed confirmation runs."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


def _mock(httpx_mock, *, plan=_PLAN, result=_RESULT) -> None:
    """Resolve payments-api / 2.1.0, then serve the dry run and (optionally) the real call."""
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme-corp/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_PROJECT}/by-version/2.1.0", json={"id": _V21}, is_optional=True
    )
    calls = iter([plan, result])
    httpx_mock.add_callback(
        lambda request: httpx.Response(200, json=next(calls)),
        method="POST",
        url=_UNPUBLISH,
        is_optional=True,
        is_reusable=True,
    )


def _posts(httpx_mock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests() if r.method == "POST"]


# --- rules ----------------------------------------------------------------------------------


def test_positionals_take_project_then_version() -> None:
    assert parse_positionals("payments-api", "2.1.0", None) == ("payments-api", "2.1.0")


def test_the_older_project_option_form_still_works() -> None:
    assert parse_positionals("2.1.0", None, "payments-api") == ("payments-api", "2.1.0")


def test_a_missing_or_contradicting_project_is_refused() -> None:
    with pytest.raises(UnpublishError, match="Name the project"):
        parse_positionals("2.1.0", None, None)
    with pytest.raises(UnpublishError, match="contradicts"):
        parse_positionals("payments-api", "2.1.0", "orders-api")


def test_a_reason_is_required_unless_silent() -> None:
    with pytest.raises(UnpublishError, match="--reason is required"):
        check_reason("   ", silent=False)
    assert check_reason(None, silent=True) is None
    assert check_reason("  bad release ", silent=False) == "bad release"


def test_the_plan_lists_every_effect() -> None:
    assert render_plan(_PLAN, reason="Security regression") == "\n".join(
        [
            "Unpublishing will:",
            "  • Hide 2.1.0 from /v1/schema, /v1/swagger, /v1/arazzo, /v1/json",
            "  • Move the 'latest' tag back to 2.0.0 (next-most-recent published)",
            "  • Leave the 'ga-2.1' tag on 2.1.0 (immutable)",
            "  • Notify webhook subscribers (3 active)",
            "  • Record the reason: Security regression",
        ]
    )


def test_a_silent_last_version_plan_says_so() -> None:
    plan = {**_PLAN, "tagsMoved": [], "tagsKept": [], "notify": False, "publishedVersionsRemaining": 0}
    text = render_plan(plan, reason=None)
    assert "Not notify webhook subscribers (--silent)" in text
    assert "Leave the project with no published version" in text
    assert "Record the reason" not in text


def test_an_unknown_subscriber_count_is_shown_as_unavailable() -> None:
    assert "(count unavailable)" in render_plan({**_PLAN, "webhookSubscribers": None}, reason="x")


def test_the_result_names_moved_tags() -> None:
    assert render_result(_RESULT) == "✔ Unpublished 2.1.0.\n  Tags moved: latest → 2.0.0"


# --- the command ----------------------------------------------------------------------------


def test_typing_the_version_unpublishes(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app,
        ["versions", "unpublish", "payments-api", "v2.1.0", "--reason", "Security regression"],
        env=_ENV,
        input="2.1.0\n",
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Unpublishing will:" in result.stderr
    assert "Move the 'latest' tag back to 2.0.0" in result.stderr
    assert "✔ Unpublished 2.1.0." in result.stdout
    assert _posts(httpx_mock) == [
        {"reason": "Security regression", "silent": False, "keepTags": False, "dryRun": True},
        {"reason": "Security regression", "silent": False, "keepTags": False},
    ]


def test_a_mistyped_version_changes_nothing(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["versions", "unpublish", "payments-api", "2.1.0", "--reason", "x"], env=_ENV, input="2.1\n"
    )
    assert result.exit_code == EXIT_USAGE
    assert "nothing was changed" in result.stderr
    assert len(_posts(httpx_mock)) == 1  # the dry run only


def test_without_a_terminal_it_refuses_unless_yes(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["versions", "unpublish", "payments-api", "2.1.0", "--reason", "x"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "--yes" in result.stderr
    assert len(_posts(httpx_mock)) == 1


def test_a_missing_reason_is_refused_before_any_request(httpx_mock) -> None:
    result = runner.invoke(app, ["versions", "unpublish", "payments-api", "2.1.0", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "--reason is required" in result.stderr
    assert httpx_mock.get_requests() == []


def test_the_only_published_version_is_refused_with_exit_6(httpx_mock) -> None:
    _mock(httpx_mock, plan={**_PLAN, "publishedVersionsRemaining": 0})
    result = runner.invoke(
        app, ["versions", "unpublish", "payments-api", "2.1.0", "--reason", "x", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_LAST_PUBLISHED_VERSION
    assert "only published version" in result.stderr
    assert len(_posts(httpx_mock)) == 1


def test_force_unpublishes_the_only_published_version(httpx_mock) -> None:
    _mock(httpx_mock, plan={**_PLAN, "publishedVersionsRemaining": 0})
    result = runner.invoke(
        app, ["versions", "unpublish", "payments-api", "2.1.0", "--reason", "x", "--yes", "--force"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(_posts(httpx_mock)) == 2


def test_silent_and_keep_tags_reach_the_server(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app,
        ["versions", "unpublish", "payments-api", "2.1.0", "--silent", "--keep-tags", "--yes"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posts(httpx_mock)[1] == {"reason": None, "silent": True, "keepTags": True}


def test_json_prints_the_unpublished_record(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app,
        [
            "--json",
            "versions",
            "unpublish",
            "payments-api",
            "2.1.0",
            "--reason",
            "Security regression",
            "--yes",
        ],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _RESULT


def test_the_project_option_form_and_a_uuid_still_work(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app,
        ["versions", "unpublish", _V21, "--project", _PROJECT, "--reason", "x", "--yes"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert all(r.url.path.endswith(f"/{_V21}/unpublish") for r in httpx_mock.get_requests())


def test_a_server_refusal_uses_the_shared_error_mapping(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme-corp/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme-corp/{_PROJECT}/by-version/2.1.0", json={"id": _V21})
    httpx_mock.add_response(
        method="POST",
        url=_UNPUBLISH,
        status_code=403,
        json={
            "detail": {
                "code": "silent_requires_admin",
                "message": "Only a tenant administrator can unpublish without notifying webhook subscribers.",
            }
        },
    )
    result = runner.invoke(
        app, ["versions", "unpublish", "payments-api", "2.1.0", "--silent", "--yes"], env=_ENV
    )
    assert result.exit_code != EXIT_SUCCESS
    assert "tenant administrator" in result.stderr


def test_versions_get_shows_the_unpublish_reason(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_PROJECT}/{_V21}",
        json={
            "id": _V21,
            "project_id": _PROJECT,
            "unpublishReason": "Security regression",
            "unpublishedAt": "2026-10-16T12:00:00Z",
            "unpublishedBy": "u1",
        },
    )
    result = runner.invoke(app, ["versions", "get", _V21, "--project-id", _PROJECT], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Unpublish Reason" in result.stdout
    assert "Security regression" in result.stdout


def test_versions_get_hides_the_unpublish_rows_for_a_never_unpublished_version(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_PROJECT}/{_V21}", json={"id": _V21, "project_id": _PROJECT}
    )
    result = runner.invoke(app, ["versions", "get", _V21, "--project-id", _PROJECT], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert "Unpublish Reason" not in result.stdout
