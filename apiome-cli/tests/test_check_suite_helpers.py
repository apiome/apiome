"""Pure helpers behind ``apiome checks`` (GNC-3.1 / #4740)."""

from __future__ import annotations

import pytest

from apiome_cli.client.check_suite import (
    FORMATS,
    build_run_request,
    exit_code_for_state,
    format_text,
)
from apiome_cli.exit_codes import EXIT_CHECK_FAILED, EXIT_CHECK_PENDING, EXIT_SUCCESS


def _component(component: str, state: str, *, counted: bool = True, **extra: object) -> dict:
    return {
        "component": component,
        "label": component.title(),
        "requirement": "required" if counted else "advisory",
        "counted": counted,
        "state": state,
        "reason": f"{component}-{state}",
        "detail": f"{component} is {state}",
        **extra,
    }


def _payload(state: str = "fail", **extra: object) -> dict:
    return {
        "run": {
            "id": "run-1",
            "state": state,
            "reason": "required-component-failed",
            "commit_sha": "abc1234",
            "components": [
                _component("lint", "pass", warned=True),
                _component("breaking", "fail"),
                _component("sdk", "fail", counted=False),
            ],
        },
        "replayed": False,
        **extra,
    }


def test_formats_are_text_json_and_md() -> None:
    assert FORMATS == ("text", "json", "md")


def test_a_run_request_carries_only_what_was_given() -> None:
    assert build_run_request() == {"publish": True}
    assert build_run_request(commit_sha="  abc1234 ", pr_number=7, publish=False) == {
        "publish": False,
        "commit_sha": "abc1234",
        "pr_number": 7,
    }
    assert "commit_sha" not in build_run_request(commit_sha="   ")


@pytest.mark.parametrize(
    ("state", "code"),
    [
        ("pass", EXIT_SUCCESS),
        ("skipped", EXIT_SUCCESS),
        ("fail", EXIT_CHECK_FAILED),
        ("pending", EXIT_CHECK_PENDING),
        ("PASS", EXIT_SUCCESS),
    ],
)
def test_each_verdict_has_its_exit_code(state: str, code: int) -> None:
    assert exit_code_for_state(state) == code


@pytest.mark.parametrize("state", [None, "", "green", "passed"])
def test_an_answer_the_cli_does_not_understand_is_never_a_green_light(state: object) -> None:
    assert exit_code_for_state(state) == EXIT_CHECK_FAILED


def test_the_codes_are_distinct_from_error_and_usage() -> None:
    assert {EXIT_CHECK_FAILED, EXIT_CHECK_PENDING}.isdisjoint({0, 1, 2, 3, 4, 5, 6})


def test_text_leads_with_the_verdict_and_what_decided_it() -> None:
    lines = format_text(_payload(), subject="pets@2.0.0")
    assert lines[0] == "API change check — pets@2.0.0: fail (required-component-failed)"
    # Only required components that failed or wait are called out; the advisory SDK is not.
    assert "  Breaking: breaking is fail" in lines
    assert not any(line.startswith("  Sdk:") for line in lines)
    table = "\n".join(lines)
    assert "pass (warning)" in table
    assert "breaking-fail" in table
    assert "  evaluation: run-1" in lines
    assert "  commit: abc1234" in lines


def test_text_says_when_it_replayed_and_when_it_is_stale() -> None:
    lines = format_text(_payload(replayed=True, stale=True), subject="pets@2.0.0")
    assert "  evaluation: run-1 (replayed — same inputs, same evidence)" in lines
    assert any(line.startswith("  stale:") for line in lines)


def test_text_reports_the_pull_request_side() -> None:
    reported = _payload(
        provider={"recorded": True},
        check={"check": {"name": "apiome/api-change", "last_publish_outcome": "dispatched"}},
    )
    assert "  pull request: apiome/api-change — dispatched" in format_text(reported, subject="p@v")
    refused = _payload(
        provider={"recorded": False, "reason": "check-binding-released", "message": "gone"}
    )
    assert any(
        "not reported (check-binding-released)" in line
        for line in format_text(refused, subject="p@v")
    )


def test_a_placeholder_shows_its_title_instead_of_a_table() -> None:
    payload = {
        "run": {
            "id": "run-2",
            "state": "pending",
            "reason": "draft-not-synchronized",
            "title": "Waiting for the Apiome draft to catch up with this commit",
            "components": [],
        }
    }
    lines = format_text(payload, subject="pets@2.0.0")
    assert "  Waiting for the Apiome draft to catch up with this commit" in lines
    assert not any("CHECK" in line for line in lines)
