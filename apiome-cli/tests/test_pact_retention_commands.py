"""Tests for ``apiome pact retention show|set|preview`` — PFX-8.14 (#7311).

Every command runs against mocked REST (``pytest-httpx``): the request it sends (path, body,
credential), what it prints, and its exit code (``0`` success / ``1`` any failure, like the rest of
``apiome pact``). ``set`` changes only the rules it is given; ``preview`` previews the saved rules,
or — with rule flags — a draft it does not save. Contradicting or incomplete flags are refused with
the reason before any write.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.commands.pact_retention import merge_rules
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app
from apiome_cli.pact_retention_output import policy_lines, preview_lines, rule_sentences

runner = CliRunner()

_API = "http://localhost:8000"
_BROKER = f"{_API}/v1/tenants/acme/pact-broker"
_POLICY = f"{_API}/v1/tenants/acme/pact-retention/policy"

_SAVED = {
    "configured": True,
    "keep_deployed_or_released": True,
    "keep_main_branch_latest": 5,
    "keep_other_branch_latest": 1,
    "keep_other_branch_days": 90,
    "keep_tags": ["keep"],
    "nightly_enabled": True,
    "restore_window_days": 30,
    "next_run_at": "2026-11-29T02:00:00+00:00",
    "last_run": {"at": "2026-11-28T02:03:00+00:00", "deleted": 412, "remaining": 0, "error": None},
    "can_edit": True,
}

_PREVIEW = {
    "draft": False,
    "nightly_enabled": True,
    "next_run_at": "2026-11-29T02:00:00+00:00",
    "plan": {
        "evaluated": 1904,
        "deleted": 2,
        "pacts": 3,
        "results": 7,
        "remaining": 0,
        "pacticipants": [
            {
                "slug": "orders-ui",
                "name": "Orders UI",
                "deleted": 2,
                "deletions": [
                    {"number": "3.2.2", "branches": ["main"], "pacts": 1, "results": 2, "created_at": "2026-01-02"},
                    {"number": "f-1", "branches": ["feat/x"], "pacts": 2, "results": 5, "created_at": "2026-02-03"},
                ],
            }
        ],
    },
}


@pytest.fixture(autouse=True)
def broker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the variables Pact tooling reads; nothing from the developer's shell."""
    for name in ("APIOME_API_KEY", "APIOME_BASE_URL", "APIOME_TENANT_ID", "PACT_BROKER_USERNAME", "PACT_BROKER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    monkeypatch.setenv("PACT_BROKER_TOKEN", "broker-token")


def _invoke(*args: str) -> Any:
    return runner.invoke(app, ["pact", "retention", *args])


# --- show -------------------------------------------------------------------------------------


def test_show_prints_the_rules_as_sentences(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    result = _invoke("show")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Every version deployed or released anywhere (always)" in result.output
    assert "The latest 5 versions on each pacticipant's main branch" in result.output
    assert "The latest 1 version on every other branch, for 90 days" in result.output
    assert "Anything tagged keep" in result.output
    assert "Clean-up runs nightly; next run 2026-11-29T02:00:00+00:00." in result.output
    assert "Last run 2026-11-28T02:03:00+00:00: removed 412 versions." in result.output
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "broker-token"


def test_show_as_json_prints_the_servers_document(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    result = _invoke("show", "-o", "json")
    assert result.exit_code == EXIT_SUCCESS and json.loads(result.output) == _SAVED


def test_show_a_refusal_exits_1_with_the_message(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, status_code=403, json={"detail": "Missing permission pacts:view"})
    result = _invoke("show")
    assert result.exit_code == EXIT_ERROR
    assert "pacts:view" in result.output


# --- set --------------------------------------------------------------------------------------


def test_set_changes_only_the_given_rules(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    httpx_mock.add_response(method="PUT", url=_POLICY, json={**_SAVED, "keep_main_branch_latest": 3})
    result = _invoke("set", "--main-branch-latest", "3", "--no-nightly")
    assert result.exit_code == EXIT_SUCCESS, result.output
    put = httpx_mock.get_requests()[1]
    assert json.loads(put.content) == {
        "keep_main_branch_latest": 3,
        "keep_other_branch_latest": 1,
        "keep_other_branch_days": 90,
        "keep_tags": ["keep"],
        "nightly_enabled": False,
        "restore_window_days": 30,
    }
    assert result.output.startswith("Clean-up rules saved.")


def test_set_with_nothing_to_change_writes_nothing(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    result = _invoke("set")
    assert result.exit_code == EXIT_ERROR
    assert "nothing to change" in result.output
    assert [request.method for request in httpx_mock.get_requests()] == ["GET"]


def test_set_refused_by_the_server_exits_1(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    httpx_mock.add_response(
        method="PUT",
        url=_POLICY,
        status_code=422,
        json={"detail": {"code": "pact-retention-keeps-in-use", "message": "Deployed and released versions are always kept."}},
    )
    result = _invoke("set", "--restore-days", "7")
    assert result.exit_code == EXIT_ERROR
    assert "Deployed and released versions are always kept." in result.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--keep-tag", "a", "--no-tags"), "contradict"),
        (("--keep-tag", "a", "--keep-tag", "a"), "more than once"),
        (("--keep-tag", " "), "needs a tag name"),
        (("--other-branch-latest", "0", "--other-branch-days", "30"), "needs an other-branch rule"),
    ],
)
def test_set_refuses_flags_it_cannot_use_before_writing(httpx_mock: Any, args: tuple[str, ...], message: str) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    result = _invoke("set", *args)
    assert result.exit_code == EXIT_ERROR and message in result.output
    assert [request.method for request in httpx_mock.get_requests()] == ["GET"]


def test_set_refuses_out_of_range_numbers_without_a_request(httpx_mock: Any) -> None:
    result = _invoke("set", "--restore-days", "0")
    assert result.exit_code == EXIT_ERROR
    assert httpx_mock.get_requests() == []


# --- preview ----------------------------------------------------------------------------------


def test_preview_of_the_saved_rules_sends_no_draft(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    httpx_mock.add_response(method="POST", url=f"{_POLICY}/preview", json=_PREVIEW)
    result = _invoke("preview")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(httpx_mock.get_requests()[1].content) == {}
    assert "If it ran now: 2 of 1,904 versions would go, with 3 pacts and 7 results." in result.output
    assert "3.2.2" in result.output and "feat/x" in result.output


def test_preview_with_flags_previews_a_draft_without_saving(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_POLICY, json=_SAVED)
    httpx_mock.add_response(method="POST", url=f"{_POLICY}/preview", json={**_PREVIEW, "draft": True})
    result = _invoke("preview", "--main-branch-latest", "1")
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(httpx_mock.get_requests()[1].content)
    assert body["rules"]["keep_main_branch_latest"] == 1 and body["rules"]["keep_tags"] == ["keep"]
    assert "Previewing rules that are not saved." in result.output
    assert all(request.method != "PUT" for request in httpx_mock.get_requests())


def test_preview_says_nothing_is_removed_while_clean_up_is_off() -> None:
    lines = preview_lines({**_PREVIEW, "nightly_enabled": False}, "table")
    assert lines[0] == "Nothing is removed while clean-up is off. If it were on, it would remove:"


# --- pure helpers -----------------------------------------------------------------------------


def test_merge_rules_zero_removes_a_rule_and_its_age() -> None:
    rules, changed = merge_rules(_SAVED, other_branch_latest=0)
    assert changed and rules["keep_other_branch_latest"] is None and rules["keep_other_branch_days"] is None
    rules, _ = merge_rules(_SAVED, main_branch_latest=0, no_tags=True)
    assert rules["keep_main_branch_latest"] is None and rules["keep_tags"] == []


def test_merge_rules_without_flags_changes_nothing() -> None:
    rules, changed = merge_rules(_SAVED)
    assert changed is False and rules["keep_main_branch_latest"] == 5


def test_rule_sentences_always_lead_with_deployed_and_released() -> None:
    assert rule_sentences({}) == ["Every version deployed or released anywhere (always)"]


def test_a_read_only_caller_is_told_once() -> None:
    lines = policy_lines({**_SAVED, "can_edit": False, "configured": False}, "markdown")
    assert lines[0] == "No clean-up rules saved yet; these are the defaults."
    assert lines[2].startswith("- Every version deployed")
    assert lines[-1].startswith("You can read these rules")
