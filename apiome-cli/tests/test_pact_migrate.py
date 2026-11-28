"""``apiome pact migrate`` — PFX-6.7 (#6959).

The command runs against a mocked source broker and a mocked Apiome (``pytest-httpx``): what it reads
from the source (and that the token never leaves the source host), what it sends to
``…/pact-migration/import`` (records in dependency order, versions oldest first, the source's
timestamps), what it reports as not portable, how it resumes from its state file, the dry run, and
its exit codes. The pure record building is ``test_pact_migration_plan``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

runner = CliRunner()

SOURCE = "https://broker.example.com"
TARGET = "http://localhost:8000/v1/tenants/acme/pact-broker"
IMPORT = "http://localhost:8000/v1/tenants/acme/pact-migration/import"
CHECK = "http://localhost:8000/v1/tenants/acme/pact-migration/check"
RESULT = f"{SOURCE}/pacts/provider/Ledger/consumer/Billing/pact-version/abc/verification-results/3"
PACT = f"{SOURCE}/pacts/provider/Ledger/consumer/Billing/version/1.0.0"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No credential leaks in from the shell; the target is PACT_BROKER_*; runs in a temp dir."""
    for name in (
        "APIOME_API_KEY",
        "APIOME_BASE_URL",
        "APIOME_TENANT_ID",
        "PACT_BROKER_USERNAME",
        "PACT_BROKER_PASSWORD",
        "PACT_SOURCE_BROKER_TOKEN",
        "PACT_SOURCE_BROKER_USERNAME",
        "PACT_SOURCE_BROKER_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PACT_BROKER_BASE_URL", TARGET)
    monkeypatch.setenv("PACT_BROKER_TOKEN", "apiome-key")
    monkeypatch.chdir(tmp_path)


