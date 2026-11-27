"""Unit tests for the pure parts of the ``pact-broker``-compatible commands — PFX-4.1 (#6938).

Broker base URL parsing, pact reading and grouping, the can-i-deploy matrix query, the bodies of
create-environment / create-webhook / verify, CI branch detection, and the output renderers. No
HTTP here; the commands are tested in ``test_pact_broker_commands.py``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from apiome_cli.client.pact_broker_connection import parse_broker_base_url
from apiome_cli.client.pact_broker_requests import (
    MAX_CONTRACTS_PER_PUBLISH,
    CanIDeployQuery,
    PactFile,
    build_environment_body,
    build_publish_bodies,
    build_verify_body,
    build_webhook_body,
    collect_pact_paths,
    deployable,
    detect_version_properties,
    parse_context,
    parse_selectors,
    read_pact_file,
)
from apiome_cli.pact_broker_output import (
    can_i_deploy_lines,
    native_version_document,
    pacticipant_lines,
    publish_lines,
    recorded_lines,
    table,
    validate_output,
    verify_lines,
    version_lines,
    webhook_created_lines,
)


def _pact(consumer: str = "Billing", provider: str = "Ledger API") -> bytes:
    return json.dumps({"consumer": {"name": consumer}, "provider": {"name": provider}, "interactions": []}).encode()


# --- broker base URL ---------------------------------------------------------------------------


def test_the_path_form_names_the_api_root_and_the_workspace() -> None:
    address = parse_broker_base_url("https://api.example.com/v1/tenants/acme/pact-broker/")
    assert address.root == "https://api.example.com"
    assert address.tenant == "acme"


def test_the_path_form_keeps_a_mount_prefix() -> None:
    address = parse_broker_base_url("https://example.com/apiome/v1/tenants/acme/pact-broker")
    assert address.root == "https://example.com/apiome"
    assert address.tenant == "acme"


def test_a_bare_host_is_the_tenant_host_alias() -> None:
    address = parse_broker_base_url("https://acme.pact.example.com")
    assert address.root == "https://acme.pact.example.com"
    assert address.tenant is None


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/v1/tenants/acme/pact-broker",
        "example.com",
        "https://example.com/some/other/path",
        "https://example.com/v1/tenants/acme/pact-broker?x=1",
    ],
)
def test_other_urls_are_refused_with_the_reason(url: str) -> None:
    with pytest.raises(ValueError):
        parse_broker_base_url(url)


# --- publish -----------------------------------------------------------------------------------


def test_directories_expand_to_their_json_files_in_name_order(tmp_path: Path) -> None:
    (tmp_path / "b.json").write_bytes(_pact())
    (tmp_path / "a.json").write_bytes(_pact())
    (tmp_path / "notes.txt").write_text("x")
    assert collect_pact_paths([tmp_path]) == [tmp_path / "a.json", tmp_path / "b.json"]
    assert collect_pact_paths([tmp_path / "b.json", tmp_path]) == [
        tmp_path / "b.json",
        tmp_path / "a.json",
        tmp_path / "b.json",
    ]


def test_an_empty_directory_or_missing_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no \\*.json"):
        collect_pact_paths([tmp_path])
    with pytest.raises(ValueError, match="no such file"):
        collect_pact_paths([tmp_path / "missing.json"])
    with pytest.raises(ValueError, match="at least one"):
        collect_pact_paths([])


def test_a_pact_file_is_read_with_its_names(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_bytes(_pact())
    pact = read_pact_file(path)
    assert (pact.consumer, pact.provider, pact.content) == ("Billing", "Ledger API", _pact())


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"not json", "not JSON"),
        (b"[1, 2]", "not a JSON object"),
        (b'{"provider": {"name": "p"}}', "consumer.name"),
        (b'{"consumer": {"name": "c"}, "provider": {}}', "provider.name"),
    ],
)
def test_a_file_that_is_not_a_pact_is_refused_with_the_reason(tmp_path: Path, content: bytes, reason: str) -> None:
    path = tmp_path / "p.json"
    path.write_bytes(content)
    with pytest.raises(ValueError, match=reason):
        read_pact_file(path)


def test_publish_bodies_group_by_consumer_and_carry_the_version_properties() -> None:
    pacts = [
        PactFile(Path("a"), "Billing", "Ledger", _pact("Billing", "Ledger")),
        PactFile(Path("b"), "Web", "Ledger", _pact("Web", "Ledger")),
        PactFile(Path("c"), "Billing", "Users", _pact("Billing", "Users")),
    ]
    bodies = build_publish_bodies(pacts, consumer_app_version="abc", branch="main", tags=["rc"], build_url="https://ci/1")
    assert [body["pacticipantName"] for body in bodies] == ["Billing", "Web"]
    billing = bodies[0]
    assert billing["pacticipantVersionNumber"] == "abc"
    assert billing["branch"] == "main" and billing["tags"] == ["rc"] and billing["buildUrl"] == "https://ci/1"
    assert [c["providerName"] for c in billing["contracts"]] == ["Ledger", "Users"]
    assert base64.b64decode(billing["contracts"][0]["content"]) == _pact("Billing", "Ledger")
    assert billing["contracts"][0]["specification"] == "pact"


def test_publish_bodies_leave_out_what_was_not_given_and_split_large_consumers() -> None:
    pacts = [PactFile(Path(str(i)), "Billing", f"P{i}", _pact("Billing", f"P{i}")) for i in range(101)]
    bodies = build_publish_bodies(pacts, consumer_app_version="1", branch=None, tags=None, build_url=None)
    assert [len(body["contracts"]) for body in bodies] == [MAX_CONTRACTS_PER_PUBLISH, 1]
    assert set(bodies[0]) == {"pacticipantName", "pacticipantVersionNumber", "contracts"}
    with pytest.raises(ValueError, match="empty"):
        build_publish_bodies(pacts, consumer_app_version=" ", branch=None, tags=None, build_url=None)


# --- auto-detect -------------------------------------------------------------------------------


def test_github_actions_branch_and_build_url_are_detected() -> None:
    env = {
        "GITHUB_HEAD_REF": "feat/x",
        "GITHUB_REF_NAME": "12/merge",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "acme/web",
        "GITHUB_RUN_ID": "42",
    }
    found = detect_version_properties(env, git_branch=lambda: "ignored")
    assert found.branch == "feat/x"
    assert found.build_url == "https://github.com/acme/web/actions/runs/42"


def test_jenkins_origin_prefix_is_removed_and_git_is_the_fallback() -> None:
    found = detect_version_properties({"GIT_BRANCH": "origin/main", "BUILD_URL": "https://jenkins/1"})
    assert (found.branch, found.build_url) == ("main", "https://jenkins/1")
    assert detect_version_properties({}, git_branch=lambda: "dev").branch == "dev"
    assert detect_version_properties({}, git_branch=lambda: None).branch is None


# --- can-i-deploy ------------------------------------------------------------------------------


def test_the_matrix_query_matches_pact_broker() -> None:
    query = CanIDeployQuery(pacticipant="Billing", version="abc", to_environment="production", ignore=("Legacy",))
    assert query.matrix_params() == [
        ("q[][pacticipant]", "Billing"),
        ("q[][version]", "abc"),
        ("latestby", "cvp"),
        ("environment", "production"),
        ("ignore[][pacticipant]", "Legacy"),
    ]


def test_latest_tagged_to_a_tag_and_branch_selectors() -> None:
    assert CanIDeployQuery(pacticipant="B", latest=True, tag="rc", to="prod").matrix_params() == [
        ("q[][pacticipant]", "B"),
        ("q[][latest]", "true"),
        ("q[][tag]", "rc"),
        ("latestby", "cvp"),
        ("latest", "true"),
        ("tag", "prod"),
    ]
    assert ("q[][branch]", "main") in CanIDeployQuery(pacticipant="B", branch="main").matrix_params()
    assert ("q[][mainBranch]", "true") in CanIDeployQuery(pacticipant="B", main_branch=True).matrix_params()


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        (CanIDeployQuery(pacticipant="B"), "exactly one way"),
        (CanIDeployQuery(pacticipant="B", version="1", latest=True), "exactly one way"),
        (CanIDeployQuery(pacticipant="B", version="1", tag="rc"), "--tag"),
        (CanIDeployQuery(pacticipant="B", version="1", to="prod", to_environment="prod"), "not both"),
        (CanIDeployQuery(pacticipant=" ", version="1"), "empty"),
    ],
)
def test_an_ambiguous_query_is_refused(query: CanIDeployQuery, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        query.validate()


def test_the_verdict_reads_summary_deployable() -> None:
    assert deployable({"summary": {"deployable": True}}) is True
    assert deployable({"summary": {"deployable": False}}) is False
    assert deployable({"summary": {"deployable": None}}) is None
    assert deployable({}) is None


# --- environments, webhooks, verify -----------------------------------------------------------


def test_the_environment_body() -> None:
    body = build_environment_body(
        name="production",
        display_name="Production",
        production=True,
        contract_required=True,
        contact_name="Team Ledger",
        contact_email_address="ledger@example.com",
    )
    assert body == {
        "name": "production",
        "production": True,
        "displayName": "Production",
        "contractRequired": True,
        "contacts": [{"name": "Team Ledger", "details": {"emailAddress": "ledger@example.com"}}],
    }
    with pytest.raises(ValueError, match="one word"):
        build_environment_body(
            name="two words", display_name=None, production=False, contract_required=False,
            contact_name=None, contact_email_address=None,
        )
    with pytest.raises(ValueError, match="--contact-name"):
        build_environment_body(
            name="test", display_name=None, production=False, contract_required=False,
            contact_name=None, contact_email_address="a@example.com",
        )


def _webhook(**overrides: object) -> dict:
    options: dict = dict(
        url="https://ci.example.com/hook",
        method="POST",
        headers=["Content-Type: application/json"],
        data='{"event": "${pactbroker.eventName}"}',
        user=None,
        consumer="Billing",
        provider=None,
        description="Run provider build",
        events=["contract_requiring_verification_published"],
    )
    options.update(overrides)
    return build_webhook_body(**options)


def test_the_webhook_body() -> None:
    body = _webhook(user="ci:s3cret")
    assert body["events"] == [{"name": "contract_requiring_verification_published"}]
    assert body["request"] == {
        "method": "POST",
        "url": "https://ci.example.com/hook",
        "headers": {"Content-Type": "application/json"},
        "body": {"event": "${pactbroker.eventName}"},
        "username": "ci",
        "password": "s3cret",
    }
    assert body["consumer"] == {"name": "Billing"} and "provider" not in body
    assert body["description"] == "Run provider build"


def test_a_webhook_body_from_a_file_or_plain_text() -> None:
    assert _webhook(data="@body.json", read_file=lambda path: '{"a": 1}')["request"]["body"] == {"a": 1}
    assert _webhook(data="plain text")["request"]["body"] == "plain text"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"method": "GET"}, "POST, PUT, PATCH"),
        ({"events": []}, "at least one event"),
        ({"url": "ftp://x"}, "http"),
        ({"headers": ["no colon"]}, "Name: value"),
        ({"user": "nopassword"}, "username:password"),
    ],
)
def test_a_webhook_the_broker_would_refuse_is_refused_first(overrides: dict, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        _webhook(**overrides)


def test_the_verify_body_has_only_what_was_given() -> None:
    minimal = build_verify_body(
        target="staging", provider_app_version="1", branch=None, build_url=None, selectors=[],
        include_pending=False, include_wip_pacts_since=None, allow_mutating=False,
        replay_without_state_setup=False, publish=True, context={},
    )
    assert minimal == {"target_ref": "staging", "provider_version": "1", "publish": True}
    full = build_verify_body(
        target="staging", provider_app_version="1", branch="main", build_url="https://ci/1",
        selectors=[{"mainBranch": True}], include_pending=True, include_wip_pacts_since="2026-01-01",
        allow_mutating=True, replay_without_state_setup=True, publish=False, context={"commit": "abc"},
    )
    assert full["selection"] == {
        "consumerVersionSelectors": [{"mainBranch": True}],
        "includePendingStatus": True,
        "includeWipPactsSince": "2026-01-01",
    }
    assert full["verification"] == {"allow_mutating": True, "replay_without_state_setup": True}
    assert full["provider_branch"] == "main" and full["publish"] is False and full["context"] == {"commit": "abc"}


def test_the_verify_body_carries_the_setup_url_and_the_skip_switch() -> None:
    common = dict(
        target="staging", provider_app_version="1", branch=None, build_url=None, selectors=[],
        include_pending=False, include_wip_pacts_since=None, allow_mutating=False,
        replay_without_state_setup=False, publish=True, context={},
    )
    body = build_verify_body(**common, provider_states_setup_url=" /_pact/states ", skip_already_verified=True)
    assert body["verification"] == {"provider_states_setup_url": "/_pact/states"}
    assert body["skip_already_verified"] is True
    absolute = build_verify_body(**common, provider_states_setup_url="https://states.example/setup")
    assert absolute["verification"]["provider_states_setup_url"] == "https://states.example/setup"
    assert "skip_already_verified" not in absolute
    for bad in ("//elsewhere/x", "ftp://x/y", "states"):
        with pytest.raises(ValueError, match="path on the target"):
            build_verify_body(**common, provider_states_setup_url=bad)


def test_selectors_and_context_are_checked() -> None:
    assert parse_selectors(['{"deployedOrReleased": true}']) == [{"deployedOrReleased": True}]
    with pytest.raises(ValueError, match="not JSON"):
        parse_selectors(["{nope"])
    with pytest.raises(ValueError, match="JSON object"):
        parse_selectors(["[1]"])
    assert parse_context(["commit=abc", "url=a=b"]) == {"commit": "abc", "url": "a=b"}
    with pytest.raises(ValueError, match="KEY=VALUE"):
        parse_context(["nothing"])


# --- output ------------------------------------------------------------------------------------


def test_output_choices() -> None:
    assert validate_output("JSON") == "json"
    assert validate_output("md") == "markdown"
    with pytest.raises(ValueError, match="table, json, markdown"):
        validate_output("yaml")


def test_tables_as_text_and_markdown() -> None:
    assert table(("A", "BB"), [("x|y", None)], "markdown") == ["| A | BB |", "|---|---|", "| x\\|y |  |"]
    text = table(("NAME", "N"), [("long-name", 1), ("a", True)], "table")
    assert text[0] == "NAME      | N"
    assert text[2] == "long-name | 1"
    assert text[3] == "a         | true"


_MATRIX = {
    "summary": {"deployable": False, "reason": "The verification for the pact between Billing (abc) and Ledger (1) failed"},
    "notices": [{"type": "error", "text": "The verification … failed"}, {"type": "info", "text": "fyi"}],
    "matrix": [
        {
            "consumer": {"name": "Billing", "version": {"number": "abc"}},
            "provider": {"name": "Ledger", "version": {"number": "1"}},
            "verificationResult": {"success": False, "_links": {"self": {"href": "https://x/verification-results/7"}}},
        },
        {
            "consumer": {"name": "Billing", "version": {"number": "abc"}},
            "provider": {"name": "Users", "version": None},
            "verificationResult": None,
        },
    ],
}


def test_can_i_deploy_prints_rows_the_verdict_and_the_notices() -> None:
    lines = can_i_deploy_lines(_MATRIX, "table")
    assert lines[0].startswith("CONSUMER")
    assert "Billing  | abc       | Ledger   | 1         | false    | 7" in lines
    assert any("???" in line for line in lines)
    assert "Computer says no ¯\\_(ツ)_/¯" in lines
    assert "error: The verification … failed" in lines and "fyi" in lines


def test_can_i_deploy_yes_unknown_dry_run_and_markdown() -> None:
    assert "Computer says yes \\o/" in can_i_deploy_lines({"summary": {"deployable": True}}, "table")
    unknown = can_i_deploy_lines({"summary": {"deployable": None}}, "table", retries=2, dry_run=True)
    assert any("missing" in line for line in unknown)
    assert any("Retried 2" in line for line in unknown) and any("dry-run" in line for line in unknown)
    md = can_i_deploy_lines(_MATRIX, "markdown")
    assert md[0].startswith("| CONSUMER") and "**Computer says no ¯\\_(ツ)_/¯**" in md
    assert "- error: The verification … failed" in md


def test_publish_lines_print_notices_or_the_version() -> None:
    assert publish_lines([{"notices": [{"type": "success", "text": "Created pact"}]}], "table") == ["Created pact"]
    fallback = publish_lines(
        [{"_embedded": {"pacticipant": {"name": "Billing"}, "version": {"number": "abc"}}}], "markdown"
    )
    assert fallback == ["- Published the pacts of Billing version abc"]


def test_pacticipant_and_version_lines() -> None:
    assert pacticipant_lines([], "table") == ["No pacticipants."]
    rows = pacticipant_lines([{"name": "Billing", "slug": "billing", "main_branch": "main", "labels": ["web"]}], "table")
    assert "Billing | billing | main" in rows[2]
    document = native_version_document(
        {"number": "abc", "build_url": "https://ci/1", "created_at": "2026-11-01", "branches": ["main"], "tags": ["rc"]}
    )
    lines = version_lines(document, "Billing", "table")
    assert "Billing     | abc     | main     | rc   | https://ci/1 | 2026-11-01" == lines[2]


def test_recorded_webhook_and_verify_lines() -> None:
    assert recorded_lines("deployment", pacticipant="B", version="1", environment="prod", application_instance="eu") == [
        "Recorded deployment of B version 1 to prod environment (application instance eu) in the Pact Broker."
    ]
    assert webhook_created_lines({"uuid": "u1", "description": "hook", "events": [{"name": "contract_published"}]}) == [
        "Webhook 'hook' created with UUID u1",
        "  events: contract_published",
    ]
    response = {
        "provider": "ledger",
        "provider_version": "1",
        "target": {"slug": "staging"},
        "outcome": "incomplete",
        "pacts": [
            {
                "consumer_name": "Billing",
                "consumer_version": "abc",
                "outcome": "incomplete",
                "pending": False,
                "counts": {"passed": 2, "skipped": 1},
                "published": False,
                "not_published_reason": "run-incomplete",
                "unsupported": [{"operation_key": "msg-1", "code": "message", "reason": "message interactions"}],
            }
        ],
    }
    lines = verify_lines(response, "table")
    assert "passed 2, skipped 1" in lines[2] and "no (run-incomplete)" in lines[2]
    assert "Verification of ledger 1 against staging: incomplete" in lines
    assert "  not replayed: msg-1 (message): message interactions" in lines


def test_verify_lines_say_why_a_run_did_not_reach_the_target_and_what_it_skipped() -> None:
    response = {
        "provider": "ledger",
        "provider_version": "1",
        "target": {"slug": "staging"},
        "outcome": "could-not-connect",
        "connection_error": "Could not connect to ledger.example (timeout)",
        "skipped": [{"consumer_name": "Billing", "reason": "already verified for 1 (result 2, passed)"}],
        "pacts": [],
    }
    lines = verify_lines(response, "table")
    assert "Verification of ledger 1 against staging: could-not-connect" in lines
    assert "  Could not connect to ledger.example (timeout) — not a failed verification; nothing was published." in lines
    assert "  skipped: Billing — already verified for 1 (result 2, passed)" in lines
