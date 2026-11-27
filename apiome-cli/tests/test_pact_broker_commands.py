"""Tests for the ``pact-broker``-compatible ``apiome pact`` commands — PFX-4.1 (#6938).

Every command runs against mocked REST (``pytest-httpx``): the request it sends (path, query, body,
credential), what it prints in each output format, and its exit code — ``pact-broker``'s ``0``
success / ``1`` any failure, including every refusal (401 / 403 / 404 / 409 / 422) and every usage
error. ``PACT_BROKER_BASE_URL`` / ``PACT_BROKER_TOKEN`` are tested against the ``APIOME_*``
settings and the flags.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

runner = CliRunner()

_API = "http://localhost:8000"
_BROKER = f"{_API}/v1/tenants/acme/pact-broker"
_NATIVE = f"{_API}/v1/tenants/acme"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No credential or broker setting leaks in from the developer's shell."""
    for name in (
        "APIOME_API_KEY",
        "APIOME_BASE_URL",
        "APIOME_TENANT_ID",
        "PACT_BROKER_BASE_URL",
        "PACT_BROKER_TOKEN",
        "PACT_BROKER_USERNAME",
        "PACT_BROKER_PASSWORD",
        "GITHUB_HEAD_REF",
        "GITHUB_REF_NAME",
        "GITHUB_RUN_ID",
        "GITHUB_REPOSITORY",
        "GIT_BRANCH",
        "BUILD_URL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def apiome_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The usual APIOME_* configuration."""
    monkeypatch.setenv("APIOME_API_KEY", "apiome-key")
    monkeypatch.setenv("APIOME_BASE_URL", _API)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme")


@pytest.fixture
def broker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the variables Pact tooling reads."""
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    monkeypatch.setenv("PACT_BROKER_TOKEN", "broker-token")


def _pact(path: Path, consumer: str = "Billing", provider: str = "Ledger API") -> Path:
    path.write_text(json.dumps({"consumer": {"name": consumer}, "provider": {"name": provider}, "interactions": []}))
    return path


def _invoke(*args: str) -> Any:
    return runner.invoke(app, ["pact", *args])


def _query(request: Any) -> list[tuple[str, str]]:
    return parse_qsl(urlparse(str(request.url)).query)


# --- connection: PACT_BROKER_* and APIOME_* ---------------------------------------------------


def test_publish_with_only_the_pact_broker_variables(tmp_path: Path, broker_env: None, httpx_mock: Any) -> None:
    _pact(tmp_path / "billing-ledger.json")
    httpx_mock.add_response(
        method="POST",
        url=f"{_BROKER}/contracts/publish",
        json={"notices": [{"type": "success", "text": "Created Billing version abc with branch main"}]},
    )
    result = _invoke("publish", str(tmp_path), "-a", "abc", "--branch", "main", "-t", "rc")
    assert result.exit_code == EXIT_SUCCESS, result.output
    request = httpx_mock.get_requests()[0]
    assert request.headers["X-API-Key"] == "broker-token"
    body = json.loads(request.content)
    assert body["pacticipantName"] == "Billing" and body["branch"] == "main" and body["tags"] == ["rc"]
    assert json.loads(base64.b64decode(body["contracts"][0]["content"]))["provider"]["name"] == "Ledger API"
    assert "Created Billing version abc with branch main" in result.output


def test_the_pact_broker_variables_win_over_apiome_settings(
    tmp_path: Path, apiome_env: None, broker_env: None, httpx_mock: Any
) -> None:
    _pact(tmp_path / "p.json")
    httpx_mock.add_response(method="POST", url=f"{_BROKER}/contracts/publish", json={"notices": []})
    assert _invoke("publish", str(tmp_path / "p.json"), "-a", "1").exit_code == EXIT_SUCCESS
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "broker-token"


def test_the_command_flags_win_over_everything(
    tmp_path: Path, apiome_env: None, broker_env: None, httpx_mock: Any
) -> None:
    _pact(tmp_path / "p.json")
    other = "https://other.example.com/v1/tenants/beta/pact-broker"
    httpx_mock.add_response(method="POST", url=f"{other}/contracts/publish", json={"notices": []})
    result = _invoke("publish", str(tmp_path / "p.json"), "-a", "1", "-b", other, "-k", "flag-key")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "flag-key"


def test_root_flags_win_over_the_pact_broker_variables(tmp_path: Path, broker_env: None, httpx_mock: Any) -> None:
    _pact(tmp_path / "p.json")
    httpx_mock.add_response(
        method="POST", url="http://root.example.com/v1/tenants/zeta/pact-broker/contracts/publish", json={}
    )
    result = runner.invoke(
        app,
        [
            "--base-url",
            "http://root.example.com",
            "--api-key",
            "root-key",
            "--tenant",
            "zeta",
            "pact",
            "publish",
            str(tmp_path / "p.json"),
            "-a",
            "1",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "root-key"


def test_apiome_settings_alone_still_work(tmp_path: Path, apiome_env: None, httpx_mock: Any) -> None:
    _pact(tmp_path / "p.json")
    httpx_mock.add_response(method="POST", url=f"{_BROKER}/contracts/publish", json={})
    assert _invoke("publish", str(tmp_path / "p.json"), "-a", "1").exit_code == EXIT_SUCCESS
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "apiome-key"


def test_the_tenant_host_alias_reaches_broker_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    monkeypatch.setenv("PACT_BROKER_BASE_URL", "https://acme.pact.example.com")
    monkeypatch.setenv("PACT_BROKER_TOKEN", "t")
    _pact(tmp_path / "p.json")
    httpx_mock.add_response(method="POST", url="https://acme.pact.example.com/contracts/publish", json={})
    assert _invoke("publish", str(tmp_path / "p.json"), "-a", "1").exit_code == EXIT_SUCCESS


def test_the_tenant_host_alias_refuses_apiome_routes_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    monkeypatch.setenv("PACT_BROKER_BASE_URL", "https://acme.pact.example.com")
    monkeypatch.setenv("PACT_BROKER_TOKEN", "t")
    result = _invoke("list-pacticipants")
    assert result.exit_code == EXIT_ERROR
    assert "tenant-host alias" in result.output
    assert httpx_mock.get_requests() == []


def test_a_malformed_broker_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACT_BROKER_BASE_URL", "https://example.com/not/a/broker")
    monkeypatch.setenv("PACT_BROKER_TOKEN", "t")
    result = _invoke("list-pacticipants")
    assert result.exit_code == EXIT_ERROR
    assert "not a Pact Broker base URL" in result.output


def test_basic_auth_password_is_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    """PFX-4.2: a pipeline configured for basic auth works; the password is the key."""
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    monkeypatch.setenv("PACT_BROKER_USERNAME", "ci")
    monkeypatch.setenv("PACT_BROKER_PASSWORD", "basic-key")
    _pact(tmp_path / "p.json")
    httpx_mock.add_response(method="POST", url=f"{_BROKER}/contracts/publish", json={})
    result = _invoke("publish", str(tmp_path / "p.json"), "-a", "1")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "basic-key"


def test_a_token_wins_over_the_basic_auth_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    monkeypatch.setenv("PACT_BROKER_TOKEN", "broker-token")
    monkeypatch.setenv("PACT_BROKER_PASSWORD", "basic-key")
    _pact(tmp_path / "p.json")
    httpx_mock.add_response(method="POST", url=f"{_BROKER}/contracts/publish", json={})
    assert _invoke("publish", str(tmp_path / "p.json"), "-a", "1").exit_code == EXIT_SUCCESS
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "broker-token"


def test_a_username_without_a_password_is_reported_not_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    monkeypatch.setenv("PACT_BROKER_USERNAME", "ci")
    result = _invoke("list-pacticipants")
    assert result.exit_code == EXIT_ERROR
    assert "PACT_BROKER_PASSWORD" in result.output and "API key" in result.output


def test_no_credential_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACT_BROKER_BASE_URL", _BROKER)
    result = _invoke("list-pacticipants")
    assert result.exit_code == EXIT_ERROR
    assert "PACT_BROKER_TOKEN" in result.output


def test_a_key_of_another_workspace_is_refused_by_the_server(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=403, json={"detail": "This credential belongs to another tenant."}
    )
    result = _invoke("list-pacticipants")
    assert result.exit_code == EXIT_ERROR
    assert "another tenant" in result.output


# --- publish -----------------------------------------------------------------------------------


def test_publish_refuses_a_non_pact_before_sending_anything(tmp_path: Path, broker_env: None, httpx_mock: Any) -> None:
    _pact(tmp_path / "a.json")
    (tmp_path / "b.json").write_text('{"openapi": "3.1.0"}')
    result = _invoke("publish", str(tmp_path), "-a", "1")
    assert result.exit_code == EXIT_ERROR
    assert "b.json: not a pact" in result.output
    assert httpx_mock.get_requests() == []


def test_publish_refuses_merge_with_the_reason(tmp_path: Path, broker_env: None) -> None:
    _pact(tmp_path / "a.json")
    result = _invoke("publish", str(tmp_path), "-a", "1", "--merge")
    assert result.exit_code == EXIT_ERROR
    assert "does not merge" in result.output


def test_publish_needs_a_version(tmp_path: Path, broker_env: None) -> None:
    _pact(tmp_path / "a.json")
    result = _invoke("publish", str(tmp_path))
    assert result.exit_code == EXIT_ERROR
    assert "consumer version" in result.output


def test_publish_sends_one_request_per_consumer(tmp_path: Path, broker_env: None, httpx_mock: Any) -> None:
    _pact(tmp_path / "a.json", consumer="Billing")
    _pact(tmp_path / "b.json", consumer="Web")
    httpx_mock.add_response(method="POST", url=f"{_BROKER}/contracts/publish", json={"notices": [{"text": "one"}]})
    httpx_mock.add_response(method="POST", url=f"{_BROKER}/contracts/publish", json={"notices": [{"text": "two"}]})
    result = runner.invoke(app, ["--json", "pact", "publish", str(tmp_path), "-a", "1"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert [json.loads(r.content)["pacticipantName"] for r in httpx_mock.get_requests()] == ["Billing", "Web"]
    assert [item["notices"][0]["text"] for item in json.loads(result.output)] == ["one", "two"]


def test_publish_auto_detects_branch_and_build_url(
    tmp_path: Path, broker_env: None, monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/billing")
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    _pact(tmp_path / "a.json")
    httpx_mock.add_response(method="POST", json={})
    result = _invoke("publish", str(tmp_path), "-a", "1", "-r", "-g")
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["branch"] == "main" and body["tags"] == ["main"]
    assert body["buildUrl"] == "https://github.com/acme/billing/actions/runs/9"


def test_publish_conflict_exits_1_with_the_server_message(tmp_path: Path, broker_env: None, httpx_mock: Any) -> None:
    _pact(tmp_path / "a.json")
    httpx_mock.add_response(
        method="POST",
        status_code=409,
        json={"detail": {"code": "pact-conflict", "message": "Version 1 already published a different pact"}},
    )
    result = _invoke("publish", str(tmp_path), "-a", "1")
    assert result.exit_code == EXIT_ERROR
    assert "already published a different pact" in result.output


# --- list-pacticipants / describe-version -----------------------------------------------------


def test_list_pacticipants_reads_every_page(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url=f"{_NATIVE}/pacticipants?limit=200&label=web",
        json={"pacticipants": [{"name": "Billing", "slug": "billing"}], "count": 1, "has_more": True, "next_cursor": "c2"},
    )
    httpx_mock.add_response(
        url=f"{_NATIVE}/pacticipants?limit=200&label=web&cursor=c2",
        json={"pacticipants": [{"name": "Web", "slug": "web", "labels": ["web"]}], "count": 1, "has_more": False},
    )
    result = _invoke("list-pacticipants", "--label", "web", "-o", "markdown")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "| NAME | HANDLE | MAIN BRANCH | REPOSITORY | LABELS |" in result.output
    assert "| Billing | billing |" in result.output and "| Web | web |" in result.output


def test_list_pacticipants_json(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json={"pacticipants": [{"name": "Billing"}], "count": 1})
    result = _invoke("list-pacticipants", "-o", "json")
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.output) == {"pacticipants": [{"name": "Billing"}], "count": 1}


def test_an_unknown_output_format_exits_1(broker_env: None) -> None:
    result = _invoke("list-pacticipants", "-o", "yaml")
    assert result.exit_code == EXIT_ERROR
    assert "table, json, markdown" in result.output


def test_describe_version_reads_the_broker_version(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url=f"{_BROKER}/pacticipants/Billing/versions/1.0%2Brc",
        json={
            "number": "1.0+rc",
            "buildUrl": "https://ci/1",
            "createdAt": "2026-11-01T00:00:00Z",
            "_embedded": {"branchVersions": [{"name": "main"}], "tags": [{"name": "prod"}]},
        },
    )
    result = _invoke("describe-version", "-a", "Billing", "-e", "1.0+rc")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "1.0+rc" in result.output and "main" in result.output and "prod" in result.output


def test_describe_version_latest_with_a_tag(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url=f"{_NATIVE}/pacticipants/Billing/versions?limit=1&tag=prod",
        json={"versions": [{"number": "9", "branches": [], "tags": ["prod"]}], "count": 1},
    )
    result = _invoke("describe-version", "-a", "Billing", "-l", "--tag", "prod")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "| 9 " in result.output


def test_describe_version_without_versions_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json={"versions": [], "count": 0})
    result = _invoke("describe-version", "-a", "Billing")
    assert result.exit_code == EXIT_ERROR
    assert "Billing has no version" in result.output


def test_describe_version_unknown_version_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(status_code=404, json={"detail": {"code": "pacticipant-version-not-found", "message": "No version 7"}})
    result = _invoke("describe-version", "-a", "Billing", "-e", "7")
    assert result.exit_code == EXIT_ERROR
    assert "No version 7" in result.output


# --- can-i-deploy ------------------------------------------------------------------------------


def _matrix(deployable: Any) -> dict[str, Any]:
    return {
        "summary": {"deployable": deployable, "reason": "reason text", "success": 1, "failed": 0, "unknown": 0},
        "notices": [],
        "matrix": [
            {
                "consumer": {"name": "Billing", "version": {"number": "abc"}},
                "provider": {"name": "Ledger", "version": {"number": "1"}},
                "verificationResult": {"success": True, "_links": {"self": {"href": "x/verification-results/3"}}},
            }
        ],
    }


def test_can_i_deploy_yes_exits_0_and_sends_the_pact_broker_query(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_matrix(True))
    result = _invoke(
        "can-i-deploy", "-a", "Billing", "-e", "abc", "--to-environment", "production", "--ignore", "Legacy"
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    request = httpx_mock.get_requests()[0]
    assert urlparse(str(request.url)).path == "/v1/tenants/acme/pact-broker/matrix"
    assert _query(request) == [
        ("q[][pacticipant]", "Billing"),
        ("q[][version]", "abc"),
        ("latestby", "cvp"),
        ("environment", "production"),
        ("ignore[][pacticipant]", "Legacy"),
    ]
    assert "Computer says yes \\o/" in result.output and "reason text" in result.output


def test_can_i_deploy_no_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_matrix(False))
    result = _invoke("can-i-deploy", "-a", "Billing", "-e", "abc", "--to-environment", "production")
    assert result.exit_code == EXIT_ERROR
    assert "Computer says no" in result.output


def test_can_i_deploy_dry_run_exits_0(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_matrix(False))
    result = _invoke("can-i-deploy", "-a", "Billing", "-e", "abc", "--to-environment", "prod", "--dry-run")
    assert result.exit_code == EXIT_SUCCESS
    assert "dry-run" in result.output


def test_can_i_deploy_retries_while_unknown(
    broker_env: None, monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("apiome_cli.commands.pact_broker.time.sleep", sleeps.append)
    httpx_mock.add_response(json=_matrix(None))
    httpx_mock.add_response(json=_matrix(True))
    result = _invoke(
        "can-i-deploy", "-a", "Billing", "-e", "abc", "--to-environment", "prod",
        "--retry-while-unknown", "3", "--retry-interval", "5",
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert sleeps == [5.0]
    assert "Retried 1 time(s)" in result.output


def test_can_i_deploy_still_unknown_after_retries_exits_1(
    broker_env: None, monkeypatch: pytest.MonkeyPatch, httpx_mock: Any
) -> None:
    monkeypatch.setattr("apiome_cli.commands.pact_broker.time.sleep", lambda _s: None)
    httpx_mock.add_response(json=_matrix(None), is_reusable=True)
    result = _invoke("can-i-deploy", "-a", "Billing", "-e", "abc", "--to-environment", "prod", "--retry-while-unknown", "2")
    assert result.exit_code == EXIT_ERROR
    assert len(httpx_mock.get_requests()) == 3


def test_can_i_deploy_json_is_the_matrix_document(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_matrix(True))
    result = _invoke("can-i-deploy", "-a", "Billing", "-l", "--to", "prod", "-o", "json")
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.output)["summary"]["deployable"] is True


@pytest.mark.parametrize(
    "args",
    [
        ["-a", "Billing", "-a", "Web", "-e", "1"],
        ["-a", "Billing"],
        ["-a", "Billing", "-e", "1", "--to", "prod", "--to-environment", "prod"],
        ["-e", "1"],
    ],
)
def test_can_i_deploy_usage_errors_exit_1_without_a_request(args: list[str], broker_env: None, httpx_mock: Any) -> None:
    result = _invoke("can-i-deploy", *args)
    assert result.exit_code == EXIT_ERROR
    assert httpx_mock.get_requests() == []


def test_can_i_deploy_without_pacts_view_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(status_code=403, json={"detail": "Missing permission pacts:view"})
    result = _invoke("can-i-deploy", "-a", "Billing", "-e", "abc", "--to-environment", "prod")
    assert result.exit_code == EXIT_ERROR
    assert "pacts:view" in result.output


# --- record-deployment / record-release --------------------------------------------------------

_ENVIRONMENTS = {"_embedded": {"environments": [{"uuid": "env-1", "name": "production"}]}}


def test_record_deployment_looks_up_the_environment(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(url=f"{_BROKER}/environments?name=production", json=_ENVIRONMENTS)
    httpx_mock.add_response(
        method="POST",
        url=f"{_BROKER}/pacticipants/Billing/versions/abc/deployed-versions/environment/env-1",
        json={"uuid": "d1"},
        status_code=201,
    )
    result = _invoke(
        "record-deployment", "-a", "Billing", "-e", "abc", "--environment", "production", "--application-instance", "eu"
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(httpx_mock.get_requests()[1].content) == {"applicationInstance": "eu"}
    assert "Recorded deployment of Billing version abc to production environment" in result.output


def test_record_release(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(url=f"{_BROKER}/environments?name=production", json=_ENVIRONMENTS)
    httpx_mock.add_response(
        method="POST",
        url=f"{_BROKER}/pacticipants/Billing/versions/abc/released-versions/environment/env-1",
        json={"uuid": "r1"},
    )
    result = _invoke("record-release", "-a", "Billing", "-e", "abc", "--environment", "production")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(httpx_mock.get_requests()[1].content) == {}
    assert "Recorded release of Billing version abc" in result.output


def test_record_deployment_to_an_unknown_environment_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json={"_embedded": {"environments": []}})
    result = _invoke("record-deployment", "-a", "Billing", "-e", "abc", "--environment", "staging")
    assert result.exit_code == EXIT_ERROR
    assert "create-environment --name staging" in result.output


def test_record_deployment_of_an_unknown_version_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_ENVIRONMENTS)
    httpx_mock.add_response(method="POST", status_code=404, json={"detail": {"code": "x", "message": "No version abc"}})
    result = _invoke("record-deployment", "-a", "Billing", "-e", "abc", "--environment", "production")
    assert result.exit_code == EXIT_ERROR
    assert "No version abc" in result.output


# --- create-environment / create-webhook -------------------------------------------------------


def test_create_environment(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{_BROKER}/environments", status_code=201, json={"uuid": "e9", "name": "production"}
    )
    result = _invoke(
        "create-environment", "--name", "production", "--production", "--contact-name", "Ledger",
        "--contact-email-address", "ledger@example.com",
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["production"] is True and body["contacts"][0]["details"] == {"emailAddress": "ledger@example.com"}
    assert "Created production environment in the Pact Broker with UUID e9" in result.output


def test_create_environment_taken_name_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(method="POST", status_code=409, json={"detail": {"code": "c", "message": "name taken"}})
    result = _invoke("create-environment", "--name", "production")
    assert result.exit_code == EXIT_ERROR
    assert "name taken" in result.output


def test_create_webhook(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{_BROKER}/webhooks",
        status_code=201,
        json={"uuid": "w1", "description": "Build", "events": [{"name": "contract_requiring_verification_published"}]},
    )
    result = _invoke(
        "create-webhook", "https://ci.example.com/build", "-X", "POST", "-H", "Content-Type: application/json",
        "-d", '{"a": 1}', "-u", "ci:secret", "--provider", "Ledger", "--description", "Build",
        "--contract-requiring-verification-published",
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["request"]["body"] == {"a": 1} and body["provider"] == {"name": "Ledger"}
    assert body["events"] == [{"name": "contract_requiring_verification_published"}]
    assert "created with UUID w1" in result.output and "secret" not in result.output


def test_create_webhook_without_an_event_exits_1(broker_env: None, httpx_mock: Any) -> None:
    result = _invoke("create-webhook", "https://ci.example.com/build")
    assert result.exit_code == EXIT_ERROR
    assert "at least one event" in result.output
    assert httpx_mock.get_requests() == []


# --- verify / migrate --------------------------------------------------------------------------

_VERIFY = {
    "provider": "ledger",
    "provider_version": "1",
    "target": {"target_id": "t", "slug": "staging", "base_url": "https://staging", "protocol": "http"},
    "success": True,
    "outcome": "passed",
    "pacts": [{"consumer_name": "Billing", "consumer_version": "abc", "outcome": "passed", "published": True}],
}


def test_verify_success_exits_0(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(method="POST", url=f"{_NATIVE}/pact-verifier/pacts/provider/Ledger/verify", json=_VERIFY)
    result = _invoke(
        "verify", "--provider", "Ledger", "-a", "1", "--target", "staging", "--branch", "main",
        "--consumer-version-selector", '{"mainBranch": true}', "--enable-pending", "--context", "commit=abc",
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["selection"] == {"consumerVersionSelectors": [{"mainBranch": True}], "includePendingStatus": True}
    assert body["provider_branch"] == "main" and body["context"] == {"commit": "abc"}
    assert "Verification of ledger 1 against staging: passed" in result.output


def test_verify_failure_exits_1(broker_env: None, httpx_mock: Any) -> None:
    httpx_mock.add_response(method="POST", json={**_VERIFY, "success": False, "outcome": "failed"})
    result = _invoke("verify", "--provider", "Ledger", "-a", "1", "--target", "staging", "--no-publish-verification-results")
    assert result.exit_code == EXIT_ERROR
    assert json.loads(httpx_mock.get_requests()[0].content)["publish"] is False


def test_verify_bad_selector_exits_1_without_a_request(broker_env: None, httpx_mock: Any) -> None:
    result = _invoke("verify", "--provider", "L", "-a", "1", "--target", "s", "--consumer-version-selector", "nope")
    assert result.exit_code == EXIT_ERROR
    assert "not JSON" in result.output
    assert httpx_mock.get_requests() == []


def test_migrate_without_from_exits_1() -> None:
    """The migration itself is tested in ``test_pact_migrate`` (PFX-6.7, #6959)."""
    assert _invoke("migrate").exit_code == EXIT_ERROR


def test_an_unknown_subcommand_exits_1() -> None:
    assert _invoke("create-or-update-pacticipant").exit_code == EXIT_ERROR