def _source_documents(*, secrets: bool = True) -> dict[str, Any]:
    """What a small PactFlow workspace answers, by path (and query)."""
    documents: dict[str, Any] = {
        "/pacticipants?size=100": {
            "_embedded": {
                "pacticipants": [
                    {
                        "name": "Billing",
                        "displayName": "Billing Service",
                        "mainBranch": "main",
                        "repositoryUrl": "https://github.com/acme/billing",
                        "createdAt": "2025-03-01T09:00:00+00:00",
                        "_embedded": {"labels": [{"name": "team-billing"}]},
                    }
                ]
            },
            # A broker behind a proxy advertises its internal address: the CLI stays on --from.
            "_links": {
                "next": {
                    "href": "http://pact-broker.internal:9292/pacticipants?page=2&size=100"
                }
            },
        },
        "/pacticipants?page=2&size=100": {
            "_embedded": {"pacticipants": [{"name": "Ledger"}]}
        },
        "/pacticipants/Billing/versions?size=100": {
            "_embedded": {
                "versions": [  # newest first, as the Pact Broker lists them
                    {"number": "1.1.0", "createdAt": "2025-03-03T09:00:00+00:00"},
                    {
                        "number": "1.0.0",
                        "buildUrl": "https://ci.example.com/1",
                        "createdAt": "2025-03-02T09:00:00+00:00",
                        "_embedded": {
                            "branchVersions": [{"name": "main"}],
                            "tags": [
                                {
                                    "name": "prod",
                                    "createdAt": "2025-03-04T09:00:00+00:00",
                                }
                            ],
                        },
                    },
                ]
            }
        },
        "/pacticipants/Ledger/versions?size=100": {
            "_embedded": {
                "versions": [
                    {"number": "7.0.0", "createdAt": "2025-03-02T10:00:00+00:00"}
                ]
            }
        },
        "/integrations": {
            "_embedded": {
                "integrations": [
                    {"consumer": {"name": "Billing"}, "provider": {"name": "Ledger"}}
                ]
            }
        },
        "/matrix?q[][pacticipant]=Billing&q[][pacticipant]=Ledger&limit=1000": {
            "matrix": [
                {
                    "consumer": {"name": "Billing", "version": {"number": "1.0.0"}},
                    "provider": {"name": "Ledger", "version": {"number": "7.0.0"}},
                    "pact": {
                        "createdAt": "2025-03-02T09:05:00+00:00",
                        "_links": {"self": {"href": PACT}},
                    },
                    "verificationResult": {
                        "success": True,
                        "verifiedAt": "2025-03-02T11:00:00+00:00",
                        "_links": {"self": {"href": RESULT}},
                    },
                },
                {  # the reverse direction is another integration's row
                    "consumer": {"name": "Ledger", "version": {"number": "7.0.0"}},
                    "provider": {"name": "Billing"},
                    "pact": {
                        "_links": {
                            "self": {
                                "href": f"{SOURCE}/pacts/provider/Billing/consumer/Ledger/version/7.0.0"
                            }
                        }
                    },
                },
            ]
        },
        "/pacts/provider/Ledger/consumer/Billing/version/1.0.0": {
            "consumer": {"name": "Billing"},
            "provider": {"name": "Ledger"},
            "interactions": [],
            "metadata": {"pactSpecification": {"version": "2.0.0"}},
            "createdAt": "2025-03-02T09:05:00+00:00",
            "_links": {"self": {"href": PACT}},
        },
        "/pacts/provider/Ledger/consumer/Billing/pact-version/abc/verification-results/3": {
            "success": True,
            "providerApplicationVersion": "7.0.0",
            "verificationDate": "2025-03-02T11:00:00+00:00",
            "testResults": {"summary": {"testCount": 1}},
        },
        "/environments": {
            "_embedded": {
                "environments": [
                    {
                        "uuid": "env-1",
                        "name": "production",
                        "displayName": "Production",
                        "production": True,
                    }
                ]
            }
        },
        "/environments/env-1/deployed-versions/currently-deployed": {
            "_embedded": {
                "deployedVersions": [
                    {
                        "applicationInstance": None,
                        "createdAt": "2025-03-05T09:00:00+00:00",
                        "_embedded": {
                            "pacticipant": {"name": "Ledger"},
                            "version": {"number": "7.0.0"},
                        },
                    }
                ]
            }
        },
        "/environments/env-1/released-versions/currently-supported": {
            "_embedded": {"releasedVersions": []}
        },
        "/webhooks": {
            "_links": {
                "pb:webhooks": [
                    {
                        "href": f"{SOURCE}/webhooks/3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
                        "title": "CI",
                    }
                ]
            }
        },
        "/webhooks/3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d": {
            "description": "Tell CI",
            "events": [
                {"name": "contract_requiring_verification_published"},
                {"name": "pactflow_only_event"},
            ],
            "request": {
                "method": "POST",
                "url": "https://ci.example.com/hooks",
                "headers": {
                    "Authorization": "**********",
                    "Content-Type": "application/json",
                },
                "body": {"token": "${user.slackToken}"},
            },
            "createdAt": "2025-03-06T09:00:00+00:00",
        },
    }
    if secrets:
        documents["/secrets"] = {
            "_embedded": {"secrets": [{"name": "slackToken", "description": "Slack"}]}
        }
    return documents


def _key(request: httpx.Request) -> str:
    parts = urlsplit(str(request.url))
    query = "&".join(f"{k}={v}" for k, v in parse_qsl(parts.query))
    return parts.path + (f"?{query}" if query else "")


