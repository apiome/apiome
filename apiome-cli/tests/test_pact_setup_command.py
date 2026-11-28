"""Tests for ``apiome pact setup`` — PFX-8.20 (#7317).

The command runs against mocked REST (``pytest-httpx``): the requests it sends, what it prints, and
its exit code (``0`` unless something failed).

* with no flag it only reads, and prints the six sections;
* ``--from-projects`` creates only the proposed pacticipants that have none; a refusal is reported
  and exits 1, a 409 reads as already there;
* ``--environments`` creates the missing ones, ``production`` as production;
* ``--ci github`` opens pull requests for repositories that belong to a pacticipant, prints the
  workflow of the ones it could not, and previews when no account is linked;
* ``--write-secrets`` sends this command's own address and key, and never prints the key;
* ``--dry-run`` writes nothing; a second run sets nothing up twice;
* bad flags are refused before any request.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.commands.pact_setup import (
    parse_environments,
    pull_request_repositories,
    wanted_pacticipants,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app
from apiome_cli.pact_setup_output import action_lines, section_lines, workflow_lines

runner = CliRunner()

_API = "http://localhost:8000"
_BROKER = f"{_API}/v1/tenants/acme/pact-broker"
_SETUP = f"{_API}/v1/tenants/acme/pact-setup"
_PACTICIPANTS = f"{_API}/v1/tenants/acme/pacticipants"
_ENVIRONMENTS = f"{_BROKER}/environments"
_REPO = "22222222-2222-4222-8222-222222222222"
_OTHER = "44444444-4444-4444-8444-444444444444"
_KEY = "broker-token-0123456789"
_WORKFLOW = "name: apiome-contracts\non:\n  pull_request:\n"


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "pacticipants",
                "title": "Who talks to whom",
                "state": "done",
                "summary": "1 pacticipant",
            },
            {
                "id": "environments",
                "title": "Where things run",
                "state": "next",
                "summary": "production, staging, or your own",
            },
            {
                "id": "pipelines",
                "title": "Connect your pipelines",
                "state": "todo",
                "summary": "A key and two variables",
            },
            {
                "id": "first-pact",
                "title": "The first consumer pact",
                "state": "todo",
                "summary": "",
            },
            {
                "id": "provider",
                "title": "The provider's side",
                "state": "todo",
                "summary": "",
            },
            {
                "id": "gates",
                "title": "Gate deploys and tell people",
                "state": "todo",
                "summary": "",
            },
        ],
        "facts": {"environments": []},
        "candidates": [
            {
                "name": "Billing API",
                "source_label": "Project · Billing API",
                "project": "billing-api",
                "repository_url": "https://github.com/acme/billing-service",
                "main_branch": "main",
                "pacticipant": "billing-service",
            },
            {
                "name": "Payments API",
                "source_label": "Project · Payments API",
                "project": "payments-api",
                "repository_url": None,
                "main_branch": None,
                "pacticipant": None,
            },
        ],
        "candidates_omitted": 0,
        "github": {
            "linked": True,
            "reason": None,
            "repositories": [
                {
                    "id": _REPO,
                    "full_name": "acme/billing-service",
                    "linked": True,
                    "pacticipant_name": "Billing Service",
                },
                {
                    "id": _OTHER,
                    "full_name": "acme/scripts",
                    "linked": False,
                    "pacticipant_name": None,
                },
            ],
        },
    }
    state.update(overrides)
    return state


@pytest.fixture(autouse=True)
def broker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the variables Pact tooling reads; nothing from the developer's shell."""
    for name in (
        "APIOME_API_KEY",
        "APIOME_BASE_URL",
        "APIOME_TENANT_ID",
        "PACT_BROKER_USERNAME",
        "PACT_BROKER_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    monkeypatch.setenv("PACT_BROKER_TOKEN", _KEY)


def _bodies(httpx_mock: Any, url: str) -> list[Any]:
    return [
        json.loads(request.content)
        for request in httpx_mock.get_requests(url=url, method="POST")
    ]


def test_with_no_flag_it_only_shows_the_sections(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state())
    result = runner.invoke(app, ["pact", "setup"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Contracts set-up: 1 of 6 done" in result.output
    assert "1. [Done] Who talks to whom — 1 pacticipant" in result.output
    assert (
        "2. [Next] Where things run" in result.output
        and "6. [To do] Gate deploys and tell people" in result.output
    )
    assert "What this run did" not in result.output
    assert [request.method for request in httpx_mock.get_requests()] == ["GET"]
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == _KEY


def test_from_projects_creates_only_what_is_missing(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state(), is_reusable=True)
    httpx_mock.add_response(
        url=_PACTICIPANTS, method="POST", status_code=201, json={"slug": "payments-api"}
    )
    result = runner.invoke(app, ["pact", "setup", "--from-projects"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _bodies(httpx_mock, _PACTICIPANTS) == [
        {"name": "Payments API", "project": "payments-api"}
    ]
    assert "pacticipant Billing API: already there — billing-service" in result.output
    assert "pacticipant Payments API: created — Project · Payments API" in result.output


def test_a_refused_pacticipant_is_reported_and_exits_1_while_a_taken_name_is_already_there(
    httpx_mock: Any,
) -> None:
    candidates = [
        {"name": "Payments API", "pacticipant": None},
        {"name": "Ledger", "pacticipant": None},
    ]
    httpx_mock.add_response(
        url=_SETUP,
        json=_state(candidates=candidates, candidates_omitted=3),
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_PACTICIPANTS,
        method="POST",
        status_code=409,
        json={"detail": {"message": "a pacticipant 'payments-api' already exists"}},
    )
    httpx_mock.add_response(
        url=_PACTICIPANTS,
        method="POST",
        status_code=403,
        json={"detail": "Permission denied"},
    )
    result = runner.invoke(app, ["pact", "setup", "--from-projects"])
    assert result.exit_code == EXIT_ERROR
    assert (
        "pacticipant Payments API: already there — a pacticipant 'payments-api' already exists"
        in result.output
    )
    assert "pacticipant Ledger: FAILED — Permission denied" in result.output
    assert "pacticipant 3 more: skipped" in result.output


def test_environments_are_created_when_missing_and_production_is_marked(
    httpx_mock: Any,
) -> None:
    httpx_mock.add_response(
        url=_SETUP, json=_state(facts={"environments": ["staging"]}), is_reusable=True
    )
    httpx_mock.add_response(
        url=_ENVIRONMENTS,
        method="POST",
        status_code=201,
        json={"uuid": "e-1"},
        is_reusable=True,
    )
    result = runner.invoke(
        app,
        [
            "pact",
            "setup",
            "--environments",
            "production, staging,qa,qa",
            "--require-contract",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    bodies = _bodies(httpx_mock, _ENVIRONMENTS)
    assert [body["name"] for body in bodies] == ["production", "qa"]
    assert bodies[0]["production"] is True and bodies[0]["contractRequired"] is True
    assert bodies[1]["production"] is False and bodies[1].get("contractRequired") in (
        False,
        None,
    )
    assert "environment production: created — production" in result.output
    assert "environment staging: already there" in result.output


def test_ci_github_opens_pull_requests_and_prints_the_workflow_it_could_not_open(
    httpx_mock: Any,
) -> None:
    httpx_mock.add_response(
        url=_SETUP,
        json=_state(facts={"environments": ["production", "staging"]}),
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=f"{_SETUP}/github/pull-requests",
        method="POST",
        json={
            "results": [
                {
                    "repository_id": _REPO,
                    "full_name": "acme/billing-service",
                    "status": "opened",
                    "url": "https://github.com/acme/billing-service/pull/7",
                    "number": 7,
                    "path": ".github/workflows/apiome-contracts.yml",
                    "content": _WORKFLOW,
                }
            ]
        },
    )
    result = runner.invoke(app, ["pact", "setup", "--ci", "github"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _bodies(httpx_mock, f"{_SETUP}/github/pull-requests") == [
        {
            "repositories": [
                {"repository_id": _REPO, "pacticipant": "Billing Service"}
            ],
            "environment": "production",
            "preview": False,
        }
    ]
    assert (
        "pull request acme/billing-service: opened — https://github.com/acme/billing-service/pull/7"
        in result.output
    )
    # A repository no pacticipant names is reported, never dropped.
    assert (
        "pull request acme/scripts: skipped — no pacticipant has this repository"
        in result.output
    )
    assert "name: apiome-contracts" not in result.output


def test_ci_github_without_a_linked_account_previews_and_prints_the_workflow(
    httpx_mock: Any,
) -> None:
    github = {
        "linked": False,
        "reason": "No registered repository has a linked GitHub account.",
        "repositories": [
            {
                "id": _REPO,
                "full_name": "acme/billing-service",
                "linked": False,
                "pacticipant_name": "Billing Service",
            }
        ],
    }
    httpx_mock.add_response(
        url=_SETUP,
        json=_state(facts={"environments": ["staging"]}, github=github),
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=f"{_SETUP}/github/pull-requests",
        method="POST",
        json={
            "results": [
                {
                    "repository_id": _REPO,
                    "full_name": "acme/billing-service",
                    "status": "preview",
                    "path": ".github/workflows/apiome-contracts.yml",
                    "content": _WORKFLOW,
                }
            ]
        },
    )
    result = runner.invoke(
        app, ["pact", "setup", "--ci", "github", "--output", "markdown"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    (body,) = _bodies(httpx_mock, f"{_SETUP}/github/pull-requests")
    assert body["preview"] is True and body["environment"] == "staging"
    assert (
        "pull request acme/billing-service: skipped — No registered repository has a linked GitHub account."
        in result.output
    )
    assert (
        "Add this to acme/billing-service as .github/workflows/apiome-contracts.yml:"
        in result.output
    )
    assert "```yaml\nname: apiome-contracts" in result.output


def test_ci_with_no_environment_fails_with_what_to_do(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state(), is_reusable=True)
    result = runner.invoke(app, ["pact", "setup", "--ci", "github"])
    assert result.exit_code == EXIT_ERROR
    assert "no environment to ask about: add --environments production" in result.output
    assert not httpx_mock.get_requests(method="POST")


def test_write_secrets_sends_this_commands_address_and_key_and_never_prints_the_key(
    httpx_mock: Any,
) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state(), is_reusable=True)
    httpx_mock.add_response(
        url=f"{_SETUP}/github/secrets",
        method="POST",
        json={
            "results": [
                {
                    "repository_id": _REPO,
                    "full_name": "acme/billing-service",
                    "status": "written",
                    "names": ["PACT_BROKER_BASE_URL", "PACT_BROKER_TOKEN"],
                }
            ]
        },
    )
    result = runner.invoke(app, ["pact", "setup", "--write-secrets"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _bodies(httpx_mock, f"{_SETUP}/github/secrets") == [
        {"repository_ids": [_REPO], "broker_base_url": _BROKER, "token": _KEY}
    ]
    assert "secrets acme/billing-service: written" in result.output
    assert (
        "secrets acme/scripts: skipped — registered without a linked GitHub account"
        in result.output
    )
    assert _KEY not in result.output


def test_a_refused_secrets_call_exits_1(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state(), is_reusable=True)
    httpx_mock.add_response(
        url=f"{_SETUP}/github/secrets",
        method="POST",
        status_code=403,
        json={"detail": "Permission denied"},
    )
    result = runner.invoke(app, ["pact", "setup", "--write-secrets"])
    assert (
        result.exit_code == EXIT_ERROR
        and "secrets GitHub: FAILED — Permission denied" in result.output
    )


def test_a_dry_run_writes_nothing_but_the_preview(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state(), is_reusable=True)
    httpx_mock.add_response(
        url=f"{_SETUP}/github/pull-requests",
        method="POST",
        json={
            "results": [
                {
                    "repository_id": _REPO,
                    "full_name": "acme/billing-service",
                    "status": "preview",
                    "path": ".github/workflows/apiome-contracts.yml",
                    "content": _WORKFLOW,
                }
            ]
        },
    )
    result = runner.invoke(
        app,
        [
            "pact",
            "setup",
            "--from-projects",
            "--environments",
            "production",
            "--ci",
            "github",
            "--write-secrets",
            "--dry-run",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    posts = httpx_mock.get_requests(method="POST")
    assert [str(request.url) for request in posts] == [f"{_SETUP}/github/pull-requests"]
    assert json.loads(posts[0].content)["preview"] is True
    assert "pacticipant Payments API: would be done (dry run)" in result.output
    assert "environment production: would be done (dry run)" in result.output
    assert "secrets acme/billing-service: would be done (dry run)" in result.output
    assert "pull request acme/billing-service: would be done (dry run)" in result.output


def test_a_second_run_sets_nothing_up_twice(httpx_mock: Any) -> None:
    done = _state(
        facts={"environments": ["production"]},
        candidates=[{"name": "Billing API", "pacticipant": "billing-service"}],
    )
    httpx_mock.add_response(url=_SETUP, json=done, is_reusable=True)
    result = runner.invoke(
        app, ["pact", "setup", "--from-projects", "--environments", "production"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert not httpx_mock.get_requests(method="POST")
    assert (
        "pacticipant Billing API: already there" in result.output
        and "environment production: already there" in result.output
    )


def test_json_output_is_the_state_and_what_was_done(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_SETUP, json=_state())
    result = runner.invoke(app, ["pact", "setup", "--output", "json"])
    document = json.loads(result.output)
    assert (
        document["actions"] == []
        and document["dry_run"] is False
        and len(document["setup"]["sections"]) == 6
    )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--ci", "gitlab"], "only: github"),
        (["--environments", "production,,staging"], "empty name"),
        (["--environments", "pre prod"], "one word"),
        (["--require-contract", "--environments", "staging"], "needs production"),
        (["--ci-environment", "staging"], "needs --ci github"),
    ],
)
def test_bad_flags_are_refused_before_any_request(
    httpx_mock: Any, args: list[str], message: str
) -> None:
    result = runner.invoke(app, ["pact", "setup", *args])
    assert result.exit_code == EXIT_ERROR
    assert message in result.output
    assert not httpx_mock.get_requests()


def test_the_helpers_keep_order_and_drop_nothing() -> None:
    assert parse_environments(None) == [] and parse_environments("a, b ,a") == [
        "a",
        "b",
    ]
    state = _state()
    assert [item["name"] for item in wanted_pacticipants(state)] == ["Payments API"]
    rows, skipped = pull_request_repositories(state)
    assert rows == [{"repository_id": _REPO, "pacticipant": "Billing Service"}]
    assert [item["name"] for item in skipped] == ["acme/scripts"]
    assert section_lines(state, "markdown")[0] == "**Contracts set-up: 1 of 6 done**"
    assert action_lines(
        [{"kind": "environment", "name": "qa", "outcome": "created"}], "markdown"
    ) == ["- environment qa: created"]
    assert workflow_lines([{"status": "opened", "content": _WORKFLOW}], "table") == []
    lines = workflow_lines(
        [
            {
                "status": "skipped",
                "full_name": "a/b",
                "path": "p.yml",
                "content": _WORKFLOW,
            }
        ],
        "table",
    )
    assert lines[:3] == ["", "Add this to a/b as p.yml:", "name: apiome-contracts"]
