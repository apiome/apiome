"""Tests for ``apiome teams list|show|create|members|assign`` (CDG-2.4 / #5963)."""

from __future__ import annotations

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client import api_paths
from apiome_cli.client.teams import (
    links_label,
    member_rows,
    parse_member,
    parse_members,
    team_rows,
    validate_kind,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000/v1/tenants/acme-corp"
_TEAMS = f"{_BASE}/teams"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _team(**extra: object) -> dict:
    return {
        "id": "t1",
        "slug": "payments",
        "name": "Payments",
        "description": "Card and wallet APIs",
        "contact_email": "payments@example.com",
        "chat_url": "https://chat.example.com/payments",
        "oncall_url": None,
        "docs_url": None,
        "member_count": 2,
        **extra,
    }


def _members() -> list[dict]:
    return [
        {"user_id": "u1", "role": "lead", "email": "ada@example.com", "name": "Ada"},
        {"user_id": "u2", "role": "member", "email": None, "name": None},
    ]


def _refused(code: str, message: str, status: int) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "detail": {"code": code, "message": message},
            "error": {"message": "Request failed"},
        },
    )


# --- helpers ---------------------------------------------------------------------------


def test_parse_member_roles_and_defaults() -> None:
    assert parse_member("u1") == {"user_id": "u1", "role": "member"}
    assert parse_member("u1:lead") == {"user_id": "u1", "role": "lead"}
    assert parse_member(" u1 : Member ") == {"user_id": "u1", "role": "member"}
    assert parse_member("auth0|x:y:lead") == {"user_id": "auth0|x:y", "role": "lead"}
    with pytest.raises(ValueError, match="role must be one of lead, member"):
        parse_member("u1:owner")
    with pytest.raises(ValueError, match="user id is required"):
        parse_member(":lead")
    with pytest.raises(ValueError, match="user id is required"):
        parse_member("  ")


def test_parse_members_refuses_duplicates() -> None:
    assert parse_members([]) == []
    assert parse_members(["u1:lead", "u2"]) == [
        {"user_id": "u1", "role": "lead"},
        {"user_id": "u2", "role": "member"},
    ]
    with pytest.raises(ValueError, match="more than once"):
        parse_members(["u1", "u1:lead"])


def test_validate_kind() -> None:
    assert validate_kind("project") == "project"
    assert validate_kind("Catalog-Item") == "catalog_item"
    with pytest.raises(ValueError, match="must be one of project, catalog_item"):
        validate_kind("repository")


def test_rows_and_links() -> None:
    assert links_label(_team()) == "email, chat"
    assert links_label({"slug": "x"}) == "-"
    assert team_rows([_team()]) == [
        {"slug": "payments", "name": "Payments", "members": 2, "links": "email, chat"}
    ]
    rows = member_rows({"members": _members()})
    assert rows[1] == {"user_id": "u2", "role": "member", "email": "-", "name": "-"}
    assert member_rows({}) == []


def test_api_paths_quote_segments() -> None:
    assert api_paths.team("acme", "a/b") == "/v1/tenants/acme/teams/a%2Fb"
    assert api_paths.team_members("acme", "pay") == "/v1/tenants/acme/teams/pay/members"
    assert api_paths.entity_owner("acme", "project", "p 1") == (
        "/v1/tenants/acme/owners/project/p%201"
    )


# --- commands --------------------------------------------------------------------------