def _mock(
    httpx_mock: Any,
    *,
    documents: Optional[dict[str, Any]] = None,
    answer: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Serve the source and Apiome; returns the bodies Apiome received."""
    source = documents if documents is not None else _source_documents()
    sent: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "localhost":
            assert request.headers.get("x-api-key") == "apiome-key"
            body = json.loads(request.content)
            sent.append(body)
            outcome = (
                "would-create" if request.url.path.endswith("/check") else "created"
            )
            default = {
                "results": [
                    {"index": i, "outcome": outcome}
                    for i, _ in enumerate(body["records"])
                ]
            }
            return httpx.Response(200, json=answer(body) if answer else default)
        assert request.url.host == "broker.example.com", (
            f"the token went to {request.url.host}"
        )
        assert request.headers.get("authorization") == "Bearer source-token"
        key = _key(request)
        if key in source:
            return httpx.Response(200, json=source[key])
        return httpx.Response(404, json={"error": "not found"})

    httpx_mock.add_callback(handle, is_reusable=True)
    return sent


def _migrate(*extra: str) -> Any:
    return runner.invoke(
        app, ["pact", "migrate", "--from", SOURCE, "--token", "source-token", *extra]
    )


def _records(sent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for body in sent for record in body["records"]]


def test_a_workspace_is_read_and_imported_in_dependency_order(httpx_mock: Any) -> None:
    sent = _mock(httpx_mock)
    result = _migrate()
    assert result.exit_code == EXIT_SUCCESS, result.output
    records = _records(sent)
    kinds = [record["kind"] for record in records]
    assert kinds == [
        "pacticipant",
        "pacticipant",
        "environment",
        "version",
        "version",
        "version",
        "pact",
        "verification",
        "deployment",
        "webhook",
    ]
    billing = records[0]
    assert billing == {
        "kind": "pacticipant",
        "name": "Billing",
        "repository_url": "https://github.com/acme/billing",
        "main_branch": "main",
        "labels": ["team-billing"],
        "created_at": "2025-03-01T09:00:00+00:00",
    }
    versions = [
        r for r in records if r["kind"] == "version" and r["pacticipant"] == "Billing"
    ]
    assert [v["number"] for v in versions] == ["1.0.0", "1.1.0"]  # oldest first
    assert versions[0]["branches"] == ["main"]
    assert versions[0]["tags"] == [
        {"name": "prod", "created_at": "2025-03-04T09:00:00+00:00"}
    ]
    pact = next(r for r in records if r["kind"] == "pact")
    assert (
        pact["consumer_version"] == "1.0.0"
        and "_links" not in pact["content"]
        and "createdAt" not in pact["content"]
    )
    verification = next(r for r in records if r["kind"] == "verification")
    assert verification["number"] == 3
    assert verification["created_at"] == "2025-03-02T11:00:00+00:00"
    assert verification["result"]["providerApplicationVersion"] == "7.0.0"
    assert "testResults" not in verification["result"]
    webhook = next(r for r in records if r["kind"] == "webhook")
    assert webhook["uuid"] == "3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    # PFX-8.15: the redacted header is sent as it is; Apiome keeps it waiting for a value.
    assert "enabled" not in webhook["webhook"]
    assert webhook["webhook"]["request"]["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "**********",
    }
    assert webhook["webhook"]["events"] == [
        {"name": "contract_requiring_verification_published"}
    ]
    assert all(body["source"] == SOURCE for body in sent)

    out = result.output
    assert "Migration from https://broker.example.com to workspace acme" in out
    assert "display name 'Billing Service' is not carried over" in out
    assert "pactflow_only_event are not fired by Apiome" in out
    assert "does not export header Authorization: imported turned off, waiting for a value" in out
    assert "refers to the secret slackToken" in out
    assert "secret slackToken: PactFlow does not export secret values" in out
    assert "deployment history" in out
    assert "its testResults are neither an array nor an object with a tests array" in out
    state = json.loads(Path("apiome-pact-migrate.state.json").read_text())
    assert state["source"] == SOURCE and state["target"] == "acme"
    assert "pact:Ledger/Billing/1.0.0" in state["done"] and len(state["done"]) == 10


def test_a_second_run_resumes_and_fetches_nothing_already_imported(
    httpx_mock: Any,
) -> None:
    sent = _mock(httpx_mock)
    assert _migrate().exit_code == EXIT_SUCCESS
    first = len(sent)
    result = _migrate()
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(sent) == first  # nothing left to send
    fetched = [
        r
        for r in httpx_mock.get_requests()
        if r.url.path.endswith(("/version/1.0.0", "/verification-results/3"))
    ]
    assert len(fetched) == 2  # the pact and the result were read by the first run only
    assert "Done earlier" in result.output


def test_refused_records_are_reported_retried_and_exit_1(httpx_mock: Any) -> None:
    def answer(body: dict[str, Any]) -> dict[str, Any]:
        results = []
        for index, record in enumerate(body["records"]):
            if record["kind"] == "webhook":
                results.append(
                    {
                        "index": index,
                        "outcome": "refused",
                        "code": "pact-webhook-invalid",
                        "message": "no secret slackToken",
                    }
                )
            else:
                results.append({"index": index, "outcome": "created"})
        return {"results": results}

    sent = _mock(httpx_mock, answer=answer)
    result = _migrate()
    assert result.exit_code == EXIT_ERROR
    assert "Refused (1):" in result.output
    assert (
        "webhook 3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d: pact-webhook-invalid: no secret slackToken"
        in result.output
    )
    done = json.loads(Path("apiome-pact-migrate.state.json").read_text())["done"]
    assert not any(key.startswith("webhook:") for key in done)
    sent.clear()
    _migrate()
    assert [record["kind"] for record in _records(sent)] == [
        "webhook"
    ]  # only the refused one is retried


def test_a_dry_run_checks_and_writes_no_state(httpx_mock: Any) -> None:
    sent = _mock(httpx_mock)
    result = _migrate("--dry-run", "--output", "json")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert {
        request.url.path
        for request in httpx_mock.get_requests()
        if request.url.host == "localhost"
    } == {urlsplit(CHECK).path}
    report = json.loads(result.output[result.output.index("{") :])
    assert report["dry_run"] is True
    assert report["kinds"]["version"] == {"read": 3, "skipped": 0, "would-create": 3}
    assert report["state_file"] is None
    assert any(item["kind"] == "secret" for item in report["not_portable"])
    assert not Path("apiome-pact-migrate.state.json").exists()
    assert len(_records(sent)) == 10


def test_an_open_source_broker_without_secrets_is_fine(httpx_mock: Any) -> None:
    _mock(httpx_mock, documents=_source_documents(secrets=False))
    result = _migrate()
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "PactFlow does not export secret values" not in result.output


def test_a_pact_the_source_no_longer_has_is_refused_with_the_reason(
    httpx_mock: Any,
) -> None:
    documents = _source_documents()
    del documents["/pacts/provider/Ledger/consumer/Billing/version/1.0.0"]
    _mock(httpx_mock, documents=documents)
    result = _migrate()
    assert result.exit_code == EXIT_ERROR
    assert (
        "pact Ledger/Billing/1.0.0: source-unreadable: the source listed it but answered 404"
        in result.output
    )


def test_the_source_refusing_the_token_stops_the_run(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=f"{SOURCE}/pacticipants?size=100", status_code=401)
    result = _migrate()
    assert result.exit_code == EXIT_ERROR
    assert "the source broker refused /pacticipants (HTTP 401)" in result.output
    assert "source-token" not in result.output


def test_a_state_file_of_another_migration_is_refused(httpx_mock: Any) -> None:
    Path("apiome-pact-migrate.state.json").write_text(
        json.dumps({"source": "https://other", "target": "acme", "done": []})
    )
    result = _migrate()
    assert result.exit_code == EXIT_ERROR
    assert "records a migration from https://other" in result.output
    assert httpx_mock.get_requests() == []


def test_from_is_required_and_must_be_http(httpx_mock: Any) -> None:
    assert runner.invoke(app, ["pact", "migrate"]).exit_code == EXIT_ERROR
    result = runner.invoke(app, ["pact", "migrate", "--from", "ftp://broker"])
    assert result.exit_code == EXIT_ERROR
    assert "must be an http(s) URL" in result.output


def test_the_token_can_come_from_the_environment(
    httpx_mock: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PACT_SOURCE_BROKER_TOKEN", "source-token")
    _mock(httpx_mock)
    result = runner.invoke(app, ["pact", "migrate", "--from", SOURCE])
    assert result.exit_code == EXIT_SUCCESS, result.output
