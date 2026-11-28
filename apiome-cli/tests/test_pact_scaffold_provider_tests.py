"""``apiome pact scaffold-provider-tests`` — PFX-8.19 (#7316)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.client.pact_provider_scaffold import has_unregistered, scaffold_path, summary_lines
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

runner = CliRunner()

_URL = "http://localhost:8000/v1/tenants/acme-corp/pact-provider-tests/billing-service?language=typescript"
_RESPONSE: dict[str, Any] = {
    "provider": "billing-service",
    "provider_name": "Billing Service",
    "language": "typescript",
    "label": "TypeScript · pact-js",
    "dependency": "npm install --save-dev @pact-foundation/pact",
    "file_name": "billing-service.pact.test.ts",
    "content": "import { Verifier } from '@pact-foundation/pact';\n",
    "pacts": 2,
    "states": [
        {"name": "an invoice exists", "params": ["id"], "registered": True},
        {"name": "a customer 7 exists", "params": [], "registered": False},
    ],
    "unregistered": 1,
    "notices": [{"code": "provider-scaffold-state-unregistered", "message": "not registered", "state": "a customer 7 exists"}],
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    for name in ("PACT_BROKER_BASE_URL", "PACT_BROKER_TOKEN", "PACT_BROKER_PASSWORD", "PACT_BROKER_USERNAME"):
        monkeypatch.delenv(name, raising=False)


def test_the_path_escapes_each_segment() -> None:
    assert scaffold_path("acme corp", "Billing Service", "go") == (
        "/v1/tenants/acme%20corp/pact-provider-tests/Billing%20Service?language=go"
    )


def test_the_summary_marks_unregistered_states_and_says_what_to_set() -> None:
    lines = summary_lines(_RESPONSE)
    assert lines[0] == (
        "billing-service.pact.test.ts — TypeScript · pact-js for Billing Service: "
        "2 provider state(s) from 2 pact(s), 1 not registered in Apiome"
    )
    assert lines[1] == "    'an invoice exists': id"
    assert lines[2] == "    'a customer 7 exists': no parameters (not registered in Apiome)"
    assert any(line.startswith("  install: npm install") for line in lines)
    assert any("PACT_BROKER_TOKEN" in line for line in lines)
    assert lines[-1] == "  notice [provider-scaffold-state-unregistered]: not registered"
    assert has_unregistered(_RESPONSE) and not has_unregistered({"unregistered": 0})


def test_the_file_is_written_and_the_summary_printed(tmp_path: Path, httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="GET", json=_RESPONSE)
    target = tmp_path / "billing.pact.test.ts"
    result = runner.invoke(
        app, ["pact", "scaffold-provider-tests", "--provider", "billing-service", "--language", "typescript", "-o", str(target)]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert target.read_text() == _RESPONSE["content"]
    assert "1 not registered in Apiome" in result.output
    assert f"wrote {target}" in result.output


def test_without_output_the_file_goes_to_stdout(httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="GET", json=_RESPONSE)
    result = runner.invoke(app, ["pact", "scaffold-provider-tests", "--provider", "billing-service", "-l", "typescript"])
    assert result.exit_code == EXIT_SUCCESS
    assert "import { Verifier }" in result.output


def test_fail_on_unregistered_exits_1(tmp_path: Path, httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="GET", json=_RESPONSE)
    result = runner.invoke(
        app,
        ["pact", "scaffold-provider-tests", "--provider", "billing-service", "-l", "typescript",
         "-o", str(tmp_path / "t.ts"), "--fail-on-unregistered"],
    )
    assert result.exit_code == EXIT_ERROR


def test_an_unknown_language_is_refused_before_sending(httpx_mock: Any, api_key_env: None) -> None:
    result = runner.invoke(app, ["pact", "scaffold-provider-tests", "--provider", "billing-service", "-l", "cobol"])
    assert result.exit_code != EXIT_SUCCESS
    assert httpx_mock.get_requests() == []


def test_an_unknown_provider_exits_1(httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(
        url=_URL, method="GET", status_code=404, json={"detail": {"code": "pacticipant-not-found", "message": "no such"}}
    )
    result = runner.invoke(app, ["pact", "scaffold-provider-tests", "--provider", "billing-service", "-l", "typescript"])
    assert result.exit_code == EXIT_ERROR