def test_list_table_and_json(httpx_mock: HTTPXMock) -> None:
    body = {"teams": [_team()], "count": 1}
    httpx_mock.add_response(url=_TEAMS, json=body)
    result = runner.invoke(app, ["teams", "list"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "payments" in out and "Payments" in out and "email, chat" in out

    httpx_mock.add_response(url=_TEAMS, json=body)
    result = runner.invoke(app, ["teams", "list", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == body

    httpx_mock.add_response(url=_TEAMS, json=body)
    result = runner.invoke(app, ["--json", "teams", "list"])
    assert json.loads(result.stdout) == body


def test_list_empty_and_bad_format(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_TEAMS, json={"teams": [], "count": 0})
    result = runner.invoke(app, ["teams", "list"])
    assert result.exit_code == EXIT_SUCCESS
    assert "No teams." in result.output

    result = runner.invoke(app, ["teams", "list", "--format", "yaml"])
    assert result.exit_code == EXIT_USAGE


def test_show_prints_details_and_members(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{_TEAMS}/payments", json=_team(members=_members()))
    result = runner.invoke(app, ["teams", "show", "payments"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "Team: Payments (payments)" in out
    assert "Chat: https://chat.example.com/payments" in out
    assert "On-call" not in out
    assert "ada@example.com" in out and "lead" in out


def test_show_unknown_team_prints_refusal(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_TEAMS}/ghost",
        status_code=404,
        json={"detail": {"code": "team-not-found", "message": "No team 'ghost'."}},
    )
    result = runner.invoke(app, ["teams", "show", "ghost"])
    assert result.exit_code == EXIT_USAGE
    assert "Error: No team 'ghost'." in result.stderr
    assert "detail" not in result.output


def test_create_sends_only_given_fields(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=_TEAMS, method="POST", status_code=201, json=_team(member_count=0)
    )
    result = runner.invoke(
        app,
        [
            "teams",
            "create",
            "Payments",
            "--slug",
            "payments",
            "--contact-email",
            "payments@example.com",
            "--chat-url",
            "https://chat.example.com/payments",
            "--oncall-url",
            "https://pager.example.com/payments",
            "--docs-url",
            "https://docs.example.com/payments",
            "--description",
            "Card and wallet APIs",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Created team Payments (payments)." in result.output
    assert json.loads(httpx_mock.get_requests()[0].content) == {
        "name": "Payments",
        "slug": "payments",
        "description": "Card and wallet APIs",
        "contact_email": "payments@example.com",
        "chat_url": "https://chat.example.com/payments",
        "oncall_url": "https://pager.example.com/payments",
        "docs_url": "https://docs.example.com/payments",
    }


def test_create_minimal_and_slug_taken(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_TEAMS, method="POST", status_code=201, json=_team())
    result = runner.invoke(app, ["teams", "create", "Payments", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["slug"] == "payments"
    assert json.loads(httpx_mock.get_requests()[0].content) == {"name": "Payments"}

    httpx_mock.add_response(
        url=_TEAMS,
        method="POST",
        status_code=409,
        json={"detail": {"code": "team-slug-taken", "message": "Slug 'payments' is taken."}},
    )
    result = runner.invoke(app, ["teams", "create", "Payments"])
    assert result.exit_code == EXIT_USAGE
    assert "Slug 'payments' is taken." in result.stderr


def test_members_lists_without_options(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{_TEAMS}/payments", json=_team(members=_members()))
    result = runner.invoke(app, ["teams", "members", "payments"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = strip_ansi(result.output)
    assert "u1" in out and "Ada" in out
    assert httpx_mock.get_requests()[0].method == "GET"


def test_members_set_replaces_membership(httpx_mock: HTTPXMock) -> None:
    updated = _team(member_count=2, members=_members())
    httpx_mock.add_response(url=f"{_TEAMS}/payments/members", method="PUT", json=updated)
    result = runner.invoke(
        app, ["teams", "members", "payments", "--set", "u1:lead", "--set", "u2"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Team payments now has 2 member(s)." in result.stderr
    assert json.loads(httpx_mock.get_requests()[0].content) == {
        "members": [
            {"user_id": "u1", "role": "lead"},
            {"user_id": "u2", "role": "member"},
        ]
    }


def test_members_clear_sends_empty_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_TEAMS}/payments/members",
        method="PUT",
        json=_team(member_count=0, members=[]),
    )
    result = runner.invoke(app, ["teams", "members", "payments", "--clear", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["member_count"] == 0
    assert json.loads(httpx_mock.get_requests()[0].content) == {"members": []}


@pytest.mark.parametrize(
    "args",
    [
        ["--set", "u1:owner"],
        ["--set", "u1", "--set", "u1:lead"],
        ["--set", "u1", "--clear"],
    ],
)
def test_members_bad_options_are_usage_errors(httpx_mock: HTTPXMock, args: list[str]) -> None:
    result = runner.invoke(app, ["teams", "members", "payments", *args])
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []


def test_members_not_in_tenant_refused(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_TEAMS}/payments/members",
        method="PUT",
        status_code=422,
        json={
            "detail": {
                "code": "team-member-not-in-tenant",
                "message": "u9 is not a member of this workspace.",
            }
        },
    )
    result = runner.invoke(app, ["teams", "members", "payments", "--set", "u9"])
    assert result.exit_code == EXIT_USAGE
    assert "u9 is not a member of this workspace." in result.stderr


def _owners(kind: str = "project", entity_id: str = "p1") -> dict:
    return {
        "kind": kind,
        "entity_id": entity_id,
        "owner": {
            "team": {"id": "t1", "slug": "payments", "name": "Payments"},
            "status": "confirmed",
            "source": "manual",
        },
        "suggestions": [],
    }


def test_assign_sets_owner(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/owners/catalog_item/c1", method="PUT", json=_owners("catalog_item", "c1")
    )
    result = runner.invoke(
        app, ["teams", "assign", "catalog-item", "c1", "--team", "payments"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "catalog_item c1 is now owned by Payments (payments)." in result.output
    assert json.loads(httpx_mock.get_requests()[0].content) == {"team": "payments"}


def test_assign_json(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{_BASE}/owners/project/p1", method="PUT", json=_owners())
    result = runner.invoke(
        app, ["--json", "teams", "assign", "project", "p1", "--team", "payments"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _owners()


def test_assign_unknown_team_exits_non_zero(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_callback(
        lambda request: _refused("owner-team-not-found", "No team 'ghost' in this tenant.", 404),
        url=f"{_BASE}/owners/project/p1",
        method="PUT",
    )
    result = runner.invoke(app, ["teams", "assign", "project", "p1", "--team", "ghost"])
    assert result.exit_code == EXIT_USAGE
    assert result.exit_code != EXIT_SUCCESS
    assert "Error: No team 'ghost' in this tenant." in result.stderr
    assert "apiome teams list" in result.stderr
    assert result.stdout == ""


def test_assign_unknown_entity_exits_non_zero(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_callback(
        lambda request: _refused("owner-entity-not-found", "No project 'p9'.", 404),
        url=f"{_BASE}/owners/project/p9",
        method="PUT",
    )
    result = runner.invoke(app, ["teams", "assign", "project", "p9", "--team", "payments"])
    assert result.exit_code == EXIT_USAGE
    assert "Error: No project 'p9'." in result.stderr
    assert "apiome teams list" not in result.stderr


def test_assign_server_error_exits_one(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/owners/project/p1", method="PUT", status_code=503, text="down"
    )
    result = runner.invoke(app, ["teams", "assign", "project", "p1", "--team", "payments"])
    assert result.exit_code == EXIT_ERROR


def test_assign_bad_kind_is_usage_error(httpx_mock: HTTPXMock) -> None:
    result = runner.invoke(app, ["teams", "assign", "repository", "r1", "--team", "payments"])
    assert result.exit_code == EXIT_USAGE
    assert "must be one of project, catalog_item" in strip_ansi(result.output)
    assert httpx_mock.get_requests() == []


def test_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(app, ["teams"])
    out = strip_ansi(result.output)
    for verb in ("list", "show", "create", "members", "assign"):
        assert verb in out
