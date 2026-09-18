"""Tests for ``apiome checks run`` / ``checks show`` (GNC-3.1 / #4740) against mocked REST."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_CHECK_FAILED,
    EXIT_CHECK_PENDING,
    EXIT_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_SUITE_URL = "http://localhost:8000/v1/tenants/acme-corp/projects/pets/versions/2.0.0/check-suite"
_RUN_URL = "http://localhost:8000/v1/tenants/acme-corp/projects/pets/check-suite/runs/run-1"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _detail(state: str = "pass", **extra: object) -> dict:
    return {
        "run": {
            "id": "run-1",
            "state": state,
            "reason": "required-components-passed" if state == "pass" else "required-component-failed",
            "title": "API change check",
            "summary": "**API change check: " + state + "**\n\n| Check | Policy | Result | Why |",
            "commit_sha": "abc1234",
            "components": [
                {
                    "component": "breaking",
                    "label": "Breaking changes",
                    "requirement": "required",
                    "counted": True,
                    "state": state,
                    "reason": "breaking-none",
                    "detail": "No classified changes.",
                }
            ],
        },
        "replayed": False,
        "stale": False,
        **extra,
    }


def test_run_posts_the_request_and_exits_zero_on_a_pass(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_SUITE_URL, status_code=201, json=_detail("pass"))
    result = runner.invoke(
        app,
        ["checks", "run", "--project", "pets", "--version", "2.0.0", "--commit", "abc1234", "--pr", "7"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "API change check — pets@2.0.0: pass" in result.output
    request = httpx_mock.get_requests()[0]
    assert json.loads(request.content) == {"publish": True, "commit_sha": "abc1234", "pr_number": 7}
    assert request.headers["X-API-Key"] == "test-key"


@pytest.mark.parametrize(
    ("state", "code"),
    [("fail", EXIT_CHECK_FAILED), ("pending", EXIT_CHECK_PENDING), ("skipped", EXIT_SUCCESS)],
)
def test_run_exits_with_the_verdict(httpx_mock: HTTPXMock, state: str, code: int) -> None:
    httpx_mock.add_response(method="POST", url=_SUITE_URL, status_code=201, json=_detail(state))
    result = runner.invoke(app, ["checks", "run", "--project", "pets", "--version", "2.0.0"])
    assert result.exit_code == code


def test_a_replay_is_still_a_verdict(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST", url=_SUITE_URL, status_code=200, json=_detail("fail", replayed=True)
    )
    result = runner.invoke(app, ["checks", "run", "--project", "pets", "--version", "2.0.0"])
    assert result.exit_code == EXIT_CHECK_FAILED
    assert "replayed" in result.output


def test_no_publish_is_sent_to_the_server(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_SUITE_URL, status_code=201, json=_detail())
    runner.invoke(app, ["checks", "run", "--project", "pets", "--version", "2.0.0", "--no-publish"])
    assert json.loads(httpx_mock.get_requests()[0].content) == {"publish": False}


def test_md_prints_the_pull_request_summary(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_SUITE_URL, status_code=201, json=_detail("fail"))
    result = runner.invoke(
        app, ["checks", "run", "--project", "pets", "--version", "2.0.0", "--format", "md"]
    )
    assert result.stdout.startswith("**API change check: fail**")
    assert result.exit_code == EXIT_CHECK_FAILED


def test_global_json_prints_the_api_response(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_SUITE_URL, status_code=201, json=_detail())
    result = runner.invoke(app, ["--json", "checks", "run", "--project", "pets", "--version", "2.0.0"])
    assert json.loads(result.stdout)["run"]["id"] == "run-1"


def test_an_unknown_format_is_a_usage_error() -> None:
    result = runner.invoke(
        app, ["checks", "run", "--project", "pets", "--version", "2.0.0", "--format", "xml"]
    )
    assert result.exit_code == EXIT_USAGE
    assert "--format" in strip_ansi(result.output)


def test_a_rejected_request_is_a_usage_error_not_a_verdict(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=_SUITE_URL,
        status_code=409,
        json={"detail": {"code": "check-suite-commit-unknown", "message": "never observed"}},
    )
    result = runner.invoke(
        app, ["checks", "run", "--project", "pets", "--version", "2.0.0", "--commit", "d" * 40]
    )
    assert result.exit_code == EXIT_USAGE


def test_a_server_error_is_an_error_not_a_verdict(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_SUITE_URL, status_code=503, json={"detail": "down"})
    result = runner.invoke(app, ["checks", "run", "--project", "pets", "--version", "2.0.0"])
    assert result.exit_code == EXIT_ERROR


def test_show_reads_the_latest_evaluation_at_a_commit(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET", url=f"{_SUITE_URL}?commit_sha=abc1234", json=_detail("pending")
    )
    result = runner.invoke(
        app, ["checks", "show", "--project", "pets", "--version", "2.0.0", "--commit", "abc1234"]
    )
    assert result.exit_code == EXIT_CHECK_PENDING
    assert "pets@2.0.0: pending" in result.output


def test_show_reads_one_evaluation_by_id(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_RUN_URL, json=_detail("pass"))
    result = runner.invoke(app, ["checks", "show", "--project", "pets", "--run", "run-1"])
    assert result.exit_code == EXIT_SUCCESS
    assert "pets evaluation run-1: pass" in result.output


def test_show_warns_when_an_evaluation_is_stale(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_SUITE_URL, json=_detail("pass", stale=True))
    result = runner.invoke(
        app, ["checks", "show", "--project", "pets", "--version", "2.0.0", "--format", "json"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "stale" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["checks", "show", "--project", "pets"],
        ["checks", "show", "--project", "pets", "--version", "2.0.0", "--run", "run-1"],
        ["checks", "show", "--project", "pets", "--run", "run-1", "--commit", "abc1234"],
    ],
)
def test_show_needs_exactly_one_subject(arguments: list[str]) -> None:
    assert runner.invoke(app, arguments).exit_code == EXIT_USAGE


def test_the_group_lists_its_commands() -> None:
    result = runner.invoke(app, ["checks"])
    assert result.exit_code == EXIT_SUCCESS
    text = strip_ansi(result.output)
    assert "run" in text and "show" in text
