"""Tests for ``apiome pact export-consumer-contract`` / ``publish-consumer-contract`` — PFX-2.6 (#6930).

The server generates the pact; the CLI builds the path and body, writes the Pact document where
it was asked to, prints every finding, and turns findings into exit 1 only with
``--fail-on-findings``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.client.pact_consumer_export import (
    build_publish_body,
    consumer_pact_path,
    has_findings,
    summary_lines,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_ROOT = (
    "http://localhost:8000/v1/tenants/acme-corp/projects/pets/consumers/web-app/pact"
)
_PACT = {
    "consumer": {"name": "web-app"},
    "provider": {"name": "pets-api"},
    "interactions": [
        {"type": "Synchronous/HTTP", "description": "listPets returns 200"}
    ],
    "metadata": {"pactSpecification": {"version": "4.0"}},
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _finding() -> dict[str, Any]:
    return {
        "outcome": "placeholder",
        "reason": "no-example",
        "message": "the specification has no example for the response field 'code'; wrote 0",
        "method": "GET",
        "path": "/pets/{petId}",
        "status": "404",
        "location": "response",
        "field": "code",
    }


def _response(
    findings: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    found = findings or []
    return {
        "consumer_name": "web-app",
        "provider_name": "pets-api",
        "consumer_pacticipant_bound": False,
        "provider_pacticipant_bound": True,
        "revision": 2,
        "version_record_id": "22222222-2222-4222-8222-222222222222",
        "version_label": "1.0.0",
        "interaction_count": 1,
        "placeholder_count": sum(1 for f in found if f["outcome"] == "placeholder"),
        "omitted_count": sum(1 for f in found if f["outcome"] == "omitted"),
        "findings": found,
        "pact": _PACT,
        **extra,
    }


# --- pure helpers ------------------------------------------------------------------------------


def test_the_export_path_escapes_segments_and_carries_the_query() -> None:
    assert (
        consumer_pact_path("acme", "pets", "web app")
        == "/v1/tenants/acme/projects/pets/consumers/web%20app/pact"
    )
    assert (
        consumer_pact_path("acme", "pets", "web", revision=3, provider="Pets API")
        == "/v1/tenants/acme/projects/pets/consumers/web/pact?revision=3&provider=Pets+API"
    )
    assert consumer_pact_path("acme", "pets", "web", publish=True).endswith(
        "/consumers/web/pact/publish"
    )


def test_the_publish_body_carries_only_what_was_given() -> None:
    assert build_publish_body(
        consumer_app_version="abc",
        branch=None,
        tags=None,
        build_url=None,
        revision=None,
        provider=None,
    ) == {"consumer_version": "abc"}
    assert build_publish_body(
        consumer_app_version="abc",
        branch="main",
        tags=["prod"],
        build_url="https://ci/1",
        revision=2,
        provider="p",
    ) == {
        "consumer_version": "abc",
        "branch": "main",
        "tags": ["prod"],
        "build_url": "https://ci/1",
        "revision": 2,
        "provider": "p",
    }


def test_the_summary_names_every_finding_and_the_notices() -> None:
    lines = summary_lines(
        _response(
            [_finding()],
            publish={"notices": [{"type": "success", "text": "Published"}]},
        )
    )
    assert lines[0] == (
        "Pact v4 for web-app → pets-api: 1 interaction(s) from contract revision 2 (specification 1.0.0)"
    )
    assert lines[1] == "  findings: 1 placeholder(s), 0 omitted"
    assert lines[2].startswith(
        "    placeholder [no-example] GET /pets/{petId} 404 response 'code': "
    )
    assert lines[3] == "  success: Published"
    assert has_findings(_response([_finding()])) and not has_findings(_response())


# --- export ------------------------------------------------------------------------------------


def test_export_writes_the_pact_file(
    tmp_path: Path, httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(url=_ROOT, method="GET", json=_response())
    target = tmp_path / "web-app-pets-api.json"
    result = runner.invoke(
        app,
        [
            "pact",
            "export-consumer-contract",
            "--project",
            "pets",
            "--consumer",
            "web-app",
            "-o",
            str(target),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(target.read_text()) == _PACT
    assert "1 interaction(s)" in result.output
    assert f"wrote {target}" in result.output


def test_export_without_output_prints_the_pact_json(
    httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(url=f"{_ROOT}?revision=1", method="GET", json=_response())
    result = runner.invoke(
        app,
        [
            "pact",
            "export-consumer-contract",
            "-p",
            "pets",
            "-c",
            "web-app",
            "--revision",
            "1",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert '"description": "listPets returns 200"' in result.stdout


def test_fail_on_findings_exits_1(
    tmp_path: Path, httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(url=_ROOT, method="GET", json=_response([_finding()]))
    result = runner.invoke(
        app,
        [
            "pact",
            "export-consumer-contract",
            "-p",
            "pets",
            "-c",
            "web-app",
            "-o",
            str(tmp_path / "p.json"),
            "--fail-on-findings",
        ],
    )
    assert result.exit_code == EXIT_ERROR
    assert "[no-example]" in result.output


def test_findings_without_the_flag_still_exit_0(
    tmp_path: Path, httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(url=_ROOT, method="GET", json=_response([_finding()]))
    result = runner.invoke(
        app,
        [
            "pact",
            "export-consumer-contract",
            "-p",
            "pets",
            "-c",
            "web-app",
            "-o",
            str(tmp_path / "p.json"),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS


def test_a_server_refusal_exits_with_the_api_error(
    httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(
        url=_ROOT,
        method="GET",
        status_code=422,
        json={
            "detail": {
                "code": "consumer-pact-export-unsupported-source",
                "message": "came from 'pact'",
            }
        },
    )
    result = runner.invoke(
        app, ["pact", "export-consumer-contract", "-p", "pets", "-c", "web-app"]
    )
    assert result.exit_code == EXIT_USAGE


# --- publish -----------------------------------------------------------------------------------


def test_publish_sends_the_version_and_prints_the_notices(
    tmp_path: Path, httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(
        url=f"{_ROOT}/publish",
        method="POST",
        json=_response(
            publish={
                "notices": [
                    {"type": "success", "text": "Published pact for web-app abc123"}
                ]
            }
        ),
    )
    target = tmp_path / "published.json"
    result = runner.invoke(
        app,
        [
            "pact",
            "publish-consumer-contract",
            "-p",
            "pets",
            "-c",
            "web-app",
            "-a",
            "abc123",
            "--branch",
            "main",
            "-t",
            "prod",
            "-o",
            str(target),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent == {"consumer_version": "abc123", "branch": "main", "tags": ["prod"]}
    assert "success: Published pact for web-app abc123" in result.output
    assert json.loads(target.read_text()) == _PACT


def test_publish_json_mode_prints_the_response(
    httpx_mock: Any, api_key_env: None
) -> None:
    httpx_mock.add_response(
        url=f"{_ROOT}/publish", method="POST", json=_response(publish={"notices": []})
    )
    result = runner.invoke(
        app,
        [
            "--json",
            "pact",
            "publish-consumer-contract",
            "-p",
            "pets",
            "-c",
            "web-app",
            "-a",
            "abc123",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["interaction_count"] == 1
